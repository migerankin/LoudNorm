"""Level estimation and gain control.

Pure math -- no COM, no audio hardware -- so the control behaviour can be unit
tested without a sound card. Everything here works in dBFS; amplitudes only
appear at the boundaries.
"""

from __future__ import annotations

import math

#: Anything at or below this is treated as digital silence.
SILENCE_DB = -120.0


def clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


def amp_to_db(amp: float) -> float:
    """Linear amplitude (0.0-1.0, as the peak meter reports) to dBFS."""
    if amp <= 1e-6:
        return SILENCE_DB
    return 20.0 * math.log10(amp)


def db_to_amp(db: float) -> float:
    """dBFS back to linear amplitude, which is what a volume slider wants."""
    if db <= SILENCE_DB:
        return 0.0
    return 10.0 ** (db / 20.0)


class EnvelopeFollower:
    """One-pole smoother with independent attack and release time constants.

    Fast attack so a sudden loud passage registers quickly; slow release so a
    brief pause between words or notes doesn't read as "this app got quieter".
    """

    def __init__(self, attack_ms: float, release_ms: float, initial_db: float = SILENCE_DB):
        self.attack_ms = attack_ms
        self.release_ms = release_ms
        self.value_db = initial_db

    @staticmethod
    def _coefficient(tau_ms: float, dt_ms: float) -> float:
        if tau_ms <= 0.0:
            return 1.0
        return 1.0 - math.exp(-dt_ms / tau_ms)

    def update(self, sample_db: float, dt_ms: float) -> float:
        rising = sample_db > self.value_db
        tau = self.attack_ms if rising else self.release_ms
        alpha = self._coefficient(tau, dt_ms)
        self.value_db += alpha * (sample_db - self.value_db)
        return self.value_db


class LoudnessTracker:
    """Turns a stream of peak readings into a stable "how loud is this app" figure.

    Returns ``None`` whenever it has no trustworthy answer -- the app is silent,
    or it hasn't produced enough audio yet to judge. Callers must hold their
    current gain in that case rather than treating it as zero.
    """

    def __init__(
        self,
        gate_db: float = -50.0,
        attack_ms: float = 150.0,
        release_ms: float = 2000.0,
        settle_ms: float = 1500.0,
        reset_after_silence_ms: float = 5000.0,
    ):
        self.gate_db = gate_db
        self.settle_ms = settle_ms
        self.reset_after_silence_ms = reset_after_silence_ms
        self._envelope = EnvelopeFollower(attack_ms, release_ms)
        self._active_ms = 0.0
        self._silent_ms = 0.0

    @property
    def settled(self) -> bool:
        return self._active_ms >= self.settle_ms

    @property
    def level_db(self) -> float:
        return self._envelope.value_db

    def update(self, peak_amp: float, dt_ms: float) -> float | None:
        sample_db = amp_to_db(peak_amp)

        if sample_db < self.gate_db:
            self._silent_ms += dt_ms
            # A long gap means the app stopped playing; make it re-earn its
            # measurement rather than acting on a stale level when it returns.
            if self._silent_ms >= self.reset_after_silence_ms:
                self._active_ms = 0.0
                self._envelope.value_db = SILENCE_DB
            return None

        self._silent_ms = 0.0
        self._active_ms += dt_ms
        self._envelope.update(sample_db, dt_ms)
        return self._envelope.value_db if self.settled else None


class GainController:
    """Drives one app's volume slider toward a target level.

    Attenuation only. A Windows session volume is 0.0-1.0, i.e. -inf..0 dB, so
    an app cannot be pushed above the level it already plays at. Loud apps come
    down to meet the target and the user raises the master volume once.
    """

    def __init__(
        self,
        target_db: float = -18.0,
        min_gain_db: float = -30.0,
        max_gain_db: float = 0.0,
        slew_db_per_s: float = 6.0,
    ):
        self.target_db = target_db
        self.min_gain_db = min_gain_db
        self.max_gain_db = max_gain_db
        self.slew_db_per_s = slew_db_per_s
        self.current_gain_db = 0.0

    def desired_gain_db(self, level_db: float) -> float:
        return clamp(self.target_db - level_db, self.min_gain_db, self.max_gain_db)

    def update(self, level_db: float | None, dt_ms: float) -> float:
        """Step the gain toward its target. ``None`` level means hold."""
        if level_db is None:
            return self.current_gain_db

        desired = self.desired_gain_db(level_db)
        max_step = self.slew_db_per_s * (dt_ms / 1000.0)
        delta = desired - self.current_gain_db

        if abs(delta) <= max_step:
            self.current_gain_db = desired
        else:
            self.current_gain_db += math.copysign(max_step, delta)

        return self.current_gain_db

    @property
    def volume_scalar(self) -> float:
        """Current gain as the 0.0-1.0 scalar a session volume expects."""
        return clamp(db_to_amp(self.current_gain_db), 0.0, 1.0)
