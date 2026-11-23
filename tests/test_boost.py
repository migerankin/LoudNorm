import threading

import numpy as np
import pytest

from autolevel.boost import (
    BoostBridge,
    BoostProcessor,
    BoostSession,
    BoostSettings,
    list_output_devices,
)
from autolevel.config import Config


def test_processor_applies_true_gain_above_unity():
    processor = BoostProcessor(gain_db=12.0, ceiling_db=-1.0)
    source = np.full((32, 2), 0.1, dtype=np.float32)

    result = processor.process(source, sample_rate=48_000)

    assert result[0, 0] == pytest.approx(0.3981, rel=1e-3)
    assert processor.applied_gain_db == pytest.approx(12.0, abs=0.01)


def test_processor_limits_hot_audio_before_it_clips():
    processor = BoostProcessor(gain_db=12.0, ceiling_db=-1.0)
    source = np.full((32, 2), 0.5, dtype=np.float32)

    result = processor.process(source, sample_rate=48_000)

    assert np.max(np.abs(result)) <= 10 ** (-1.0 / 20.0)
    assert processor.limiter_reduction_db < 0.0


def test_processor_does_not_mutate_capture_buffer():
    processor = BoostProcessor(gain_db=6.0, ceiling_db=-1.0)
    source = np.full((8, 2), 0.1, dtype=np.float32)
    original = source.copy()

    processor.process(source, sample_rate=48_000)

    np.testing.assert_array_equal(source, original)


@pytest.mark.parametrize(
    ("gain_db", "ceiling_db"),
    [
        (float("nan"), -1.0),
        (float("inf"), -1.0),
        (6.0, float("nan")),
        (6.0, float("-inf")),
    ],
)
def test_processor_rejects_non_finite_settings(gain_db, ceiling_db):
    with pytest.raises(ValueError, match="有限"):
        BoostProcessor(gain_db=gain_db, ceiling_db=ceiling_db)


def test_processor_rejects_overflowing_finite_gain():
    with pytest.raises(ValueError, match="增益"):
        BoostProcessor(gain_db=1e308)


def test_processor_sanitizes_non_finite_capture_samples():
    processor = BoostProcessor(gain_db=6.0, ceiling_db=-1.0)
    source = np.array([[np.nan, np.inf], [-np.inf, 0.5]], dtype=np.float32)

    result = processor.process(source, sample_rate=48_000)

    assert np.all(np.isfinite(result))
    assert np.max(np.abs(result)) <= 10 ** (-1.0 / 20.0)


class FakeEndpoint:
    def __init__(self, endpoint_id, name, isloopback=False):
        self.id = endpoint_id
        self.name = name
        self.isloopback = isloopback


class FakeRecorder:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def record(self, numframes):
        return np.full((numframes, 2), 0.1, dtype=np.float32)


class FakePlayer:
    def __init__(self, played):
        self.played = played

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def play(self, data):
        self.played.append(data.copy())


class FakeLoopback(FakeEndpoint):
    def recorder(self, **_kwargs):
        return FakeRecorder()


class FakeSpeaker(FakeEndpoint):
    def __init__(self, endpoint_id, name, played):
        super().__init__(endpoint_id, name)
        self._played = played

    def player(self, **_kwargs):
        return FakePlayer(self._played)


class FakeAudio:
    def __init__(self):
        self.played = []
        self.source = FakeLoopback("source-id", "CABLE Input", isloopback=True)
        self.output = FakeSpeaker("output-id", "Speakers", self.played)

    def all_speakers(self):
        return [FakeEndpoint(self.source.id, self.source.name), self.output]

    def all_microphones(self, include_loopback=False):
        assert include_loopback
        return [self.source]

    def default_speaker(self):
        return self.output


def test_device_listing_marks_default_and_loopback_capability():
    devices = list_output_devices(FakeAudio())

    assert [(d.name, d.is_default, d.can_loopback) for d in devices] == [
        ("CABLE Input", False, True),
        ("Speakers", True, False),
    ]


def test_bridge_captures_amplifies_and_renders_until_stopped(monkeypatch):
    import autolevel.boost as boost

    com_calls = []

    def initialize_com():
        com_calls.append(("init", threading.get_ident()))

        def uninitialize():
            com_calls.append(("uninit", threading.get_ident()))

        return uninitialize

    monkeypatch.setattr(boost, "_initialize_com", initialize_com)
    audio = FakeAudio()
    settings = BoostSettings(
        source_device="CABLE Input",
        output_device="Speakers",
        gain_db=6.0,
        ceiling_db=-1.0,
        sample_rate=48_000,
        block_frames=64,
    )
    bridge = BoostBridge(settings, audio=audio)

    bridge.start()
    assert bridge.ready.wait(1.0)
    while not audio.played:
        threading.Event().wait(0.001)
    bridge.stop()
    bridge.join(1.0)

    assert bridge.error is None
    assert not bridge.is_alive()
    assert audio.played[0][0, 0] == pytest.approx(0.1995, rel=1e-3)
    assert bridge.frames_processed >= 64
    assert bridge.max_output_peak == pytest.approx(0.1995, rel=1e-3)
    assert [action for action, _ in com_calls] == ["init", "uninit"]
    assert com_calls[0][1] == com_calls[1][1]


def test_bridge_rejects_using_the_same_endpoint_for_source_and_output():
    audio = FakeAudio()
    settings = BoostSettings(
        source_device="CABLE Input",
        output_device="CABLE Input",
        gain_db=6.0,
    )
    bridge = BoostBridge(settings, audio=audio)

    bridge.start()
    bridge.join(1.0)

    assert isinstance(bridge.error, ValueError)
    assert "必须" in str(bridge.error)


class FakeBridge:
    def __init__(self, error=None, alive=False):
        self.ready = threading.Event()
        self.error = error
        self.alive = alive
        self.started = False
        self.stopped = False
        self.joined = False
        self.status = "Boosting +6.0 dB"

    def start(self):
        self.started = True
        self.ready.set()

    def stop(self):
        self.stopped = True

    def join(self, _timeout=None):
        self.joined = True

    def is_alive(self):
        return self.alive


def test_boost_session_starts_and_cleans_up_an_enabled_bridge():
    bridge = FakeBridge()
    config = Config(boost_enabled=True, boost_source_device="CABLE Input")
    session = BoostSession(config, bridge_factory=lambda _settings: bridge)

    session.start()
    session.close()

    assert bridge.started
    assert bridge.stopped
    assert bridge.joined


def test_boost_session_does_nothing_in_dry_run():
    created = []
    config = Config(boost_enabled=True, boost_source_device="CABLE Input")
    session = BoostSession(config, dry_run=True, bridge_factory=created.append)

    session.start()

    assert created == []
    assert session.status == "试运行中不启用增强"


def test_boost_session_surfaces_stream_startup_errors_and_cleans_up():
    bridge = FakeBridge(ValueError("missing endpoint"))
    config = Config(boost_enabled=True, boost_source_device="CABLE Input")
    session = BoostSession(config, bridge_factory=lambda _settings: bridge)

    with pytest.raises(RuntimeError, match="missing endpoint"):
        session.start()

    assert bridge.stopped
    assert bridge.joined


def test_boost_session_cleans_up_when_thread_start_fails(monkeypatch):
    config = Config(boost_enabled=True, boost_source_device="CABLE Input")
    session = BoostSession(config)

    def fail_start(_thread):
        raise RuntimeError("cannot start worker thread")

    monkeypatch.setattr(threading.Thread, "start", fail_start)

    with pytest.raises(RuntimeError, match="cannot start worker thread"):
        session.start()

    assert session.bridge is None
    assert session.close() is True


def test_boost_session_retains_a_bridge_that_did_not_stop():
    bridge = FakeBridge(alive=True)
    config = Config(boost_enabled=True, boost_source_device="CABLE Input")
    session = BoostSession(config, bridge_factory=lambda _settings: bridge)
    session.start()

    assert session.close() is False
    assert session.bridge is bridge
    assert "停止" in session.status
    with pytest.raises(RuntimeError, match="仍在停止中"):
        session.start()

    bridge.alive = False
    assert session.close() is True
    assert session.bridge is None
