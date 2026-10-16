# FoxGrid

Open-Source-Werkzeug für Funkamateure: Eine Gruppe peilt gemeinsam einen Störsender auf einem
70-cm-Relais. Teilnehmer erfassen Peilungen (Standort, Richtung, Unsicherheit, Feldstärke), das Backend
berechnet live den wahrscheinlichsten Standort des Störers samt Fehlerellipse und verteilt das Ergebnis
an alle. Lizenz: MIT.

**Stand: Phase 2 (Robustheit und Koordination).** Plan und offene Fragen: [docs/phase0-plan.md](docs/phase0-plan.md),
Konventionen: [CLAUDE.md](CLAUDE.md).

## Aufbau

| Verzeichnis | Inhalt |
|---|---|
| `engine/` | `foxgrid_engine` – Peil-Engine (numpy, pyproj), ohne Web/DB-Abhängigkeiten |
| `backend/` | FastAPI, SQLAlchemy/GeoAlchemy2, Alembic, WebSocket + Redis |
| `app/` | Flutter-App (Android, iOS, Web) |
| `tools/simulator/` | Spielt einen Einsatz mit simulierten Peilern ab |

## Starten

Voraussetzungen: Docker, [uv](https://docs.astral.sh/uv/), Flutter (stable).

```bash
cp .env.example .env        # Passwort und JWT-Secret anpassen
docker compose up -d --build   # API (Port 8000), PostGIS, Redis; Migrationen laufen automatisch
curl localhost:8000/healthz
```

Auf Apple-Silicon läuft das Standard-PostGIS-Image per Emulation (amd64); über
`FOXGRID_POSTGIS_IMAGE` lässt sich ein natives Image setzen.

App starten (der Server-URL-Standard ist `http://localhost:8000`, im Android-Emulator `http://10.0.2.2:8000`):

```bash
cd app
flutter run -d chrome          # Web-Leitstand
flutter run -d emulator-5554   # Android-Emulator
```

Einsatz anlegen: In der App Tab „Einsatz anlegen“; über das Personen-Symbol erscheint die Einladung
(Token und Link `foxgrid://join?server=…&token=…`). Andere Geräte treten mit Token oder Link bei.
Ein QR-Code zum Scannen kommt in Phase 2.

## Simulator (Abnahme)

```bash
uv run tools/simulator/run.py --interval-s 8
```

Legt einen Einsatz an, lässt fünf simulierte Peiler beitreten (einer davon mit grob falscher Peilung),
startet eine Aussendung und meldet nach jeder Peilung den Abstand der Schätzung zur wahren Position. Die
ausgegebene Einladung kann in der App eingegeben werden, um live zuzusehen. Exit-Code ≠ 0, wenn der Fehler
größer als `--max-error-m` (Standard 600 m) ist.

## Tests

```bash
cd engine  && uv run ruff check . && uv run mypy --strict foxgrid_engine && uv run pytest
cd backend && uv run ruff check . && uv run pytest     # startet PostGIS + Redis per testcontainers
cd app     && flutter analyze && flutter test
```

## Umfang

**Phase 1:** Einsatz anlegen, Beitritt per Token, Positionsupdates, manuelle Peilung, Strahlenfächer live,
MLE-Punkt und Ellipse, Aussendung starten/stoppen, Ausreißer markieren (Peilungen werden nie gelöscht).

**Phase 2:**
- Heatmap-Konturen (50/80/95 % Wahrscheinlichkeitsmasse), Filter nach Aussendung, Zeitfenster und
  Altersgewichtung (`GET /missions/{id}/estimate/query`)
- Chat (Einsatz- und Team-Kanal, Team-Nachrichten bleiben privat) und Aufgaben mit Zuweisung an Team oder Teilnehmer
- Offline-first: Alle Schreibaktionen landen zuerst in der lokalen Drift-Datenbank (Sync-Queue mit Retry und
  Backoff), der Sync-Status steht oben in der Leiste; der letzte Stand wird für den Offline-Start zwischengespeichert
- Kachel-Cache (angesehene Kacheln) und gezielter Kartenausschnitt-Download nur mit eigenem Tile-Server
- Missweisung nach dem World Magnetic Model (`GET /declination`), in der App vorbelegt und überschreibbar
- Export als GPX, KML, JSON und PDF-Protokoll (Karte, Peilungen, Ergebnis) über das Menü der Karte
- Nachtmodus (rotes Farbschema)
- Push bei Aussendungsstart: serverseitig fertig (FCM HTTP v1), siehe unten

## Push-Benachrichtigungen einrichten

Der Server verschickt bei Aussendungsstart einen Push an alle anderen Teilnehmer, sobald
`FOXGRID_FCM_PROJECT_ID` und `FOXGRID_FCM_CREDENTIALS_FILE` (Service-Account-Schlüssel eines Firebase-Projekts)
gesetzt sind; ohne Konfiguration wird der Push nur geloggt. Geräte melden ihr Token per
`POST /api/v1/push-tokens`. **Die App registriert noch kein Token:** dafür braucht sie die
Firebase-Konfigurationsdateien deines Projekts (`google-services.json`, `GoogleService-Info.plist`) und das
Paket `firebase_messaging`. Bis dahin gibt es Vibration und Banner nur bei geöffneter App.

## Bekannte Grenzen

- Web: Die Offline-Queue liegt nur im Arbeitsspeicher, weil keine sqlite-WASM-Dateien mitgeliefert werden;
  auf Android/iOS ist sie persistent (SQLite). Kein Kachel-Cache im Browser (nutzt den HTTP-Cache).
- Positionsupdates werden nicht nachgesendet, wenn die Verbindung fehlt (nur Peilungen, Chat, Aufgaben,
  Ausreißer-Markierungen und Aussendungen laufen über die Queue).
- Die automatische Missweisung braucht einmal Netz; danach gilt der zwischengespeicherte Wert.
- Kartenkacheln kommen von `tile.openstreetmap.org` bzw. `tile.opentopomap.org`. Deren Nutzungsrichtlinien
  verbieten Massen-Downloads; für Produktivbetrieb und Offline-Gebiete wird ein eigener Tile-Server benötigt.
- Raster-PNG der Engine, QR-Scanner, Nahpeilung (Phase 3) und MQTT (Phase 4) fehlen noch.
