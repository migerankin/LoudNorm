"""Real registry round trips, against a scratch key.

Deliberately not mocked -- the value of this module is that it talks to the
actual registry correctly. SCRATCH_KEY is under the user's own hive and is
removed after each test, so the real logon entry is never touched.
"""

import sys
import winreg

import pytest

from autolevel import startup

SCRATCH_KEY = r"Software\autolevel-test"
VALUE = "autolevel-pytest"


@pytest.fixture(autouse=True)
def clean_scratch_key():
    yield
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, SCRATCH_KEY)
    except OSError:
        pass


def test_absent_entry_reads_as_disabled():
    assert not startup.is_enabled(SCRATCH_KEY, VALUE)
    assert startup.current_command(SCRATCH_KEY, VALUE) is None


def test_enable_then_disable_round_trip():
    written = startup.enable(SCRATCH_KEY, VALUE)
    assert startup.is_enabled(SCRATCH_KEY, VALUE)
    assert startup.current_command(SCRATCH_KEY, VALUE) == written

    assert startup.disable(SCRATCH_KEY, VALUE) is True
    assert not startup.is_enabled(SCRATCH_KEY, VALUE)


def test_disable_is_idempotent():
    assert startup.disable(SCRATCH_KEY, VALUE) is False


def test_enable_twice_does_not_duplicate():
    startup.enable(SCRATCH_KEY, VALUE)
    startup.enable(SCRATCH_KEY, VALUE)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, SCRATCH_KEY) as key:
        assert winreg.QueryInfoKey(key)[1] == 1


def test_set_enabled_matches_explicit_calls():
    startup.set_enabled(True, SCRATCH_KEY, VALUE)
    assert startup.is_enabled(SCRATCH_KEY, VALUE)
    startup.set_enabled(False, SCRATCH_KEY, VALUE)
    assert not startup.is_enabled(SCRATCH_KEY, VALUE)


def test_stale_entry_is_detected():
    """A moved or rebuilt exe must not be reported as correctly registered."""
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, SCRATCH_KEY, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, VALUE, 0, winreg.REG_SZ, r'"C:\old\path\autolevel-gui.exe"')

    assert startup.is_enabled(SCRATCH_KEY, VALUE)
    assert not startup.is_current(SCRATCH_KEY, VALUE)


def test_fresh_entry_is_current():
    startup.enable(SCRATCH_KEY, VALUE)
    assert startup.is_current(SCRATCH_KEY, VALUE)


# --- the command itself ----------------------------------------------------- #

def test_command_starts_minimized():
    """Logon start must go straight to the tray and begin balancing."""
    assert "--minimized" in startup.launch_command()


def test_command_quotes_the_executable():
    """Program Files has a space in it."""
    assert startup.launch_command().startswith('"')


def test_dev_command_invokes_the_gui_subcommand():
    if startup.is_frozen():
        pytest.skip("running frozen; there is no dev command form")
    command = startup.launch_command()
    assert "-m autolevel gui" in command


def test_frozen_gui_build_takes_minimized_directly(monkeypatch, tmp_path):
    exe = tmp_path / "autolevel-gui.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))

    assert startup.launch_command() == f'"{exe}" --minimized'


def test_frozen_console_build_prefers_the_gui_exe_beside_it(monkeypatch, tmp_path):
    console = tmp_path / "autolevel.exe"
    windowed = tmp_path / "autolevel-gui.exe"
    console.write_bytes(b"")
    windowed.write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(console))

    assert startup.launch_command() == f'"{windowed}" --minimized'


def test_lone_console_build_gets_its_subcommand(monkeypatch, tmp_path):
    """Registering the console exe bare would fail silently at every logon."""
    console = tmp_path / "autolevel.exe"
    console.write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(console))

    assert startup.launch_command() == f'"{console}" gui --minimized'


def test_dev_command_prefers_a_windowless_interpreter():
    if startup.is_frozen():
        pytest.skip("running frozen")
    from pathlib import Path

    if not Path(sys.executable).with_name("pythonw.exe").exists():
        pytest.skip("no pythonw.exe alongside this interpreter")
    assert "pythonw.exe" in startup.launch_command()
