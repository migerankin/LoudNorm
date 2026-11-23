"""The application mark: a small level meter, drawn rather than shipped.

Generating it keeps a binary asset out of the repo and lets the tray icon change
colour with state. Only depends on Pillow, so ``packaging/make_icon.py`` can use
it without pulling in pystray.
"""

from __future__ import annotations

ACTIVE = (76, 155, 232, 255)   # accent blue, matching the GUI
IDLE = (139, 143, 150, 255)    # dim grey

#: Relative bar heights. Uneven on purpose -- a flat row reads as a barcode at
#: 16x16, where most people will actually see this.
BARS = (0.45, 0.85, 0.60, 1.00, 0.35)


def render(size: int = 64, active: bool = True):
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    colour = ACTIVE if active else IDLE

    margin = size * 0.14
    usable = size - 2 * margin
    bar_width = usable / (len(BARS) * 2 - 1)
    radius = max(1.0, bar_width * 0.35)

    for index, height in enumerate(BARS):
        x0 = margin + index * bar_width * 2
        y1 = size - margin
        y0 = y1 - usable * height
        draw.rounded_rectangle([x0, y0, x0 + bar_width, y1], radius=radius, fill=colour)

    return image


def write_ico(path, sizes=(16, 24, 32, 48, 64, 128, 256)) -> None:
    """Write a multi-resolution .ico for the packaged executable."""
    render(256, active=True).save(path, format="ICO", sizes=[(s, s) for s in sizes])
