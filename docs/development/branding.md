# FoxGrid branding

Chosen app icon: **crosshair fox** ("Fadenkreuz-Fuchs": a crosshair with fox ears over a grid, with the
orange error ellipse from the map in the centre).

| File | Purpose |
|---|---|
| `docs/branding/fadenkreuz-fuchs/background.svg` | background layer, flat `#0B3B3C` |
| `docs/branding/fadenkreuz-fuchs/foreground.svg` | foreground layer (grid, ears, ring, ellipse, ticks) on transparent |
| `docs/branding/fadenkreuz-fuchs/icon.svg` | both layers together |
| `docs/branding/alternatives/` | the rejected drafts "Peilfuchs" and "Signalpfeil" |

Colours: background `#0B3B3C`, orange `#FF7A1A`, white `#FFFFFF`.

## Regenerating the icons

Do not edit the generated PNGs by hand. Change the SVGs and run:

```bash
python3 tools/branding/generate_icons.py   # needs rsvg-convert and ImageMagick (magick)
```

The script writes iOS (all sizes of the `AppIcon.appiconset`, full-bleed and without alpha channel), Android
(adaptive with foreground, background and monochrome layers for themed icons, plus fallback PNGs) and web
(favicon, `Icon-192/512`, maskable variants).

iOS icons must stay full-bleed and without alpha (the system masks them). The App ID
(Android `applicationId`/`namespace`, iOS bundle ID) is `com.itwebservice.foxgrid`; Firebase, APNs and store listings are
tied to it, so do not change it once they exist.

## Liquid Glass (iOS 26)

iOS rounds the icon itself and adds highlights, depth and refraction on top of the layers. That is why the
layers are flat, without baked-in gradients, shadows or rounding, and the background is kept separate.
The Xcode asset contains the classic full-bleed PNG. For the real glass icon:

1. Open Icon Composer (part of Xcode 26) and create a new icon.
2. Import `background.svg` as the background and `foreground.svg` as a group above it. Grid, ears,
   ring and ellipse can be set as separate groups there so the glass treats them individually.
3. Save as `AppIcon.icon` and drag it into the Runner target. The result can only be judged in Icon Composer
   or on a device running iOS 26.
