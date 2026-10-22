# FoxGrid – Phase 0: Plan (archived)

> **Archived planning document.** This is the original design draft that preceded the implementation (translated from the
> German original). It is kept for the reasoning behind the design. It is **not** kept up to date: for the current state see
> [Architecture](../../concepts/architecture.md), [Data model](../../reference/data-model.md) and [API reference](../../reference/api.md).
> The open questions in section 5 were answered during the project; the decisions are recorded in [ADR index](../README.md).

Status at the time: draft for approval. No code, only schema, API and open questions.

## 1. Architecture in brief

```
Flutter (iOS/Android/Web) ──REST/WS──► FastAPI (n workers) ──► PostgreSQL+PostGIS
   Drift (offline queue)                    │  ▲
                                            ▼  │ Pub/Sub
                                          Redis ──► WS fan-out to all workers
                                            │
                       Recompute job (debounce 500 ms, per mission) ──► foxgrid_engine
```

- **Recompute**: bearing write → Redis key `recompute:{mission}` with 500 ms debounce → exactly one worker (Redis lock) calls the engine in a thread pool → stores `estimates` → event `estimate_updated`.
- **Engine** receives plain data structures (list of bearings, params) and returns result dataclasses. No knowledge of the DB.
- **Idempotency**: `bearings.id` = client UUID (PK). `POST` with an existing ID and identical content → 200 with the existing object; different content → 409.
- **Immutability**: no `DELETE` endpoint; a DB trigger forbids `DELETE` on `bearings`. Changes (outlier, deactivation, note) create rows in `bearing_revisions`.

## 2. Database schema (PostgreSQL 16 + PostGIS)

All geometries `geography(Point,4326)`, times `timestamptz` (UTC), IDs `uuid` unless stated otherwise.

### Core

| Table | Columns (selection) | Notes |
|---|---|---|
| `missions` | id, name, frequency_mhz numeric(8,4), search_area geography(Polygon), status enum(`active`,`ended`), created_at, ended_at, track_retention_days int default 30, engine_params jsonb | `engine_params`: cell size, ε, half-life, default scope |
| `invites` | id, mission_id, token_hash, default_role, max_uses, uses, expires_at, revoked_at | token only as hash; plaintext shown once on creation |
| `teams` | id, mission_id, name | unique(mission_id,name) |
| `participants` | id, mission_id, callsign, role enum(`lead`,`fixed`,`mobile`), team_id, joined_at, last_seen_at, is_active | unique(mission_id, callsign) |
| `position_samples` | id bigserial, mission_id, participant_id, geom, accuracy_m, heading_deg, speed_mps, recorded_at (client), received_at | index(mission_id, recorded_at), GiST(geom); purge job after mission end + retention |
| `transmissions` | id, mission_id, seq int, started_at, ended_at, source enum(`manual`,`relay`,`mqtt`), started_by, ended_by, note | at most one open per mission (partial unique index on `ended_at IS NULL`) |
| `bearings` | id (client UUID), mission_id, participant_id, transmission_id null, station geom, station_accuracy_m, azimuth_true_deg numeric(5,2) [0,360), azimuth_input_ref enum(`true`,`magnetic`,`compass`), declination_deg_applied, sigma_deg numeric(5,2) NOT NULL >0, rssi_dbm, s_meter, attenuation_db default 0, polarization enum(`h`,`v`,`unknown`), measured_at (client), received_at, note, is_outlier bool, is_active bool, source enum(`manual`,`sensor`), sensor_id null | check constraints; never deleted |
| `bearing_revisions` | id bigserial, bearing_id, changed_by, changed_at, changes jsonb | append-only |
| `estimates` | id, mission_id, computed_at, scope enum(`current_transmission`,`all`), transmission_id null, input_hash, n_bearings, params jsonb, mle geom, cov_xx, cov_yy, cov_xy, ellipse_1s jsonb, ellipse_2s jsonb, contours jsonb (GeoJSON 50/80/95), raster_png_path null | `input_hash` avoids duplicate computation; history is kept for the log |

### Coordination

| Table | Columns | Notes |
|---|---|---|
| `messages` | id (client UUID), mission_id, author_id, team_id null, body, sent_at (client), received_at | `team_id` = team channel, otherwise mission channel |
| `tasks` | id (client UUID), mission_id, title, description, status enum(`open`,`in_progress`,`done`,`cancelled`), assignee_participant_id null, assignee_team_id null, created_by, created_at, updated_at, location geom null | CHECK: at most one assignee type |
| `task_events` | id, task_id, actor_id, at, change jsonb | history |
| `push_tokens` | id, participant_id, platform enum(`fcm`,`apns`,`webpush`), token, created_at | |
| `audit_log` | id, mission_id, actor_id, action, entity, entity_id, at, detail jsonb | join, mission end, role change etc. |

### Later phases

| Table | Phase | Purpose |
|---|---|---|
| `rssi_samples` (id UUID, mission_id, participant_id, transmission_id, geom, rssi_dbm, attenuation_db, measured_at, received_at) | 3 | RSSI track of homing |
| `sensors` (id, mission_id, name, kind, fixed_geom, api_key_hash, last_seen_at) | 4 | MQTT bearing stations |
| `suggestions` (id, mission_id, computed_at, candidates jsonb) | 4 | position suggestions (finally not implemented; computed per request) |

Migrations: Alembic. Phase 1 contains `missions, invites, teams, participants, position_samples, transmissions, bearings, bearing_revisions, estimates, audit_log`; `messages/tasks/push_tokens` come in phase 2.

## 3. API list

Base `/api/v1`, auth `Authorization: Bearer <JWT>`; JWT claims: `sub` (participant_id), `mission_id`, `role`.

### Auth / joining
| Method | Path | Purpose |
|---|---|---|
| POST | `/missions` | create mission (returns first lead invite + JWT) |
| POST | `/join` | body: invite_token, callsign, role → participant + JWT (re-join with the same callsign → same participant) |
| POST | `/missions/{id}/invites` | create invite (lead) |
| DELETE | `/missions/{id}/invites/{inv}` | revoke invite (lead) – revocation, not data deletion |

### Missions / participants / teams
| Method | Path |
|---|---|
| GET/PATCH | `/missions/{id}` (name, frequency, area, status, `engine_params`) |
| POST | `/missions/{id}/end` |
| GET | `/missions/{id}/participants` · PATCH `/participants/{pid}` (role/team, lead) |
| GET/POST | `/missions/{id}/teams` · PATCH `/teams/{tid}` |
| POST | `/missions/{id}/positions` (batch, throttled; also via WS) |
| GET | `/missions/{id}/positions?participant=&since=` (tracks) |

### Transmissions
| Method | Path |
|---|---|
| POST | `/missions/{id}/transmissions/start` · `/stop` |
| GET | `/missions/{id}/transmissions` |

### Bearings
| Method | Path | Note |
|---|---|---|
| POST | `/missions/{id}/bearings` | client UUID, idempotent; assigned to the open transmission (or explicit `transmission_id`) |
| GET | `/missions/{id}/bearings?transmission=&since=&include_inactive=` | |
| GET | `/missions/{id}/bearings/{bid}` · `/revisions` | |
| PATCH | `/missions/{id}/bearings/{bid}` | only `is_outlier`, `is_active`, `note`; writes a revision |
| – | *no DELETE* | |

### Estimate
| Method | Path |
|---|---|
| GET | `/missions/{id}/estimate?scope=current\|all&half_life_min=&cell_m=` |
| GET | `/missions/{id}/estimate/history` |
| GET | `/missions/{id}/estimate/raster.png` (optional; not implemented) |

### Coordination (phase 2)
`GET/POST /missions/{id}/messages`, `GET/POST/PATCH /missions/{id}/tasks`, `POST /push-tokens`.

### Export (phase 2)
`GET /missions/{id}/export.gpx|kml|json|pdf`.

### WebSocket `/ws/missions/{id}?token=<JWT>`
- **Server→client**: `participant_position`, `bearing_created`, `bearing_updated`, `transmission_started`, `transmission_ended`, `estimate_updated`, `message`, `task_updated`. Each event: `{type, mission_id, seq, ts, data}`; `seq` is monotonic per mission, the client can catch up with `?since_seq=` (gapless reconnect; finally replaced by reloading the snapshot).
- **Client→server**: `position` (server throttles to ≥5 s per participant), `ping`.
- Fan-out: Redis channel `mission:{id}`.

### Misc
`GET /healthz`, `GET /declination?lat=&lon=&t=` (WMM value for clients without a local table).

## 4. Phase 1 scope and order (proposal)

1. Repo scaffold, Compose (api, postgis, redis), `.env.example`, CI skeleton.
2. `foxgrid_engine` + tests (isolated, first, as it is the highest risk).
3. Alembic + models, auth/join, missions, positions.
4. Bearings, transmissions, recompute worker, WebSocket + Redis.
5. Flutter: join, map (participants, rays, MLE, ellipse), bearing sheet (manual), transmission start/stop. In phase 1 **without** the Drift queue (it comes in phase 2); the idempotency UUID is already in.
6. `tools/simulator` + acceptance test.

## 5. Open questions (as asked at the time)

**Domain (direction finding / radio)**
1. **Bearing antenna**: assume directional antennas with maximum bearing (Yagi/quad/Doppler)? Then "behind the station only ε" is right. For minimum bearing (loop, null) or Doppler with 180° ambiguity a flag and a different likelihood model would be needed. Should this be provided for?
2. **Sigma → κ**: κ ≈ 1/σ² (σ in rad) (normal approximation). Is that right, or should σ be read as the half-width (3 dB) of the antenna?
3. **Several bearings from the same location**: treat as independent, or attenuate per participant/location in a correlation-aware way (otherwise whoever bears most often dominates)?
4. **Attenuator**: only a correction of RSSI (as specified), or also a hint of how "strong" a signal was?
5. **RSSI/S-meter**: input as S-units and dBm with conversion (S9 = −93 dBm at 144 MHz; for 70 cm usually −93 dBm by IARU convention or −73 dBm on HF?). Which convention?
6. **Timestamp drift**: phone clocks are sometimes seconds off. Should age weighting use `measured_at` (client) or `received_at`? Proposal: `measured_at`, but warn if |Δ| to `received_at` > 60 s (offline case excepted).

**Technical / operations**
7. **Offline tile cache**: the OSM tile usage policy forbids bulk download and use by apps without their own tile server. Options: (a) own tile server/PMTiles extract (e.g. region via `protomaps`), (b) commercial provider with offline licence, (c) cache only while viewing normally, small number of tiles. How to solve this? OpenTopoMap has similar restrictions.
8. **Push**: FCM (Android + web) and APNs (iOS) need Firebase/Apple accounts and certificates. Are these available/wanted? Web push on iOS only works as an installed PWA, and `Vibration` is not available in Safari. Acceptable?
9. **Declination**: computation on the server (`pygeomag`/`geomag`, endpoint) and/or on the client (WMM coefficients as a Dart table)? Proposal: the client computes offline with a bundled 5° grid table for the search area, the server checks afterwards.
10. **Grid size**: 50 m at large extents (e.g. 80 km bearing distance) gives >10⁶ cells and breaks 200 ms. Proposal: cap the cell count (e.g. 250×250) and coarsen the resolution adaptively, optionally two-stage (coarse → fine around the maximum). Agreed?
11. **Privacy/GDPR**: callsigns and location tracks are personal data. Is a notice plus retention period enough, or is consent on joining and a data access/deletion route needed? Who hosts (single instance in a club, public, multi-tenant)?
12. **Invite tokens**: single or multiple use? Expiry? May anyone with a token choose the callsign freely (no verification; callsign spoofing possible)? Is that enough for the club?
13. **Roles**: what may `lead` do exclusively (end mission, mark outliers, invites)? May all participants mark other people's bearings as outliers?
14. **Transmission assignment**: a bearing without a running transmission (e.g. captured offline, synced later) → assign to a past transmission by `measured_at`, or `transmission_id = null`? Proposal: assign by time window.
15. **Flutter web + Drift**: Drift on the web runs via WASM/IndexedDB with restrictions. Phase 1 does not need it yet – ok to settle this in phase 2?
16. **Mobile targets**: the Android emulator is named for acceptance; do we need an iOS build from phase 1 or later?
17. **Licences**: OSM tiles require attribution; WMM is public domain (NOAA). Ok?
18. **PDF report (phase 2)**: server-side (e.g. WeasyPrint/ReportLab with map rendering) preferred?

## 6. Assumptions if nothing else is said
- Maximum bearing with a directional antenna (question 1), κ ≈ 1/σ² (2), `measured_at` counts (6), cell cap 250×250 (10), bearings assigned by time window (14), server JWT lifetime = mission duration + 24 h.
- Phase 1 without push, Drift queue and offline map tiles.
