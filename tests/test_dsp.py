import math

import pytest

from autolevel.dsp import (
    SILENCE_DB,
    EnvelopeFollower,
    GainController,
    LoudnessTracker,
    amp_to_db,
    clamp,
    db_to_amp,
)


def feed(obj, peak, ms, dt=50.0):
    """Run a constant peak through a tracker for `ms` milliseconds."""
    result = None
    for _ in range(int(ms / dt)):
        result = obj.update(peak, dt)
    return result


# --- conversions ----------------------------------------------------------- #

def test_unity_amplitude_is_zero_dbfs():
    assert amp_to_db(1.0) == pytest.approx(0.0)


def test_half_amplitude_is_about_minus_six_db():
    assert amp_to_db(0.5) == pytest.approx(-6.02, abs=0.01)


def test_silence_does_not_produce_negative_infinity():
    assert amp_to_db(0.0) == SILENCE_DB
    assert math.isfinite(amp_to_db(0.0))


def test_db_amplitude_roundtrip():
    for amp in (0.001, 0.05, 0.25, 0.5, 1.0):
        assert db_to_amp(amp_to_db(amp)) == pytest.approx(amp, rel=1e-6)


def test_clamp_bounds():
    assert clamp(5, 0, 1) == 1
    assert clamp(-5, 0, 1) == 0
    assert clamp(0.5, 0, 1) == 0.5


# --- envelope follower ----------------------------------------------------- #

def test_attack_is_faster_than_release():
    """A rising signal must be tracked faster than a falling one."""
    rising = EnvelopeFollower(attack_ms=50, release_ms=2000, initial_db=-40)
    falling = EnvelopeFollower(attack_ms=50, release_ms=2000, initial_db=-10)

    rising.update(-10.0, 50.0)
    falling.update(-40.0, 50.0)

    moved_up = rising.value_db - (-40)
    moved_down = (-10) - falling.value_db
    assert moved_up > moved_down * 5


def test_envelope_converges_to_a_constant_input():
    env = EnvelopeFollower(attack_ms=100, release_ms=100)
    for _ in range(200):
        env.update(-12.0, 50.0)
    assert env.value_db == pytest.approx(-12.0, abs=0.01)


# --- loudness tracker ------------------------------------------------------ #

def test_silent_app_reports_no_level():
    tracker = LoudnessTracker(gate_db=-50.0)
    assert feed(tracker, db_to_amp(-70.0), 3000) is None


def test_level_is_withheld_until_settled():
    tracker = LoudnessTracker(gate_db=-50.0, settle_ms=1000.0)
    assert tracker.update(0.5, 50.0) is None, "must not act on the first sample"
    assert feed(tracker, 0.5, 2000) is not None


def test_settled_level_tracks_the_source():
    tracker = LoudnessTracker(gate_db=-50.0, attack_ms=100.0, settle_ms=500.0)
    level = feed(tracker, 0.5, 4000)
    assert level == pytest.approx(-6.02, abs=0.5)


def test_long_silence_forces_resettling():
    """An app that stops and restarts must re-earn its measurement."""
    tracker = LoudnessTracker(gate_db=-50.0, settle_ms=1000.0, reset_after_silence_ms=2000.0)
    assert feed(tracker, 0.5, 3000) is not None

    feed(tracker, 0.0, 3000)
    assert not tracker.settled
    assert tracker.update(0.5, 50.0) is None


def test_brief_pause_does_not_reset():
    tracker = LoudnessTracker(gate_db=-50.0, settle_ms=1000.0, reset_after_silence_ms=5000.0)
    feed(tracker, 0.5, 3000)
    feed(tracker, 0.0, 500)
    assert tracker.settled


# --- gain controller ------------------------------------------------------- #

def test_loud_app_is_attenuated_toward_the_target():
    ctl = GainController(target_db=-18.0, slew_db_per_s=1000.0)
    ctl.update(-6.0, 100.0)
    assert ctl.current_gain_db == pytest.approx(-12.0)


def test_quiet_app_is_never_boosted():
    """A session volume cannot exceed 1.0, so gain must stay at or below 0 dB."""
    ctl = GainController(target_db=-18.0, max_gain_db=0.0, slew_db_per_s=1000.0)
    ctl.update(-40.0, 100.0)
    assert ctl.current_gain_db == pytest.approx(0.0)
    assert ctl.volume_scalar <= 1.0


def test_attenuation_is_bounded():
    ctl = GainController(target_db=-60.0, min_gain_db=-30.0, slew_db_per_s=1000.0)
    ctl.update(0.0, 100.0)
    assert ctl.current_gain_db == pytest.approx(-30.0)


def test_gain_changes_are_slew_limited():
    ctl = GainController(target_db=-18.0, slew_db_per_s=6.0)
    ctl.update(-6.0, 100.0)  # wants -12 dB, may only travel 0.6 dB
    assert ctl.current_gain_db == pytest.approx(-0.6)


def test_gain_reaches_target_after_enough_steps():
    ctl = GainController(target_db=-18.0, slew_db_per_s=6.0)
    for _ in range(100):
        ctl.update(-6.0, 100.0)
    assert ctl.current_gain_db == pytest.approx(-12.0)


def test_no_level_holds_current_gain():
    """Silence must freeze the slider, not drive it anywhere."""
    ctl = GainController(target_db=-18.0, slew_db_per_s=6.0)
    for _ in range(100):
        ctl.update(-6.0, 100.0)
    held = ctl.current_gain_db

    for _ in range(50):
        ctl.update(None, 100.0)
    assert ctl.current_gain_db == pytest.approx(held)


def test_volume_scalar_matches_gain():
    ctl = GainController()
    ctl.current_gain_db = -6.02
    assert ctl.volume_scalar == pytest.approx(0.5, abs=0.001)

    ctl.current_gain_db = 0.0
    assert ctl.volume_scalar == pytest.approx(1.0)


def test_two_apps_at_different_levels_converge_to_the_same_output():
    """The whole point: unequal sources, equal perceived output."""
    loud = GainController(target_db=-18.0, slew_db_per_s=1000.0)
    quiet = GainController(target_db=-18.0, slew_db_per_s=1000.0)

    loud_level, quiet_level = -4.0, -14.0
    loud.update(loud_level, 100.0)
    quiet.update(quiet_level, 100.0)

    assert loud_level + loud.current_gain_db == pytest.approx(
        quiet_level + quiet.current_gain_db, abs=0.01
    )
