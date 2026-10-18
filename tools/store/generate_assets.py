#!/usr/bin/env python3
"""Build the App Store / Play Store graphics from raw app screenshots and the branding SVGs.

Inputs (checked in so the output is reproducible):
  store/screenshots/raw/<device>/<NN_name>.png    plain screenshots taken from the running app
  store/captions.json                              captions per screenshot and locale
  docs/branding/fadenkreuz-fuchs/icon.svg          icon source

Outputs (fastlane layout, under store/metadata/):
  app-store-icon-1024.png                                  upload by hand in App Store Connect
  ios/screenshots/<locale>/<device>_<NN_name>.png          fastlane deliver
  android/<locale>/images/{icon,featureGraphic}.png        fastlane supply
  android/<locale>/images/<phone|sevenInch|tenInch>Screenshots/<NN_name>.png

    python3 tools/store/generate_assets.py        # needs rsvg-convert and ImageMagick (magick)
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STORE = ROOT / "store"
ICON_SVG = ROOT / "docs/branding/fadenkreuz-fuchs/icon.svg"

BACKGROUND = "#0B3B3C"
ORANGE = "#FF7A1A"
FONT = "Arial-Bold"
FONT_REGULAR = "Arial"

METADATA = STORE / "metadata"
LOCALES = {"de": "de-DE", "en": "en-US"}

# raw dir -> (store platform, output name, canvas size)
# iOS: file name prefix (deliver detects the device class from the pixel size).
# Android: fastlane supply screenshot folder.
DEVICES = {
    "iphone": ("ios", "iphone-6.9", (1320, 2868)),
    "ipad": ("ios", "ipad-13", (2064, 2752)),
    "android-phone": ("android", "phoneScreenshots", (1080, 1920)),
    "android-tablet-7": ("android", "sevenInchScreenshots", (1200, 1920)),
    "android-tablet-10": ("android", "tenInchScreenshots", (1600, 2560)),
}

TAGLINE = {
    "de": "Störsender gemeinsam finden",
    "en": "Find interferers together",
}
SUBLINE = {
    "de": "Peilungen live zu einem Standort verdichten",
    "en": "Fuse bearings live into one location",
}


def run(*cmd: object) -> None:
    subprocess.run([str(c) for c in cmd], check=True)


def make_icons() -> None:
    STORE.mkdir(parents=True, exist_ok=True)
    ios = STORE / "app-store-icon-1024.png"
    run("rsvg-convert", "-w", 1024, "-h", 1024, "-o", ios, ICON_SVG)
    # The App Store rejects alpha channels.
    run("magick", ios, "-background", BACKGROUND, "-alpha", "remove", "-alpha", "off", ios)
    for locale in LOCALES.values():
        images = METADATA / "android" / locale / "images"
        images.mkdir(parents=True, exist_ok=True)
        run("rsvg-convert", "-w", 512, "-h", 512, "-o", images / "icon.png", ICON_SVG)


def make_feature_graphic(lang: str) -> None:
    out_dir = METADATA / "android" / LOCALES[lang] / "images"
    out_dir.mkdir(parents=True, exist_ok=True)
    icon = out_dir / ".icon.png"
    run("rsvg-convert", "-w", 360, "-h", 360, "-o", icon, ICON_SVG)
    rounded = out_dir / ".rounded.png"
    # Round the icon's corners with an explicit mask.
    run(
        "magick", icon, "-resize", "300x300", "-alpha", "set",
        "(", "-size", "300x300", "xc:black", "-fill", "white",
        "-draw", "roundrectangle 0,0 299,299 60,60", ")",
        "-compose", "DstIn", "-composite", rounded,
    )
    run(
        "magick", "-size", "1024x500", f"xc:{BACKGROUND}",
        rounded, "-geometry", "+60+100", "-compose", "Over", "-composite",
        "-font", FONT, "-fill", "white", "-pointsize", "88", "-annotate", "+400+230", "FoxGrid",
        "-font", FONT, "-fill", ORANGE, "-pointsize", "36", "-annotate", "+404+300", TAGLINE[lang],
        "-font", FONT_REGULAR, "-fill", "#C8DADA", "-pointsize", "26", "-annotate", "+404+350", SUBLINE[lang],
        "-alpha", "off",
        out_dir / "featureGraphic.png",
    )
    rounded.unlink()
    icon.unlink()


def frame(raw: Path, caption: str, size: tuple[int, int], out: Path) -> None:
    width, height = size
    phone_w = int(width * 0.84)
    font = int(width * 0.062)
    spacing = int(width * 0.01)
    lines = caption.count("\n") + 1
    # Leave room for every caption line, never less than 20 % of the canvas.
    top = max(int(height * 0.20), int(height * 0.045) + lines * (font + spacing) + int(height * 0.02))
    radius = int(width * 0.05)
    shot = out.parent / ".shot.png"
    # Scale the screenshot, round its corners and add a thin light border.
    run(
        "magick", raw, "-resize", f"{phone_w}x",
        "(", "+clone", "-alpha", "extract", "-fill", "black", "-colorize", "100",
        "-fill", "white", "-draw", f"roundrectangle 0,0 {phone_w - 1},{height * 2},{radius},{radius}", ")",
        "-alpha", "off", "-compose", "CopyOpacity", "-composite", shot,
    )
    run(
        "magick", "-size", f"{width}x{height}", f"xc:{BACKGROUND}",
        shot, "-gravity", "north", "-geometry", f"+0+{top}", "-composite",
        "-gravity", "north", "-font", FONT, "-fill", "white",
        "-pointsize", str(font), "-interline-spacing", str(spacing),
        "-annotate", f"+0+{int(height * 0.045)}", caption,
        out,
    )
    shot.unlink()


def make_screenshots(captions: dict[str, dict[str, str]]) -> None:
    for raw_dir_name, (platform, out_name, size) in DEVICES.items():
        raw_dir = STORE / "screenshots/raw" / raw_dir_name
        if not raw_dir.is_dir():
            print(f"skip {raw_dir_name}: no raw screenshots")
            continue
        for raw in sorted(raw_dir.glob("*.png")):
            for lang, locale in LOCALES.items():
                text = captions[raw.stem][lang]
                if platform == "ios":
                    out = METADATA / "ios/screenshots" / locale / f"{out_name}_{raw.name}"
                else:
                    out = METADATA / "android" / locale / "images" / out_name / raw.name
                out.parent.mkdir(parents=True, exist_ok=True)
                frame(raw, text, size, out)
                print("wrote", out.relative_to(ROOT))


def main() -> None:
    captions = json.loads((STORE / "captions.json").read_text())
    make_icons()
    for lang in TAGLINE:
        make_feature_graphic(lang)
    make_screenshots(captions)


if __name__ == "__main__":
    main()
