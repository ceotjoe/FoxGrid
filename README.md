# FoxGrid

Open-Source-Werkzeug für Funkamateure: Eine Gruppe peilt gemeinsam einen Störsender auf einem
VHF/UHF (beliebige Frequenz, z. B. 2 m, 70 cm, 23 cm), etwa auf einem Relais. Teilnehmer erfassen Peilungen (Standort, Richtung, Unsicherheit, Feldstärke), das Backend
berechnet live den wahrscheinlichsten Standort des Störers samt Fehlerellipse und verteilt das Ergebnis
an alle. Lizenz: MIT.

**Stand: Phase 4 (Automatisierung).** Plan und offene Fragen: [docs/phase0-plan.md](docs/phase0-plan.md),
Konventionen: [CLAUDE.md](CLAUDE.md). Store-Release: [docs/release.md](docs/release.md).

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

## App-Icon

Das Icon (Fadenkreuz-Fuchs) liegt als SVG-Ebenen in [docs/branding](docs/branding) und wird mit
`python3 tools/branding/generate_icons.py` für iOS, Android (adaptiv, Themed Icons) und Web erzeugt.
Dort steht auch, wie daraus in Icon Composer ein Liquid-Glass-Icon für iOS 26 entsteht.

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

**Phase 3 (Nahpeilung):**
- Homing-Screen (Kompass-Symbol in der Kartenleiste): großer Pfeil zum wahrscheinlichsten Standort mit Distanz,
  Hinweis „im 1σ-Bereich“, Pegelverlauf, farbige Spur nach Feldstärke (blau schwach, rot stark) und Karte
- Schnelleingabe unten fixiert: S-Meter-Tasten (S1 … S9+60, S9 = −93 dBm, 6 dB je S-Stufe nach IARU für VHF/UHF),
  dBm-Feld, Dämpfungsglied (aus/10/20/30/40 dB) und „letzten Wert alle 2 s mitschreiben“
- RSSI-Logging über dieselbe Offline-Queue (`POST /missions/{id}/rssi`, idempotent, nie gelöscht, nur deaktivierbar)
- RSSI-Fusion in der Engine: Log-Distanz-Pfadverlustmodell mit unbekanntem Exponenten und Referenzpegel
  (pro Kandidatenpunkt gefittet), Messwerte vorher um die Dämpfung korrigiert, geht als zusätzliche Likelihood ein
  (`engine_params`: `use_rssi`, `rssi_sigma_db`, `rssi_weight`); Karte, PDF, GPX, KML und JSON enthalten die Spur
- Funkgeräte-Abstraktion für CAT-S-Meter (Icom CI-V, Kenwood/Yaesu ASCII) mit Kalibrierung; siehe Grenzen
- Simulator: `uv run tools/simulator/run.py --bearers 2 --outliers 0 --homing`

**Phase 4 (Automatisierung):**
- MQTT-Ingest für automatische Peilstationen (Mosquitto und ein eigener Ingest-Dienst, Compose-Profil `mqtt`),
  Schema, Sicherheitsmodell und Beispielclient: [docs/mqtt.md](docs/mqtt.md). Jede Station ist ein Sensor mit
  eigenem API-Schlüssel und erscheint als eigener Teilnehmer; Leads legen sie in der App unter *Sensoren* an
- Relais-Hook (`tools/relay_hook/hook.py`): meldet „Squelch offen ohne CTCSS“ als Aussendung der Quelle `relay`
  (Banner, Push, Zuordnung der Peilungen), entprellt und mit `--simulate` ohne Hardware testbar
- Positionsvorschläge: Die Karte zeigt auf Wunsch (Glühbirnen-Symbol) die drei besten Orte für die nächste
  Peilung mit dem erwarteten Flächengewinn. Reine Anzeige, es wird niemand losgeschickt.

```bash
docker compose --profile mqtt up -d            # zusätzlich Mosquitto und Ingest-Dienst
uv run tools/sensor_client/station.py --help   # Beispielclient für eine Peilstation
uv run tools/relay_hook/hook.py --help         # Relais-Hook
```

**Phase 5 (Rundstrahler):**
- Feste Stationen mit Rundstrahlantenne (Rolle *fixed*) melden den S-Wert des Störers über das Sendemast-Symbol
  in der Kartenleiste. **Gemessen wird auf der Eingabefrequenz des Relais** (Reverse-Taste): auf der Ausgabe hört man
  nur das Relais. Der Standort kommt per GPS oder wird als fester Standort eingegeben (z. B. Heim-QTH, gilt je Einsatz). Die Meldung läuft über dieselbe Offline-Queue wie alle Messwerte.
- Die Engine fusioniert die Pegel mehrerer Stationen über das Log-Distanzmodell. Jede Station bekommt einen
  unbekannten Offset (Antenne, Kabel, Empfänger, Prior ±6 dB, `engine_params.rssi_station_sigma_db`); es braucht
  mindestens 4 Stationen (`rssi_omni_min_stations`), pro Station und Aussendung zählt der Median.
- Kalibrierung (optional): Die Einsatzleitung legt den Relais-Standort fest (Station → *Relais festlegen*, oder
  `PATCH /missions/{id}`). Jede Station misst einmal den Pegel der Relais-**Ausgabe**; daraus werden die relativen
  Offsets der Stationen berechnet.
- Karte: Je Station ein Marker mit dem letzten S-Wert (blau schwach, rot stark) und ein **Entfernungsring**, auf dem das
  Pegelmodell den Störer sieht, samt zwei blassen Ringen für die Streuung des Fits (abschaltbar im Filter). Wo sich die Ringe
  treffen, liegt die Schätzung. Das Relais erscheint als Sendemast.
- Erwartung: nur ein grobes Gebiet (Größenordnung km bei Stationen in 2–15 km Entfernung, siehe
  `uv run tools/simulator/omni_eval.py`). Peilungen dominieren, sobald sie vorliegen.

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
- CAT: Es gibt Protokolle, Kalibrierung, Profile (IC-705, IC-9700, Kenwood, Yaesu FT-991A) und einen
  Abfrage-Dienst, aber **keinen Transport**. USB-OTG und Bluetooth brauchen je ein Plattform-Plugin und eine
  Hardware zum Testen; bis dahin tippst du die Werte ein. Die Rohskalen der Geräte sind Näherungen, die
  Kalibrierung in den Einstellungen gleicht Abweichungen aus.
- RSSI-Fusion: Das Modell nimmt eine Quelle mit isotroper Abstrahlung und Gauß-Streuung (Standard 6 dB) an;
  Reflexionen und Abschattung erzeugen Ausreißer, die nur über die Streuung abgefangen werden. Mit weniger als
  5 Messwerten wird die Spur ignoriert. Die S9-Konvention (−93 dBm) gilt für VHF/UHF (ab ca. 30 MHz), nicht für KW; unter 30 MHz warnt die App beim Anlegen eines Einsatzes.
- Der Pfeil nutzt den GPS-Kurs ab 1,5 m/s und sonst Kompass plus Missweisung; ohne Kompass (Web) zeigt er
  relativ zu Norden.
- Positionsvorschläge rechnen mit der Fisher-Information der Peilungen (Gauß-Näherung ohne Ausreißeranteil und
  ohne RSSI) und bevorzugen bei gleicher Winkelgenauigkeit Orte nahe am Ziel. Gelände, Straßen und Erreichbarkeit
  kennt die Engine nicht; nur das Suchgebiet des Einsatzes schränkt die Kandidaten ein.
- Der MQTT-Schlüssel steckt in jeder Nachricht: ohne TLS am Broker ist er mitlesbar (siehe docs/mqtt.md).
  Der Relais-Hook und die Peilstationen sind nur gegen Simulation und einen Testbroker geprüft, nicht an echter
  Hardware. Der Controller des Relais muss seinen Zustand als `{"squelch": …, "ctcss": …}` per MQTT melden.
- Raster-PNG der Engine und der QR-Scanner fehlen noch.
