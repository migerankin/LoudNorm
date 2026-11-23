"""Entry point for the windowed executable.

Kept separate from ``cli.py`` so the packaged GUI never imports argparse-driven
console behaviour, and so a config error surfaces in a dialog rather than on a
stdout that a windowed process does not have.
"""

from __future__ import annotations

import sys


def main() -> int:
    from .config import Config

    try:
        config = Config.load()
    except Exception as exc:
        try:
            import tkinter.messagebox as messagebox

            messagebox.showerror(
                "autolevel",
                f"Your configuration file could not be loaded, so defaults are being used.\n\n{exc}",
            )
        except Exception:
            pass
        config = Config()

    from .gui import run_gui

    # Parsed directly rather than with argparse: this is the windowed entry
    # point, and argparse errors would go to a stderr that does not exist.
    minimized = "--minimized" in sys.argv[1:]
    return run_gui(config, start_minimized=minimized)


if __name__ == "__main__":
    sys.exit(main())
