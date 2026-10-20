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
- Push: `app/services/push.py` (FCM HTTP v1 or log-only). The app registers its FCM token (`PushRegistrar` in `lib/state/push.dart`, `lib/core/push.dart`);
  `firebase_messaging` is pinned to ^16 on purpose (17 only offers installation IDs, not the FCM registration token the server sends to). Firebase
  config files are gitignored and come from CI secrets; Android builds without `google-services.json` (plugin applied conditionally), iOS does not.
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
- Plan: 5a engine, 5b backend/API, 5c app (all done). Fixed stations report an
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

## Access control notes (leaked invite links, steps A + B)
- Plan: threat model "link leak / saboteur" in the session of 2026-10-19; step A done (device binding, roles, link defaults, removal),
  step B done (join lobby + participants UI), step C done (trust + quarantine), steps D (plausibility + rate limits) and E (audit view, join code, `docs/sicherheit.md`) done; the plan is complete.
- Lobby: `participants.status` = `pending`|`active`|`rejected` (separate from `is_active` = removed). New joiners are `pending` unless the invite has
  `auto_approve`. `deps.member` (so `lead` too) answers 403 `participant is pending|rejected`; only `GET /missions/{id}/me` works for them (the app
  polls it on `PendingScreen`). WebSocket handshake refuses non-active participants; push targets are active participants only.
  Lead approves via `PATCH .../participants/{pid}` `{"status": "active"|"rejected"}`; events `participant_updated` (list sync) and `participant_removed` (closes the socket).
- `POST .../invites/replace` revokes every open invite and issues one default link; `rotate` replaces a single one.
- App: `Session.status`, `ui/pending_screen.dart` (gate in `main.dart`), `ui/participants_screen.dart` (lead menu with badge); `MissionNotifier.applyParticipant`
  also updates the own session role live. Tests that join a second participant use `Mission.join` (helpers approve automatically).
- `participants.device_hash` = SHA-256 of a per-install secret (`JoinIn.device_secret`, app: `core/device_secret.dart`, SharedPreferences).
  Re-joining a callsign needs the same secret (403 otherwise, audited as `join_denied`); legacy rows without a hash bind on the next join.
  Lead releases it with `PATCH /missions/{id}/participants/{pid}` `{"reset_device": true}`.
- The invite decides the role of a new participant (`mobile`|`fixed`); `JoinIn.role` is ignored. Leads only come from promotion via the same PATCH.
  The app join screen therefore has no role picker, and there is no app UI yet for a lead to promote someone to `fixed` (planned with step B).
- Invites always expire/limit: defaults `FOXGRID_INVITE_TTL_HOURS` (24) and `FOXGRID_INVITE_MAX_USES` (20), also for the first invite of a mission.
  `POST .../invites/{id}/rotate` revokes and replaces.
- Removal = `is_active=false` (token check is per request); event `participant_removed` makes the WebSocket of that participant close with 4403.
- Trust (step C): `participants.trusted`. Every query that feeds an estimate goes through `domain.trusted_only(stmt, Bearing|RssiSample)`
  (recompute incl. calibration offsets, `/estimate/query`, `/suggestions`); a new such query must use it too. New joiners via `auto_approve` links start untrusted,
  lobby approval or promotion to `fixed`/`lead` trusts (unless `trusted` is sent explicitly); changing trust triggers a recompute. Untrusted data is still stored, listed and exported.
- `POST /missions/{id}/participants/{pid}/quarantine` (lead; `{"remove": bool}`): deactivates all active bearings (revision with `reason: "quarantine"`, `bearing_updated` events)
  and RSSI samples, sets `trusted=false`, audits the counts. No bulk undo (reactivate bearings one by one via PATCH). Not for sensors or the lead themself.
- Rate limits (step D): `services/ratelimit.enforce(redis, bucket, subject, limit, cost)` fixed one-minute window in Redis, 429 + `Retry-After`; settings `rate_*_per_min`
  (0 = off; tests switch the join limit off because all tests join from 127.0.0.1). The app already treats 429 as retry. Mind `FORWARDED_ALLOW_IPS` behind a proxy.
- Plausibility (`services/plausibility.py`, pure functions, plain haversine, no pyproj): `GET /missions/{id}/plausibility` (lead) returns hints per active, non-sensor participant:
  `bearings_disagree` (needs an `all` estimate with >= 3 bearings), `impossible_speed`, `bearing_off_track`, `no_track`. Hints only, never automatic actions; thresholds are constants at the top of the module.
- Join code (step E): `participants.join_code` (4 digits, only for pending joiners of non-`auto_approve` invites, cleared on approve/reject). `participant_out(..., show_code=True)` only for the
  joiner (join response, `/me`) and the lead (`/participants`, `/snapshot`); events and other members never carry it. Audit: `GET /missions/{id}/audit?scope=security|all&limit=` (lead).
  Privacy docs (`docs/privacy*.md`) list the device-secret hash, join code and security log; keep them in sync.
