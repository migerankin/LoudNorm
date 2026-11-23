"""The control loop: measure every app, decide a gain, write it back."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .config import Config
from .dsp import GainController, LoudnessTracker, amp_to_db, clamp, db_to_amp
from .sessions import ManagedSession, SessionRegistry

#: Don't issue a COM write for a change smaller than this (~0.04 dB near unity).
WRITE_EPSILON = 0.005


@dataclass
class AppState:
    """Per-application measurement and control state."""

    session: ManagedSession
    tracker: LoudnessTracker
    controller: GainController
    peak: float = 0.0
    #: Smoothed source level, or None while silent or still settling.
    level_db: float | None = None
    written_volume: float | None = None
    writes: int = field(default=0)
    #: Extra attenuation from auto-pause ducking, on top of the balancing gain.
    duck_db: float = 0.0

    @property
    def name(self) -> str:
        return self.session.name

    @property
    def gain_db(self) -> float:
        return self.controller.current_gain_db

    @property
    def status(self) -> str:
        if self.level_db is not None:
            return "活跃"
        return "静音" if not self.tracker.settled else "暂停"


class Balancer:
    """Holds one AppState per session and steps them all on a fixed cadence."""

    def __init__(self, config: Config, registry: SessionRegistry, dry_run: bool = False):
        self.config = config
        self.registry = registry
        self.dry_run = dry_run
        self.states: dict[str, AppState] = {}
        #: Lowercased process-name substrings currently ducked by auto-pause.
        #: Applied as an offset here rather than written directly, so ducking
        #: and balancing never race each other for the same volume slider.
        self.duck_patterns: set[str] = set()
        self.duck_db: float = -20.0

    def _duck_offset(self, process_name: str) -> float:
        if not self.duck_patterns:
            return 0.0
        lowered = process_name.lower()
        return self.duck_db if any(p in lowered for p in self.duck_patterns) else 0.0

    def _state_for(self, session: ManagedSession) -> AppState:
        state = self.states.get(session.key)
        if state is None:
            cfg = self.config
            state = AppState(
                session=session,
                tracker=LoudnessTracker(
                    gate_db=cfg.gate_db,
                    attack_ms=cfg.attack_ms,
                    release_ms=cfg.release_ms,
                    settle_ms=cfg.settle_ms,
                    reset_after_silence_ms=cfg.reset_after_silence_ms,
                ),
                controller=GainController(
                    target_db=cfg.target_db,
                    min_gain_db=cfg.min_gain_db,
                    max_gain_db=cfg.max_gain_db,
                    slew_db_per_s=cfg.slew_db_per_s,
                ),
            )
            self.states[session.key] = state
        return state

    def set_target(self, target_db: float) -> None:
        """Retarget every app while running. Safe to call from the loop thread."""
        self.config.target_db = target_db
        for state in self.states.values():
            state.controller.target_db = target_db

    def refresh(self) -> None:
        """Re-enumerate sessions and drop state for ones that went away."""
        self.registry.refresh()
        live = set(self.registry.sessions)
        for key in list(self.states):
            if key not in live:
                del self.states[key]

    def tick(self, dt_ms: float) -> list[AppState]:
        """Advance every managed app by ``dt_ms`` and apply the resulting gains."""
        results: list[AppState] = []

        for session in self.registry.sessions.values():
            state = self._state_for(session)

            state.peak = session.peak()
            state.level_db = state.tracker.update(state.peak, dt_ms)
            state.controller.update(state.level_db, dt_ms)

            state.duck_db = self._duck_offset(session.name)
            target_volume = clamp(
                db_to_amp(state.controller.current_gain_db + state.duck_db), 0.0, 1.0
            )
            if not self.dry_run and (
                state.written_volume is None
                or abs(target_volume - state.written_volume) >= WRITE_EPSILON
            ):
                if session.set_volume(target_volume):
                    state.written_volume = target_volume
                    state.writes += 1

            results.append(state)

        results.sort(key=lambda s: s.name.lower())
        return results

    def run(self, on_update=None, should_stop=None) -> None:
        """Loop until ``should_stop()`` returns True or the caller interrupts.

        ``on_update(states)`` is called once per tick for display purposes.
        """
        cfg = self.config
        poll_s = cfg.poll_interval_ms / 1000.0

        self.refresh()
        last_tick = time.perf_counter()
        last_refresh = last_tick

        while not (should_stop and should_stop()):
            now = time.perf_counter()
            dt_ms = (now - last_tick) * 1000.0
            last_tick = now

            if (now - last_refresh) * 1000.0 >= cfg.refresh_interval_ms:
                self.refresh()
                last_refresh = now

            states = self.tick(dt_ms)
            if on_update is not None:
                on_update(states)

            # Sleep the remainder of the interval so dt stays near poll_interval
            # even when a tick runs long.
            elapsed = time.perf_counter() - now
            if elapsed < poll_s:
                time.sleep(poll_s - elapsed)


def observe(registry: SessionRegistry, config: Config) -> list[tuple[str, float, float]]:
    """One-shot read of every session: (name, peak dBFS, current volume).

    Used by ``list``; makes no changes.
    """
    registry.refresh()
    rows = []
    for session in registry.sessions.values():
        rows.append((session.name, amp_to_db(session.peak()), session.current_volume()))
    rows.sort(key=lambda r: r[0].lower())
    return rows
