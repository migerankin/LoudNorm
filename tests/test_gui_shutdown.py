import queue
from types import SimpleNamespace

from autolevel.config import Config
from autolevel.gui import AutoLevelWindow, BalancerThread


class FakeWidget:
    def __init__(self):
        self.calls = []

    def config(self, **kwargs):
        self.calls.append(kwargs)


class FakeTray:
    available = True

    def __init__(self):
        self.calls = []

    def set_balancing(self, *args):
        self.calls.append(("set_balancing", args))

    def stop(self):
        self.calls.append(("stop", ()))


class BlockedThread:
    restored = 0
    error = None
    media_error = None

    def __init__(self):
        self.stopped = False
        self.joined = False
        self.alive = True

    def stop(self):
        self.stopped = True

    def join(self, timeout=None):
        self.joined = timeout

    def is_alive(self):
        return self.alive


def test_gui_stop_retains_a_worker_that_is_still_alive():
    thread = BlockedThread()
    scheduled = []
    window = SimpleNamespace(
        _thread=thread,
        status=FakeWidget(),
        start_button=FakeWidget(),
        autopause_status=FakeWidget(),
        tray=FakeTray(),
        tray_state={"balancing": True},
        after=lambda delay, callback: scheduled.append((delay, callback)),
    )

    stopped = AutoLevelWindow._stop(window)

    assert stopped is False
    assert window._thread is thread
    assert scheduled
    assert not window.tray.calls


def test_gui_quit_waits_for_a_worker_that_is_still_stopping():
    calls = []
    window = SimpleNamespace(
        _quitting=True,
        _thread=object(),
        config_obj=SimpleNamespace(close_to_tray=True),
        tray=FakeTray(),
        status=FakeWidget(),
        update_idletasks=lambda: None,
        _stop=lambda: False,
        destroy=lambda: calls.append("destroy"),
        hide_window=lambda: calls.append("hide"),
    )

    AutoLevelWindow._on_close(window)

    assert calls == []
    assert window.tray.calls == []


def test_non_tray_window_close_finishes_after_deferred_worker_stop():
    calls = []
    scheduled = []
    thread = BlockedThread()
    tray = FakeTray()
    tray.available = False
    window = SimpleNamespace(
        _quitting=False,
        _thread=thread,
        config_obj=SimpleNamespace(close_to_tray=False),
        tray=tray,
        tray_state={"balancing": True},
        status=FakeWidget(),
        start_button=FakeWidget(),
        autopause_status=FakeWidget(),
        update_idletasks=lambda: None,
        after=lambda delay, callback: scheduled.append((delay, callback)),
        destroy=lambda: calls.append("destroy"),
        hide_window=lambda: calls.append("hide"),
    )
    window._stop = lambda: AutoLevelWindow._stop(window)
    window._finish_stop = lambda: AutoLevelWindow._finish_stop(window)

    AutoLevelWindow._on_close(window)

    assert calls == []
    assert window._quitting is True
    thread.alive = False
    AutoLevelWindow._poll_stop(window)
    assert calls == ["destroy"]
    assert ("stop", ()) in tray.calls


def test_balancer_worker_waits_for_the_boost_stream_to_close(monkeypatch):
    import autolevel.gui as gui
    import autolevel.mediasessions as mediasessions

    close_timeouts = []

    class FakeBoostSession:
        status = ""

        def __init__(self, config, dry_run=False):
            pass

        def start(self):
            pass

        def close(self, timeout=3.0):
            close_timeouts.append(timeout)
            return True

    class FakeBalancer:
        def __init__(self, config, registry, dry_run=False):
            pass

        def run(self, on_update=None, should_stop=None):
            pass

    class FakeController:
        available = True
        error = None

        def close(self):
            pass

    class FakeRunner:
        def __init__(self, settings, controller, balancer):
            pass

        def shutdown(self):
            pass

    monkeypatch.setattr(gui, "BoostSession", FakeBoostSession)
    monkeypatch.setattr(gui, "SessionRegistry", lambda **kwargs: object())
    monkeypatch.setattr(gui, "Balancer", FakeBalancer)
    monkeypatch.setattr(gui, "AutoPauseRunner", FakeRunner)
    monkeypatch.setattr(mediasessions, "MediaController", FakeController)

    BalancerThread(Config(), queue.Queue(), dry_run=True).run()

    assert close_timeouts == [None]
