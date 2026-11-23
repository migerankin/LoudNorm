"""Creating and naming profiles."""

import pytest

from autolevel.config import Config
from autolevel.profiles import ProfileLibrary


def library(tmp_path):
    return ProfileLibrary.load(tmp_path / "profiles.json")


# --- naming ----------------------------------------------------------------- #

def test_any_name_is_allowed():
    for name in ["Movie Night", "raid-night", "Late night 2am", "café", "Zone 3"]:
        assert ProfileLibrary.validate_name(name) == name


def test_surrounding_whitespace_is_trimmed():
    assert ProfileLibrary.validate_name("  Movie Night  ") == "Movie Night"


def test_blank_names_are_refused():
    for name in ["", "   ", None]:
        with pytest.raises(ValueError, match="必须有名称"):
            ProfileLibrary.validate_name(name)


def test_absurdly_long_names_are_refused():
    with pytest.raises(ValueError, match="40 个字符"):
        ProfileLibrary.validate_name("x" * 41)


def test_a_forty_character_name_is_fine():
    assert ProfileLibrary.validate_name("x" * 40)


# --- creating ---------------------------------------------------------------- #

def test_creating_a_profile_from_settings(tmp_path):
    lib = library(tmp_path)
    lib.put("Movie Night", Config(target_db=-24.0))
    assert "Movie Night" in lib.names()
    assert lib.get("Movie Night").target_db == -24.0


def test_created_profile_persists(tmp_path):
    lib = library(tmp_path)
    lib.put("Movie Night", Config(target_db=-24.0))
    lib.save()
    assert ProfileLibrary.load(tmp_path / "profiles.json").get("Movie Night").target_db == -24.0


def test_creating_can_refuse_to_clobber(tmp_path):
    """The UI asks before replacing, so it needs a non-overwriting mode."""
    lib = library(tmp_path)
    with pytest.raises(ValueError, match="已存在"):
        lib.put("游戏", Config(), overwrite=False)


def test_overwriting_is_allowed_when_asked_for(tmp_path):
    lib = library(tmp_path)
    lib.put("游戏", Config(target_db=-9.0), overwrite=True)
    assert lib.get("游戏").target_db == -9.0


def test_exists_reports_membership(tmp_path):
    lib = library(tmp_path)
    assert lib.exists("游戏")
    assert lib.exists("  游戏  "), "should ignore stray whitespace"
    assert not lib.exists("Nope")


def test_creating_an_invalid_config_is_refused(tmp_path):
    lib = library(tmp_path)
    with pytest.raises(ValueError):
        lib.put("Broken", Config(gate_db=-5.0, target_db=-18.0))
    assert "Broken" not in lib.names()


def test_created_profiles_carry_voice_toggles(tmp_path):
    lib = library(tmp_path)
    lib.put("Solo", Config(
        autopause_voice_apps=["discord", "teams"],
        autopause_voice_disabled=["teams"],
    ))
    lib.save()

    restored = ProfileLibrary.load(tmp_path / "profiles.json").get("Solo")
    assert restored.active_voice_apps() == ["discord"]


# --- duplicating -------------------------------------------------------------- #

def test_duplicate_copies_the_settings(tmp_path):
    lib = library(tmp_path)
    lib.duplicate("游戏", "Gaming Night")
    assert lib.get("Gaming Night").target_db == lib.get("游戏").target_db


def test_duplicate_is_independent_of_its_source(tmp_path):
    from dataclasses import replace

    lib = library(tmp_path)
    lib.duplicate("游戏", "Gaming Night")
    lib.profiles["Gaming Night"] = replace(lib.get("Gaming Night"), target_db=-30.0)
    assert lib.get("游戏").target_db != -30.0


def test_duplicate_refuses_an_existing_name(tmp_path):
    lib = library(tmp_path)
    with pytest.raises(ValueError, match="已存在"):
        lib.duplicate("游戏", "休闲")


def test_duplicate_of_a_missing_profile_raises(tmp_path):
    lib = library(tmp_path)
    with pytest.raises(ValueError, match="没有名为"):
        lib.duplicate("Nope", "Copy")


def test_duplicate_rejects_a_blank_name(tmp_path):
    lib = library(tmp_path)
    with pytest.raises(ValueError, match="必须有名称"):
        lib.duplicate("游戏", "  ")
