"""Command line interface."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

from .autopause import AutoPauseRunner, settings_from_config
from .balancer import Balancer, observe
from .config import Config, default_config_path
from .dsp import amp_to_db
from .sessions import SessionRegistry
from .text import pad

METER_FLOOR_DB = -60.0
METER_WIDTH = 24


def _enable_ansi() -> None:
    try:
        import colorama

        colorama.just_fix_windows_console()
    except Exception:
        # Windows Terminal and modern conhost handle VT without help.
        pass


def _meter_bar(level_db: float | None, width: int = METER_WIDTH) -> str:
    if level_db is None or level_db <= METER_FLOOR_DB:
        return "." * width
    filled = round((level_db - METER_FLOOR_DB) / (0.0 - METER_FLOOR_DB) * width)
    filled = max(0, min(width, filled))
    return "#" * filled + "." * (width - filled)


def _format_db(value: float | None) -> str:
    if value is None or value <= METER_FLOOR_DB:
        return "   --  "
    return f"{value:6.1f} "


class LiveTable:
    """Redraws a fixed block of lines in place, without clearing the screen."""

    def __init__(self, min_interval_s: float = 0.1):
        self.min_interval_s = min_interval_s
        self._last_draw = 0.0
        self._last_lines = 0

    def draw(self, lines: list[str], force: bool = False) -> None:
        now = time.perf_counter()
        if not force and now - self._last_draw < self.min_interval_s:
            return
        self._last_draw = now

        out = []
        if self._last_lines:
            out.append(f"\x1b[{self._last_lines}A")
        for line in lines:
            out.append("\x1b[2K" + line + "\n")
        # Wipe leftovers if the table shrank (an app closed).
        for _ in range(max(0, self._last_lines - len(lines))):
            out.append("\x1b[2K\n")
        if self._last_lines > len(lines):
            out.append(f"\x1b[{self._last_lines - len(lines)}A")

        sys.stdout.write("".join(out))
        sys.stdout.flush()
        self._last_lines = len(lines)


def _table_lines(states, config: Config, header_note: str, extra: str | None = None) -> list[str]:
    lines = [
        header_note,
        extra if extra is not None else "",
        f"  {pad('应用', 22)} {pad('电平', 7, 'right')} {pad('增益', 7, 'right')}  "
        f"{pad('电平条', METER_WIDTH)}  状态",
        f"  {'-' * 22} {'-' * 7} {'-' * 7}  {'-' * METER_WIDTH}  ------",
    ]
    if not states:
        lines.append("  (暂无应用在播放音频)")
    for state in states:
        gain = f"{state.gain_db:6.1f} " if state.session.adjusted or state.gain_db else "   0.0 "
        status = "已压低" if state.duck_db else state.status
        lines.append(
            f"  {state.name[:22]:<22} {_format_db(state.level_db)}{gain}"
            f" {_meter_bar(state.level_db)}  {status}"
        )
    lines.append("")
    lines.append(f"  目标 {config.target_db:.1f} dBFS   Ctrl+C 停止")
    return lines


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #

def cmd_list(args, config: Config) -> int:
    registry = SessionRegistry(manages=config.manages)
    rows = observe(registry, config)
    if not rows:
        print("当前没有任何应用存在音频会话。")
        return 0

    print(f"{pad('应用', 24)} {pad('峰值', 9, 'right')}  {pad('音量', 7, 'right')}")
    print(f"{'-' * 24} {'-' * 9}  {'-' * 7}")
    for name, peak_db, volume in rows:
        peak = "  --" if peak_db <= METER_FLOOR_DB else f"{peak_db:6.1f} dB"
        print(f"{name[:24]:<24} {peak:>9}  {volume * 100:6.0f}%")
    return 0


def cmd_monitor(args, config: Config) -> int:
    _enable_ansi()
    registry = SessionRegistry(manages=config.manages)
    balancer = Balancer(config, registry, dry_run=True)
    table = LiveTable()

    print("正在监看电平，不会修改任何音量。\n")
    try:
        balancer.run(
            on_update=lambda states: table.draw(
                _table_lines(states, config, "  监视模式 - 只读，不会修改任何设置")
            )
        )
    except KeyboardInterrupt:
        print("\n已停止。")
    return 0


def _peak_levels(states) -> dict:
    """Process name -> current peak dBFS, for voice-activity detection.

    Raw peak, not the balancer's settled envelope: voice needs to register
    within a fraction of a second, long before an app would be settled.
    """
    levels: dict[str, float] = {}
    for state in states:
        level_db = amp_to_db(state.peak)
        if level_db > levels.get(state.name, -999.0):
            levels[state.name] = level_db
    return levels


def _close_boost(boost, error_prefix: str = "增强出错") -> bool:
    try:
        stopped = boost.close()
    except Exception as exc:
        print(f"{error_prefix}：关闭失败：{exc}", file=sys.stderr)
        return False
    if not stopped:
        print(f"{error_prefix}：音频流未能停止", file=sys.stderr)
    return stopped


def cmd_run(args, config: Config) -> int:
    _enable_ansi()
    from .boost import BoostSession

    boost = BoostSession(config, dry_run=args.dry_run)
    registry = None
    runner = None
    controller = None
    balancer_started = False
    boost_stopped = True
    try:
        try:
            boost.start()
        except RuntimeError as exc:
            print(f"增强出错：{exc}", file=sys.stderr)
            return 1

        registry = SessionRegistry(manages=config.manages)
        balancer = Balancer(config, registry, dry_run=args.dry_run)
        table = LiveTable()

        if config.autopause_enabled:
            from .mediasessions import MediaController

            controller = MediaController()
            runner = AutoPauseRunner(settings_from_config(config), controller, balancer)
            if not controller.available:
                print(
                    "警告：媒体控制不可用，自动暂停不会生效 "
                    f"({controller.error})"
                )

        note = (
            "  试运行 - 仅显示将要应用的调整，不做任何修改"
            if args.dry_run
            else "  平衡中 - 正在调整各应用的音量"
        )
        print(
            f"目标 {config.target_db:.1f} dBFS。"
            "按 Ctrl+C 可恢复每个应用的原始音量。\n"
        )

        def on_update(states):
            activity = []
            if runner is not None:
                runner.tick(time.perf_counter(), _peak_levels(states))
                if runner.status:
                    activity.append(runner.status)
            if boost.status:
                activity.append(boost.status)
            extra = f"  {' | '.join(activity)}" if activity else ""
            table.draw(_table_lines(states, config, note, extra))

        try:
            balancer_started = True
            balancer.run(on_update=on_update)
        except KeyboardInterrupt:
            pass
    finally:
        boost_stopped = _close_boost(boost)
        if runner is not None:
            runner.shutdown()
        if controller is not None:
            controller.close()
        if registry is not None and balancer_started:
            if config.restore_on_exit and not args.dry_run:
                restored = registry.restore_all()
                print(f"\n已恢复 {restored} 个应用的原始音量。")
            else:
                print()
    if not boost_stopped:
        return 1
    return 0


def cmd_media(args, config: Config) -> int:
    """List media sessions so their app ids can be copied into the config."""
    from .mediasessions import STATUS_PLAYING, MediaController

    controller = MediaController()
    if not controller.available:
        print(f"媒体传输控制不可用：{controller.error}", file=sys.stderr)
        return 1

    sessions = controller.snapshot()
    controller.close()

    if not sessions:
        print("没有媒体会话。请先播放一段视频或音乐再试。")
        return 0

    print(f"{pad('应用 ID', 46)} {pad('状态', 8)} 正在播放")
    print(f"{'-' * 46} {'-' * 8} {'-' * 30}")
    for s in sessions:
        state = "播放中" if s.status == STATUS_PLAYING else "已暂停"
        print(f"{s.app_id[:46]:<46} {pad(state, 8)} {s.label[:40]}")

    print("\n把应用 ID 中有辨识度的片段填进 autopause_trigger / autopause_music 即可。")
    return 0


def cmd_boost(args, config: Config) -> int:
    """List endpoints used to route selected apps through true software gain."""
    from .boost import BoostSession, list_output_devices

    if args.open_mixer:
        os.startfile("ms-settings:apps-volume")

    devices = list_output_devices()
    print(f"{pad('输出端点', 50)} {pad('默认', 8)} 回环")
    print(f"{'-' * 50} {'-' * 8} {'-' * 8}")
    for device in devices:
        print(
            f"{device.name[:50]:<50} "
            f"{pad('是' if device.is_default else '', 8)} "
            f"{'是' if device.can_loopback else '否'}"
        )

    print("\n为选中的应用启用真实增强：")
    print("  1. 在 Windows 音量合成器中把这些应用路由到非默认的源端点。")
    print("  2. 把 boost_source_device 设为该端点名称。")
    print("  3. 把 boost_output_device 设为你的扬声器，然后启用 boost_enabled。")
    if config.boost_enabled:
        output = config.boost_output_device or "（默认扬声器）"
        print(
            f"\n当前配置：{config.boost_source_device} -> {output}，"
            f"+{config.boost_gain_db:.1f} dB"
        )

    if args.check:
        candidate = replace(
            config,
            boost_enabled=True,
            boost_source_device=args.boost_source or config.boost_source_device,
            boost_output_device=(
                args.boost_output
                if args.boost_output is not None
                else config.boost_output_device
            ),
            boost_gain_db=(
                args.boost_gain
                if args.boost_gain is not None
                else config.boost_gain_db
            ),
        )
        try:
            candidate.validate()
        except ValueError as exc:
            print(f"\n增强检查失败：{exc}", file=sys.stderr)
            return 2
        if args.seconds < 0:
            print("\n增强检查失败：--seconds 不能为负数", file=sys.stderr)
            return 2

        session = BoostSession(candidate)
        bridge = None
        stopped = True
        failed = False
        try:
            session.start()
            bridge = session.bridge
            time.sleep(args.seconds)
        except RuntimeError as exc:
            print(f"\n增强检查失败：{exc}", file=sys.stderr)
            failed = True
        finally:
            stopped = _close_boost(session, "\n增强检查失败")

        if failed or not stopped:
            return 1
        if bridge is None or bridge.error is not None:
            detail = bridge.error if bridge is not None else "桥接未能启动"
            print(f"\n增强检查失败：{detail}", file=sys.stderr)
            return 1
        print(
            f"\n增强检查通过：{bridge.frames_processed} 帧，"
            f"峰值 {bridge.max_output_peak:.6f}，"
            f"实际增益 {bridge.processor.applied_gain_db:+.2f} dB"
        )
    return 0


def cmd_gui(args, config: Config) -> int:
    from .gui import run_gui

    return run_gui(config, start_minimized=args.minimized)


def cmd_profiles(args, config: Config) -> int:
    from .profiles import MODIFIED_SUFFIX, ProfileLibrary

    library = ProfileLibrary.load()

    if args.save:
        library.put(args.save, config)
        library.active = args.save
        library.save()
        print(f"已将当前设置保存为配置档 {args.save!r}。")
        return 0

    if args.delete:
        if not library.delete(args.delete):
            print(f"没有名为 {args.delete!r} 的配置档。", file=sys.stderr)
            return 1
        library.save()
        print(f"已删除配置档 {args.delete!r}。")
        return 0

    if args.activate:
        try:
            chosen = library.activate(args.activate)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
        library.save()
        path = chosen.save()
        print(f"已切换到 {args.activate!r}，设置已写入 {path}。")
        return 0

    if not library.names():
        print("还没有配置档。可这样创建：autolevel profiles --save <名称>")
        return 0

    label = library.label_for(config)
    for name in library.names():
        profile = library.get(name)
        marker = "*" if name == label else " "
        print(f" {marker} {pad(name, 16)} 目标 {profile.target_db:6.1f} dBFS   "
              f"自动暂停 {'开' if profile.autopause_enabled else '关'}   "
              f"语音 {profile.autopause_voice_action}")

    if label.endswith(MODIFIED_SUFFIX):
        print(f"\n当前设置以 {library.active!r} 为起点，但之后已被修改。")
        print(f"可这样保存：autolevel profiles --save {library.active}")
    elif library.skipped:
        print(f"\n已跳过无法读取的配置档：{', '.join(library.skipped)}")
    return 0


def cmd_startup(args, config: Config) -> int:
    from . import startup

    if args.enable and args.disable:
        print("--enable 与 --disable 只能选一个。", file=sys.stderr)
        return 2

    if args.enable:
        print(f"已注册开机启动：\n  {startup.enable()}")
        return 0
    if args.disable:
        print("已取消开机启动。" if startup.disable() else "本来就没有开机启动项。")
        return 0

    command = startup.current_command()
    if command is None:
        print("未设置为开机启动。")
        print(f"可用以下命令启用：autolevel startup --enable\n  将运行：{startup.launch_command()}")
    elif startup.is_current():
        print(f"开机启动：\n  {command}")
    else:
        print(f"已设为开机启动，但该项已过期：\n  已注册：{command}")
        print(f"  当前构建：{startup.launch_command()}")
        print("重新运行 'autolevel startup --enable' 可指向当前构建。")
    return 0


def cmd_config(args, config: Config) -> int:
    path = args.config or default_config_path()
    if args.init:
        if path.exists() and not args.force:
            print(f"{path} 已存在。如需覆盖请加 --force。")
            return 1
        written = config.save(path)
        print(f"已写入默认配置：{written}")
        return 0

    print(f"# {path}{'' if path.exists() else '  (尚未创建；以下为默认值)'}")
    print(json.dumps(asdict(config), indent=2))
    return 0


# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autolevel",
        description="自动平衡 Windows 上每个应用的音量。",
    )
    parser.add_argument("--config", type=Path, help="配置文件路径")
    parser.add_argument(
        "--profile", metavar="NAME",
        help="本次运行使用某个已保存配置档的设置",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="列出当前音频会话后退出")
    p_list.set_defaults(func=cmd_list)

    p_monitor = sub.add_parser("monitor", help="实时监看电平，不做任何修改")
    p_monitor.set_defaults(func=cmd_monitor)

    p_run = sub.add_parser("run", help="持续平衡各应用的音量")
    p_run.add_argument("--dry-run", action="store_true", help="只计算增益，绝不写入")
    p_run.add_argument("--target", type=float, metavar="DBFS", help="目标电平（默认 -18）")
    p_run.add_argument("--min-gain", type=float, metavar="DB", help="最大衰减量")
    p_run.add_argument("--slew", type=float, metavar="DB_PER_S", help="音量变化速度")
    p_run.add_argument("--exclude", metavar="NAMES", help="要忽略的进程名，逗号分隔")
    p_run.add_argument("--only", metavar="NAMES", help="只管理的进程名，逗号分隔")
    p_run.add_argument(
        "--autopause", action="store_true",
        help="视频播放期间暂停音乐",
    )
    p_run.add_argument(
        "--autopause-action", choices=("pause", "duck"), metavar="MODE",
        help="'pause' 停止音乐，'duck' 只是降低音量",
    )
    p_run.add_argument("--trigger", metavar="NAMES", help="播放时会让音乐暂停的应用")
    p_run.add_argument("--music", metavar="NAMES", help="要暂停或降低音量的应用")
    p_run.add_argument(
        "--voice", metavar="NAMES",
        help="语音活动会降低音乐的应用（如 discord）",
    )
    p_run.add_argument(
        "--voice-action", choices=("pause", "duck"), metavar="MODE",
        help="语音活动时执行的动作，默认 duck",
    )
    p_run.add_argument(
        "--boost", action="store_true",
        help="通过已配置的源端点启用超过 100% 的增益",
    )
    p_run.add_argument(
        "--boost-source", metavar="DEVICE",
        help="被增强应用所路由到的渲染端点",
    )
    p_run.add_argument(
        "--boost-output", metavar="DEVICE",
        help="接收放大后音频的扬声器端点（默认：系统默认设备）",
    )
    p_run.add_argument("--boost-gain", type=float, metavar="DB", help="超过 100% 的真实增益")
    p_run.set_defaults(func=cmd_run)

    p_media = sub.add_parser("media", help="列出媒体会话及其应用 ID")
    p_media.set_defaults(func=cmd_media)

    p_boost = sub.add_parser("boost", help="列出端点并配置真实的音频增强")
    p_boost.add_argument(
        "--open-mixer", action="store_true",
        help="打开 Windows 的按应用输出路由设置",
    )
    p_boost.add_argument(
        "--check", action="store_true",
        help="短暂开启已配置的桥接并报告音频流状态",
    )
    p_boost.add_argument("--boost-source", metavar="DEVICE", help="要检查的源端点")
    p_boost.add_argument(
        "--boost-output", metavar="DEVICE",
        help="要检查的输出端点；省略则使用配置值或默认扬声器",
    )
    p_boost.add_argument("--boost-gain", type=float, metavar="DB", help="检查时使用的增益")
    p_boost.add_argument(
        "--seconds", type=float, default=1.0, metavar="N",
        help="检查时长（秒），默认 1",
    )
    p_boost.set_defaults(func=cmd_boost)

    p_gui = sub.add_parser("gui", help="打开桌面窗口")
    p_gui.add_argument(
        "--minimized", action="store_true",
        help="隐藏到托盘启动，并立即开始平衡",
    )
    p_gui.set_defaults(func=cmd_gui)

    p_profiles = sub.add_parser("profiles", help="列出、保存、切换或删除配置档")
    p_profiles.add_argument("--activate", metavar="NAME", help="切换到此配置档")
    p_profiles.add_argument("--save", metavar="NAME", help="把当前设置保存为 NAME")
    p_profiles.add_argument("--delete", metavar="NAME", help="删除配置档")
    p_profiles.set_defaults(func=cmd_profiles)

    p_startup = sub.add_parser("startup", help="管理开机自动启动")
    p_startup.add_argument("--enable", action="store_true", help="开机时运行 autolevel")
    p_startup.add_argument("--disable", action="store_true", help="不再开机运行")
    p_startup.set_defaults(func=cmd_startup)

    p_config = sub.add_parser("config", help="查看或创建配置文件")
    p_config.add_argument("--init", action="store_true", help="写入默认配置文件")
    p_config.add_argument("--force", action="store_true", help="覆盖已存在的配置")
    p_config.set_defaults(func=cmd_config)

    return parser


def _apply_overrides(config: Config, args) -> None:
    if getattr(args, "target", None) is not None:
        config.target_db = args.target
    if getattr(args, "min_gain", None) is not None:
        config.min_gain_db = args.min_gain
    if getattr(args, "slew", None) is not None:
        config.slew_db_per_s = args.slew
    if getattr(args, "exclude", None):
        config.exclude = [n.strip() for n in args.exclude.split(",") if n.strip()]
    if getattr(args, "only", None):
        config.include_only = [n.strip() for n in args.only.split(",") if n.strip()]
    if getattr(args, "autopause", False):
        config.autopause_enabled = True
    if getattr(args, "autopause_action", None):
        config.autopause_action = args.autopause_action
    if getattr(args, "trigger", None):
        config.autopause_trigger = [n.strip() for n in args.trigger.split(",") if n.strip()]
    if getattr(args, "music", None):
        config.autopause_music = [n.strip() for n in args.music.split(",") if n.strip()]
    if getattr(args, "voice", None):
        config.autopause_voice_apps = [n.strip() for n in args.voice.split(",") if n.strip()]
    if getattr(args, "voice_action", None):
        config.autopause_voice_action = args.voice_action
    if getattr(args, "boost", False):
        config.boost_enabled = True
    if getattr(args, "boost_source", None):
        config.boost_source_device = args.boost_source
    if getattr(args, "boost_output", None):
        config.boost_output_device = args.boost_output
    if getattr(args, "boost_gain", None) is not None:
        config.boost_gain_db = args.boost_gain


def main(argv: list[str] | None = None) -> int:
    if sys.platform != "win32":
        print("autolevel 使用 Windows Core Audio API，只能在 Windows 上运行。", file=sys.stderr)
        return 2

    args = build_parser().parse_args(argv)

    try:
        config = Config.load(args.config)
        if args.profile:
            from .profiles import ProfileLibrary

            chosen = ProfileLibrary.load().get(args.profile)
            if chosen is None:
                print(f"没有名为 {args.profile!r} 的配置档。"
                      "可用 autolevel profiles 列出。", file=sys.stderr)
                return 2
            config = chosen
        _apply_overrides(config, args)
        config.validate()
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2

    return args.func(args, config)


if __name__ == "__main__":
    raise SystemExit(main())
