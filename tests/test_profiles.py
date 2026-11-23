import json

import pytest

from autolevel.config import Config
from autolevel.profiles import STARTER_PROFILES, ProfileLibrary, starter_library


def library(tmp_path, **kw):
    return ProfileLibrary.load(tmp_path / "profiles.json", **kw)


# --- seeding ---------------------------------------------------------------- #

def test_first_run_seeds_gaming_and_chilling(tmp_path):
    lib = library(tmp_path)
    assert lib.names() == ["休闲", "游戏"]


def test_seeded_profiles_are_valid(tmp_path):
    for config in library(tmp_path).profiles.values():
        config.validate()


def test_seeded_profiles_actually_differ(tmp_path):
    """Two identical presets would be pointless."""
    lib = library(tmp_path)
    assert lib.get("游戏") != lib.get("休闲")
    assert lib.get("游戏").target_db != lib.get("休闲").target_db


def test_gaming_never_hard_pauses():
    """Stopping audio dead mid-game is the wrong response; duck instead."""
    assert STARTER_PROFILES["游戏"]["autopause_action"] == "duck"


def test_seeding_writes_the_file(tmp_path):
    library(tmp_path)
    assert (tmp_path / "profiles.json").exists()


def test_seeding_can_be_declined(tmp_path):
    assert library(tmp_path, seed=False).names() == []


# --- persistence ------------------------------------------------------------ #

def test_round_trip(tmp_path):
    lib = library(tmp_path)
    lib.put("Quiet", Config(target_db=-30.0))
    lib.activate("Quiet")
    lib.save()

    reloaded = library(tmp_path)
    assert reloaded.get("Quiet").target_db == -30.0
    assert reloaded.active == "Quiet"


def test_unknown_keys_are_dropped_not_fatal(tmp_path):
    """A profile written by a newer build must still load in an older one."""
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps({
        "active": "Future",
        "profiles": {"Future": {"target_db": -19.0, "invented_later": 42}},
    }), encoding="utf-8")

    lib = ProfileLibrary.load(path)
    assert lib.get("Future").target_db == -19.0


def test_invalid_profile_is_skipped_not_crashed(tmp_path):
    """One bad profile must not stop the app from starting."""
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps({
        "profiles": {
            "Good": {"target_db": -18.0},
            "Broken": {"gate_db": -5.0, "target_db": -18.0},  # gate above target
        },
    }), encoding="utf-8")

    lib = ProfileLibrary.load(path)
    assert lib.names() == ["Good"]
    assert lib.skipped == ["Broken"]


def test_corrupt_file_falls_back_to_starters(tmp_path):
    path = tmp_path / "profiles.json"
    path.write_text("{not json at all", encoding="utf-8")
    assert ProfileLibrary.load(path).names() == ["休闲", "游戏"]


def test_active_pointing_at_a_missing_profile_is_cleared(tmp_path):
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps({
        "active": "Deleted", "profiles": {"Kept": {"target_db": -18.0}},
    }), encoding="utf-8")
    assert ProfileLibrary.load(path).active is None


# --- mutation ---------------------------------------------------------------- #

def test_put_rejects_an_invalid_config(tmp_path):
    lib = library(tmp_path)
    with pytest.raises(ValueError):
        lib.put("Bad", Config(gate_db=-5.0, target_db=-18.0))


def test_put_rejects_a_blank_name(tmp_path):
    with pytest.raises(ValueError):
        library(tmp_path).put("   ", Config())


def test_delete(tmp_path):
    lib = library(tmp_path)
    assert lib.delete("游戏") is True
    assert lib.names() == ["休闲"]
    assert lib.delete("游戏") is False


def test_deleting_the_active_profile_clears_active(tmp_path):
    lib = library(tmp_path)
    lib.activate("游戏")
    lib.delete("游戏")
    assert lib.active is None


def test_rename_carries_the_active_marker(tmp_path):
    lib = library(tmp_path)
    lib.activate("游戏")
    lib.rename("游戏", "Raid Night")
    assert set(lib.names()) == {"休闲", "Raid Night"}
    assert lib.active == "Raid Night"


def test_rename_onto_an_existing_name_is_refused(tmp_path):
    lib = library(tmp_path)
    with pytest.raises(ValueError, match="已存在"):
        lib.rename("游戏", "休闲")


def test_rename_to_itself_is_allowed(tmp_path):
    lib = library(tmp_path)
    lib.rename("游戏", "游戏")
    assert "游戏" in lib.names()


def test_activate_returns_the_settings(tmp_path):
    lib = library(tmp_path)
    assert lib.activate("休闲").target_db == lib.get("休闲").target_db


def test_activate_unknown_name_raises(tmp_path):
    with pytest.raises(ValueError):
        library(tmp_path).activate("Nope")


# --- drift detection ---------------------------------------------------------- #

def test_matching_identifies_an_exact_profile(tmp_path):
    lib = library(tmp_path)
    assert lib.matching(lib.get("游戏")) == "游戏"


def test_matching_returns_none_once_settings_drift(tmp_path):
    lib = library(tmp_path)
    from dataclasses import replace

    assert lib.matching(replace(lib.get("游戏"), target_db=-11.0)) is None


def test_label_names_the_profile_when_settings_match(tmp_path):
    lib = library(tmp_path)
    lib.activate("游戏")
    assert lib.label_for(lib.get("游戏")) == "游戏"


def test_label_flags_modified_settings(tmp_path):
    """The selector must not claim you are on Gaming after you changed things."""
    from dataclasses import replace

    lib = library(tmp_path)
    lib.activate("游戏")
    drifted = replace(lib.get("游戏"), target_db=-11.0)
    assert lib.label_for(drifted) == "游戏（已修改）"


def test_label_for_settings_from_no_profile(tmp_path):
    lib = library(tmp_path, seed=False)
    assert lib.label_for(Config()) == "（未保存）"


def test_starter_library_is_independent_of_stored_state():
    assert set(starter_library()) == set(STARTER_PROFILES)
