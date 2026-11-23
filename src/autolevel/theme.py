"""Dark editor theme: one palette, one set of fonts, styled ttk widgets.

The look is deliberately code-editor-ish -- monospace for anything that is a
value, proportional for prose, and comment-grey for explanatory text. Numbers a
user might compare (levels, gains, dB) are always monospace so their digits line
up column-wise.

ttk widgets need explicit styling on Windows or they render as light-grey
Win32 controls in the middle of a dark window. ``init_styles`` handles that; call
it once against the root window.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

# --- palette ---------------------------------------------------------------- #

BG = "#1e1f22"        # window / editor background
BG_DEEP = "#17181b"   # insets: entries, meter troughs
PANEL = "#26282c"     # toolbars, footers, tab strip
RAISED = "#2f3238"    # hover
BORDER = "#3a3d43"

FG = "#e6e6e6"        # primary text
FG_MUTED = "#a2a6ad"  # secondary
FG_DIM = "#7f848d"    # comments, disabled

ACCENT = "#4c9be8"    # keyword blue: identifiers, active state
ACCENT_HOVER = "#5aa9f0"
GREEN = "#5ac37a"      # healthy levels
AMBER = "#e0a33e"      # hot levels, warnings
RED = "#c2554d"        # stop
RED_HOVER = "#d4645c"
PURPLE = "#b98bd6"     # numeric literals

# --- fonts ------------------------------------------------------------------ #
# The interface text is Chinese, so the proportional family must be one with
# CJK coverage; Segoe UI has none and would render tofu boxes. Microsoft YaHei
# UI ships with Windows and covers Latin digits too. MONO stays Consolas to keep
# the numeric columns aligned -- Windows' font linking supplies the CJK glyphs.

UI = ("Microsoft YaHei UI", 9)
UI_MED = ("Microsoft YaHei UI", 10)
UI_BOLD = ("Microsoft YaHei UI", 10, "bold")
UI_SMALL = ("Microsoft YaHei UI", 8)
MONO = ("Consolas", 9)
MONO_MED = ("Consolas", 10)
MONO_SMALL = ("Consolas", 8)


def init_styles(root: tk.Misc) -> None:
    """Style the ttk widgets we use so they match the dark palette."""
    style = ttk.Style(root)
    # clam is the only built-in theme that honours most colour options on
    # Windows; the native themes ignore background entirely.
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=0)
    style.configure(
        "TNotebook.Tab",
        background=PANEL, foreground=FG_DIM,
        padding=(16, 8), borderwidth=0, font=UI,
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", BG), ("active", RAISED)],
        foreground=[("selected", ACCENT), ("active", FG)],
    )

    style.configure(
        "Horizontal.TScale",
        background=PANEL, troughcolor=BG_DEEP,
        bordercolor=BORDER, lightcolor=ACCENT, darkcolor=ACCENT,
    )

    style.configure(
        "TCombobox",
        fieldbackground=BG_DEEP, background=PANEL, foreground=FG,
        arrowcolor=FG_MUTED, bordercolor=BORDER,
        lightcolor=BORDER, darkcolor=BORDER, insertcolor=FG,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", BG_DEEP)],
        selectbackground=[("readonly", BG_DEEP)],
        selectforeground=[("readonly", FG)],
        bordercolor=[("focus", ACCENT)],
    )
    # The dropdown is a Tk listbox, not a ttk widget, so it needs option_add.
    root.option_add("*TCombobox*Listbox.background", BG_DEEP)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    root.option_add("*TCombobox*Listbox.font", MONO)

    style.configure(
        "Vertical.TScrollbar",
        background=PANEL, troughcolor=BG, bordercolor=BG,
        arrowcolor=FG_DIM, darkcolor=PANEL, lightcolor=PANEL,
    )
    style.map("Vertical.TScrollbar", background=[("active", RAISED)])


# --- widget factories -------------------------------------------------------- #
# Plain tk widgets, because ttk cannot be coloured per-widget without inventing
# a named style for each variation.


def label(parent, text="", *, fg=FG, bg=BG, font=UI, **kw) -> tk.Label:
    return tk.Label(parent, text=text, fg=fg, bg=bg, font=font, **kw)


def comment(parent, text="", *, bg=BG, **kw) -> tk.Label:
    """Explanatory text, styled like a code comment."""
    return tk.Label(parent, text=text, fg=FG_DIM, bg=bg, font=UI_SMALL,
                    anchor="w", justify="left", **kw)


def key_label(parent, text="", *, bg=BG, **kw) -> tk.Label:
    """A config.json key, shown as an identifier."""
    return tk.Label(parent, text=text, fg=ACCENT, bg=bg, font=MONO, anchor="w", **kw)


def entry(parent, *, bg=BG_DEEP, width=24, font=MONO, **kw) -> tk.Entry:
    widget = tk.Entry(
        parent, bg=bg, fg=FG, insertbackground=ACCENT,
        relief="flat", font=font, width=width,
        highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT,
        disabledbackground=BG, disabledforeground=FG_DIM, **kw
    )
    return widget


def check(parent, text="", *, variable=None, command=None, bg=BG, fg=FG, font=UI, **kw):
    return tk.Checkbutton(
        parent, text=text, variable=variable, command=command,
        bg=bg, fg=fg, font=font, selectcolor=BG_DEEP,
        activebackground=bg, activeforeground=FG,
        highlightthickness=0, bd=0, anchor="w", **kw
    )


def button(parent, text="", *, command=None, kind="normal",
           padx=14, pady=6, **kw) -> tk.Button:
    palette = {
        "primary": (ACCENT, ACCENT_HOVER, "#ffffff"),
        "danger": (RED, RED_HOVER, "#ffffff"),
        "normal": (PANEL, RAISED, FG),
    }[kind]
    base, hover, text_colour = palette
    widget = tk.Button(
        parent, text=text, command=command,
        bg=base, fg=text_colour, activebackground=hover, activeforeground=text_colour,
        relief="flat", bd=0, font=UI_BOLD if kind != "normal" else UI,
        padx=padx, pady=pady, cursor="hand2", **kw
    )
    widget.bind("<Enter>", lambda _e: widget.config(bg=hover))
    widget.bind("<Leave>", lambda _e: widget.config(bg=base))
    return widget


def separator(parent, *, bg=BORDER) -> tk.Frame:
    return tk.Frame(parent, bg=bg, height=1)
