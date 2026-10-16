# FoxGrid Branding

Gewähltes App-Icon: **Fadenkreuz-Fuchs** (Fadenkreuz mit Fuchsohren über einem Raster, in der Mitte die
orange Fehlerellipse wie in der Karte).

| Datei | Zweck |
|---|---|
| `fadenkreuz-fuchs/background.svg` | Hintergrundebene, flach `#0B3B3C` |
| `fadenkreuz-fuchs/foreground.svg` | Vordergrundebene (Raster, Ohren, Ring, Ellipse, Ticks) auf transparent |
| `fadenkreuz-fuchs/icon.svg` | beide Ebenen zusammen |
| `alternatives/` | die verworfenen Entwürfe „Peilfuchs“ und „Signalpfeil“ |

Farben: Hintergrund `#0B3B3C`, Orange `#FF7A1A`, Weiß `#FFFFFF`.

## Icons neu erzeugen

```bash
python3 tools/branding/generate_icons.py   # braucht rsvg-convert und ImageMagick (magick)
```

Das Skript schreibt iOS (alle Größen des `AppIcon.appiconset`, vollflächig und ohne Alphakanal), Android
(adaptiv mit Vordergrund-, Hintergrund- und Monochrom-Ebene für Themed Icons plus Fallback-PNGs) und Web
(Favicon, `Icon-192/512`, maskierbare Varianten).

## Liquid Glass (iOS 26)

iOS rundet das Icon selbst ab und legt Glanz, Tiefe und Lichtbrechung über die Ebenen. Deshalb sind die
Ebenen flach, ohne eingebackene Verläufe, Schatten oder Rundung, und der Hintergrund liegt getrennt.
Das Xcode-Asset enthält das klassische vollflächige PNG. Für das echte Glas-Icon:

1. Icon Composer öffnen (Teil von Xcode 26) und ein neues Icon anlegen.
2. `background.svg` als Hintergrund und `foreground.svg` als Gruppe darüber importieren. Raster, Ohren,
   Ring und Ellipse lassen sich dort als eigene Gruppen setzen, damit das Glas sie getrennt behandelt.
3. Als `AppIcon.icon` speichern und ins Runner-Target ziehen. Das Ergebnis lässt sich nur im Icon Composer
   oder auf einem Gerät mit iOS 26 beurteilen.
