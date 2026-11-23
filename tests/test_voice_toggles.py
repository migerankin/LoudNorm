"""Per-app enable/disable for voice trigger apps."""

import pytest

from autolevel.autopause import settings_from_config
from autolevel.config import Config


def test_all_apps_active_by_default():
    config = Config()
    assert config.active_voice_apps() == config.autopause_voice_apps


def test_disabling_an_app_removes_it_from_the_active_set():
    config = Config(
        autopause_voice_apps=["discord", "teams", "zoom"],
        autopause_voice_disabled=["teams"],
    )
    assert config.active_voice_apps() == ["discord", "zoom"]


def test_disabled_app_is_kept_in_the_roster():
    """Unticking must not lose the name -- that is the whole point."""
    config = Config(
        autopause_voice_apps=["discord", "teams"],
        autopause_voice_disabled=["teams"],
    )
    assert "teams" in config.autopause_voice_apps


def test_disabling_is_case_insensitive():
    config = Config(
        autopause_voice_apps=["Discord", "Teams"],
        autopause_voice_disabled=["discord"],
    )
    assert config.active_voice_apps() == ["Teams"]


def test_disabling_everything_leaves_nothing_active():
    config = Config(
        autopause_voice_apps=["discord"],
        autopause_voice_disabled=["discord"],
    )
    assert config.active_voice_apps() == []


def test_stale_disabled_entry_is_ignored():
    """An app removed from the roster while unticked must not break anything."""
    config = Config(
        autopause_voice_apps=["discord"],
        autopause_voice_disabled=["teams", "an-app-that-is-gone"],
    )
    assert config.active_voice_apps() == ["discord"]
    config.validate()


def test_engine_settings_use_only_enabled_apps():
    config = Config(
        autopause_voice_apps=["discord", "teams"],
        autopause_voice_disabled=["discord"],
    )
    assert settings_from_config(config).voice_apps == ["teams"]


def test_a_disabled_app_may_be_excluded_from_balancing():
    """The excluded/voice-trigger clash only matters for apps still switched on."""
    config = Config(
        autopause_enabled=True,
        exclude=["discord.exe"],
        autopause_voice_apps=["discord"],
        autopause_voice_disabled=["discord"],
    )
    config.validate()  # must not raise


def test_an_enabled_app_still_cannot_be_excluded():
    config = Config(
        autopause_enabled=True,
        exclude=["discord.exe"],
        autopause_voice_apps=["discord"],
    )
    with pytest.raises(ValueError, match="语音触发"):
        config.validate()


def test_old_config_without_the_key_still_loads(tmp_path):
    """Configs written before this feature existed must keep working."""
    import json

    path = tmp_path / "config.json"
    path.write_text(json.dumps({"autopause_voice_apps": ["discord"]}), encoding="utf-8")

    config = Config.load(path)
    assert config.autopause_voice_disabled == []
    assert config.active_voice_apps() == ["discord"]


def test_toggles_survive_a_save_and_load(tmp_path):
    path = tmp_path / "config.json"
    Config(
        autopause_voice_apps=["discord", "teams"],
        autopause_voice_disabled=["teams"],
    ).save(path)

    assert Config.load(path).active_voice_apps() == ["discord"]
