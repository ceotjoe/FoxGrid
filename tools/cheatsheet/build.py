# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow>=10"]
# ///
"""Build the two-page A4 bearer cheat sheet (PDF) from annotated app screenshots.

Usage:
    uv run tools/cheatsheet/build.py            # builds DE + EN into docs/user-guide/
    uv run tools/cheatsheet/build.py --lang de

Needs Google Chrome (headless) for HTML -> PDF. Raw screenshots live in
``docs/user-guide/img/cheatsheet/raw/``; marker positions in ``annotations.json``.
Markers are drawn into copies of the screenshots (``img/cheatsheet/annotated/``), so they
stay legible when printed in black and white (number badge plus a thick frame).
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "docs" / "user-guide"
RAW = GUIDE / "img" / "cheatsheet" / "raw"
ANN = GUIDE / "img" / "cheatsheet" / "annotated"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
ORANGE = (232, 89, 12)

FONT_CANDIDATES = ["/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/SFNS.ttf"]


def font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def annotate(name: str, spec: dict) -> Path:
    img = Image.open(RAW / f"{name}.png").convert("RGB")
    img = img.crop((0, 0, img.width, spec["crop"]))
    draw = ImageDraw.Draw(img)
    f = font(58)
    for mark in spec["marks"]:
        x0, y0, x1, y1 = mark["rect"]
        pad = 8
        draw.rounded_rectangle((x0 - pad, y0 - pad, x1 + pad, y1 + pad), radius=22, outline="white", width=14)
        draw.rounded_rectangle((x0 - pad, y0 - pad, x1 + pad, y1 + pad), radius=22, outline=ORANGE, width=8)
        r = 44
        cx, cy = mark.get("at", (x0 - pad + 6, y0 - pad + 6))
        cx = max(cx, r + 6)
        cy = max(cy, r + 6)
        draw.ellipse((cx - r - 5, cy - r - 5, cx + r + 5, cy + r + 5), fill="white")
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=ORANGE)
        draw.text((cx, cy), str(mark["n"]), fill="white", font=f, anchor="mm")
    ANN.mkdir(parents=True, exist_ok=True)
    out = ANN / f"{name}.jpg"
    img.save(out, quality=88)
    return out


def data_uri(path: Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode()


T = {
    "de": {
        "lang": "de",
        "title": "FoxGrid – Cheat Sheet Peiler",
        "sub": "Vorderseite: Beitreten, Karte, Peilung erfassen · Rückseite: Nahpeilung, Sync, Regeln. Bezeichnungen wie in der App.",
        "col1": ("1 · Beitreten", [
            "Rufzeichen eintragen.",
            "Einladung einfügen: Link der Einsatzleitung antippen (füllt das Feld) oder Token einfügen.",
            "<b>Beitreten</b> tippen.",
        ]),
        "col2": ("2 · Freigabe abwarten", [
            "4-stelliger Code: der Einsatzleitung <b>per Funk nennen</b>. Nach der Freigabe öffnet sich die Karte.",
        ]),
        "col3": ("3 · Karte", [
            "Schätzung: Zahl der Peilungen, Fehlergröße (1σ).",
            "Roter Marker = wahrscheinlichster Ort, Ellipsen = Fehlerbereich.",
            "Glühbirne: 3 beste Orte für die nächste Peilung (erscheinen als 1–3 auf der Karte).",
            "Chat.",
            "Nahpeilung (Kompass), siehe Rückseite.",
            "Wolke: Sync-Status, Tippen → „Jetzt senden“.",
            "<b>Zielkreuz-Taste: Peilung erfassen.</b>",
            "Aussendung Start/Ende: Sendung des Störers melden. Roter Banner „Störer sendet“ = jetzt peilen.",
        ]),
        "col4": ("4 · Peilung erfassen", [
            "<b>Azimut</b> in ° eingeben.",
            "„Kompass“: Azimut vom Gerätekompass übernehmen.",
            "<b>rechtweisend</b> (wahr Nord) oder <b>magnetisch</b> wählen – die App rechnet um.",
            "<b>Genauigkeit σ</b> wählen (Pflicht, vorgewählt: mittel).",
            "Optional: RSSI, Dämpfung, Polarisation, Notiz.",
            "<b>Speichern.</b> Der Standort kommt automatisch per GPS.",
        ]),
        "sigma_h": "Welche Genauigkeit?",
        "sigma": [("scharf ±5°", "klare, stabile Peilung"), ("mittel ±15°", "brauchbar, etwas Streuung"), ("schlecht ±30°", "schwach, Reflexionen, unsicher")],
        "sigma_note": "Ehrlich bleiben: ein zu scharfer Wert verzieht das Ergebnis, ein breiter wird nur schwächer gewichtet.",
        "map_h": "Karte lesen",
        "map": [
            "Ellipse lang und schmal → Peilungen fast parallel. <b>Standort so wählen, dass sich die Peillinien in einem großen Winkel schneiden.</b>",
            "Strahlen = alle Peilungen. Filter „Aussendung / Alle“ oben links.",
            "Glühbirne und Filter sind nur Vorschläge – niemand wird geschickt.",
        ],
        "join_h": "Beim Beitreten",
        "join": ["Link nur im geschlossenen Team weitergeben.", "„Zuletzt benutzt“ auf dem Beitritts-Bildschirm: erneut beitreten ohne neue Einladung (nur am selben Gerät)."],
        "bk1": ("5 · Nahpeilung (Kompass-Symbol)", [
            "Pfeil zeigt zum wahrscheinlichsten Ort, mit Entfernung. Er nutzt GPS-Kurs (ab 1,5 m/s), sonst Kompass.",
            "Verlauf des Signalpegels, Farbe der Spur: blau schwach, rot stark.",
            "<b>Pegel in dBm</b> eintippen → <b>Erfassen</b>. Darunter: Schalter „Letzten Wert alle 2 s mitschreiben“.",
            "<b>S-Taste</b> tippen erfasst den Wert (S1, S3, S5, S7 …, seitlich wischen; S9 = −93 dBm, 6 dB je S-Stufe).",
            "<b>Dämpfung</b> wählen (aus / 10 / 20 / 30 / 40 dB): den wirklich benutzten Wert, er wird herausgerechnet.",
        ]),
        "bk2": ("6 · Wo als Nächstes peilen?", [
            "Orte 1–3: Peilrichtung von dort und erwartete Fehlerellipse danach.",
            "Nur Vorschläge, keine Anweisungen.",
        ]),
        "bk_note": "Erst ab 5 Messwerten gehen die Pegel in die Schätzung ein. Reflexionen verfälschen Pegel – Peilungen bleiben verlässlicher.",
        "sync_h": "Offline und Sync",
        "sync": [
            "Alles wird <b>zuerst lokal gespeichert</b> und automatisch gesendet (Wolke oben). Fehlgeschlagenes bleibt sichtbar.",
            "Ohne Netz: Peilungen, Messwerte, Chat und Ausreißer-Markierungen werden eingereiht. <b>Positionsupdates nicht.</b>",
            "Die Missweisung braucht <b>einmal</b> Netz, danach gilt der gespeicherte Wert. Karten: nur bereits angesehene Kacheln.",
        ],
        "corr_h": "Korrekturen",
        "corr": [
            "<b>Peilungen werden nie gelöscht</b> – nur als Ausreißer markiert oder deaktiviert.",
            "Fremde Peilungen markieren: Leitung, Co-Leitung, Auswerter. Eigene Fehleingabe: im Chat melden.",
        ],
        "team_h": "Teamarbeit",
        "team": [
            "Chat: Einsatzkanal und Teamkanäle. Aufgaben: zugewiesene bearbeiten, Status pflegen.",
            "Du siehst die Positionen der anderen, sie sehen deine. Beobachter (Gäste) sehen weder Chat noch Positionen.",
        ],
        "rights_h": "Rechte als Peiler",
        "can": "Peilungen und Messwerte erfassen, chatten, zugewiesene Aufgaben, Position teilen, exportieren (GPX/KML/JSON/PDF)",
        "cannot": "externe Peilungen eingeben, fremde Peilungen markieren, fremde Sendungen beenden, Aufgaben/Einladungen erstellen, Rollen ändern, Einsatz beenden",
        "can_h": "Du darfst",
        "cannot_h": "Du darfst nicht",
        "flow_h": "Ablauf im Einsatz",
        "flow": ["Beitreten, Freigabe abwarten", "Banner „Störer sendet“ → peilen", "Peilung erfassen (Zielkreuz-Taste)", "Schätzung prüfen, Glühbirne ansehen", "Standort wechseln, erneut peilen", "Im Nahbereich: Nahpeilung"],
        "foot": "FoxGrid · Bildschirmfotos: Übungseinsatz mit simulierten Teilnehmern",
        "p": "Seite",
    },
    "en": {
        "lang": "en",
        "title": "FoxGrid – Bearer cheat sheet",
        "sub": "Front: join, map, capture a bearing · Back: homing, sync, rules. Labels as in the app (German).",
        "col1": ("1 · Join", [
            "Enter your <b>callsign</b> (<i>Rufzeichen</i>).",
            "Paste the invite: tap the lead's link (fills the field) or paste the token.",
            "Tap <b>Beitreten</b>.",
        ]),
        "col2": ("2 · Wait for approval", [
            "4-digit code: <b>tell it to the lead over the radio</b>. The map opens once you are approved.",
        ]),
        "col3": ("3 · Map", [
            "Estimate: number of bearings, error size (1σ).",
            "Red marker = most likely location, ellipses = error region.",
            "Bulb: the 3 best places for your next bearing (shown as 1–3 on the map).",
            "Chat.",
            "Homing (compass), see back.",
            "Cloud: sync status, tap → \"Jetzt senden\".",
            "<b>Crosshair button: capture a bearing.</b>",
            "Aussendung Start/Ende: report the interferer's transmission. Red banner \"Störer sendet\" = take bearings now.",
        ]),
        "col4": ("4 · Capture a bearing", [
            "Enter the <b>azimuth</b> in °.",
            "\"Kompass\": take the azimuth from the device compass.",
            "Choose <b>rechtweisend</b> (true north) or <b>magnetisch</b> – the app converts.",
            "Choose the <b>uncertainty σ</b> (mandatory, preselected: mittel).",
            "Optional: RSSI, attenuation, polarisation, note.",
            "<b>Speichern.</b> Your position comes from GPS automatically.",
        ]),
        "sigma_h": "Which uncertainty?",
        "sigma": [("scharf ±5°", "clear, stable bearing"), ("mittel ±15°", "usable, some spread"), ("schlecht ±30°", "weak, reflections, unsure")],
        "sigma_note": "Be honest: a value that is too sharp pulls the result off; a wide one is simply weighted less.",
        "map_h": "Reading the map",
        "map": [
            "Long, narrow ellipse → bearings nearly parallel. <b>Move so the bearing lines cross at a wide angle.</b>",
            "Rays = all bearings. Filter \"Aussendung / Alle\" at the top left.",
            "Bulb and filters only suggest – nobody is sent anywhere.",
        ],
        "join_h": "When joining",
        "join": ["Share the link inside the closed team only.", "\"Zuletzt benutzt\" on the join screen: rejoin without a new invite (same device only)."],
        "bk1": ("5 · Homing (compass icon)", [
            "The arrow points to the most likely location, with distance. It uses the GPS course (above 1.5 m/s), otherwise the compass.",
            "Signal level history; track colour: blue weak, red strong.",
            "Type the <b>level in dBm</b> → <b>Erfassen</b>. Below: switch \"Letzten Wert alle 2 s mitschreiben\" (log every 2 s).",
            "Tapping an <b>S-button</b> records the value (S1, S3, S5, S7 …, swipe sideways; S9 = −93 dBm, 6 dB per S-unit).",
            "Choose the <b>Dämpfung</b> (off / 10 / 20 / 30 / 40 dB) you really use; it is corrected for.",
        ]),
        "bk2": ("6 · Where to bear next?", [
            "Places 1–3: bearing direction from there and the expected error ellipse afterwards.",
            "Suggestions only, not instructions.",
        ]),
        "bk_note": "Levels count towards the estimate from 5 readings on. Reflections distort levels – bearings stay more reliable.",
        "sync_h": "Offline & sync",
        "sync": [
            "Everything is <b>saved locally first</b> and sent automatically (cloud at the top). Failed items stay visible.",
            "Without network: bearings, readings, chat and outlier flags are queued. <b>Position updates are not.</b>",
            "The declination needs the network <b>once</b>, then the cached value is used. Maps: only tiles you have viewed.",
        ],
        "corr_h": "Corrections",
        "corr": [
            "<b>Bearings are never deleted</b> – only flagged as outlier or deactivated.",
            "Flagging other people's bearings: lead, deputy, analyst. Wrong entry of your own: tell them in the chat.",
        ],
        "team_h": "Teamwork",
        "team": [
            "Chat: mission and team channels. Tasks: work on what is assigned to you, update the status.",
            "You see the positions of the others, they see yours. Observers (guests) see neither chat nor positions.",
        ],
        "rights_h": "Your rights as a bearer",
        "can": "capture bearings and readings, chat, assigned tasks, share position, export (GPX/KML/JSON/PDF)",
        "cannot": "enter external bearings, flag others' bearings, stop others' transmissions, create tasks/invites, change roles, end the mission",
        "can_h": "You can",
        "cannot_h": "You cannot",
        "flow_h": "Typical sequence",
        "flow": ["Join, wait for approval", "Banner \"Störer sendet\" → take bearings", "Capture the bearing (crosshair button)", "Check the estimate, look at the bulb", "Change position, take the next bearing", "Close range: homing"],
        "foot": "FoxGrid · Screenshots: exercise mission with simulated participants",
        "p": "Page",
    },
}

CSS = """
@page{size:A4;margin:0}
*{box-sizing:border-box}
html,body{margin:0}
body{font:8.2pt/1.28 -apple-system,Helvetica,Arial,sans-serif;color:#1a1a1a;-webkit-print-color-adjust:exact;print-color-adjust:exact}
.page{width:210mm;height:297mm;padding:9mm 10mm 7mm;position:relative;overflow:hidden;page-break-after:always}
.page:last-child{page-break-after:auto}
h1{font-size:15pt;margin:0;border-bottom:2.2px solid #e8590c;padding-bottom:2px}
.sub{font-size:7.4pt;color:#555;margin:2px 0 5px}
h2{font-size:9.6pt;margin:0 0 2px;color:#c2410c}
h3{font-size:8.4pt;margin:6px 0 2px;color:#c2410c}
.row{display:flex;gap:4mm}
.col{flex:1;min-width:0}
.shot{width:100%;border:1px solid #999;border-radius:6px;display:block}
ol.k{list-style:none;margin:3px 0 0;padding:0}
ol.k li{position:relative;padding-left:15px;margin:0 0 2px;font-size:7.5pt;line-height:1.25}
ol.k li::before{content:attr(data-n);position:absolute;left:0;top:0.5px;width:11px;height:11px;border-radius:50%;background:#e8590c;color:#fff;font-weight:700;font-size:7pt;line-height:11px;text-align:center}
ul{margin:2px 0;padding-left:13px}li{margin:0 0 1.5px}
table{border-collapse:collapse;width:100%;margin:2px 0}
th,td{border:1px solid #bbb;padding:1px 4px;text-align:left;vertical-align:top;font-size:7.8pt}
th{background:#f1f1f1}
.box{border:1px solid #e8590c;border-left-width:4px;background:#fff7f0;border-radius:3px;padding:2px 6px;margin:5px 0;font-size:7.8pt}
.two{display:flex;gap:6mm}.two>div{flex:1;min-width:0}
.flow{display:flex;gap:2mm}.flow>div{flex:1;border:1px solid #e8590c;border-radius:4px;padding:4px 5px;font-size:8pt;background:#fff7f0}
.flow b{display:block;color:#e8590c;font-size:13pt;line-height:1}
.foot{position:absolute;left:10mm;right:10mm;bottom:4mm;font-size:6.6pt;color:#777;display:flex;justify-content:space-between}
"""


def legend(items: list[str]) -> str:
    return '<ol class="k">' + "".join(f'<li data-n="{i}">{t}</li>' for i, t in enumerate(items, 1)) + "</ol>"


def shot(uri: str, w: str | None = None) -> str:
    style = f' style="width:{w}"' if w else ""
    return f'<img class="shot" src="{uri}"{style}>'


def page_html(lang: str, imgs: dict[str, str]) -> str:
    t = T[lang]
    h1, b1 = t["col1"]
    h2, b2 = t["col2"]
    h3, b3 = t["col3"]
    h4, b4 = t["col4"]
    hb1, bb1 = t["bk1"]
    hb2, bb2 = t["bk2"]
    sigma_rows = "".join(f"<tr><td><b>{a}</b></td><td>{b}</td></tr>" for a, b in t["sigma"])
    front = f"""
<div class="page">
<h1>{t['title']}</h1><div class="sub">{t['sub']}</div>
<div class="row">
 <div class="col"><h2>{h1}</h2>{shot(imgs['01_join'])}{legend(b1)}
   <h2 style="margin-top:7px">{h2}</h2>{shot(imgs['02_pending'])}{legend(b2)}</div>
 <div class="col" style="flex:1.04"><h2>{h3}</h2>{shot(imgs['03_map'])}{legend(b3)}</div>
 <div class="col" style="flex:1.04"><h2>{h4}</h2>{shot(imgs['04_capture'])}{legend(b4)}</div>
</div>
<div class="two" style="margin-top:4px">
 <div><h3>{t['sigma_h']}</h3><table>{sigma_rows}</table><div style="font-size:7.4pt;margin-top:2px"><i>{t['sigma_note']}</i></div></div>
 <div><h3>{t['map_h']}</h3><ul>{''.join(f'<li>{x}</li>' for x in t['map'])}</ul>
 <h3>{t['join_h']}</h3><ul>{''.join(f'<li>{x}</li>' for x in t['join'])}</ul></div>
</div>
<div class="foot"><span>{t['foot']}</span><span>{t['p']} 1/2</span></div>
</div>"""
    back = f"""
<div class="page">
<h1>{t['title']}</h1><div class="sub">{t['sub']}</div>
<div class="row">
 <div class="col" style="flex:1.1"><h2>{hb1}</h2>{shot(imgs['06_homing'])}{legend(bb1)}</div>
 <div class="col" style="flex:1.1"><h2>{hb2}</h2>{shot(imgs['05_suggest'])}{legend(bb2)}
   <div class="box">{t['bk_note']}</div></div>
 <div class="col" style="flex:1.05">
   <h3 style="margin-top:0">{t['sync_h']}</h3><ul>{''.join(f'<li>{x}</li>' for x in t['sync'])}</ul>
   <h3>{t['corr_h']}</h3><ul>{''.join(f'<li>{x}</li>' for x in t['corr'])}</ul>
   <h3>{t['team_h']}</h3><ul>{''.join(f'<li>{x}</li>' for x in t['team'])}</ul>
   <h3>{t['rights_h']}</h3>
   <table><tr><th>{t['can_h']}</th></tr><tr><td>{t['can']}</td></tr><tr><th>{t['cannot_h']}</th></tr><tr><td>{t['cannot']}</td></tr></table>
 </div>
</div>
<h3 style="margin-top:8mm">{t['flow_h']}</h3>
<div class="flow">{''.join(f'<div><b>{i}</b>{x}</div>' for i, x in enumerate(t['flow'], 1))}</div>
<div class="foot"><span>{t['foot']}</span><span>{t['p']} 2/2</span></div>
</div>"""
    return f"<!doctype html><html lang='{t['lang']}'><meta charset=utf-8><title>{t['title']}</title><style>{CSS}</style><body>{front}{back}</body></html>"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=["de", "en"], action="append")
    args = ap.parse_args()
    spec = json.loads((Path(__file__).parent / "annotations.json").read_text())
    imgs = {k: data_uri(annotate(k, v)) for k, v in spec.items() if not k.startswith("_")}
    for lang in args.lang or ["de", "en"]:
        html = page_html(lang, imgs)
        suffix = ".de" if lang == "de" else ""
        pdf = GUIDE / f"bearer-cheat-sheet-screens{suffix}.pdf"
        with tempfile.TemporaryDirectory() as tmp:
            h = Path(tmp) / "sheet.html"
            h.write_text(html)
            subprocess.run(
                [CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={pdf}", h.as_uri()],
                check=True, capture_output=True,
            )
        print(pdf)
    return 0


if __name__ == "__main__":
    sys.exit(main())
