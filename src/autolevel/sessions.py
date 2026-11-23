"""Thin wrapper over the Windows Core Audio session API.

Everything COM-flavoured lives here so the rest of the package stays testable.

Two facts about this API drive the design, both established by measurement
rather than assumption (see docs/CALIBRATION.md):

* ``IAudioMeterInformation.GetPeakValue`` on a session reports the app's own
  output level and is *not* scaled by the session volume. Measurement is
  therefore independent of our own adjustments -- the loop is open-loop.
* ``ISimpleAudioVolume`` accepts 0.0-1.0 only. Apps can be attenuated, never
  amplified past their own output level.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

import comtypes
from pycaw.api.endpointvolume import IAudioMeterInformation
from pycaw.pycaw import AudioUtilities

log = logging.getLogger(__name__)

#: AudioSessionState values from the Core Audio headers.
STATE_INACTIVE, STATE_ACTIVE, STATE_EXPIRED = 0, 1, 2


@dataclass
class ManagedSession:
    """One application's audio session, plus the state we keep about it."""

    key: str
    pid: int
    name: str
    _meter: object = field(repr=False)
    _volume: object = field(repr=False)
    #: The user's own setting, captured before we touched anything.
    original_volume: float = 1.0
    #: Whether we have actually written a volume yet.
    adjusted: bool = False

    def peak(self) -> float:
        """Peak amplitude 0.0-1.0 since the previous call. 0.0 if unavailable."""
        try:
            return float(self._meter.GetPeakValue())
        except Exception:  # session died between enumeration and read
            return 0.0

    def current_volume(self) -> float:
        try:
            return float(self._volume.GetMasterVolume())
        except Exception:
            return self.original_volume

    def set_volume(self, scalar: float) -> bool:
        scalar = 0.0 if scalar < 0.0 else 1.0 if scalar > 1.0 else scalar
        try:
            self._volume.SetMasterVolume(scalar, None)
            self.adjusted = True
            return True
        except Exception as exc:
            log.debug("could not set volume for %s: %r", self.name, exc)
            return False

    def restore(self) -> bool:
        if not self.adjusted:
            return True
        try:
            self._volume.SetMasterVolume(self.original_volume, None)
            self.adjusted = False
            return True
        except Exception as exc:
            log.debug("could not restore %s: %r", self.name, exc)
            return False


class SessionRegistry:
    """Keeps a live view of per-app sessions, remembering what we changed.

    Sessions come and go as apps start, stop, and go idle. Original volumes are
    captured the first time a session is seen and replayed when it disappears or
    when we shut down, so nothing is left turned down after we exit.
    """

    def __init__(self, manages=None):
        #: Predicate deciding whether a process name is ours to manage.
        self._manages = manages or (lambda _name: True)
        self._own_pid = os.getpid()
        self._sessions: dict[str, ManagedSession] = {}
        comtypes.CoInitialize()

    @property
    def sessions(self) -> dict[str, ManagedSession]:
        return self._sessions

    @staticmethod
    def _key(raw_session, pid: int) -> str:
        # InstanceIdentifier is unique per session instance, so two windows of
        # the same app don't collide. It is occasionally unavailable.
        try:
            identifier = raw_session.InstanceIdentifier
            if identifier:
                return str(identifier)
        except Exception:
            pass
        return f"pid:{pid}"

    def refresh(self) -> tuple[list[ManagedSession], list[ManagedSession]]:
        """Re-enumerate sessions. Returns (added, removed).

        Removed sessions have already had their original volume restored where
        that was still possible.
        """
        try:
            raw_sessions = AudioUtilities.GetAllSessions()
        except Exception as exc:
            log.warning("session enumeration failed: %r", exc)
            return [], []

        seen: dict[str, ManagedSession] = {}
        added: list[ManagedSession] = []

        for raw in raw_sessions:
            process = raw.Process
            if process is None:
                continue  # system sounds; no process to attribute it to

            try:
                name = process.name()
                pid = process.pid
            except Exception:
                continue  # process exited mid-enumeration

            if pid == self._own_pid:
                continue  # never attenuate our own true-boost render session
            if not self._manages(name):
                continue

            key = self._key(raw, pid)
            existing = self._sessions.get(key)
            if existing is not None:
                seen[key] = existing
                continue

            try:
                meter = raw._ctl.QueryInterface(IAudioMeterInformation)
                volume = raw.SimpleAudioVolume
                original = float(volume.GetMasterVolume())
            except Exception as exc:
                log.debug("skipping %s, no meter or volume interface: %r", name, exc)
                continue

            session = ManagedSession(
                key=key, pid=pid, name=name,
                _meter=meter, _volume=volume, original_volume=original,
            )
            seen[key] = session
            added.append(session)

        removed = [s for key, s in self._sessions.items() if key not in seen]
        for session in removed:
            session.restore()

        self._sessions = seen
        return added, removed

    def restore_all(self) -> int:
        """Put every app we touched back. Returns how many were restored."""
        restored = 0
        for session in self._sessions.values():
            if session.adjusted and session.restore():
                restored += 1
        return restored
