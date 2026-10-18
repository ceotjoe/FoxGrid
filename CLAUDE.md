# FoxGrid – Project Conventions

FoxGrid is an open-source (MIT) app for a group of radio amateurs to jointly locate an interferer on VHF/UHF (any frequency, e.g. 2 m, 70 cm, 23 cm; the S-meter scale is the VHF one, below 30 MHz the app only warns).
Participants record bearings (position, azimuth, uncertainty, field strength); the backend fuses them live into a
most-likely interferer location and pushes the result to everyone. Phase 1 = coarse bearing (triangulation),
later homing (RSSI). Also used for team coordination (chat, tasks).

Language: **README and user docs in German; code, comments, commit messages, identifiers in English.**

## Status
Phase 0 (planning, `docs/phase0-plan.md`) done; All four phases implemented (MVP, robustness and coordination, homing, automation). Work strictly phase by phase; stop after each phase, summarize
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
(GeoJSON, 50/80/95 % mass), optional PNG raster. Later: RSSI path-loss fusion (done), next-bearing suggestion (P4).
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

## Phase 2 notes
- Engine returns probability-mass contours (marching squares in `foxgrid_engine/contours.py`); the API stores
  them on `estimates.contours` as GeoJSON polygons keyed "50"/"80"/"95".
- Team chat messages are published on the Redis channel `mission:{id}:team:{team}`; the WebSocket subscribes to the
  caller's team channel only. `GET /snapshot` also returns only the messages the caller may see.
- Push: `app/services/push.py` (FCM HTTP v1 or log-only). The app does not register tokens yet (needs Firebase files).
- App offline queue: `OutboxStore` (Drift on native, memory on web) + `SyncService` (head-of-line, exponential
  backoff, 4xx = failed and visible, 409 on tx start/stop = success). All writes go through `MissionNotifier`.
- `app/lib/core/database.g.dart` is generated (`dart run build_runner build`) and committed.
- flutter_map_tile_caching is incompatible with flutter_map 8 / latlong2 0.10, so `core/tile_cache.dart` is our own
  small file cache. Bulk download is blocked for public OSM servers (tile usage policy).
- Provider overrides in tests need `import 'package:flutter_riverpod/misc.dart' show Override;` (Riverpod 3).

## Phase 3 notes
- Engine RSSI fusion (`foxgrid_engine/rssi.py`): per candidate point a weighted LS fit of
  `level = p0 - 10 n log10(d)` (n clipped to [1.5, 6]) gives a Gaussian log-likelihood from the residuals. Levels are
  `rssi_dbm + attenuation_db`. `estimate(bearings, params, rssi=[...])`; fewer than `rssi_min_samples` (5) are ignored;
  an RSSI-only estimate is allowed. Cost grows with samples, so only the newest `rssi_max_samples` (300) are used.
- `rssi_samples` table is append-only (delete trigger), samples can be deactivated via PATCH. Both estimate scopes use
  the samples of the same transmission scope. Estimate `params.rssi_fit` is exposed as `EstimateOut.rssi`.
- S-meter convention is IARU VHF/UHF (S9 = -93 dBm, 6 dB/S) in `app/lib/core/signal.dart`: one place to change.
- CAT: `app/lib/core/radio/` has protocol codecs (Icom CI-V, ASCII SM0), `RawScale` calibration and
  `RadioSignalSource`. No `RadioTransport` implementation exists yet (needs USB/Bluetooth plugins).
- Homing screen layout: scrolling content plus a pinned `_EntryPanel` so S-meter taps never scroll away.
- Lazy `ListView` widget tests need a tall viewport (`tester.view.physicalSize`) or controls are not built.

## Branding
- App icon: "Fadenkreuz-Fuchs", SVG layers in `docs/branding/fadenkreuz-fuchs/`. Do not edit the generated PNGs by hand:
  change the SVGs and run `python3 tools/branding/generate_icons.py` (needs `rsvg-convert` and `magick`).
- iOS icons must stay full-bleed and without alpha (the system masks them); Android has adaptive foreground,
  background colour and monochrome layers in `mipmap-anydpi-v26`.
- App ID (Android `applicationId`/`namespace`, iOS bundle id): `com.itwebservice.foxgrid`. Firebase, APNs and store
  listings are tied to it, so do not change it once they exist.

## Phase 4 notes
- MQTT ingest is its own process (`python -m app.mqtt_ingest`, compose profile `mqtt`), never inside the API workers
  (they would process every message N times). Handlers live in `app/services/ingest.py` and are called directly in
  tests; `tests/test_ingest.py` also runs the real service against a Mosquitto testcontainer.
- A sensor owns a virtual participant (role `fixed`, callsign from its name) so bearings keep their participant FK;
  `POST /join` refuses sensor callsigns. API keys: `fgs_` + token, only the SHA-256 is stored, shown once.
- Transmission start/stop logic is shared (`app/services/transmissions.py`) by REST and the relay path
  (`source = 'relay'`). A repeated start/stop from a relay is a harmless `duplicate`.
- Position suggestions (`foxgrid_engine/suggest.py`) use analytic Fisher information, deliberately not the grid
  posterior: its outlier-mixture tails make a good extra bearing look like it grows the ellipse.
- Suggestions are computed per request (milliseconds), nothing is stored; no `suggestions` table exists.
- Mosquitto password file is rebuilt at every start (`entrypoint` in `docker-compose.yml`); the MQTT password
  is optional in `.env` so plain `docker compose up` keeps working, only the broker refuses to start without it.
- `tools/relay_hook` and `tools/sensor_client` have their own tests: `uv run --with pytest --with aiomqtt pytest tools/relay_hook`.

## Release notes
- Store release is tag-driven (`.github/workflows/release.yml`, fastlane in `fastlane/`, setup in `docs/release.md`).
  Release builds accept HTTPS servers only (`serverUrlError` in `join_screen.dart`); cleartext is allowed in the
  debug manifest only. Android signs from `android/key.properties` or `FOXGRID_*` env vars, never commit keystores.
- Store texts/graphics: `store/metadata/{ios,android}/<locale>/` (fastlane layout, de-DE + en-US). Raw screenshots in
  `store/screenshots/raw/`, captions in `store/captions.json`; regenerate with `python3 tools/store/generate_assets.py`.
  Do not edit the generated PNGs by hand.
- `app/ios/Runner/PrivacyInfo.xcprivacy`, `docs/privacy*.md` and `docs/store-compliance.md` must stay in sync when the
  data flow changes. The privacy policy is a draft until the provider details are filled in.

## Phase 5 notes (omnidirectional stations, 5a = engine only)
- Plan: `/Users/joerg/.claude/plans/mossy-watching-barto.md` (5a engine, 5b backend/API, 5c app). Fixed stations report an
  S-value of the interferer on the repeater **input** frequency (on the output you only hear the repeater).
- Engine: `RssiSample(group=<station>, event=<transmission>)` marks fixed-station readings. Model
  `level = p0 + b_k - 10 n log10(d)` with a per-station offset `b_k ~ N(0, rssi_station_sigma_db)`: GLS via Woodbury in
  `rssi.py` (`_fit_arrays`). One reading per (station, transmission) is used (median, `usable_samples`); at least
  `rssi_omni_min_stations` (4) distinct stations are needed, the homing track still needs `rssi_min_samples`.
  `RssiSample.offset_db` is a known calibration offset; `RssiFit.station_offsets_db` returns the estimated ones.
- Expected accuracy (`uv run tools/simulator/omni_eval.py`): coarse area only, median error 1-4 km for stations 2-15 km away.
- 5b backend: `rssi_samples.receiver` (`mobile`|`omni`) and `is_calibration`; omni readings only from role `fixed`/`lead`;
  sensor RSSI is stored as `omni`. Mission has `repeater_lat/lon/input_mhz/output_mhz` (set at create or `PATCH /missions/{id}`,
  lead only). Calibration readings (repeater **output**, known position) never enter the fit: `calibration_offsets` in
  `services/recompute.py` turns them into relative station offsets (assumed exponent 3, needs 3 stations, centred on the mean)
  which are passed to the engine as `offset_db`. `rssi.station_offsets_db` of an estimate is keyed by participant id.
- 5c app: `lib/ui/station_screen.dart` (role `fixed`/lead; S-value buttons, calibration switch, lead dialog for the repeater).
  Readings go through `MissionNotifier.logRssi(receiver: 'omni', isCalibration: ...)`, the repeater through
  `setRepeater` (outbox kind `mission`, PATCH). The map draws station markers (latest S value) and the repeater; the
  homing dots only show `mobile` readings. A station can type in a fixed location (`stationPositionProvider`, persisted per mission) which wins over GPS.
- Map rings: `_stationRings` in `map_screen.dart` draws, per station, the distance from `ringDistanceM` (`core/signal.dart`) with the
  estimate's `rssi` fit (p0, n, offsets) and +-residual bands; filter toggle `showRings`. The calibration offset is not known to the app,
  so rings use only the estimated offset.
