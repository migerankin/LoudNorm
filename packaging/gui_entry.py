"""PyInstaller entry point for the windowed build.

A top-level script rather than the package module itself, because PyInstaller
runs its entry file as ``__main__`` where relative imports do not resolve.
"""

from autolevel.gui_main import main

raise SystemExit(main())
