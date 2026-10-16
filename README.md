# FoxGrid

Open-Source-Werkzeug für Funkamateure: Eine Gruppe peilt gemeinsam einen Störsender auf einem
70-cm-Relais. Teilnehmer erfassen Peilungen (Standort, Richtung, Unsicherheit, Feldstärke), das Backend
berechnet live den wahrscheinlichsten Standort des Störers samt Fehlerellipse und verteilt das Ergebnis
an alle. Lizenz: MIT.

**Stand: Phase 1 (MVP).** Plan und offene Fragen: [docs/phase0-plan.md](docs/phase0-plan.md),
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

## Phase 1: Umfang und bekannte Grenzen

Enthalten: Einsatz anlegen, Beitritt per Token, Positionsupdates, manuelle Peilung, Strahlenfächer live,
MLE-Punkt und Ellipse, Aussendung starten/stoppen, Ausreißer markieren (Peilungen werden nie gelöscht).

Noch nicht enthalten (spätere Phasen): Drift-Offline-Queue, Offline-Kacheln, Push, automatische
Missweisung (Phase 1: manuelle Eingabe), Heatmap-Konturen, Chat/Aufgaben, Export, Nahpeilung.
Die Kartenkacheln kommen direkt von `tile.openstreetmap.org` bzw. `tile.opentopomap.org`; für den
Produktivbetrieb ist ein eigener Tile-Server nötig (siehe offene Frage 7).
