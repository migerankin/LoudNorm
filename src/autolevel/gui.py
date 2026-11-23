"""Desktop window for autolevel.

The main window does one job: show what is playing and how it is being adjusted.
Everything configurable lives in ``settingsui.py``, so this stays readable at a
glance while balancing is running.

Threading contract, which is the subtle part:

* The balancer runs on a worker thread that initialises its own COM apartment.
  ``SessionRegistry`` calls ``CoInitialize`` in its constructor, so the registry
  must be *built* on that thread, not handed to it.
* COM objects never cross threads. The worker publishes frozen ``Frame`` objects
  through a ``queue.Queue``; Tk widgets are only ever touched from the main
  thread, which drains that queue on a timer.
"""

from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from dataclasses import fields as dataclass_fields
from dataclasses import replace
from tkinter import ttk

from . import startup, theme
from .autopause import AutoPauseRunner, settings_from_config
from .balancer import Balancer
from .boost import BoostSession
from .config import Config
from .dsp import amp_to_db
from .profiles import ProfileLibrary
from .sessions import SessionRegistry
from .settingsui import SettingsWindow
from .text import pad
from .tray import TrayIcon

METER_FLOOR_DB = -60.0
METER_WIDTH = 230
METER_HEIGHT = 12
POLL_MS = 60


@dataclass(frozen=True)
class Snapshot:
    """A COM-free view of one app, safe to hand to the Tk thread."""

    key: str
    name: str
    level_db: float | None
    gain_db: float
    status: str
    managed: bool
    ducked: bool = False


@dataclass(frozen=True)
class Frame:
    """One published update from the worker thread."""

    apps: tuple[Snapshot, ...]
    autopause_status: str = ""
    boost_status: str = ""


class BalancerThread(threading.Thread):
    """Runs the control loop and publishes snapshots."""

    def __init__(self, config: Config, out: queue.Queue, dry_run: bool = False):
        super().__init__(daemon=True, name="autolevel-balancer")
        self._config = config
        self._out = out
        self._dry_run = dry_run
        #: Mutated live from the GUI thread; the engine re-reads it every tick.
        self.autopause = settings_from_config(config)
        self.media_error: str | None = None
        # Not _stop: Thread._stop is a private method the interpreter calls
        # during join(), and shadowing it breaks shutdown.
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._target_db = config.target_db
        self._disabled: set[str] = set()
        self.error: BaseException | None = None
        self.restored = 0

    # --- called from the GUI thread ---------------------------------------- #

    def set_target(self, target_db: float) -> None:
        with self._lock:
            self._target_db = target_db

    def set_disabled(self, names: set[str]) -> None:
        with self._lock:
            self._disabled = {n.lower() for n in names}

    def apply_autopause(self, config: Config) -> None:
        """Push changed auto-pause settings into the running engine.

        Mutated field by field rather than replaced: the engine, the runner and
        the voice detector all hold a reference to this object, so rebinding it
        here would leave every one of them on the old settings -- which is
        exactly the bug this method exists to fix.
        """
        fresh = settings_from_config(config)
        with self._lock:
            for field in dataclass_fields(fresh):
                setattr(self.autopause, field.name, getattr(fresh, field.name))

    def stop(self) -> None:
        self._stop_event.set()

    # --- worker thread ------------------------------------------------------ #

    def _manages(self, process_name: str) -> bool:
        with self._lock:
            if process_name.lower() in self._disabled:
                return False
        return self._config.manages(process_name)

    def run(self) -> None:
        registry = None
        controller = None
        runner = None
        boost = BoostSession(self._config, dry_run=self._dry_run)
        try:
            boost.start()
            # Built here so COM is initialised on this thread.
            registry = SessionRegistry(manages=self._manages)
            balancer = Balancer(self._config, registry, dry_run=self._dry_run)

            from .mediasessions import MediaController

            controller = MediaController()
            if not controller.available:
                self.media_error = controller.error
            runner = AutoPauseRunner(self.autopause, controller, balancer)

            def on_update(states):
                with self._lock:
                    target = self._target_db
                if target != balancer.config.target_db:
                    balancer.set_target(target)

                # Raw peak, not the settled envelope: voice must register within
                # a fraction of a second.
                levels: dict[str, float] = {}
                for s in states:
                    level_db = amp_to_db(s.peak)
                    if level_db > levels.get(s.name, -999.0):
                        levels[s.name] = level_db
                runner.tick(time.perf_counter(), levels)

                self._out.put(Frame(
                    apps=tuple(
                        Snapshot(
                            key=s.session.key,
                            name=s.name,
                            level_db=s.level_db,
                            gain_db=s.gain_db,
                            status=s.status,
                            managed=True,
                            ducked=bool(s.duck_db),
                        )
                        for s in states
                    ),
                    autopause_status=runner.status,
                    boost_status=boost.status,
                ))

            balancer.run(on_update=on_update, should_stop=self._stop_event.is_set)
        except BaseException as exc:  # surfaced in the status bar
            self.error = exc
        finally:
            boost.close(timeout=None)
            if runner is not None:
                try:
                    runner.shutdown()
                except Exception:
                    pass
            if controller is not None:
                controller.close()
            if registry is not None and self._config.restore_on_exit and not self._dry_run:
                try:
                    self.restored = registry.restore_all()
                except Exception:
                    pass
            self._out.put(None)  # sentinel: the loop has ended


class MeterRow:
    """One application's row: name, level bar, and what is being done to it."""

    def __init__(self, parent: tk.Widget, name: str, on_toggle):
        self.name = name
        self.enabled = tk.BooleanVar(value=True)

        self.frame = tk.Frame(parent, bg=theme.BG)
        self.frame.columnconfigure(1, weight=1)

        self.check = theme.check(self.frame, variable=self.enabled,
                                 command=lambda: on_toggle(name))
        self.check.grid(row=0, column=0, rowspan=2, padx=(4, 8))

        self.label = theme.label(self.frame, name, font=theme.MONO_MED, anchor="w")
        self.label.grid(row=0, column=1, sticky="w")

        self.detail = theme.label(
            self.frame, "", fg=theme.FG_DIM, font=theme.MONO, anchor="w"
        )
        self.detail.grid(row=1, column=1, sticky="w")

        self.canvas = tk.Canvas(
            self.frame, width=METER_WIDTH, height=METER_HEIGHT,
            bg=theme.BG_DEEP, highlightthickness=0, bd=0,
        )
        self.canvas.grid(row=0, column=2, rowspan=2, padx=(10, 6), pady=7)
        self._bar = self.canvas.create_rectangle(
            0, 0, 0, METER_HEIGHT, fill=theme.GREEN, width=0
        )

    def update(self, snap: Snapshot) -> None:
        status = "已压低" if snap.ducked else snap.status

        if snap.level_db is None:
            self.canvas.coords(self._bar, 0, 0, 0, METER_HEIGHT)
            self.detail.config(
                text=f"{pad(status, 7)}      --      增益 {snap.gain_db:6.1f} dB"
            )
            return

        fraction = (snap.level_db - METER_FLOOR_DB) / (0.0 - METER_FLOOR_DB)
        fraction = max(0.0, min(1.0, fraction))
        self.canvas.coords(self._bar, 0, 0, int(fraction * METER_WIDTH), METER_HEIGHT)

        if snap.ducked:
            colour = theme.ACCENT
        else:
            colour = theme.AMBER if snap.level_db > -6 else theme.GREEN
        self.canvas.itemconfig(self._bar, fill=colour)
        self.detail.config(
            text=f"{pad(status, 7)} {snap.level_db:6.1f} dB  增益 {snap.gain_db:6.1f} dB"
        )

    def set_dim(self, dim: bool) -> None:
        self.label.config(fg=theme.FG_DIM if dim else theme.FG)

    def destroy(self) -> None:
        self.frame.destroy()


class AutoLevelWindow(tk.Tk):
    def __init__(self, config: Config, start_minimized: bool = False):
        super().__init__()
        self.config_obj = config
        self.title("autolevel - 音量自动平衡")
        self.geometry("620x560")
        self.minsize(580, 420)
        self.configure(bg=theme.BG)
        theme.init_styles(self)

        self._queue: queue.Queue = queue.Queue()
        self._thread: BalancerThread | None = None
        self._rows: dict[str, MeterRow] = {}
        self._disabled: set[str] = set()
        self._settings_window: SettingsWindow | None = None
        self._quitting = False
        self.library = ProfileLibrary.load()

        #: Plain mirror of GUI state for the tray thread to read. Never let the
        #: tray touch a Tk variable directly.
        self.tray_state = {
            "balancing": False,
            "autopause": config.autopause_enabled,
            "profiles": self.library.names(),
            "profile": self.library.label_for(config),
        }

        self._build()
        self._apply_window_icon()

        self.tray = TrayIcon(self)
        self.tray.start()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Control-comma>", lambda _e: self.open_settings())
        self.after(POLL_MS, self._drain)

        if start_minimized:
            # Launched at logon: go straight to the tray and start working.
            self.withdraw()
            self.after(400, self._start)
        elif not self.tray.available:
            self.status.config(text=f"托盘不可用：{self.tray.error}", fg=theme.AMBER)

    def _apply_window_icon(self) -> None:
        try:
            from PIL import ImageTk

            from .iconart import render

            self._icon_image = ImageTk.PhotoImage(render(64, active=True))
            self.iconphoto(True, self._icon_image)
        except Exception:
            pass  # cosmetic only

    # --- layout -------------------------------------------------------------- #

    def _build(self) -> None:
        header = tk.Frame(self, bg=theme.PANEL)
        header.pack(fill="x", side="top")

        self.start_button = theme.button(
            header, text="开始平衡", command=self._toggle, kind="primary"
        )
        self.start_button.pack(side="left", padx=(12, 6), pady=12)

        theme.button(header, text="设置",
                     command=self.open_settings).pack(side="left", pady=12)

        profile_outer = tk.Frame(header, bg=theme.PANEL)
        profile_outer.pack(side="left", padx=(14, 0), pady=12)
        theme.label(profile_outer, "配置档", bg=theme.PANEL, fg=theme.FG_DIM,
                    font=theme.UI_SMALL, anchor="w").pack(anchor="w")
        profile_box = tk.Frame(profile_outer, bg=theme.PANEL)
        profile_box.pack()
        self.profile_var = tk.StringVar()
        self.profile_combo = ttk.Combobox(
            profile_box, textvariable=self.profile_var, state="readonly",
            width=18, font=theme.MONO,
        )
        self.profile_combo.pack(side="left")
        self.profile_combo.bind("<<ComboboxSelected>>", self._on_profile_selected)

        theme.button(profile_box, text="+", command=self.prompt_new_profile,
                     padx=8, pady=2).pack(side="left", padx=(4, 0))
        self.refresh_profile_selector()

        slider_box = tk.Frame(header, bg=theme.PANEL)
        slider_box.pack(side="right", padx=12)

        self.target_label = theme.label(
            slider_box, bg=theme.PANEL, fg=theme.FG, font=theme.MONO
        )
        self.target_label.pack(anchor="e")

        self.target = tk.DoubleVar(value=self.config_obj.target_db)
        ttk.Scale(
            slider_box, from_=-40.0, to=-6.0, orient="horizontal",
            variable=self.target, command=self._on_target, length=180,
        ).pack()
        self._on_target(None)

        theme.separator(self).pack(fill="x")

        # --- toggles -------------------------------------------------------
        subbar = tk.Frame(self, bg=theme.PANEL)
        subbar.pack(fill="x")

        self.autopause_on = tk.BooleanVar(value=self.config_obj.autopause_enabled)
        theme.check(
            subbar, text="自动暂停", variable=self.autopause_on,
            command=self._on_autopause_toggle, bg=theme.PANEL, fg=theme.FG_MUTED,
        ).pack(side="left", padx=(12, 10), pady=7)

        self.dry_run = tk.BooleanVar(value=False)
        theme.check(
            subbar, text="试运行", variable=self.dry_run,
            bg=theme.PANEL, fg=theme.FG_MUTED,
        ).pack(side="left", pady=7)

        self.autopause_status = theme.label(
            subbar, bg=theme.PANEL, fg=theme.FG_DIM, font=theme.UI, anchor="e",
        )
        self.autopause_status.pack(side="right", padx=12, pady=7)

        theme.separator(self).pack(fill="x")

        # --- app list ------------------------------------------------------
        body = tk.Frame(self, bg=theme.BG)
        body.pack(fill="both", expand=True)

        self.rows_frame = tk.Frame(body, bg=theme.BG)
        self.rows_frame.pack(fill="both", expand=True, padx=8, pady=8)

        self.empty_label = theme.label(
            self.rows_frame,
            "当前没有应用在播放音频。\n"
            "随便播放点什么，它就会出现在这里。",
            fg=theme.FG_DIM, font=theme.UI_MED, justify="center",
        )
        self.empty_label.pack(pady=48)

        # --- status --------------------------------------------------------
        theme.separator(self).pack(fill="x", side="bottom")
        self.status = theme.label(
            self, "已停止", bg=theme.PANEL, fg=theme.FG_DIM,
            anchor="w", padx=12, pady=7,
        )
        self.status.pack(fill="x", side="bottom")

    # --- controls ------------------------------------------------------------ #

    def _on_target(self, _event) -> None:
        value = round(self.target.get(), 1)
        self.target_label.config(text=f"目标 {value:6.1f} dBFS")
        if self._thread is not None:
            self._thread.set_target(value)

    def _on_autopause_toggle(self) -> None:
        """Takes effect immediately; the engine releases the music when unticked."""
        self.tray_state["autopause"] = self.autopause_on.get()
        if self._thread is not None:
            self._thread.autopause.enabled = self.autopause_on.get()

    def _on_row_toggle(self, name: str) -> None:
        row = self._rows.get(name)
        if row is None:
            return
        if row.enabled.get():
            self._disabled.discard(name)
        else:
            self._disabled.add(name)
        row.set_dim(not row.enabled.get())
        if self._thread is not None:
            self._thread.set_disabled(self._disabled)

    # --- profiles --------------------------------------------------------------- #

    def refresh_profile_selector(self) -> None:
        """Re-read the library and show which profile the current settings are."""
        names = self.library.names()
        label = self.library.label_for(self.config_obj)
        # "(modified)" and "(unsaved)" are states, not selectable profiles, so
        # they appear as the shown value without joining the list.
        self.profile_combo.config(values=names)
        self.profile_var.set(label)
        self.tray_state["profiles"] = names
        self.tray_state["profile"] = label
        tray = getattr(self, "tray", None)
        if tray is not None:
            tray.refresh_menu()

    def _on_profile_selected(self, _event=None) -> None:
        self.switch_profile(self.profile_var.get())

    def prompt_new_profile(self) -> None:
        """Name and save the current settings as a new profile, from the header."""
        from .settingsui import NameDialog

        NameDialog(
            self, "新建配置档", "把当前设置保存为配置档，名称：",
            on_ok=self.create_profile, exists=self.library.exists,
        )

    def create_profile(self, name: str) -> str | None:
        """Returns an error string to keep the dialog open, or None on success."""
        try:
            name = self.library.validate_name(name)
            self.library.put(name, self.config_obj)
            self.library.active = name
            self.library.save()
        except (ValueError, OSError) as exc:
            return str(exc)

        self.refresh_profile_selector()
        if self._settings_window is not None and self._settings_window.winfo_exists():
            self._settings_window.refresh_profiles()
        self.status.config(text=f"已将当前设置保存为配置档 '{name}'。",
                           fg=theme.FG_MUTED)
        return None

    def switch_profile(self, name: str) -> None:
        """Load a profile's settings and make them current."""
        try:
            config = self.library.activate(name)
        except ValueError:
            self.refresh_profile_selector()
            return

        self.apply_settings(config)
        try:
            config.save()
            self.library.save()
        except OSError:
            pass  # in-memory switch still worked

        if self._settings_window is not None and self._settings_window.winfo_exists():
            self._settings_window.load(config)
            self._settings_window._base = config
            self._settings_window.refresh_profiles()

        self.status.config(
            text=f"已切换到配置档 '{name}'。"
                 + ("需重启平衡才能让全部设置生效。" if self._thread else ""),
            fg=theme.FG_MUTED,
        )

    # --- settings ------------------------------------------------------------- #

    def open_settings(self) -> None:
        if self._settings_window is not None and self._settings_window.winfo_exists():
            self._settings_window.lift()
            self._settings_window.focus_force()
            return
        self._settings_window = SettingsWindow(
            self, self.config_obj, self.apply_settings,
            library=self.library, on_library_change=self.refresh_profile_selector,
        )

    def apply_settings(self, config: Config) -> None:
        """Called by the settings panel once its values validate."""
        self.config_obj = config

        self.target.set(config.target_db)
        self._on_target(None)
        self.autopause_on.set(config.autopause_enabled)
        self._on_autopause_toggle()
        self.refresh_profile_selector()

        if self._thread is not None:
            self._thread.apply_autopause(config)
            # Target and every auto-pause setting are live. Level shaping and
            # endpoint streams are built when the loop starts, so say so rather
            # than pretending everything took effect.
            self.status.config(
                text="设置已保存。目标电平与自动暂停已经生效；电平和增强相关设置"
                     "需在平衡重启后生效。",
                fg=theme.FG_MUTED,
            )

    def refresh_startup_checkbox(self) -> None:
        """Called from the tray after it flips the registry entry."""
        window = self._settings_window
        if window is not None and window.winfo_exists():
            from .settingsui import START_WITH_WINDOWS

            window._vars[START_WITH_WINDOWS].set(startup.is_enabled())

    # --- tray-facing API ------------------------------------------------------ #

    def show_window(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()

    def hide_window(self) -> None:
        self.withdraw()

    def toggle_balancing(self) -> None:
        self._toggle()

    def set_autopause(self, enabled: bool) -> None:
        self.autopause_on.set(enabled)
        self._on_autopause_toggle()

    def quit_app(self) -> None:
        self._quitting = True
        self._on_close()

    # --- run / stop ------------------------------------------------------------ #

    def _toggle(self) -> None:
        if self._thread is None:
            self._start()
        else:
            self._stop()

    def _start(self) -> None:
        cfg = replace(
            self.config_obj,
            target_db=round(self.target.get(), 1),
            autopause_enabled=self.autopause_on.get(),
        )

        self._thread = BalancerThread(cfg, self._queue, dry_run=self.dry_run.get())
        self._thread.set_disabled(self._disabled)
        self._thread.start()

        self.tray_state["balancing"] = True
        self.tray.set_balancing(True)
        self.start_button.config(text="停止", bg=theme.RED, activebackground=theme.RED_HOVER)
        mode = "试运行 - 只计算增益，不做任何修改" if self.dry_run.get() else "平衡中"
        self.status.config(text=mode, fg=theme.FG)

    def _stop(self) -> bool:
        if self._thread is None:
            return True
        self._thread.stop()
        self._thread.join(timeout=3.0)
        if self._thread.is_alive():
            self.status.config(
                text="正在停止音频流，等待工作线程结束…",
                fg=theme.AMBER,
            )
            self.start_button.config(text="正在停止…", state=tk.DISABLED)
            self.after(100, lambda: AutoLevelWindow._poll_stop(self))
            return False

        self._finish_stop()
        return True

    def _poll_stop(self) -> None:
        if self._thread is None:
            return
        if self._thread.is_alive():
            self.after(100, lambda: AutoLevelWindow._poll_stop(self))
            return
        self._finish_stop()
        if self._quitting:
            self.tray.stop()
            self.destroy()

    def _finish_stop(self) -> None:
        if self._thread is None:
            return

        restored = self._thread.restored
        error = self._thread.error
        media_error = self._thread.media_error
        self._thread = None

        self.tray_state["balancing"] = False
        self.tray.set_balancing(False)
        self.autopause_status.config(
            text=f"媒体控制不可用：{media_error}" if media_error else "",
            fg=theme.AMBER,
        )
        self.start_button.config(
            text="开始平衡", bg=theme.ACCENT,
            activebackground=theme.ACCENT_HOVER, state=tk.NORMAL,
        )
        if error is not None:
            self.status.config(text=f"因错误停止：{error!r}", fg=theme.AMBER)
        else:
            self.status.config(
                text=f"已停止。已将 {restored} 个应用恢复为原始音量。",
                fg=theme.FG_DIM,
            )

    # --- snapshot intake ----------------------------------------------------- #

    def _drain(self) -> None:
        latest = None
        try:
            while True:
                item = self._queue.get_nowait()
                if item is None:
                    continue  # loop ended; _stop() reports the outcome
                latest = item
        except queue.Empty:
            pass

        if latest is not None:
            self._render(latest.apps)
            active = sum(1 for a in latest.apps if a.level_db is not None)
            self.tray.set_balancing(True, f"正在平衡 {active} 个应用")
            status = " | ".join(
                part for part in (latest.autopause_status, latest.boost_status) if part
            )
            highlight = "已暂停音乐" in status or "已降低音乐" in status
            self.autopause_status.config(
                text=status, fg=theme.ACCENT if highlight else theme.FG_DIM
            )
        self.after(POLL_MS, self._drain)

    def _render(self, snapshots) -> None:
        by_name: dict[str, Snapshot] = {}
        for snap in snapshots:
            # Two sessions from one process are shown as one row.
            if snap.name not in by_name or (snap.level_db or -999) > (
                by_name[snap.name].level_db or -999
            ):
                by_name[snap.name] = snap

        for name in list(self._rows):
            if name not in by_name and name not in self._disabled:
                self._rows.pop(name).destroy()

        for name, snap in sorted(by_name.items()):
            row = self._rows.get(name)
            if row is None:
                self.empty_label.pack_forget()
                row = MeterRow(self.rows_frame, name, self._on_row_toggle)
                row.frame.pack(fill="x", pady=1)
                self._rows[name] = row
            row.update(snap)

        if not self._rows:
            self.empty_label.pack(pady=48)

        if self._thread is not None and not self.dry_run.get():
            self.status.config(text=f"正在平衡 {len(self._rows)} 个应用", fg=theme.FG)

    # --- shutdown ------------------------------------------------------------ #

    def _on_close(self) -> None:
        # The X button hides rather than quits, so balancing survives; quitting
        # is an explicit choice from the tray menu.
        if not self._quitting and self.config_obj.close_to_tray and self.tray.available:
            self.hide_window()
            return

        self._quitting = True
        if self._thread is not None:
            self.status.config(text="正在恢复音量…", fg=theme.FG)
            self.update_idletasks()
            if not self._stop():
                return
        self.tray.stop()
        self.destroy()


def run_gui(config: Config | None = None, start_minimized: bool = False) -> int:
    AutoLevelWindow(config or Config(), start_minimized=start_minimized).mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run_gui())
