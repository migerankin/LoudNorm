"""Display-width helpers for text laid out in fixed columns.

CJK characters occupy two columns while ``str.ljust`` counts characters, so a
translated label padded with plain formatting shifts every column after it.
These helpers pad by display width instead, which keeps the CLI tables and the
GUI meter rows aligned now that the labels are Chinese.
"""

from __future__ import annotations

import unicodedata

#: East Asian width classes that occupy two columns in a terminal.
_WIDE = ("W", "F")


def display_width(text: str) -> int:
    """Width of ``text`` in columns, counting wide characters as two."""
    return sum(2 if unicodedata.east_asian_width(ch) in _WIDE else 1 for ch in text)


def pad(text: str, width: int, align: str = "left") -> str:
    """Pad ``text`` to ``width`` display columns."""
    fill = " " * max(0, width - display_width(text))
    return fill + text if align == "right" else text + fill
