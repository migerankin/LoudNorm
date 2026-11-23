import pytest

from autolevel.boost import settings_from_config
from autolevel.cli import _apply_overrides, build_parser, cmd_boost
from autolevel.config import Config
from autolevel.settingsui import GROUPS


class _NonStoppingBoostSession:
    status = ""
    bridge = None
    start_error = None

    def __init__(self, config, dry_run=False):
        pass

    def start(self):
        if self.start_error is not None:
            raise RuntimeError(self.start_error)

    def close(self):
        return False


class _CloseRaisingBoostSession:
    status = ""
    start_exception = None

    class Bridge:
        error = None
        frames_processed = 960
        max_output_peak = 0.25

        class Processor:
            applied_gain_db = 6.0

        processor = Processor()

    def __init__(self, config, dry_run=False):
        self.bridge = self.Bridge()

    def start(self):
        if self.start_exception is not None:
            raise self.start_exception

    def close(self):
        raise RuntimeError("close failed")


def test_bridge_settings_are_copied_from_config():
    config = Config(
        boost_source_device="CABLE Input",
        boost_output_device="USB Speakers",
        boost_gain_db=9.0,
        boost_ceiling_db=-2.0,
        boost_sample_rate=44_100,
        boost_block_frames=256,
    )

    settings = settings_from_config(config)

    assert settings.source_device == "CABLE Input"
    assert settings.output_device == "USB Speakers"
    assert settings.gain_db == 9.0
    assert settings.ceiling_db == -2.0
    assert settings.sample_rate == 44_100
    assert settings.block_frames == 256


def test_cli_run_can_enable_and_configure_true_boost():
    args = build_parser().parse_args(
        [
            "run",
            "--boost",
            "--boost-source",
            "CABLE Input",
            "--boost-output",
            "USB Speakers",
            "--boost-gain",
            "10",
        ]
    )
    config = Config()

    _apply_overrides(config, args)

    assert config.boost_enabled
    assert config.boost_source_device == "CABLE Input"
    assert config.boost_output_device == "USB Speakers"
    assert config.boost_gain_db == 10.0


def test_cli_has_a_boost_device_discovery_command():
    args = build_parser().parse_args(["boost"])

    assert args.command == "boost"


def test_settings_panel_declares_a_true_boost_tab():
    groups = {title: {setting.key: setting for setting in settings} for title, settings in GROUPS}

    assert {
        "boost_enabled",
        "boost_source_device",
        "boost_output_device",
        "boost_gain_db",
        "boost_ceiling_db",
        "boost_sample_rate",
        "boost_block_frames",
    } <= set(groups["增强"])
    assert groups["增强"]["boost_source_device"].kind == "text"
    assert groups["增强"]["boost_sample_rate"].kind == "int"


def test_boost_command_accepts_endpoint_stream_check():
    args = build_parser().parse_args([
        "boost", "--check",
        "--boost-source", "CABLE Input",
        "--boost-output", "Speakers",
        "--boost-gain", "9",
        "--seconds", "0.25",
    ])

    assert args.check is True
    assert args.boost_source == "CABLE Input"
    assert args.boost_output == "Speakers"
    assert args.boost_gain == 9.0
    assert args.seconds == 0.25


def test_boost_stream_check_reports_processed_audio(monkeypatch, capsys):
    import autolevel.boost as boost

    class FakeProcessor:
        applied_gain_db = 6.0

    class FakeBridge:
        error = None
        frames_processed = 960
        max_output_peak = 0.25
        processor = FakeProcessor()

    class FakeSession:
        def __init__(self, config):
            assert config.boost_enabled is True
            assert config.boost_source_device == "CABLE Input"
            self.bridge = FakeBridge()

        def start(self):
            pass

        def close(self):
            return True

    monkeypatch.setattr(boost, "BoostSession", FakeSession)
    monkeypatch.setattr(boost, "list_output_devices", lambda: [])
    args = build_parser().parse_args([
        "boost", "--check", "--boost-source", "CABLE Input", "--seconds", "0"
    ])

    assert cmd_boost(args, Config()) == 0
    output = capsys.readouterr().out
    assert "960 帧" in output
    assert "峰值 0.250000" in output
    assert "+6.00 dB" in output


def test_boost_stream_check_reports_shutdown_failure(monkeypatch, capsys):
    import autolevel.boost as boost

    class FakeBridge:
        error = None
        frames_processed = 1
        max_output_peak = 0.0
        processor = type("Processor", (), {"applied_gain_db": 6.0})()

    class FakeSession:
        def __init__(self, config):
            self.bridge = FakeBridge()

        def start(self):
            pass

        def close(self):
            return False

    monkeypatch.setattr(boost, "BoostSession", FakeSession)
    monkeypatch.setattr(boost, "list_output_devices", lambda: [])
    args = build_parser().parse_args([
        "boost", "--check", "--boost-source", "CABLE Input", "--seconds", "0"
    ])

    assert cmd_boost(args, Config()) == 1
    assert "未能停止" in capsys.readouterr().err


def test_run_closes_boost_when_session_registry_startup_fails(monkeypatch):
    import autolevel.boost as boost
    import autolevel.cli as cli

    closed = []

    class FakeBoostSession:
        status = ""

        def __init__(self, config, dry_run=False):
            pass

        def start(self):
            pass

        def close(self):
            closed.append(True)

    def fail_registry(*args, **kwargs):
        raise RuntimeError("registry failed")

    monkeypatch.setattr(boost, "BoostSession", FakeBoostSession)
    monkeypatch.setattr(cli, "SessionRegistry", fail_registry)
    args = build_parser().parse_args(["run"])

    with pytest.raises(RuntimeError, match="registry failed"):
        cli.cmd_run(args, Config())

    assert closed == [True]


def test_run_reports_a_boost_bridge_that_did_not_stop(monkeypatch, capsys):
    import autolevel.boost as boost
    import autolevel.cli as cli

    class FakeBoostSession:
        status = ""

        def __init__(self, config, dry_run=False):
            pass

        def start(self):
            pass

        def close(self):
            return False

    class FakeBalancer:
        def __init__(self, config, registry, dry_run=False):
            pass

        def run(self, on_update=None):
            pass

    monkeypatch.setattr(boost, "BoostSession", FakeBoostSession)
    monkeypatch.setattr(cli, "SessionRegistry", lambda **kwargs: object())
    monkeypatch.setattr(cli, "Balancer", FakeBalancer)
    args = build_parser().parse_args(["run"])

    assert cli.cmd_run(args, Config(restore_on_exit=False)) == 1
    assert "未能停止" in capsys.readouterr().err


def test_run_reports_shutdown_failure_after_boost_start_error(monkeypatch, capsys):
    import autolevel.boost as boost
    import autolevel.cli as cli

    class FailedStart(_NonStoppingBoostSession):
        start_error = "start failed"

    monkeypatch.setattr(boost, "BoostSession", FailedStart)
    args = build_parser().parse_args(["run"])

    assert cli.cmd_run(args, Config()) == 1
    error = capsys.readouterr().err
    assert "start failed" in error
    assert "未能停止" in error


def test_run_reports_shutdown_failure_after_unexpected_start_error(monkeypatch, capsys):
    import autolevel.boost as boost
    import autolevel.cli as cli

    class FailedStart(_NonStoppingBoostSession):
        def start(self):
            raise ValueError("unexpected start failure")

    monkeypatch.setattr(boost, "BoostSession", FailedStart)
    args = build_parser().parse_args(["run"])

    with pytest.raises(ValueError, match="unexpected start failure"):
        cli.cmd_run(args, Config())
    assert "未能停止" in capsys.readouterr().err


def test_run_reports_shutdown_failure_after_registry_error(monkeypatch, capsys):
    import autolevel.boost as boost
    import autolevel.cli as cli

    monkeypatch.setattr(boost, "BoostSession", _NonStoppingBoostSession)
    monkeypatch.setattr(
        cli,
        "SessionRegistry",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("registry failed")),
    )
    args = build_parser().parse_args(["run"])

    with pytest.raises(RuntimeError, match="registry failed"):
        cli.cmd_run(args, Config())
    assert "未能停止" in capsys.readouterr().err


def test_run_reports_shutdown_failure_after_balancer_error(monkeypatch, capsys):
    import autolevel.boost as boost
    import autolevel.cli as cli

    restored = []

    class FakeRegistry:
        def restore_all(self):
            restored.append(True)
            return 0

    class FakeBalancer:
        def __init__(self, config, registry, dry_run=False):
            pass

        def run(self, on_update=None):
            raise RuntimeError("balance failed")

    monkeypatch.setattr(boost, "BoostSession", _NonStoppingBoostSession)
    monkeypatch.setattr(cli, "SessionRegistry", lambda **kwargs: FakeRegistry())
    monkeypatch.setattr(cli, "Balancer", FakeBalancer)
    args = build_parser().parse_args(["run"])

    with pytest.raises(RuntimeError, match="balance failed"):
        cli.cmd_run(args, Config())
    assert "未能停止" in capsys.readouterr().err
    assert restored == [True]


def test_run_reports_shutdown_failure_after_autopause_error(monkeypatch, capsys):
    import autolevel.boost as boost
    import autolevel.cli as cli
    import autolevel.mediasessions as mediasessions

    restored = []

    class FakeRegistry:
        def restore_all(self):
            restored.append(True)
            return 0

    monkeypatch.setattr(boost, "BoostSession", _NonStoppingBoostSession)
    monkeypatch.setattr(cli, "SessionRegistry", lambda **kwargs: FakeRegistry())
    monkeypatch.setattr(cli, "Balancer", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        mediasessions,
        "MediaController",
        lambda: (_ for _ in ()).throw(RuntimeError("media failed")),
    )
    args = build_parser().parse_args(["run"])

    with pytest.raises(RuntimeError, match="media failed"):
        cli.cmd_run(args, Config(autopause_enabled=True))
    assert "未能停止" in capsys.readouterr().err
    assert restored == []


def test_run_reports_shutdown_failure_after_media_availability_error(monkeypatch, capsys):
    import autolevel.boost as boost
    import autolevel.cli as cli
    import autolevel.mediasessions as mediasessions

    class FakeController:
        @property
        def available(self):
            raise RuntimeError("availability failed")

        def close(self):
            pass

    monkeypatch.setattr(boost, "BoostSession", _NonStoppingBoostSession)
    monkeypatch.setattr(cli, "SessionRegistry", lambda **kwargs: object())
    monkeypatch.setattr(cli, "Balancer", lambda *args, **kwargs: object())
    monkeypatch.setattr(mediasessions, "MediaController", FakeController)
    args = build_parser().parse_args(["run"])

    with pytest.raises(RuntimeError, match="availability failed"):
        cli.cmd_run(args, Config(autopause_enabled=True))
    assert "未能停止" in capsys.readouterr().err


def test_boost_check_reports_shutdown_failure_after_start_error(monkeypatch, capsys):
    import autolevel.boost as boost

    class FailedStart(_NonStoppingBoostSession):
        start_error = "start failed"

    monkeypatch.setattr(boost, "BoostSession", FailedStart)
    monkeypatch.setattr(boost, "list_output_devices", lambda: [])
    args = build_parser().parse_args(
        ["boost", "--check", "--boost-source", "CABLE Input", "--seconds", "0"]
    )

    assert cmd_boost(args, Config()) == 1
    error = capsys.readouterr().err
    assert "start failed" in error
    assert "未能停止" in error


def test_boost_check_reports_shutdown_failure_after_unexpected_start_error(
    monkeypatch, capsys
):
    import autolevel.boost as boost

    class FailedStart(_NonStoppingBoostSession):
        def start(self):
            raise ValueError("unexpected start failure")

    monkeypatch.setattr(boost, "BoostSession", FailedStart)
    monkeypatch.setattr(boost, "list_output_devices", lambda: [])
    args = build_parser().parse_args(
        ["boost", "--check", "--boost-source", "CABLE Input", "--seconds", "0"]
    )

    with pytest.raises(ValueError, match="unexpected start failure"):
        cmd_boost(args, Config())
    assert "未能停止" in capsys.readouterr().err


def test_boost_check_reports_shutdown_failure_when_interrupted(monkeypatch, capsys):
    import autolevel.boost as boost
    import autolevel.cli as cli

    monkeypatch.setattr(boost, "BoostSession", _NonStoppingBoostSession)
    monkeypatch.setattr(boost, "list_output_devices", lambda: [])
    monkeypatch.setattr(
        cli.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    args = build_parser().parse_args(
        ["boost", "--check", "--boost-source", "CABLE Input", "--seconds", "1"]
    )

    with pytest.raises(KeyboardInterrupt):
        cmd_boost(args, Config())
    assert "未能停止" in capsys.readouterr().err


def _close_error_check_args(seconds="0"):
    return build_parser().parse_args(
        ["boost", "--check", "--boost-source", "CABLE Input", "--seconds", seconds]
    )


def test_boost_check_reports_close_exception_on_normal_exit(monkeypatch, capsys):
    import autolevel.boost as boost

    monkeypatch.setattr(boost, "BoostSession", _CloseRaisingBoostSession)
    monkeypatch.setattr(boost, "list_output_devices", lambda: [])

    assert cmd_boost(_close_error_check_args(), Config()) == 1
    assert "close failed" in capsys.readouterr().err


def test_boost_check_reports_close_exception_after_start_error(monkeypatch, capsys):
    import autolevel.boost as boost

    class FailedStart(_CloseRaisingBoostSession):
        start_exception = RuntimeError("start failed")

    monkeypatch.setattr(boost, "BoostSession", FailedStart)
    monkeypatch.setattr(boost, "list_output_devices", lambda: [])

    assert cmd_boost(_close_error_check_args(), Config()) == 1
    error = capsys.readouterr().err
    assert "start failed" in error
    assert "close failed" in error


def test_boost_check_preserves_unexpected_error_when_close_raises(monkeypatch, capsys):
    import autolevel.boost as boost

    class FailedStart(_CloseRaisingBoostSession):
        start_exception = ValueError("unexpected start failure")

    monkeypatch.setattr(boost, "BoostSession", FailedStart)
    monkeypatch.setattr(boost, "list_output_devices", lambda: [])

    with pytest.raises(ValueError, match="unexpected start failure"):
        cmd_boost(_close_error_check_args(), Config())
    assert "close failed" in capsys.readouterr().err


def test_boost_check_preserves_interrupt_when_close_raises(monkeypatch, capsys):
    import autolevel.boost as boost
    import autolevel.cli as cli

    monkeypatch.setattr(boost, "BoostSession", _CloseRaisingBoostSession)
    monkeypatch.setattr(boost, "list_output_devices", lambda: [])
    monkeypatch.setattr(
        cli.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    with pytest.raises(KeyboardInterrupt):
        cmd_boost(_close_error_check_args("1"), Config())
    assert "close failed" in capsys.readouterr().err


def test_run_restores_volumes_when_close_raises(monkeypatch, capsys):
    import autolevel.boost as boost
    import autolevel.cli as cli

    restored = []

    class FakeRegistry:
        def restore_all(self):
            restored.append(True)
            return 1

    class FailedBalancer:
        def __init__(self, config, registry, dry_run=False):
            pass

        def run(self, on_update=None):
            raise ValueError("balance failed")

    monkeypatch.setattr(boost, "BoostSession", _CloseRaisingBoostSession)
    monkeypatch.setattr(cli, "SessionRegistry", lambda **kwargs: FakeRegistry())
    monkeypatch.setattr(cli, "Balancer", FailedBalancer)
    args = build_parser().parse_args(["run"])

    with pytest.raises(ValueError, match="balance failed"):
        cli.cmd_run(args, Config())
    assert restored == [True]
    assert "close failed" in capsys.readouterr().err
