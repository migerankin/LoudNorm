import json
from dataclasses import fields

import pytest

from autolevel.config import Config


FLOAT_FIELDS = [
    "target_db",
    "min_gain_db",
    "max_gain_db",
    "gate_db",
    "attack_ms",
    "release_ms",
    "settle_ms",
    "reset_after_silence_ms",
    "slew_db_per_s",
    "poll_interval_ms",
    "refresh_interval_ms",
    "boost_gain_db",
    "boost_ceiling_db",
    "autopause_duck_db",
    "autopause_trigger_min_s",
    "autopause_resume_delay_s",
    "autopause_voice_gate_db",
    "autopause_voice_hold_s",
]
INTEGER_FIELDS = ["boost_sample_rate", "boost_block_frames"]
NUMERIC_FIELDS = FLOAT_FIELDS + INTEGER_FIELDS


def test_defaults_are_valid():
    Config().validate()


def test_numeric_field_spec_covers_every_declared_number():
    declared = {
        config_field.name
        for config_field in fields(Config)
        if config_field.type in (float, int, "float", "int")
    }
    assert set(NUMERIC_FIELDS) == declared


@pytest.mark.parametrize("field", FLOAT_FIELDS)
def test_float_fields_reject_booleans(field):
    with pytest.raises(ValueError, match=rf"^{field} 必须是数字$"):
        Config(**{field: True}).validate()


@pytest.mark.parametrize("field", INTEGER_FIELDS)
@pytest.mark.parametrize("value", [True, 48000.5])
def test_integer_fields_require_integers(field, value):
    with pytest.raises(ValueError, match=rf"^{field} 必须是整数$"):
        Config(**{field: value}).validate()


def test_excluded_process_is_not_managed():
    cfg = Config(exclude=["Discord.exe"])
    assert not cfg.manages("discord.exe"), "matching must be case-insensitive"
    assert cfg.manages("chrome.exe")


def test_include_only_restricts_scope():
    cfg = Config(include_only=["chrome.exe"])
    assert cfg.manages("chrome.exe")
    assert not cfg.manages("spotify.exe")


def test_exclude_wins_over_include_only():
    cfg = Config(include_only=["chrome.exe"], exclude=["chrome.exe"])
    assert not cfg.manages("chrome.exe")


def test_gain_range_must_be_ordered():
    with pytest.raises(ValueError, match="min_gain_db"):
        Config(min_gain_db=6.0, max_gain_db=0.0).validate()


def test_gate_above_target_is_rejected():
    """Otherwise apps sitting at the target level read as silent and never settle."""
    with pytest.raises(ValueError, match="gate_db"):
        Config(gate_db=-10.0, target_db=-18.0).validate()


def test_positive_intervals_required():
    with pytest.raises(ValueError):
        Config(poll_interval_ms=0).validate()
    with pytest.raises(ValueError):
        Config(slew_db_per_s=0).validate()


def test_enabling_true_boost_requires_a_source_endpoint():
    with pytest.raises(ValueError, match="boost_source_device"):
        Config(boost_enabled=True, boost_source_device="").validate()


def test_true_boost_requires_positive_gain():
    with pytest.raises(ValueError, match="boost_gain_db"):
        Config(
            boost_enabled=True,
            boost_source_device="CABLE Input",
            boost_gain_db=0.0,
        ).validate()


def test_true_boost_rejects_overflowing_gain():
    with pytest.raises(ValueError, match="boost_gain_db"):
        Config(boost_gain_db=1e308).validate()


def test_true_boost_ceiling_must_be_below_full_scale():
    with pytest.raises(ValueError, match="boost_ceiling_db"):
        Config(boost_ceiling_db=0.1).validate()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("boost_gain_db", float("nan")),
        ("boost_gain_db", float("inf")),
        ("boost_ceiling_db", float("nan")),
        ("boost_ceiling_db", float("-inf")),
        ("boost_sample_rate", float("nan")),
        ("boost_block_frames", float("inf")),
    ],
)
def test_true_boost_rejects_non_finite_numbers(field, value):
    with pytest.raises(ValueError, match=field):
        Config(**{field: value}).validate()


@pytest.mark.parametrize("field", NUMERIC_FIELDS)
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_config_rejects_non_finite_numeric_fields(field, value):
    with pytest.raises(ValueError, match=field):
        Config(**{field: value}).validate()


@pytest.mark.parametrize("field", NUMERIC_FIELDS)
def test_config_rejects_oversized_integers(field):
    with pytest.raises(ValueError, match=field):
        Config(**{field: 10**1000}).validate()


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    original = Config(
        target_db=-22.0,
        exclude=["obs64.exe"],
        boost_enabled=True,
        boost_source_device="CABLE Input",
        boost_output_device="Speakers",
        boost_gain_db=8.0,
    )
    original.save(path)

    loaded = Config.load(path)
    assert loaded.target_db == -22.0
    assert loaded.exclude == ["obs64.exe"]
    assert loaded.boost_source_device == "CABLE Input"
    assert loaded.boost_output_device == "Speakers"
    assert loaded.boost_gain_db == 8.0


def test_missing_file_yields_defaults(tmp_path):
    assert Config.load(tmp_path / "absent.json") == Config()


def test_unknown_key_is_reported(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"target_db": -18.0, "typo_here": 1}), encoding="utf-8")
    with pytest.raises(ValueError, match="typo_here"):
        Config.load(path)


def test_invalid_saved_config_is_rejected_on_load(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"gate_db": -5.0, "target_db": -18.0}), encoding="utf-8")
    with pytest.raises(ValueError):
        Config.load(path)
