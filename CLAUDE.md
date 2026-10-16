# FoxGrid – Project Conventions

FoxGrid is an open-source (MIT) app for a group of radio amateurs to jointly locate an interferer on a 70 cm repeater.
Participants record bearings (position, azimuth, uncertainty, field strength); the backend fuses them live into a
most-likely interferer location and pushes the result to everyone. Phase 1 = coarse bearing (triangulation),
later homing (RSSI). Also used for team coordination (chat, tasks).

Language: **README and user docs in German; code, comments, commit messages, identifiers in English.**

## Status
Phase 0 (planning, `docs/phase0-plan.md`) done; Phase 1 (MVP) implemented, awaiting user OK for Phase 2. Work strictly phase by phase; stop after each phase, summarize
(what is done, how to start, how to test) and wait for the user's OK. Ask instead of guessing on domain questions
(DF technique, amateur radio).

## Stack (binding)
- App + web control room: Flutter (stable), Dart null safety, `flutter_map` (OSM / OpenTopoMap), Riverpod,
  `geolocator`, `flutter_compass`, `drift` (local DB + offline sync queue), `dio` (REST), WebSocket client.
- Backend: Python 3.12, FastAPI, SQLAlchemy 2 + GeoAlchemy2, Alembic, Pydantic v2.
- DB: PostgreSQL 16 + PostGIS. Live: FastAPI WebSockets + Redis Pub/Sub (multi-worker fan-out).
- Engine: own package `foxgrid_engine` (numpy, pyproj only; **no web/DB deps**).
- Optional from Phase 4: MQTT (Mosquitto).
- Dev: `docker compose up` (api, db, redis, mqtt when needed).

## Repo layout
```
CLAUDE.md  README.md  docker-compose.yml  .env.example
backend/   app/{api,models,schemas,services,ws}  alembic/  tests/
engine/    foxgrid_engine/  tests/            # pure Python, isolated tests
app/       Flutter project (iOS, Android, Web)
tools/simulator/                              # replays a mission with simulated bearers
docs/      phase0-plan.md, ADRs
```

## Domain rules (critical – do not violate)
- Azimuth is **always stored as true north (rechtweisend)**. The app converts compass/magnetic input using the
  declination for the position (WMM or precomputed table). Manual input: user picks true or magnetic.
  Store which reference was entered and the declination applied (audit).
- `sigma_deg` is **mandatory**. Presets: sharp ±5°, medium ±15°, poor ±30°.
- All timestamps come from the client in UTC; server additionally stores `received_at`.
- Bearings are **never deleted** – only flagged outlier / deactivated. Edits are append-only revisions. Log stays complete.
- Bearings carry a client-generated UUID (idempotent offline sync; duplicate POST = no-op / 200).
- Position tracks are purged N days after mission end (default 30, configurable). Bearings are kept.
- Every new/changed bearing triggers an estimate recompute: background, debounce 500 ms.
- Auth: per-mission invite tokens (QR/link) -> participant gives callsign -> JWT. No passwords.

## Engine (`foxgrid_engine`)
Grid in local metric projection (UTM via pyproj), >= 5 km margin, default 50 m cell. Per bearing/cell: von Mises over
(measured azimuth − direction station→cell), kappa from sigma, outlier mixture eps (default 0.1) with uniform;
cells behind the station (>90°) get eps only. Fusion = sum of log-likelihoods of active bearings, optional age
decay (half-life) and per-transmission scoping. Output: MLE point, covariance + 1σ/2σ ellipse, contours
(GeoJSON, 50/80/95 % mass), optional PNG raster. Later: RSSI path-loss fusion (P3), next-bearing suggestion (P4).
Perf budget: 200×200 cells, 50 bearings < 200 ms (vectorised numpy). Tests: exact 3-bearer hit < 20 m, noisy within
2σ ellipse, gross outlier barely shifts result, parallel bearings -> elongated ellipse, 359°/1° wraparound.

## Commands
```
cp .env.example .env && docker compose up -d --build        # api + db + redis
cd backend && uv run ruff check . && uv run mypy app && uv run pytest   # PostGIS+Redis via testcontainers
cd engine  && uv run ruff check . && uv run mypy --strict foxgrid_engine && uv run pytest
cd app     && flutter analyze && flutter test
uv run tools/simulator/run.py                               # replay mission with 5 simulated bearers
cd backend && uv run alembic revision --autogenerate -m "..."   # needs FOXGRID_DATABASE_URL
```

## Implementation notes
- Bearings store lat/lon floats; PostGIS `geom` columns are generated in SQL (migration 0001) and ignored by
  Alembic autogenerate. A DB trigger forbids DELETE on bearings.
- Engine grid covers stations plus robust ray intersections plus margin, capped at `max_cells` per axis.
- Recompute: per-mission trailing debounce (500 ms, max wait 2 s) + Redis lock; both scopes (`current`, `all`).
- Events: Redis channel `mission:{id}`; clients reload `GET /missions/{id}/snapshot` after reconnect
  (no `since_seq` replay yet).
- Python is pinned to 3.12 via `.python-version`.

## Quality rules
- `ruff` (backend + engine), `mypy --strict` (engine), `flutter analyze` with zero warnings.
- Engine coverage > 90 %; API integration tests against real PostGIS; widget tests for the capture flow.
- GitHub Actions: lint + tests for backend, engine, app.
- No secrets in repo; config via `.env` (+ `.env.example`).
- Small, traceable commits with meaningful messages. Only commit when the user asks.
- Offline-first app: all writes go to local Drift DB first, then a sync queue with retry + exponential backoff;
  sync status always visible.
