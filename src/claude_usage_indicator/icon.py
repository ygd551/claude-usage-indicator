"""Generates the tray/launcher icon: a warm terracotta circle with a 'C'."""
import math
import os

import cairo

SIZES = [16, 22, 24, 32, 48, 64, 128, 256]
BG = (0.82, 0.42, 0.31)   # terracotta
FG = (1.0, 0.98, 0.94)    # warm white


def _draw(size, path):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    ctx = cairo.Context(surface)

    cx = cy = size / 2
    r = size / 2

    ctx.set_source_rgb(*BG)
    ctx.arc(cx, cy, r, 0, 2 * math.pi)
    ctx.fill()

    ring_r = size * 0.30
    thickness = size * 0.155
    gap_deg = 62

    ctx.set_source_rgb(*FG)
    ctx.set_line_width(thickness)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    start = math.radians(gap_deg / 2)
    end = math.radians(360 - gap_deg / 2)
    ctx.arc(cx, cy, ring_r, start, end)
    ctx.stroke()

    surface.write_to_png(path)


def install_icons(icon_theme_dir=None):
    """Writes claude-usage-indicator.png into ~/.local/share/icons/hicolor/<size>/apps/."""
    icon_theme_dir = icon_theme_dir or os.path.expanduser("~/.local/share/icons/hicolor")
    for size in SIZES:
        d = os.path.join(icon_theme_dir, f"{size}x{size}", "apps")
        os.makedirs(d, exist_ok=True)
        _draw(size, os.path.join(d, "claude-usage-indicator.png"))
    return icon_theme_dir
