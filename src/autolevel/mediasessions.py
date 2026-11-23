"""Windows media transport controls (GSMTC).

This is a different layer from the Core Audio session API in ``sessions.py``.
Core Audio knows *how loud* an app is; this knows *what it is playing and
whether it is playing*, and can pause one specific app.

Targeting matters: sending a global VK_MEDIA_PLAY_PAUSE would be dispatched to
whichever app currently owns media control -- quite possibly the video we are
reacting to, rather than the music we mean to pause. GSMTC lets us call
``try_pause_async`` on a named session instead.

The WinRT API is async, so it runs on a private event loop in its own thread.
Callers only ever touch ``snapshot()``, ``pause()`` and ``play()``, all of which
are thread safe.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass

# GlobalSystemMediaTransportControlsSessionPlaybackStatus
STATUS_CLOSED, STATUS_OPENED, STATUS_CHANGING = 0, 1, 2
STATUS_STOPPED, STATUS_PLAYING, STATUS_PAUSED = 3, 4, 5


@dataclass(frozen=True)
class MediaSession:
    """A COM-free snapshot of one media session.

    Defined before the winsdk import so tests can build these without WinRT.
    """

    app_id: str
    status: int
    title: str = ""
    artist: str = ""
    can_pause: bool = False
    can_play: bool = False

    @property
    def playing(self) -> bool:
        return self.status == STATUS_PLAYING

    @property
    def label(self) -> str:
        if self.title and self.artist:
            return f"{self.title} - {self.artist}"
        return self.title or self.app_id


try:
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as _SessionManager,
    )

    WINSDK_AVAILABLE = True
    WINSDK_ERROR: str | None = None
except Exception as _exc:  # pragma: no cover - depends on the machine
    _SessionManager = None
    WINSDK_AVAILABLE = False
    WINSDK_ERROR = repr(_exc)


def matches(name: str, patterns) -> bool:
    """Case-insensitive substring match against a process name or media app id.

    One pattern has to cover both identifier styles: ``spotify`` matches the
    process ``Spotify.exe`` and the media app id
    ``SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify``.

    A trailing ``.exe`` is stripped from the pattern, because the obvious thing
    to type is the process name as ``autolevel list`` prints it -- and
    ``chrome.exe`` would otherwise never match the media app id ``Chrome``,
    failing silently.
    """
    lowered = name.lower()
    for pattern in patterns:
        pattern = pattern.strip().lower()
        if pattern.endswith(".exe"):
            pattern = pattern[:-4]
        if pattern and pattern in lowered:
            return True
    return False


class MediaController:
    """Background poller and remote control for media sessions."""

    def __init__(self, poll_interval_s: float = 0.4, startup_timeout_s: float = 6.0):
        self.poll_interval_s = poll_interval_s
        self.available = False
        self.error: str | None = WINSDK_ERROR
        self._sessions: list[MediaSession] = []
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._manager = None
        self._ready = threading.Event()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        if not WINSDK_AVAILABLE:
            return

        self._thread = threading.Thread(
            target=self._thread_main, name="autolevel-media", daemon=True
        )
        self._thread.start()
        self._ready.wait(timeout=startup_timeout_s)

    # --- background thread -------------------------------------------------- #

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._poll_forever())
        except BaseException as exc:  # pragma: no cover - environmental
            self.error = repr(exc)
            self.available = False
        finally:
            self._ready.set()
            try:
                loop.close()
            except Exception:
                pass

    async def _poll_forever(self) -> None:
        self._manager = await _SessionManager.request_async()
        self.available = True
        self.error = None
        await self._refresh()
        self._ready.set()

        while not self._stop_event.is_set():
            await asyncio.sleep(self.poll_interval_s)
            try:
                await self._refresh()
            except Exception as exc:
                self.error = repr(exc)

    async def _refresh(self) -> None:
        found: list[MediaSession] = []
        for raw in self._manager.get_sessions():
            try:
                info = raw.get_playback_info()
                app_id = raw.source_app_user_model_id or ""
                title = artist = ""
                # Metadata is a separate async call and fails on some apps;
                # play state alone is enough to act on.
                try:
                    props = await raw.try_get_media_properties_async()
                    title = props.title or ""
                    artist = props.artist or ""
                except Exception:
                    pass
                found.append(
                    MediaSession(
                        app_id=app_id,
                        status=int(info.playback_status),
                        title=title,
                        artist=artist,
                        can_pause=bool(info.controls.is_pause_enabled),
                        can_play=bool(info.controls.is_play_enabled),
                    )
                )
            except Exception:
                continue  # session vanished mid-enumeration

        with self._lock:
            self._sessions = found

    # --- public, thread safe ------------------------------------------------- #

    def snapshot(self) -> list[MediaSession]:
        with self._lock:
            return list(self._sessions)

    def _control(self, app_id: str, want_play: bool) -> bool:
        if not self.available or self._loop is None:
            return False

        async def action() -> bool:
            for raw in self._manager.get_sessions():
                if (raw.source_app_user_model_id or "") != app_id:
                    continue
                if want_play:
                    return bool(await raw.try_play_async())
                return bool(await raw.try_pause_async())
            return False

        try:
            future = asyncio.run_coroutine_threadsafe(action(), self._loop)
            return bool(future.result(timeout=3.0))
        except Exception as exc:
            self.error = repr(exc)
            return False

    def pause(self, app_id: str) -> bool:
        return self._control(app_id, want_play=False)

    def play(self, app_id: str) -> bool:
        return self._control(app_id, want_play=True)

    def close(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
