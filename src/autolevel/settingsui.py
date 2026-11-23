"""Settings panel.

Fields are declared, not hand-built: one ``Setting`` per row, grouped into tabs.
Adding a config option means adding one line here.

Each row shows the actual ``config.json`` key it maps to, with a comment-style
description under it. That keeps the panel honest -- there is no GUI-only vocabulary
to learn -- and it means anyone editing the file by hand already knows the names.

Saving goes through ``Config.validate()``, so the panel refuses bad combinations
with the same message the CLI would give rather than failing later at runtime.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass, fields, replace
from tkinter import ttk

from . import startup, theme
from .config import Config, default_config_path
from .profiles import MODIFIED_SUFFIX, ProfileLibrary

#: Pseudo-key: lives in the registry, not in config.json.
START_WITH_WINDOWS = "__start_with_windows__"


@dataclass(frozen=True)
class Setting:
    key: str
    kind: str  # "float" | "int" | "text" | "bool" | "choice" | "list"
    help: str
    choices: tuple = ()
    width: int = 10


GROUPS: tuple[tuple[str, tuple[Setting, ...]], ...] = (
    ("电平", (
        Setting("target_db", "float",
                "所有应用都被拉向的目标电平。设得越低，留给未经真实增强桥接的"
                "应用余量越大。"),
        Setting("min_gain_db", "float",
                "单个应用最多可被压低多少，作为安全上限。"),
        Setting("slew_db_per_s", "float",
                "音量变化的速度。越小越平滑；过大会出现明显的抽吸感。"),
        Setting("gate_db", "float",
                "低于此电平即视为静音，音量保持不动而不做调整。"),
        Setting("settle_ms", "float",
                "需要持续有可听音频多久，才会去调整该应用的音量。"),
        Setting("attack_ms", "float", "电平上升被记录的快慢。"),
        Setting("release_ms", "float", "电平下降被记录的快慢。"),
        Setting("exclude", "list",
                "永不接管的进程名，逗号分隔。例如：obs64.exe", width=34),
    )),
    ("增强", (
        Setting("boost_enabled", "bool",
                "启用超过 100% 的真实软件增益。被增强的应用需要在 Windows 音量"
                "合成器中路由到源端点。"),
        Setting("boost_source_device", "text",
                "接收这些应用的另一个渲染端点。可运行 'autolevel boost' "
                "复制准确的端点名称。", width=34),
        Setting("boost_output_device", "text",
                "接收放大后信号的扬声器。留空则使用 Windows 当前默认输出。", width=34),
        Setting("boost_gain_db", "float",
                "超过 100% 的实际增益。+6 dB 约为两倍幅度。"),
        Setting("boost_ceiling_db", "float",
                "峰值限幅上限。-1 dBFS 可避免削波并保留余量。"),
        Setting("boost_sample_rate", "int",
                "桥接采样率。48000 是 Windows 常见的共享模式采样率。"),
        Setting("boost_block_frames", "int",
                "每个音频块的帧数。48 kHz 下 480 帧约等于 10 ms。"),
    )),
    ("自动暂停", (
        Setting("autopause_enabled", "bool",
                "视频开始播放时把音乐压低或暂停。"),
        Setting("autopause_trigger", "list",
                "这些应用的媒体播放会压低音乐。浏览器可覆盖 YouTube 一类的站点。",
                width=34),
        Setting("autopause_music", "list",
                "要被暂停或压低的音乐应用。", width=34),
        Setting("autopause_action", "choice",
                "视频触发时的动作：pause 停止播放，duck 只是降低音量。",
                choices=("pause", "duck")),
        Setting("autopause_duck_db", "float", "压低时降低多少 dB。"),
        Setting("autopause_trigger_min_s", "float",
                "视频需持续播放这么久才会动音乐，避免拖动进度条时误触发。"),
        Setting("autopause_resume_delay_s", "float",
                "视频停止后延迟多久恢复音乐。"),
    )),
    ("语音", (
        Setting("autopause_voice_apps", "applist",
                "这些应用的语音活动会压低音乐。它们不注册媒体会话，因此改用响度"
                "检测。取消勾选只是停用而不会丢掉条目；移除才会真正删除。"),
        Setting("autopause_voice_action", "choice",
                "语音默认只压低；为一句话就把音乐掐断，比降低音量更糟。",
                choices=("duck", "pause")),
        Setting("autopause_voice_gate_db", "float",
                "超过此峰值电平即视为在说话。若通知提示音老是触发，可调高此值。"),
        Setting("autopause_voice_hold_s", "float",
                "在说话的字句间隙保持音乐处于压低状态。"),
    )),
    ("窗口", (
        Setting(START_WITH_WINDOWS, "bool",
                "开机时启动，直接进入托盘并开始平衡。"),
        Setting("close_to_tray", "bool",
                "关闭窗口时隐藏而不是退出。退出请用托盘菜单。"),
        Setting("restore_on_exit", "bool",
                "退出时把所有应用恢复到原始音量。"),
    )),
)

CONFIG_KEYS = {f.name for f in fields(Config)}


class NameDialog(tk.Toplevel):
    """Small themed prompt for naming things.

    Used instead of ``tkinter.simpledialog``, which renders as a light-grey
    Windows dialog in the middle of a dark app. ``on_ok`` returns an error
    string to keep the dialog open, or None to accept and close.
    """

    def __init__(self, parent, title: str, prompt: str, on_ok,
                 initial: str = "", exists=None):
        super().__init__(parent)
        self.on_ok = on_ok
        self.exists = exists or (lambda _name: False)
        self.title(title)
        self.configure(bg=theme.BG)
        self.resizable(False, False)
        self.transient(parent)

        theme.label(self, prompt, wraplength=340, justify="left", anchor="w").pack(
            fill="x", padx=16, pady=(16, 6)
        )

        self.value = tk.StringVar(value=initial)
        entry = theme.entry(self, textvariable=self.value, width=32, font=theme.MONO_MED)
        entry.pack(padx=16, fill="x")
        entry.focus_set()
        entry.select_range(0, tk.END)

        self.message = theme.comment(self, "")
        self.message.pack(fill="x", padx=16, pady=(6, 0))

        buttons = tk.Frame(self, bg=theme.BG)
        buttons.pack(fill="x", padx=16, pady=14)
        self.ok_button = theme.button(buttons, text="保存", command=self._submit,
                                      kind="primary")
        self.ok_button.pack(side="right")
        theme.button(buttons, text="取消", command=self.destroy).pack(side="right", padx=6)

        self.value.trace_add("write", lambda *_: self._check())
        self.bind("<Return>", lambda _e: self._submit())
        self.bind("<Escape>", lambda _e: self.destroy())
        self._check()

        # Centre on the parent so it doesn't land in a corner of the screen.
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + 120
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.grab_set()

    def _check(self) -> None:
        name = self.value.get().strip()
        if name and self.exists(name):
            self.message.config(
                text=f"已存在名为 {name!r} 的配置档，保存将覆盖它。",
                fg=theme.AMBER,
            )
            self.ok_button.config(text="替换")
        else:
            self.message.config(text="", fg=theme.FG_DIM)
            self.ok_button.config(text="保存")

    def _submit(self) -> None:
        error = self.on_ok(self.value.get())
        if error:
            self.message.config(text=error, fg=theme.AMBER)
            return
        self.destroy()


class AppToggleList(tk.Frame):
    """An editable list of app names, each with its own enable checkbox.

    Unticking keeps the name in the list, which is the point: switching Discord
    off for an evening should not mean retyping it tomorrow.
    """

    def __init__(self, parent, on_message=None):
        super().__init__(parent, bg=theme.BG)
        self._on_message = on_message or (lambda *_a: None)
        self._rows: list[tuple[str, tk.BooleanVar, tk.Frame]] = []

        self._list = tk.Frame(self, bg=theme.BG)
        self._list.pack(fill="x")

        adder = tk.Frame(self, bg=theme.BG)
        adder.pack(fill="x", pady=(8, 0))
        self._entry = theme.entry(adder, width=22)
        self._entry.pack(side="left")
        theme.button(adder, text="添加", command=self._add_typed,
                     padx=10, pady=3).pack(side="left", padx=6)
        self._entry.bind("<Return>", lambda _e: self._add_typed())

    # --- state ------------------------------------------------------------- #

    def set_value(self, names, disabled) -> None:
        off = {str(n).strip().lower() for n in disabled}
        for _name, _var, frame in self._rows:
            frame.destroy()
        self._rows.clear()
        for name in names:
            self._append(str(name), str(name).strip().lower() not in off)

    def names(self) -> list[str]:
        return [name for name, _var, _frame in self._rows]

    def disabled(self) -> list[str]:
        return [name for name, var, _frame in self._rows if not var.get()]

    # --- editing ----------------------------------------------------------- #

    def _append(self, name: str, enabled: bool) -> None:
        row = tk.Frame(self._list, bg=theme.BG)
        row.pack(fill="x", pady=1)
        var = tk.BooleanVar(value=enabled)
        theme.check(row, variable=var).pack(side="left")
        theme.label(row, name, font=theme.MONO, anchor="w").pack(side="left")
        theme.button(row, text="移除", command=lambda n=name: self._remove(n),
                     padx=8, pady=1).pack(side="right")
        self._rows.append((name, var, row))

    def _remove(self, name: str) -> None:
        for index, (existing, _var, frame) in enumerate(self._rows):
            if existing == name:
                frame.destroy()
                del self._rows[index]
                self._on_message(f"已移除 {name!r}。")
                return

    def _add_typed(self) -> None:
        name = self._entry.get().strip()
        if not name:
            self._on_message("请先输入应用名称，例如：discord")
            return
        if any(name.lower() == existing.lower() for existing in self.names()):
            self._on_message(f"{name!r} 已在列表中。")
            return
        self._append(name, True)
        self._entry.delete(0, tk.END)
        self._on_message(f"已添加 {name!r}，点“保存”后生效。")


class SettingsWindow(tk.Toplevel):
    """Edits a Config and hands the result back through ``on_apply``."""

    def __init__(self, parent, config: Config, on_apply, library=None, on_library_change=None):
        super().__init__(parent)
        self.on_apply = on_apply
        self.library = library if library is not None else ProfileLibrary.load()
        self.on_library_change = on_library_change or (lambda: None)
        self.title("autolevel - 设置")
        self.configure(bg=theme.BG)
        self.geometry("620x600")
        self.minsize(560, 480)
        self.transient(parent)

        self._vars: dict[str, tk.Variable] = {}
        self._widgets: dict[str, tk.Widget] = {}
        #: What edits are applied on top of. Updated on each successful save.
        self._base = config

        self._build()
        self.load(config)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<Control-s>", lambda _e: self.save())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    # --- construction --------------------------------------------------------- #

    def _build(self) -> None:
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=10, pady=(10, 0))

        for title, settings in GROUPS:
            tab = tk.Frame(notebook, bg=theme.BG)
            notebook.add(tab, text=title)
            for setting in settings:
                self._build_row(tab, setting)

        profiles_tab = tk.Frame(notebook, bg=theme.BG)
        notebook.add(profiles_tab, text="配置档")
        self._build_profiles_tab(profiles_tab)

        theme.separator(self).pack(fill="x", pady=(10, 0))

        footer = tk.Frame(self, bg=theme.PANEL)
        footer.pack(fill="x", side="bottom")

        self.message = theme.label(
            footer, text="", bg=theme.PANEL, fg=theme.FG_DIM,
            font=theme.UI, anchor="w", wraplength=340, justify="left",
        )
        self.message.pack(side="left", padx=12, pady=10, fill="x", expand=True)

        theme.button(footer, text="保存", command=self.save,
                     kind="primary").pack(side="right", padx=(6, 12), pady=10)
        theme.button(footer, text="默认值",
                     command=self.load_defaults).pack(side="right", pady=10)
        theme.button(footer, text="关闭",
                     command=self.destroy).pack(side="right", padx=6, pady=10)

        path_bar = tk.Frame(self, bg=theme.BG)
        path_bar.pack(fill="x", side="bottom")
        theme.label(
            path_bar, text=str(default_config_path()),
            fg=theme.FG_DIM, font=theme.MONO_SMALL, anchor="w",
        ).pack(side="left", padx=12, pady=(6, 4))

    def _build_row(self, parent: tk.Widget, setting: Setting) -> None:
        row = tk.Frame(parent, bg=theme.BG)
        row.pack(fill="x", padx=14, pady=(10, 0))
        row.columnconfigure(0, weight=1)

        theme.key_label(row, setting.key).grid(row=0, column=0, sticky="w")

        if setting.kind == "applist":
            widget = AppToggleList(row, on_message=lambda text: self._say(text, theme.FG_MUTED))
            widget.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
            self._widgets[setting.key] = widget
            # No Tk variable: the widget owns both the roster and the
            # disabled list, and writes them back in collect().
            theme.comment(row, setting.help, wraplength=560).grid(
                row=1, column=0, columnspan=2, sticky="w", pady=(2, 0)
            )
            return

        if setting.kind == "bool":
            var = tk.BooleanVar()
            widget = theme.check(row, variable=var)
        elif setting.kind == "choice":
            var = tk.StringVar()
            widget = ttk.Combobox(
                row, textvariable=var, values=list(setting.choices),
                state="readonly", width=8, font=theme.MONO,
            )
        else:
            var = tk.StringVar()
            widget = theme.entry(row, textvariable=var, width=setting.width)

        widget.grid(row=0, column=1, sticky="e")
        self._vars[setting.key] = var
        self._widgets[setting.key] = widget

        theme.comment(row, setting.help, wraplength=560).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(2, 0)
        )

    # --- profiles tab ---------------------------------------------------------- #

    def _build_profiles_tab(self, parent: tk.Widget) -> None:
        theme.comment(
            parent,
            "配置档是这些设置的完整副本。载入一个配置档会替换其他标签页上的全部内容。",
            wraplength=560,
        ).pack(fill="x", padx=14, pady=(12, 8))

        body = tk.Frame(parent, bg=theme.BG)
        body.pack(fill="both", expand=True, padx=14)

        self.profile_list = tk.Listbox(
            body, bg=theme.BG_DEEP, fg=theme.FG, font=theme.MONO,
            selectbackground=theme.ACCENT, selectforeground="#ffffff",
            relief="flat", highlightthickness=1,
            highlightbackground=theme.BORDER, highlightcolor=theme.ACCENT,
            activestyle="none", height=8,
        )
        self.profile_list.pack(side="left", fill="both", expand=True)

        buttons = tk.Frame(body, bg=theme.BG)
        buttons.pack(side="left", fill="y", padx=(10, 0))
        theme.button(buttons, text="载入", command=self.load_profile,
                     kind="primary").pack(fill="x", pady=(0, 6))
        theme.button(buttons, text="更新", command=self.update_profile,
                     kind="primary").pack(fill="x", pady=(0, 6))
        theme.button(buttons, text="复制…",
                     command=self.prompt_duplicate).pack(fill="x", pady=3)
        theme.button(buttons, text="重命名…",
                     command=self.prompt_rename).pack(fill="x", pady=3)
        theme.button(buttons, text="删除", command=self.delete_profile).pack(fill="x", pady=3)

        namer = tk.Frame(parent, bg=theme.BG)
        namer.pack(fill="x", padx=14, pady=(12, 0))
        theme.button(namer, text="用当前设置新建配置档…",
                     command=self.prompt_save_as, kind="primary").pack(side="left")
        theme.comment(
            parent,
            "“更新”会用其他标签页上当前显示的值覆盖所选配置档；“新建”则把这些值"
            "存成你指定的新名称。",
            wraplength=560,
        ).pack(fill="x", padx=14, pady=(6, 0))

        self.refresh_profiles()

    def refresh_profiles(self) -> None:
        self.profile_list.delete(0, tk.END)
        for name in self.library.names():
            marker = " *" if name == self.library.active else "  "
            self.profile_list.insert(tk.END, f"{marker} {name}")
        if self.library.skipped:
            self._say(f"已跳过无法读取的配置档：{', '.join(self.library.skipped)}",
                      theme.AMBER)

    def _selected_profile(self) -> str | None:
        selection = self.profile_list.curselection()
        if not selection:
            self._say("请先选择一个配置档。", theme.FG_MUTED)
            return None
        return self.library.names()[selection[0]]

    def load_profile(self) -> None:
        name = self._selected_profile()
        if name is None:
            return
        config = self.library.activate(name)
        self.load(config)
        self._base = config
        self.on_apply(config)
        try:
            config.save()
            self.library.save()
        except OSError as exc:
            self._say(f"已载入，但无法写入磁盘：{exc}", theme.AMBER)
            return
        self.refresh_profiles()
        self.on_library_change()
        self._say(f"已载入配置档 {name!r}。", theme.GREEN)

    # Each prompt_* opens the dialog; each verb takes a name and returns an
    # error string or None, so the logic is reachable without a dialog.

    def prompt_save_as(self) -> None:
        NameDialog(
            self, "新建配置档", "为此配置档命名：",
            on_ok=self.save_as_profile, exists=self.library.exists,
        )

    def save_as_profile(self, name: str) -> str | None:
        try:
            # Save what is on screen, not what was last applied.
            config = self.collect(self._base)
            self.library.put(self.library.validate_name(name), config)
        except ValueError as exc:
            return str(exc)

        self.library.active = self.library.validate_name(name)
        try:
            self.library.save()
        except OSError as exc:
            return f"无法写入配置档：{exc}"

        self.refresh_profiles()
        self.on_library_change()
        self._say(f"已保存配置档 {name.strip()!r}。", theme.GREEN)
        return None

    def update_profile(self, name: str | None = None) -> str | None:
        """Overwrite an existing profile with the values currently on screen.

        Save writes config.json only; without this there is no way to fold an
        edit back into the profile it came from.
        """
        name = name or self._selected_profile()
        if name is None:
            return "请先选择一个配置档。"
        try:
            config = self.collect(self._base)
            self.library.put(name, config, overwrite=True)
            self.library.active = name
            self.library.save()
        except (ValueError, OSError) as exc:
            self._say(str(exc), theme.AMBER)
            return str(exc)

        self._base = config
        self.on_apply(config)
        self.refresh_profiles()
        self.on_library_change()
        self._say(f"已用当前设置更新 {name!r}。", theme.GREEN)
        return None

    def prompt_duplicate(self) -> None:
        source = self._selected_profile()
        if source is None:
            return
        NameDialog(
            self, "复制配置档", f"把 {source!r} 复制为新的配置档，名称：",
            on_ok=lambda name: self.duplicate_profile(source, name),
            initial=f"{source} 副本", exists=self.library.exists,
        )

    def duplicate_profile(self, source: str, name: str) -> str | None:
        try:
            self.library.duplicate(source, name)
            self.library.save()
        except (ValueError, OSError) as exc:
            return str(exc)
        self.refresh_profiles()
        self.on_library_change()
        self._say(f"已把 {source!r} 复制为 {name.strip()!r}。", theme.GREEN)
        return None

    def prompt_rename(self) -> None:
        current = self._selected_profile()
        if current is None:
            return
        NameDialog(
            self, "重命名配置档", f"把 {current!r} 重命名为：",
            on_ok=lambda name: self.rename_profile(name, current),
            initial=current, exists=lambda n: n != current and self.library.exists(n),
        )

    def rename_profile(self, name: str, current: str | None = None) -> str | None:
        current = current or self._selected_profile()
        if current is None:
            return "请先选择一个配置档。"
        try:
            self.library.rename(current, name)
            self.library.save()
        except (ValueError, OSError) as exc:
            return str(exc)
        self.refresh_profiles()
        self.on_library_change()
        self._say(f"已重命名为 {name.strip()!r}。", theme.GREEN)
        return None

    def delete_profile(self) -> None:
        name = self._selected_profile()
        if name is None:
            return
        self.library.delete(name)
        try:
            self.library.save()
        except OSError as exc:
            self._say(f"无法写入配置档：{exc}", theme.AMBER)
            return
        self.refresh_profiles()
        self.on_library_change()
        self._say(f"已删除 {name!r}。", theme.FG_MUTED)

    # --- loading and reading --------------------------------------------------- #

    def load(self, config: Config) -> None:
        for _title, settings in GROUPS:
            for setting in settings:
                if setting.kind == "applist":
                    self._widgets[setting.key].set_value(
                        config.autopause_voice_apps, config.autopause_voice_disabled
                    )
                    continue

                var = self._vars[setting.key]
                if setting.key == START_WITH_WINDOWS:
                    var.set(startup.is_enabled())
                    continue

                value = getattr(config, setting.key)
                if setting.kind == "list":
                    var.set(", ".join(value))
                elif setting.kind == "bool":
                    var.set(bool(value))
                else:
                    var.set(str(value))
        self._say("")

    def load_defaults(self) -> None:
        """Reset the fields only. Nothing is written until Save."""
        defaults = Config()
        for _title, settings in GROUPS:
            for setting in settings:
                if setting.key == START_WITH_WINDOWS:
                    continue
                if setting.kind == "applist":
                    self._widgets[setting.key].set_value(
                        defaults.autopause_voice_apps, defaults.autopause_voice_disabled
                    )
                    continue
                value = getattr(defaults, setting.key)
                var = self._vars[setting.key]
                if setting.kind == "list":
                    var.set(", ".join(value))
                elif setting.kind == "bool":
                    var.set(bool(value))
                else:
                    var.set(str(value))
        self._say("字段已重置为默认值，尚未保存任何内容。", theme.FG_MUTED)

    def collect(self, base: Config) -> Config:
        """Build a Config from the fields. Raises ValueError if anything is off."""
        values: dict = {}
        for _title, settings in GROUPS:
            for setting in settings:
                if setting.key not in CONFIG_KEYS:
                    continue

                if setting.kind == "applist":
                    widget = self._widgets[setting.key]
                    values["autopause_voice_apps"] = widget.names()
                    values["autopause_voice_disabled"] = widget.disabled()
                    continue

                raw = self._vars[setting.key].get()

                if setting.kind == "bool":
                    values[setting.key] = bool(raw)
                elif setting.kind == "list":
                    values[setting.key] = [p.strip() for p in str(raw).split(",") if p.strip()]
                elif setting.kind == "choice":
                    values[setting.key] = str(raw)
                elif setting.kind == "text":
                    values[setting.key] = str(raw).strip()
                elif setting.kind == "int":
                    try:
                        values[setting.key] = int(raw)
                    except (TypeError, ValueError):
                        raise ValueError(f"{setting.key}：{raw!r} 不是整数") from None
                else:
                    try:
                        values[setting.key] = float(raw)
                    except (TypeError, ValueError):
                        raise ValueError(f"{setting.key}：{raw!r} 不是数字") from None

        candidate = replace(base, **values)
        candidate.validate()
        return candidate

    # --- actions ---------------------------------------------------------------- #

    def save(self) -> bool:
        try:
            config = self.collect(self._base)
        except ValueError as exc:
            self._say(str(exc), theme.AMBER)
            return False

        try:
            startup.set_enabled(bool(self._vars[START_WITH_WINDOWS].get()))
        except OSError as exc:
            self._say(f"设置本身有效，但写入开机启动项失败：{exc}", theme.AMBER)

        self._base = config
        self.on_apply(config)
        try:
            path = config.save()
            message = f"已保存到 {path}"
        except OSError as exc:
            self._say(f"已应用，但无法写入文件：{exc}", theme.AMBER)
            return True

        # Save writes the settings, not the profile they came from. Say so,
        # rather than leaving the selector quietly reading "(modified)".
        if self.library.label_for(config).endswith(MODIFIED_SUFFIX):
            message += (
                f"  配置档 '{self.library.active}' 仍是旧值 —— "
                "可用“配置档 > 更新”把改动合并进去。"
            )
            self._say(message, theme.AMBER)
        else:
            self._say(message, theme.GREEN)
        return True

    def _say(self, text: str, colour: str = theme.FG_DIM) -> None:
        self.message.config(text=text, fg=colour)
