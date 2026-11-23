import os
from types import SimpleNamespace

from autolevel.sessions import SessionRegistry


def test_registry_skips_the_current_process_before_scope_matching(monkeypatch):
    checked_names = []
    raw = SimpleNamespace(
        Process=SimpleNamespace(name=lambda: "autolevel.exe", pid=os.getpid())
    )
    monkeypatch.setattr(
        "autolevel.sessions.AudioUtilities.GetAllSessions", lambda: [raw]
    )

    registry = SessionRegistry(manages=lambda name: checked_names.append(name) or True)
    added, removed = registry.refresh()

    assert added == []
    assert removed == []
    assert checked_names == []
