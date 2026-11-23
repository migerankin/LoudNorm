"""Regressions for two reported bugs.

1. Auto-pause settings changed while balancing never reached the running engine,
   so picking "pause" kept ducking until you restarted.
2. There was no way to fold an edited setting back into the profile it came from.
"""

from dataclasses import fields, replace

from autolevel.autopause import (
    VIDEO,
    VOICE,
    AutoPauseEngine,
    AutoPauseRunner,
    AutoPauseSettings,
    Intent,
    settings_from_config,
)
from autolevel.config import Config
from autolevel.mediasessions import STATUS_PLAYING, MediaSession


def playing(app_id):
    return MediaSession(app_id=app_id, status=STATUS_PLAYING)


def settings(**kw):
    base = dict(enabled=True, trigger_apps=["chrome"], music_apps=["spotify"],
                voice_apps=["discord"], trigger_min_s=0.4, resume_delay_s=2.0)
    base.update(kw)
    return AutoPauseSettings(**base)


class FakeController:
    """Stands in for the media controller; records what it was told to do."""

    available = True

    def __init__(self, sessions=()):
        self.sessions = list(sessions)
        self.calls = []

    def snapshot(self):
        return list(self.sessions)

    def pause(self, app_id):
        self.calls.append(("pause", app_id))
        return True

    def play(self, app_id):
        self.calls.append(("play", app_id))
        return True


class FakeBalancer:
    def __init__(self):
        self.duck_patterns = set()
        self.duck_db = 0.0


# --- bug 2: settings must apply to a live engine ----------------------------- #

def test_switching_duck_to_pause_mid_run_releases_the_duck():
    """The reported symptom: 'pause' selected but the music kept ducking."""
    config = settings(action="duck")
    engine = AutoPauseEngine(config)

    engine.update([playing("Chrome"), playing("Spotify")], 0.0)
    assert engine.update([playing("Chrome"), playing("Spotify")], 0.5) == [
        Intent("duck", "spotify")
    ]

    config.action = "pause"  # user changes it while the video is still playing
    intents = engine.update([playing("Chrome"), playing("Spotify")], 1.0)

    assert Intent("unduck", "spotify") in intents, "the old duck must be released"
    assert Intent("pause", "Spotify") in intents, "the new action must be applied"
    assert engine.action == "pause"


def test_switching_pause_to_duck_mid_run_resumes_what_was_paused():
    config = settings(action="pause")
    engine = AutoPauseEngine(config)

    engine.update([playing("Chrome"), playing("Spotify")], 0.0)
    engine.update([playing("Chrome"), playing("Spotify")], 0.5)

    config.action = "duck"
    intents = engine.update([playing("Chrome"), playing("Spotify")], 1.0)

    assert Intent("play", "Spotify") in intents
    assert Intent("duck", "spotify") in intents


def test_unchanged_action_does_not_thrash():
    config = settings(action="duck")
    engine = AutoPauseEngine(config)
    engine.update([playing("Chrome"), playing("Spotify")], 0.0)
    engine.update([playing("Chrome"), playing("Spotify")], 0.5)
    assert engine.update([playing("Chrome"), playing("Spotify")], 1.0) == []


def test_disabling_a_voice_app_mid_run_stops_it_triggering():
    config = settings(voice_apps=["discord"], voice_action="duck")
    engine = AutoPauseEngine(config)

    engine.update([playing("Spotify")], 0.0, voice_active={"discord.exe"})
    engine.update([playing("Spotify")], 0.5, voice_active={"discord.exe"})
    assert engine.kind == VOICE

    config.voice_apps = []  # unticked in the settings panel
    engine.update([playing("Spotify")], 1.0, voice_active={"discord.exe"})
    intents = engine.update([playing("Spotify")], 3.5, voice_active={"discord.exe"})

    assert Intent("unduck", "spotify") in intents
    assert engine.kind is None


def test_runner_follows_a_changed_voice_gate():
    """The detector cached the gate at construction and never re-read it."""
    config = settings(voice_gate_db=-45.0, voice_hold_s=0.5)
    runner = AutoPauseRunner(config, FakeController([playing("Spotify")]), FakeBalancer())

    runner.tick(0.0, {"discord.exe": -60.0})
    assert runner.detector.gate_db == -45.0

    config.voice_gate_db = -70.0
    runner.tick(0.1, {"discord.exe": -60.0})
    assert runner.detector.gate_db == -70.0, "detector must re-read the gate"
    assert "discord.exe" in runner.detector.update({"discord.exe": -60.0}, 0.2)


def test_runner_follows_a_changed_hold():
    config = settings(voice_hold_s=1.5)
    runner = AutoPauseRunner(config, FakeController(), FakeBalancer())
    runner.tick(0.0, {})
    config.voice_hold_s = 9.0
    runner.tick(0.1, {})
    assert runner.detector.hold_s == 9.0


def test_every_autopause_field_can_be_pushed_in_place():
    """apply_autopause mutates rather than rebinding, because the engine, runner
    and detector all hold a reference to the same settings object."""
    live = settings_from_config(Config(autopause_action="duck"))
    engine = AutoPauseEngine(live)
    fresh = settings_from_config(Config(autopause_action="pause", autopause_duck_db=-9.0))

    for field in fields(fresh):
        setattr(live, field.name, getattr(fresh, field.name))

    assert engine.settings.action == "pause", "the engine must see the change"
    assert engine.settings.duck_db == -9.0


def test_video_still_beats_voice_after_an_action_change():
    config = settings(action="pause", voice_action="duck")
    engine = AutoPauseEngine(config)
    engine.update([playing("Chrome"), playing("Spotify")], 0.0, voice_active={"discord.exe"})
    engine.update([playing("Chrome"), playing("Spotify")], 0.5, voice_active={"discord.exe"})
    assert engine.kind == VIDEO
    assert engine.action == "pause"


# --- bug 1: a profile must be updatable in place ----------------------------- #

def test_updating_a_profile_overwrites_it(tmp_path):
    from autolevel.profiles import ProfileLibrary

    library = ProfileLibrary.load(tmp_path / "profiles.json")
    library.put("Mine", Config(target_db=-18.0))

    library.put("Mine", replace(library.get("Mine"), target_db=-25.0), overwrite=True)

    assert library.get("Mine").target_db == -25.0


def test_updating_persists(tmp_path):
    from autolevel.profiles import ProfileLibrary

    path = tmp_path / "profiles.json"
    library = ProfileLibrary.load(path)
    library.put("Mine", Config(target_db=-18.0))
    library.save()

    library.put("Mine", Config(target_db=-25.0), overwrite=True)
    library.save()

    assert ProfileLibrary.load(path).get("Mine").target_db == -25.0


def test_updating_clears_the_modified_marker(tmp_path):
    from autolevel.profiles import ProfileLibrary

    library = ProfileLibrary.load(tmp_path / "profiles.json")
    library.put("Mine", Config(target_db=-18.0))
    library.activate("Mine")

    edited = Config(target_db=-25.0)
    assert library.label_for(edited) == "Mine（已修改）"

    library.put("Mine", edited, overwrite=True)
    assert library.label_for(edited) == "Mine"
