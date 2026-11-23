"""User configuration: defaults, JSON persistence, CLI overrides."""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


MAX_BOOST_GAIN_DB = 60.0


def default_config_path() -> Path:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return Path(base) / "autolevel" / "config.json"


@dataclass
class Config:
    # --- what "balanced" means -------------------------------------------------
    #: Every app is pulled toward this level. Lower leaves more headroom for
    #: apps that are not routed through the separate true-boost bridge.
    target_db: float = -18.0
    #: Furthest an app may be turned down. Guards against a badly mismeasured
    #: app being driven to inaudibility.
    min_gain_db: float = -30.0
    #: Attenuation only -- a session volume cannot exceed 1.0. Raising this
    #: above 0.0 does nothing; the scalar is clamped.
    max_gain_db: float = 0.0

    # --- how it reacts ---------------------------------------------------------
    #: Below this an app counts as silent and its volume is held, not adjusted.
    gate_db: float = -50.0
    attack_ms: float = 150.0
    release_ms: float = 2000.0
    #: Audible audio required before an app's volume is touched at all.
    settle_ms: float = 1500.0
    #: Silence this long makes an app re-settle before being adjusted again.
    reset_after_silence_ms: float = 5000.0
    #: Volume travel speed. Higher reacts faster but can sound like pumping.
    slew_db_per_s: float = 6.0

    # --- loop timing -----------------------------------------------------------
    poll_interval_ms: float = 50.0
    #: Session enumeration is far more expensive than meter reads, so it runs
    #: on its own slower cadence.
    refresh_interval_ms: float = 1000.0

    # --- scope -----------------------------------------------------------------
    #: Process names left completely alone, case-insensitive.
    exclude: list[str] = field(default_factory=list)
    #: If non-empty, only these process names are managed.
    include_only: list[str] = field(default_factory=list)
    #: Put every touched app back the way it was on exit.
    restore_on_exit: bool = True

    # --- true above-unity boost ------------------------------------------------
    #: Capture a separate render endpoint, amplify it in software, and play it
    #: through boost_output_device. Chosen apps are assigned to the source in
    #: Windows' per-application Volume Mixer.
    boost_enabled: bool = False
    boost_source_device: str = ""
    #: Empty means the current default speaker.
    boost_output_device: str = ""
    boost_gain_db: float = 6.0
    #: Peak limiter ceiling. Leaving headroom below 0 dBFS avoids inter-sample
    #: clipping in the physical output device.
    boost_ceiling_db: float = -1.0
    boost_sample_rate: int = 48000
    boost_block_frames: int = 480

    # --- window behaviour ------------------------------------------------------
    #: Closing the window hides it to the tray instead of quitting.
    close_to_tray: bool = True

    # --- auto-pause ------------------------------------------------------------
    #: Pause (or duck) the music when a video starts playing.
    autopause_enabled: bool = False
    #: Apps whose playback silences the music, matched as substrings against the
    #: media session app id. Browsers cover YouTube and everything like it.
    autopause_trigger: list[str] = field(
        default_factory=lambda: ["chrome", "msedge", "firefox", "opera", "brave"]
    )
    #: Apps to pause or turn down.
    autopause_music: list[str] = field(default_factory=lambda: ["spotify"])
    #: "pause" stops playback outright; "duck" just turns it down.
    autopause_action: str = "pause"
    autopause_duck_db: float = -20.0
    #: Video must play this long before the music is touched.
    autopause_trigger_min_s: float = 0.4
    #: Delay after the video stops before the music comes back.
    autopause_resume_delay_s: float = 2.0

    # --- voice activity --------------------------------------------------------
    #: Apps whose audio level quietens the music, matched on process name.
    #: These register no media session, so they are detected by loudness.
    autopause_voice_apps: list[str] = field(
        default_factory=lambda: ["discord", "teams", "zoom"]
    )
    #: Names from the roster above that are currently switched off. Kept as a
    #: separate list rather than removing them, so unticking an app in the UI
    #: does not lose it -- and so an old config without this key still loads.
    autopause_voice_disabled: list[str] = field(default_factory=list)
    #: Voice ducks rather than pauses by default; stopping the music dead for one
    #: word in a call is worse than turning it down.
    autopause_voice_action: str = "duck"
    #: Peak level above which a voice app counts as talking.
    autopause_voice_gate_db: float = -45.0
    #: Keep counting as talking this long after the level drops, so the gaps
    #: between words don't make the music stutter back in.
    autopause_voice_hold_s: float = 1.5

    # ---------------------------------------------------------------------------
    def active_voice_apps(self) -> list[str]:
        """Voice trigger apps that are actually switched on.

        Stale entries in the disabled list -- an app that was removed from the
        roster while unticked -- are simply ignored rather than being an error.
        """
        off = {name.strip().lower() for name in self.autopause_voice_disabled}
        return [name for name in self.autopause_voice_apps if name.strip().lower() not in off]

    def manages(self, process_name: str) -> bool:
        name = process_name.lower()
        if any(name == e.lower() for e in self.exclude):
            return False
        if self.include_only:
            return any(name == i.lower() for i in self.include_only)
        return True

    def validate(self) -> None:
        numeric_fields = (
            config_field
            for config_field in fields(self)
            if config_field.type in (float, int, "float", "int")
        )
        for config_field in numeric_fields:
            value = getattr(self, config_field.name)
            if config_field.type in (int, "int"):
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValueError(f"{config_field.name} 必须是整数")
            elif isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{config_field.name} 必须是数字")
            try:
                finite = math.isfinite(value)
            except (TypeError, OverflowError):
                finite = False
            if not finite:
                raise ValueError(f"{config_field.name} 必须是有限数字")
        if self.min_gain_db > self.max_gain_db:
            raise ValueError(
                f"min_gain_db ({self.min_gain_db}) 不能大于 max_gain_db ({self.max_gain_db})"
            )
        if self.poll_interval_ms <= 0:
            raise ValueError("poll_interval_ms 必须为正数")
        if self.slew_db_per_s <= 0:
            raise ValueError("slew_db_per_s 必须为正数")
        if self.boost_enabled and not self.boost_source_device.strip():
            raise ValueError(
                "已启用 boost_enabled，但 boost_source_device 为空；请选择被增强应用"
                "所路由到的源端点"
            )
        if self.boost_enabled and self.boost_gain_db <= 0.0:
            raise ValueError("启用增强时 boost_gain_db 必须大于 0 dB")
        if self.boost_gain_db > MAX_BOOST_GAIN_DB:
            raise ValueError(
                f"boost_gain_db 不能超过 {MAX_BOOST_GAIN_DB:g} dB"
            )
        if self.boost_ceiling_db > 0.0:
            raise ValueError("boost_ceiling_db 必须不高于 0 dBFS")
        if self.boost_sample_rate <= 0:
            raise ValueError("boost_sample_rate 必须为正数")
        if self.boost_block_frames <= 0:
            raise ValueError("boost_block_frames 必须为正数")
        if self.autopause_action not in ("pause", "duck"):
            raise ValueError(
                f"autopause_action 必须是 'pause' 或 'duck'，而不是 {self.autopause_action!r}"
            )
        if self.autopause_voice_action not in ("pause", "duck"):
            raise ValueError(
                f"autopause_voice_action 必须是 'pause' 或 'duck'，"
                f"而不是 {self.autopause_voice_action!r}"
            )
        if self.autopause_enabled and not self.autopause_music:
            raise ValueError("已启用 autopause_enabled，但 autopause_music 为空")
        if self.autopause_voice_gate_db >= 0.0:
            raise ValueError("autopause_voice_gate_db 必须低于 0 dBFS")
        if self.autopause_enabled:
            # Voice detection reads levels the balancer collects, so an excluded
            # app is invisible to it -- and would fail silently.
            blind = [
                name for name in self.exclude
                if any(v.strip().lower() in name.lower() for v in self.active_voice_apps())
            ]
            if blind:
                raise ValueError(
                    f"{', '.join(blind)} 同时出现在 exclude 与语音触发名单中；语音检测"
                    "读取的是平衡器采集的电平，被排除的应用永远不会触发。请从 exclude "
                    "或 autopause_voice_apps 中移除它。"
                )
        if self.gate_db >= self.target_db:
            raise ValueError(
                f"gate_db ({self.gate_db}) 必须低于 target_db ({self.target_db})，"
                "否则处于目标电平的应用会被当成静音"
            )

    # ---------------------------------------------------------------------------
    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or default_config_path()
        if not path.exists():
            return cls()

        data = json.loads(path.read_text(encoding="utf-8"))
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"{path} 中存在未知的配置项：{', '.join(sorted(unknown))}")

        cfg = cls(**data)
        cfg.validate()
        return cfg

    def save(self, path: Path | None = None) -> Path:
        path = path or default_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
        return path
