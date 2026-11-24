# FoxGrid – Cheat Sheet für Peiler

*Eine A4-Seite zum Ausdrucken und Ausgeben im Einsatz. Bezeichnungen wie in der App.*

## 1 · Beitreten
1. **Link / QR-Code** der Einsatzleitung öffnen (`foxgrid://join?…`). Nur innerhalb des geschlossenen Teams weitergeben.
2. **Rufzeichen** eingeben.
3. Auf dem Warte-Bildschirm auf die Freigabe der Einsatzleitung warten. Er zeigt einen **4-stelligen Code** – die Leitung kann ihn per Funk abfragen.
4. Später: **„Zuletzt benutzt"** im Beitritts-Bildschirm tritt ohne neue Einladung wieder bei (nur am selben Gerät).

## 2 · Peilung erfassen
| Schritt | Was tun |
|---|---|
| 1 | Auf das **Sendungs-Banner** achten (Push, wenn die App im Hintergrund ist) – Sendungen werden gestartet und beendet. |
| 2 | Peilung mit eigener Ausrüstung an deinem Standort nehmen (GPS muss an sein). |
| 3 | **Azimut** eingeben und **rechtweisend oder magnetisch** wählen. Die App rechnet mit der Missweisung deines Standorts um und zeigt den verwendeten Wert. |
| 4 | **Unsicherheit σ** wählen – **Pflichtfeld**. |
| 5 | Optional: Signalstärke und Notiz. Speichern. |

| Unsicherheit | Wann |
|---|---|
| **Scharf ±5°** | klare, stabile Peilung |
| **Mittel ±15°** | brauchbar, etwas Streuung |
| **Schlecht ±30°** | schwach, Reflexionen, unsicher |
| Eigener Wert | wenn du es genauer weißt |

*Bei σ ehrlich bleiben: ein zu scharfer Wert verzieht das Ergebnis, ein breiter wird einfach schwächer gewichtet.*

## 3 · Karte lesen
- **Oranger Marker** = wahrscheinlichster Ort des Störers. **Ellipsen** = 1σ- und 2σ-Fehlerbereich.
- **Strahlen** = alle Peilungen. Lange, schmale Ellipse = Peilungen verlaufen fast parallel.
- **Glühbirne** = die 3 besten Orte für die nächste Peilung. Nur ein Vorschlag, niemand wird geschickt.
- **Filter:** Konturen (50/80/95 %), Sendungen oder Zeitfenster wählen, Alterungsgewichtung, Entfernungsringe fester Stationen.
- **So bewegen, dass sich die Peillinien in einem großen Winkel schneiden** – das verkleinert die Ellipse am schnellsten.

## 4 · Nahbereich – Homing (Kompass-Symbol)
- Großer **Pfeil** zeigt zum wahrscheinlichsten Ort, mit Entfernung. Innerhalb des 1σ-Bereichs erscheint ein Hinweis.
- Pfeilquelle: GPS-Kurs über 1,5 m/s, sonst Kompass + Missweisung.
- **Schnelleingabe** unten: S-Tasten **S1 … S9+60** (S9 = −93 dBm, 6 dB je S-Stufe), dBm-Feld (ohne Vorzeichen = negativ, `+5` = positiv, ±-Taste schaltet das Vorzeichen durch).
- **Dämpfungsglied** (aus / 10 / 20 / 30 / 40 dB): den wirklich genutzten Wert wählen – wird nachträglich herausgerechnet.
- Schalter **„letzten Wert alle 2 s protokollieren"** nimmt eine Reihe auf. Erst ab **5 Messwerten** gehen sie ein.
- Spurfarbe: blau = schwach, rot = stark. Reflexionen verfälschen Pegel – **Peilungen bleiben verlässlicher**.

## 5 · Teamarbeit
- **Chat:** Einsatzkanal und Teamkanäle. **Aufgaben:** zugewiesene Aufgaben bearbeiten und Status pflegen.
- Du **siehst** die Positionen der anderen, sie sehen deine.
- Beobachter (Gäste) sehen das Ergebnis, aber weder Chat noch Positionen.

## 6 · Offline & Sync
- Alles wird **zuerst lokal gespeichert** und dann automatisch gesendet (Wiederholung mit Backoff). Die **Sync-Leiste oben ist immer sichtbar**; fehlgeschlagene Einträge bleiben sichtbar.
- Ohne Netz werden Peilungen, Messwerte, Chat und Ausreißer-Markierungen eingereiht. **Positionsupdates werden nicht nachgesendet.**
- Die automatische Missweisung braucht **einmal** Netz, danach gilt der gespeicherte Wert. Karten zeigen nur bereits angesehene Kacheln.

## 7 · Korrekturen
- **Peilungen werden nie gelöscht.** Zweifelhafte werden als **Ausreißer** markiert oder deaktiviert; Änderungen bleiben als Revisionen erhalten.
- Fremde Peilungen markieren dürfen nur Leitung, Co-Leitung und Auswerter. Eigene Fehleingabe: Auswerter oder Leitung im Chat informieren.

## 8 · Was du darfst – und was nicht
| Du darfst | Du darfst nicht |
|---|---|
| Peilungen und Messwerte erfassen, chatten, zugewiesene Aufgaben bearbeiten, Position teilen, exportieren (GPX/KML/JSON/PDF) | externe Peilungen eingeben, fremde Peilungen markieren, fremde Sendungen beenden, Aufgaben oder Einladungen erstellen, Rollen ändern, den Einsatz beenden |
