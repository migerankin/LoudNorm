"""System tray icon.

pystray runs its own Win32 message loop on a background thread, so **every**
callback here arrives off the Tk thread. Nothing in this module may touch a
widget or a Tk variable directly; actions are marshalled with ``after(0, ...)``
and menu state is read from ``window.tray_state``, a plain dict the GUI thread
keeps updated. Reading a ``BooleanVar`` from the tray thread would be a
cross-thread Tk access and is exactly the kind of thing that works until it
doesn't.
"""

from __future__ import annotations

import threading

from . import startup
from .iconart import render

try:
    import pystray

    PYSTRAY_AVAILABLE = True
    PYSTRAY_ERROR: str | None = None
except Exception as _exc:  # pragma: no cover - depends on the machine
    pystray = None
    PYSTRAY_AVAILABLE = False
    PYSTRAY_ERROR = repr(_exc)


class TrayIcon:
    """Tray presence for the main window.

    ``window`` must provide ``show_window()``, ``hide_window()``,
    ``toggle_balancing()``, ``set_autopause()``, ``quit_app()`` and a
    ``tray_state`` dict with ``balancing`` / ``autopause`` keys.
    """

    def __init__(self, window):
        self.window = window
        self.available = PYSTRAY_AVAILABLE
        self.error = PYSTRAY_ERROR
        self._icon = None
        self._thread: threading.Thread | None = None
        self._active = False

    # --- marshalling --------------------------------------------------------- #

    def _dispatch(self, method_name: str, *args) -> None:
        """Run a window method on the Tk thread."""
        window = self.window
        try:
            window.after(0, lambda: getattr(window, method_name)(*args))
        except Exception:
            pass  # window already destroyed

    def _state(self, key: str) -> bool:
        return bool(getattr(self.window, "tray_state", {}).get(key, False))

    def _state_value(self, key: str):
        return getattr(self.window, "tray_state", {}).get(key)

    def refresh_menu(self) -> None:
        """Rebuild the menu after the profile list changes."""
        if self._icon is None:
            return
        try:
            self._icon.menu = self._build_menu()
            self._icon.update_menu()
        except Exception:
            pass

    # --- menu ---------------------------------------------------------------- #

    def _on_profile_click(self, _icon, item) -> None:
        self._dispatch("switch_profile", str(item.text))

    def _is_active_profile(self, item) -> bool:
        return self._state_value("profile") == str(item.text)

    def _profile_items(self):
        """One entry per saved profile, ticked if it is the current one.

        Built from ``tray_state`` rather than the library, so nothing on this
        thread touches Tk or re-reads the file. Bound methods rather than
        closures because pystray inspects ``co_argcount`` and rejects any
        callback taking more than two arguments -- and default arguments count,
        so the obvious ``lambda n=name:`` capture raises ValueError.
        """
        Item = pystray.MenuItem
        names = list(getattr(self.window, "tray_state", {}).get("profiles", []))
        if not names:
            return (Item("没有已保存的配置档", None, enabled=False),)
        return tuple(
            Item(name, self._on_profile_click, checked=self._is_active_profile, radio=True)
            for name in names
        )

    def _build_menu(self):
        Item = pystray.MenuItem
        return pystray.Menu(
            Item("打开 autolevel", lambda: self._dispatch("show_window"), default=True),
            pystray.Menu.SEPARATOR,
            Item("配置档", pystray.Menu(*self._profile_items())),
            pystray.Menu.SEPARATOR,
            Item(
                "平衡",
                lambda: self._dispatch("toggle_balancing"),
                checked=lambda _item: self._state("balancing"),
            ),
            Item(
                "视频播放时暂停音乐",
                lambda: self._dispatch("set_autopause", not self._state("autopause")),
                checked=lambda _item: self._state("autopause"),
            ),
            pystray.Menu.SEPARATOR,
            Item(
                "开机自动启动",
                self._toggle_startup,
                checked=lambda _item: startup.is_enabled(),
            ),
            pystray.Menu.SEPARATOR,
            Item("退出", self._quit),
        )

    def _toggle_startup(self) -> None:
        # Registry only, no Tk involved, so it is safe on this thread.
        startup.set_enabled(not startup.is_enabled())
        self._dispatch("refresh_startup_checkbox")

    def _quit(self) -> None:
        self.stop()
        self._dispatch("quit_app")

    # --- lifecycle ----------------------------------------------------------- #

    def start(self) -> bool:
        if not self.available:
            return False
        self._icon = pystray.Icon(
            "autolevel",
            icon=render(64, active=False),
            title="autolevel - 已停止",
            menu=self._build_menu(),
        )
        self._thread = threading.Thread(
            target=self._icon.run, name="autolevel-tray", daemon=True
        )
        self._thread.start()
        return True

    def set_balancing(self, active: bool, detail: str = "") -> None:
        """Recolour the icon and update its tooltip. Safe from the Tk thread."""
        if self._icon is None:
            return
        if active != self._active:
            self._active = active
            try:
                self._icon.icon = render(64, active=active)
            except Exception:
                pass
        tooltip = f"autolevel - {detail}" if detail else (
            "autolevel - 平衡中" if active else "autolevel - 已停止"
        )
        try:
            # Windows caps tray tooltips at 128 characters.
            self._icon.title = tooltip[:127]
        except Exception:
            pass

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None
