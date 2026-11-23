"""Quieten the music when something more important is playing.

Two independent kinds of trigger, because the two live on different Windows APIs:

* **video** -- a media session reports playback (browser, VLC, anything that
  registers transport controls). Detected through ``mediasessions.py``.
* **voice** -- an app is simply *making noise* above a threshold. Discord, Teams
  and Zoom register no media session at all, so nothing in the media layer can
  see a call. Their Core Audio peak level can.

They get separate actions on purpose. Stopping the music outright is right for a
video you sat down to watch; it is obnoxious for one word in a Discord call, so
voice ducks by default.

The engine is a pure state machine over snapshots and an injected clock, so all
of this is unit tested with no audio, browser, or voice call involved.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .mediasessions import MediaSession, matches

VIDEO, VOICE = "video", "voice"


@dataclass
class AutoPauseSettings:
    enabled: bool = False
    #: Apps whose *media playback* should quieten the music. Substring matched.
    trigger_apps: list[str] = field(default_factory=lambda: ["chrome", "msedge", "firefox"])
    #: Apps to pause or duck.
    music_apps: list[str] = field(default_factory=lambda: ["spotify"])
    #: What a video does: "pause" stops playback, "duck" turns it down.
    action: str = "pause"
    duck_db: float = -20.0
    #: Trigger must persist this long before acting.
    trigger_min_s: float = 0.4
    #: Wait this long after the trigger stops before restoring.
    resume_delay_s: float = 2.0
    #: If a paused app is still playing this long after we paused it, the user
    #: restarted it deliberately.
    override_grace_s: float = 2.5

    # --- voice activity ---------------------------------------------------
    #: Apps whose *audio level* should quieten the music, matched on process
    #: name. These have no media session, so they are detected by loudness.
    voice_apps: list[str] = field(default_factory=lambda: ["discord", "teams", "zoom"])
    #: Voice ducks rather than pauses by default -- see the module docstring.
    voice_action: str = "duck"
    #: Peak level above which a voice app counts as talking.
    voice_gate_db: float = -45.0
    #: Keep counting as "talking" this long after the level drops, so the gaps
    #: between words don't make the music stutter back in.
    voice_hold_s: float = 1.5


@dataclass(frozen=True)
class Intent:
    """A requested action. ``app`` is a media app id, or a pattern when ducking."""

    kind: str  # "pause" | "play" | "duck" | "unduck"
    app: str


class VoiceDetector:
    """Turns per-app peak levels into "who is currently talking".

    The hold is the whole point. Speech is full of gaps of a few hundred
    milliseconds; without a hold the music would duck and unduck between words.
    """

    def __init__(self, gate_db: float = -45.0, hold_s: float = 1.5):
        self.gate_db = gate_db
        self.hold_s = hold_s
        self._last_above: dict[str, float] = {}

    def update(self, levels, now: float) -> set[str]:
        """``levels`` maps process name to peak dBFS. Returns names still active."""
        for name, level_db in levels.items():
            if level_db >= self.gate_db:
                self._last_above[name] = now

        active = set()
        for name, seen in list(self._last_above.items()):
            if now - seen <= self.hold_s:
                active.add(name)
            elif now - seen > self.hold_s * 4:
                del self._last_above[name]  # long gone; stop tracking
        return active

    def reset(self) -> None:
        self._last_above.clear()


class AutoPauseEngine:
    def __init__(self, settings: AutoPauseSettings):
        self.settings = settings
        self.trigger_label = ""
        #: Which trigger class is currently engaged: VIDEO, VOICE, or None.
        self.kind: str | None = None
        self.action: str | None = None
        self._debounce: dict[str, dict] = {
            VIDEO: {"since": None, "stopped_at": None, "on": False},
            VOICE: {"since": None, "stopped_at": None, "on": False},
        }
        self._paused_at: dict[str, float] = {}
        self._overridden: set[str] = set()
        self._ducking = False

    @property
    def active(self) -> bool:
        return self.kind is not None

    @property
    def paused_apps(self) -> set[str]:
        return set(self._paused_at)

    # --- main entry point ---------------------------------------------------- #

    def update(self, sessions: list[MediaSession], now: float, voice_active=()) -> list[Intent]:
        s = self.settings
        if not s.enabled:
            if self.kind or self._paused_at or self._ducking:
                return self.reset()
            return []

        music = [x for x in sessions if matches(x.app_id, s.music_apps)]

        video_sessions = [
            x for x in sessions
            if matches(x.app_id, s.trigger_apps) and not matches(x.app_id, s.music_apps)
        ]
        playing = [x for x in video_sessions if x.playing]
        # A music app never counts as a trigger, so overlapping patterns cannot
        # make the music trigger against itself.
        talking = [
            n for n in voice_active
            if matches(n, s.voice_apps) and not matches(n, s.music_apps)
        ]

        video_on = self._settle(VIDEO, bool(playing), now)
        voice_on = self._settle(VOICE, bool(talking), now)

        # Video wins when both are going: it is the stronger response.
        if video_on:
            kind, action = VIDEO, s.action
            label = playing[0].label if playing else self.trigger_label or "某个视频"
        elif voice_on:
            kind, action = VOICE, s.voice_action
            label = talking[0] if talking else self.trigger_label or "语音通话"
        else:
            kind, action, label = None, None, ""

        intents: list[Intent] = []
        if kind != self.kind or (kind is not None and action != self.action):
            # Switching class *or action* must undo the previous response before
            # applying the new one, or a duck is left behind under a pause. The
            # action check matters because settings can change mid-run.
            intents += self._release()
            self.kind, self.action = kind, action

        self.trigger_label = label
        if kind is not None:
            intents += self._engage(music, now, action)
        return intents

    # --- helpers -------------------------------------------------------------- #

    def _settle(self, kind: str, raw: bool, now: float) -> bool:
        """Debounce a raw trigger into a stable on/off state."""
        s = self.settings
        state = self._debounce[kind]

        if raw:
            state["stopped_at"] = None
            if state["since"] is None:
                state["since"] = now
            if not state["on"] and now - state["since"] >= s.trigger_min_s:
                state["on"] = True
        else:
            state["since"] = None
            if state["on"]:
                if state["stopped_at"] is None:
                    state["stopped_at"] = now
                elif now - state["stopped_at"] >= s.resume_delay_s:
                    state["on"] = False
                    state["stopped_at"] = None
        return state["on"]

    def _engage(self, music: list[MediaSession], now: float, action: str) -> list[Intent]:
        s = self.settings
        intents: list[Intent] = []

        if action == "duck":
            if not self._ducking:
                self._ducking = True
                intents += [Intent("duck", p) for p in s.music_apps]
            return intents

        for session in music:
            app = session.app_id
            if app in self._overridden:
                continue

            if app in self._paused_at:
                # We asked it to pause. Still playing well after the fact means
                # the user pressed play again; stop interfering.
                if session.playing and now - self._paused_at[app] >= s.override_grace_s:
                    self._overridden.add(app)
                    del self._paused_at[app]
                continue

            if session.playing:
                intents.append(Intent("pause", app))
                self._paused_at[app] = now

        return intents

    def _release(self) -> list[Intent]:
        intents = [Intent("play", app) for app in self._paused_at]
        if self._ducking:
            intents += [Intent("unduck", p) for p in self.settings.music_apps]
            self._ducking = False
        self._paused_at.clear()
        self._overridden.clear()
        return intents

    def reset(self) -> list[Intent]:
        """Release everything. Used when the feature is switched off."""
        intents = self._release()
        for state in self._debounce.values():
            state.update({"since": None, "stopped_at": None, "on": False})
        self.kind = self.action = None
        self.trigger_label = ""
        return intents


class AutoPauseRunner:
    """Connects the engine to the media controller and the balancer."""

    def __init__(self, settings: AutoPauseSettings, controller, balancer=None):
        self.settings = settings
        self.controller = controller
        self.balancer = balancer
        self.engine = AutoPauseEngine(settings)
        self.detector = VoiceDetector(settings.voice_gate_db, settings.voice_hold_s)
        self.last_error: str | None = None

    @property
    def status(self) -> str:
        if not self.settings.enabled:
            return "自动暂停：关闭"
        if not getattr(self.controller, "available", False):
            return "自动暂停不可用（不支持媒体会话）"

        engine = self.engine
        if engine.kind == VIDEO:
            verb = "降低" if engine.action == "duck" else "暂停"
            return f"已{verb}音乐 - {engine.trigger_label[:44]} 正在播放"
        if engine.kind == VOICE:
            verb = "降低" if engine.action == "duck" else "暂停"
            return f"已{verb}音乐 - {engine.trigger_label[:30]} 有语音活动"
        return "自动暂停已就绪"

    def tick(self, now: float, app_levels=None) -> list[Intent]:
        """``app_levels`` maps process name to current peak dBFS."""
        # Settings can be edited while running, and the detector caches these.
        self.detector.gate_db = self.settings.voice_gate_db
        self.detector.hold_s = self.settings.voice_hold_s
        voice = self.detector.update(app_levels or {}, now)
        intents = self.engine.update(self.controller.snapshot(), now, voice)
        for intent in intents:
            self._apply(intent)
        return intents

    def _apply(self, intent: Intent) -> None:
        if intent.kind == "pause":
            if not self.controller.pause(intent.app):
                self.last_error = f"无法暂停 {intent.app}"
        elif intent.kind == "play":
            if not self.controller.play(intent.app):
                self.last_error = f"无法恢复 {intent.app}"
        elif intent.kind == "duck" and self.balancer is not None:
            self.balancer.duck_db = self.settings.duck_db
            self.balancer.duck_patterns.add(intent.app.lower())
        elif intent.kind == "unduck" and self.balancer is not None:
            self.balancer.duck_patterns.discard(intent.app.lower())

    def shutdown(self) -> None:
        for intent in self.engine.reset():
            self._apply(intent)
        self.detector.reset()


def settings_from_config(config) -> AutoPauseSettings:
    return AutoPauseSettings(
        enabled=config.autopause_enabled,
        trigger_apps=list(config.autopause_trigger),
        music_apps=list(config.autopause_music),
        action=config.autopause_action,
        duck_db=config.autopause_duck_db,
        trigger_min_s=config.autopause_trigger_min_s,
        resume_delay_s=config.autopause_resume_delay_s,
        voice_apps=config.active_voice_apps(),
        voice_action=config.autopause_voice_action,
        voice_gate_db=config.autopause_voice_gate_db,
        voice_hold_s=config.autopause_voice_hold_s,
    )
