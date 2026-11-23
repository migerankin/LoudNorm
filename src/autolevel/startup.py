"""Start with Windows, via the per-user Run key.

`HKCU\\...\\CurrentVersion\\Run` is used rather than a scheduled task or a
Startup-folder shortcut: it needs no admin rights, no COM shortcut plumbing, and
is trivially reversible with one registry delete. The tradeoff is that Windows
gives it no start delay, which does not matter here -- the app tolerates having
no audio sessions to manage at logon and simply picks them up as they appear.

The key location is injectable so tests exercise the real registry round trip
against a scratch key instead of the user's actual startup entry.
"""

from __future__ import annotations

import sys
import winreg
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "autolevel"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def launch_command() -> str:
    """The command Windows should run at logon.

    Starts hidden in the tray and begins balancing immediately -- an audio
    balancer that launches idle at logon would be pointless.
    """
    if is_frozen():
        executable = Path(sys.executable)
        # The windowed build takes --minimized directly. The console build does
        # not -- it needs its subcommand -- and registering it bare would fail
        # silently at every logon. Prefer the GUI exe beside it if there is one.
        if "gui" in executable.stem.lower():
            return f'"{executable}" --minimized'
        windowed = executable.with_name("autolevel-gui.exe")
        if windowed.exists():
            return f'"{windowed}" --minimized'
        return f'"{executable}" gui --minimized'

    # Development checkout: prefer pythonw.exe so no console window appears.
    interpreter = Path(sys.executable)
    windowless = interpreter.with_name("pythonw.exe")
    if windowless.exists():
        interpreter = windowless
    return f'"{interpreter}" -m autolevel gui --minimized'


def current_command(key_path: str = RUN_KEY, value_name: str = VALUE_NAME) -> str | None:
    """The registered logon command, or None if there isn't one."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, value_name)
            return str(value)
    except FileNotFoundError:
        return None
    except OSError:
        return None


def is_enabled(key_path: str = RUN_KEY, value_name: str = VALUE_NAME) -> bool:
    return current_command(key_path, value_name) is not None


def is_current(key_path: str = RUN_KEY, value_name: str = VALUE_NAME) -> bool:
    """True if the registered command still points at this build.

    Moving or rebuilding the exe leaves a stale entry behind, which would fail
    silently at the next logon.
    """
    registered = current_command(key_path, value_name)
    return registered is not None and registered == launch_command()


def enable(key_path: str = RUN_KEY, value_name: str = VALUE_NAME) -> str:
    """Register for logon start. Returns the command written."""
    command = launch_command()
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, command)
    return command


def disable(key_path: str = RUN_KEY, value_name: str = VALUE_NAME) -> bool:
    """Remove the logon entry. True if one was actually removed."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, value_name)
            return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_enabled(enabled: bool, key_path: str = RUN_KEY, value_name: str = VALUE_NAME) -> bool:
    if enabled:
        enable(key_path, value_name)
        return True
    return disable(key_path, value_name)
