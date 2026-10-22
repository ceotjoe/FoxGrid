# FoxGrid – Project Conventions

FoxGrid is an open-source (MIT) app for a group of radio amateurs to jointly locate an interferer on VHF/UHF (any frequency, e.g. 2 m,
70 cm, 23 cm; the S-meter scale is the VHF one, below 30 MHz the app only warns).
Participants record bearings (position, azimuth, uncertainty, field strength); the backend fuses them live into a
most-likely interferer location and pushes the result to everyone. Also used for team coordination (chat, tasks).

Language: **everything is English**: README, docs, code, comments, commit messages, identifiers. The app UI is German
(quote German labels where needed). Only store listings (`store/metadata/*/de-DE`) and the German privacy policy are localised.

## Status
All five phases are implemented (MVP, robustness and coordination, homing, automation, omnidirectional stations), plus access
control. The documentation map is `docs/README.md`; this file only holds the rules for working on the repo. Work strictly in
steps; stop after each, summarize (what is done, how to start, how to test) and wait for the user's OK. Ask instead of guessing
on domain questions (DF technique, amateur radio).

## Stack (binding)
- App + web control room: Flutter (stable), Dart null safety, `flutter_map` (OSM / OpenTopoMap), Riverpod,
  `geolocator`, `flutter_compass`, `drift` (local DB + offline sync queue), `dio` (REST), WebSocket client.
- Backend: Python 3.12 (pinned via `.python-version`), FastAPI, SQLAlchemy 2 + GeoAlchemy2, Alembic, Pydantic v2.
- DB: PostgreSQL 16 + PostGIS. Live: FastAPI WebSockets + Redis Pub/Sub (multi-worker fan-out).
- Engine: own package `foxgrid_engine` (numpy, pyproj only; **no web/DB deps**).
- Optional: MQTT (Mosquitto, own ingest process).
- Dev: `docker compose up` (api, db, redis, mqtt when needed).

## Repo layout
```
CLAUDE.md  README.md  CONTRIBUTING.md  SECURITY.md  CHANGELOG.md  docker-compose.yml  .env.example
backend/   app/{api,models,schemas,services,ws}  alembic/  tests/
engine/    foxgrid_engine/  tests/            # pure Python, isolated tests
app/       Flutter project (iOS, Android, Web)
tools/     simulator, sensor_client, relay_hook, branding, store
deploy/    Caddyfile, mosquitto
docs/      README.md (index), user-guide/, concepts/, reference/, operations/, development/, privacy/, adr/
```

## Domain rules (critical – do not violate; full text in `docs/concepts/domain-rules.md`)
- Azimuth is **always stored as true north (rechtweisend)**; store which reference was entered and the declination applied.
- `sigma_deg` is **mandatory**. Presets: sharp ±5°, medium ±15°, poor ±30°.
- All timestamps come from the client in UTC; the server additionally stores `received_at`.
- Bearings are **never deleted** – only flagged outlier / deactivated. Edits are append-only revisions. A DB trigger forbids DELETE.
- Bearings carry a client-generated UUID (idempotent offline sync; duplicate POST = no-op / 200).
- Position tracks are purged N days after mission end (default 30). Bearings are kept.
- Every new/changed bearing triggers an estimate recompute: background, debounce 500 ms.
- Every query that feeds an estimate goes through `domain.trusted_only(stmt, Bearing|RssiSample)`.
- Auth: per-mission invite tokens (QR/link) -> participant gives callsign -> JWT. No passwords.

## Commands
```
cp .env.example .env && docker compose up -d --build        # api + db + redis
cd backend && uv run ruff check . && uv run mypy app && uv run pytest   # PostGIS+Redis via testcontainers
cd engine  && uv run ruff check . && uv run mypy --strict foxgrid_engine && uv run pytest
cd app     && flutter analyze && flutter test
uv run tools/simulator/run.py                               # replay mission with 5 simulated bearers
cd backend && uv run alembic revision --autogenerate -m "..."   # needs FOXGRID_DATABASE_URL
```

## Quality rules
- `ruff` (backend + engine), `mypy --strict` (engine), `flutter analyze` with zero warnings.
- Engine coverage > 90 %; API integration tests against real PostGIS; widget tests for the capture flow.
- GitHub Actions: lint + tests for backend, engine, app.
- No secrets in repo; config via `.env` (+ `.env.example`).
- Small, traceable commits with meaningful messages. Only commit when the user asks.
- Offline-first app: all writes go to the local Drift DB first, then a sync queue with retry + exponential backoff;
  sync status always visible.
- Keep docs in sync with behaviour. Privacy-relevant changes: `app/ios/Runner/PrivacyInfo.xcprivacy`, `docs/privacy/*.md` and
  `docs/operations/store-compliance.md` must stay in sync.

## Where the implementation notes went
They used to live here and are now in `docs/`; update them there, not in this file.

| Topic | Document |
|---|---|
| Engine (grid, von Mises, RSSI, omni stations, suggestions) | `docs/concepts/engine.md` |
| Architecture, recompute, events, offline sync, MQTT ingest | `docs/concepts/architecture.md` |
| Backend conventions (trust, rate limits, plausibility, join code, stations) | `docs/development/backend.md` |
| App internals (outbox, tiles, join/session, homing, stations, push) | `docs/development/app.md` |
| Test conventions, generated files, simulator | `docs/development/setup-and-testing.md` |
| Access control for leaked links (device binding, approval, trust, quarantine) | `docs/user-guide/mission-lead-security.md`, ADR 0005 |
| Push, release, store compliance, deployment | `docs/operations/` |
| MQTT, API, configuration, data model, limitations | `docs/reference/` |
| Branding / icons (do not edit generated PNGs; App ID `com.itwebservice.foxgrid` is fixed) | `docs/development/branding.md` |

Generated files that must not be edited by hand: `app/lib/core/database.g.dart` (`dart run build_runner build`), app icons
(`tools/branding/generate_icons.py`), store graphics (`tools/store/generate_assets.py`).
