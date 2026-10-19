#!/usr/bin/env python3
"""Render the FoxGrid app icons for iOS, Android and web from the SVG layers.

Source of truth: docs/branding/fadenkreuz-fuchs/{background,foreground}.svg (viewBox 0 0 200 200).
Needs `rsvg-convert` (librsvg) and ImageMagick's `magick`.

    python3 tools/branding/generate_icons.py
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "docs/branding/fadenkreuz-fuchs"
APP = ROOT / "app"

BACKGROUND = "#0B3B3C"
ORANGE = "#FF7A1A"


def inner(svg_file: Path) -> str:
    return re.sub(r"^<svg[^>]*>|</svg>\s*$", "", svg_file.read_text().strip())


FOREGROUND = inner(SRC / "foreground.svg")

# Themed (monochrome) Android icon: alpha-only silhouette, so the ellipse becomes an outline.
MONOCHROME = """
  <polygon points="52,66 58,22 94,48" fill="#fff"/>
  <polygon points="148,66 142,22 106,48" fill="#fff"/>
  <circle cx="100" cy="106" r="58" fill="none" stroke="#fff" stroke-width="9"/>
  <g transform="rotate(-28 100 106)"><ellipse cx="100" cy="106" rx="36" ry="17" fill="none" stroke="#fff" stroke-width="7"/></g>
  <g stroke="#fff" stroke-width="6" stroke-linecap="round">
    <line x1="100" y1="30" x2="100" y2="58"/><line x1="100" y1="154" x2="100" y2="182"/>
    <line x1="24" y1="106" x2="52" y2="106"/><line x1="148" y1="106" x2="176" y2="106"/>
  </g>
  <circle cx="100" cy="106" r="6" fill="#fff"/>
"""


def svg(body: str, viewbox: str = "0 0 200 200") -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{viewbox}">{body}</svg>'


def full_bleed(viewbox: str = "0 0 200 200") -> str:
    x, y, w, h = (float(v) for v in viewbox.split())
    return svg(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{BACKGROUND}"/>{FOREGROUND}', viewbox)


def rounded() -> str:
    return svg(
        '<clipPath id="r"><rect width="200" height="200" rx="46"/></clipPath>'
        f'<g clip-path="url(#r)"><rect width="200" height="200" fill="{BACKGROUND}"/>{FOREGROUND}</g>'
    )


def circle() -> str:
    return svg(
        '<clipPath id="r"><circle cx="100" cy="100" r="100"/></clipPath>'
        f'<g clip-path="url(#r)"><rect width="200" height="200" fill="{BACKGROUND}"/>{FOREGROUND}</g>'
    )


def render(source: str, px: int, out: Path, flatten: bool = False) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False) as f:
        f.write(source)
        tmp = Path(f.name)
    try:
        subprocess.run(
            ["rsvg-convert", "-w", str(px), "-h", str(px), str(tmp), "-o", str(out)], check=True
        )
        if flatten:  # App Store icons must not have an alpha channel
            subprocess.run(
                ["magick", str(out), "-background", BACKGROUND, "-alpha", "remove", "-alpha", "off", str(out)],
                check=True,
            )
    finally:
        tmp.unlink()


def ios() -> None:
    folder = APP / "ios/Runner/Assets.xcassets/AppIcon.appiconset"
    source = full_bleed()  # iOS applies the mask (and the Liquid Glass effect) itself
    for png in folder.glob("Icon-App-*.png"):
        m = re.match(r"Icon-App-([\d.]+)x[\d.]+@(\d)x\.png", png.name)
        assert m, png.name
        render(source, round(float(m.group(1)) * int(m.group(2))), png, flatten=True)


def ios_liquid_glass() -> None:
    """Copy the layered Icon Composer bundle (iOS 26 Liquid Glass); the PNGs above stay as fallback."""
    target = APP / "ios/Runner/AppIcon.icon"
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(SRC / "liquid-glass/AppIcon.icon", target)


def android() -> None:
    res = APP / "android/app/src/main/res"
    densities = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}
    # Adaptive layers are 108 dp; only the inner 66 dp are guaranteed visible, so the glyph
    # (160 units wide) is scaled to fill 66 dp: the canvas then spans 108/66*160 units.
    span = 108 / 66 * 160
    viewbox = f"{100 - span / 2:.2f} {100 - span / 2:.2f} {span:.2f} {span:.2f}"
    for name, scale in densities.items():
        folder = res / f"mipmap-{name}"
        render(rounded(), round(48 * scale), folder / "ic_launcher.png")
        render(circle(), round(48 * scale), folder / "ic_launcher_round.png")
        render(svg(FOREGROUND, viewbox), round(108 * scale), folder / "ic_launcher_foreground.png")
        render(svg(MONOCHROME, viewbox), round(108 * scale), folder / "ic_launcher_monochrome.png")
    anydpi = res / "mipmap-anydpi-v26"
    anydpi.mkdir(exist_ok=True)
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
        '    <background android:drawable="@color/ic_launcher_background"/>\n'
        '    <foreground android:drawable="@mipmap/ic_launcher_foreground"/>\n'
        '    <monochrome android:drawable="@mipmap/ic_launcher_monochrome"/>\n'
        "</adaptive-icon>\n"
    )
    (anydpi / "ic_launcher.xml").write_text(xml)
    (anydpi / "ic_launcher_round.xml").write_text(xml)
    (res / "values/ic_launcher_background.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
        f'    <color name="ic_launcher_background">{BACKGROUND}</color>\n</resources>\n'
    )


def web() -> None:
    folder = APP / "web"
    render(rounded(), 32, folder / "favicon.png")
    for px in (192, 512):
        render(rounded(), px, folder / f"icons/Icon-{px}.png")
        # maskable: full bleed with the glyph inside the central 80 % safe zone
        render(full_bleed("-25 -25 250 250"), px, folder / f"icons/Icon-maskable-{px}.png")


if __name__ == "__main__":
    ios()
    ios_liquid_glass()
    android()
    web()
    print("icons written")
