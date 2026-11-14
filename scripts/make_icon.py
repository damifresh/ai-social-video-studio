#!/usr/bin/env python3
"""Generate the macOS app icon (.icns) for AI Social Video Studio.

The artwork is drawn from scratch with Pillow — gradient rounded square, a
play triangle and a subtle clapper-board hint. Output is written to
desktop/build/icon.iconset and desktop/build/icon.icns.

    backend/.venv/bin/python scripts/make_icon.py
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "desktop" / "build"
ICONSET = BUILD / "icon.iconset"
SIZE = 1024


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def gradient(size: int) -> Image.Image:
    """Diagonal indigo -> violet -> cyan gradient."""
    img = Image.new("RGB", (size, size))
    px = img.load()
    stops = [(0.0, (67, 56, 202)), (0.55, (109, 71, 232)), (1.0, (14, 165, 214))]
    for y in range(size):
        for x in range(size):
            t = (x / size) * 0.55 + (y / size) * 0.45
            for i in range(len(stops) - 1):
                a0, c0 = stops[i]
                a1, c1 = stops[i + 1]
                if a0 <= t <= a1:
                    f = (t - a0) / max(1e-9, a1 - a0)
                    px[x, y] = tuple(int(lerp(c0[k], c1[k], f)) for k in range(3))
                    break
            else:
                px[x, y] = stops[-1][1]
    return img


def rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return mask


def build_master() -> Image.Image:
    size = SIZE
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    body = gradient(size).convert("RGBA")

    # soft inner glow top-left
    glow = Image.new("L", (size, size), 0)
    gd = ImageDraw.Draw(glow)
    gd.ellipse([-size * 0.35, -size * 0.45, size * 0.75, size * 0.55], fill=70)
    glow = glow.filter(ImageFilter.GaussianBlur(size * 0.08))
    body = Image.composite(Image.new("RGBA", (size, size), (255, 255, 255, 255)), body, glow.point(lambda v: int(v * 0.55)))

    mask = rounded_mask(size, int(size * 0.225))
    canvas.paste(body, (0, 0), mask)

    # clapper stripes (top band)
    band_h = int(size * 0.155)
    band = Image.new("RGBA", (size, band_h), (255, 255, 255, 30))
    bd = ImageDraw.Draw(band)
    step = int(size * 0.16)
    for i in range(-1, 8):
        bd.polygon(
            [
                (i * step, 0),
                (i * step + step * 0.5, 0),
                (i * step + step * 0.5 - band_h * 0.55, band_h),
                (i * step - band_h * 0.55, band_h),
            ],
            fill=(255, 255, 255, 34),
        )
    band_mask = Image.new("L", (size, band_h), 0)
    ImageDraw.Draw(band_mask).rounded_rectangle(
        [int(size * 0.22), int(size * 0.215), int(size * 0.78), int(size * 0.215) + band_h],
        radius=int(band_h / 2),
        fill=255,
    )
    canvas.paste(band, (0, int(size * 0.215)), band_mask)

    # play triangle
    d = ImageDraw.Draw(canvas)
    cx, cy = size * 0.505, size * 0.565
    r = size * 0.20
    tri = [
        (cx - r * 0.62, cy - r),
        (cx - r * 0.62, cy + r),
        (cx + r * 1.05, cy),
    ]
    # shadow
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).polygon([(x + 6, y + 12) for x, y in tri], fill=(4, 8, 24, 120))
    shadow = shadow.filter(ImageFilter.GaussianBlur(10))
    canvas = Image.alpha_composite(canvas, shadow)
    d = ImageDraw.Draw(canvas)
    d.polygon(tri, fill=(255, 255, 255, 246))

    # small "spark" dot to imply generated motion
    d.ellipse([size * 0.755, size * 0.70, size * 0.795, size * 0.74], fill=(125, 249, 255, 235))

    return canvas


def main() -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    if ICONSET.exists():
        shutil.rmtree(ICONSET)
    ICONSET.mkdir(parents=True, exist_ok=True)

    master = build_master()
    master.save(BUILD / "icon_1024.png")

    specs = [
        ("icon_16x16.png", 16),
        ("icon_16x16@2x.png", 32),
        ("icon_32x32.png", 32),
        ("icon_32x32@2x.png", 64),
        ("icon_128x128.png", 128),
        ("icon_128x128@2x.png", 256),
        ("icon_256x256.png", 256),
        ("icon_256x256@2x.png", 512),
        ("icon_512x512.png", 512),
        ("icon_512x512@2x.png", 1024),
    ]
    for name, px in specs:
        master.resize((px, px), Image.LANCZOS).save(ICONSET / name)

    subprocess.run(["iconutil", "-c", "icns", str(ICONSET), "-o", str(BUILD / "icon.icns")], check=True)
    for p in sorted(BUILD.glob("icon.*")):
        print(f"{p.relative_to(ROOT)}  {p.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
