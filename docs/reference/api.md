# API reference

The REST API lives under `/api/v1`; the live channel is a WebSocket. This page is an overview. For exact request and response
schemas enable the generated OpenAPI documentation with `FOXGRID_ENABLE_DOCS=true` (`/docs`, `/openapi.json`; off by default in
production). Source of truth: `backend/app/api/` and `backend/app/schemas/api.py`.

## Authentication

`Authorization: Bearer <JWT>`. The token carries `sub` (participant ID), `mission_id` and `role`; lifetime `FOXGRID_JWT_TTL_HOURS`
(72 h). A JWT is obtained from `POST /missions` (creator becomes lead), `POST /join` (invite token + callsign) or
`POST /missions/{id}/rejoin` (callsign + device secret). Roles: `lead`, `fixed`, `mobile`.

Participants whose `status` is `pending` or `rejected` are refused (403) on everything except `GET /missions/{id}/me`.
Rate-limited endpoints answer `429` with a `Retry-After` header. Creating a bearing with an existing ID and identical content
returns 200 (idempotent), with different content 409.

## Missions, invites, participants

| Method | Path | Who | Purpose |
|---|---|---|---|
| POST | `/missions` | anyone (rate limited) | create a mission; returns the lead JWT and first invite |
| POST | `/join` | invite holder | invite token, callsign, device secret → participant + JWT (status `pending` unless auto-approved) |
| POST | `/missions/{id}/rejoin` | known device | callsign + device secret → new JWT without an invite |
| GET / PATCH | `/missions/{id}` | member / lead | read; PATCH sets the repeater (`repeater.lat/lon/input_mhz/output_mhz`) |
| POST | `/missions/{id}/end` | lead | end the mission (event `mission_ended`) |
| GET | `/missions/{id}/me` | any participant incl. pending | own participant record (also the join code for a pending joiner) |
| GET | `/missions/{id}/snapshot` | member | everything a client needs after (re)connect: mission, participants, bearings, transmissions, estimate, messages the caller may see, tasks |
| POST | `/missions/{id}/invites` | lead | new invite (`default_role`, `max_uses`, `expires_in_hours`, `auto_approve`) |
| POST | `/missions/{id}/invites/replace` | lead | revoke all open invites and issue one default link |
| POST | `/missions/{id}/invites/{invite_id}/rotate` | lead | revoke and replace a single invite |
| DELETE | `/missions/{id}/invites/{invite_id}` | lead | revoke an invite (no data is deleted) |
| GET | `/missions/{id}/participants` | lead sees join codes | participant list |
| PATCH | `/missions/{id}/participants/{pid}` | lead | `role`, `is_active` (remove/restore), `reset_device`, `status` (`active`/`rejected`), `trusted` |
| POST | `/missions/{id}/participants/{pid}/quarantine` | lead | deactivate all bearings and readings of a participant, withdraw trust; body `{"remove": bool}` |
| GET | `/missions/{id}/audit?scope=security\|all&limit=` | lead | security log |
| GET | `/missions/{id}/plausibility` | lead | plausibility hints per participant |

## Positions and transmissions

| Method | Path | Purpose |
|---|---|---|
| POST | `/missions/{id}/positions` | batch of position samples (throttled; 202) |
| GET | `/missions/{id}/positions?participant=&since=&limit=` | tracks |
| POST | `/missions/{id}/transmissions/start` · `/stop` | start/stop a transmission (409 on a repeated start/stop is treated as success by the app); only the starter and the lead may stop |
| GET | `/missions/{id}/transmissions` | list |

## Bearings

| Method | Path | Purpose |
|---|---|---|
| POST | `/missions/{id}/bearings` | create (client UUID, idempotent); assigned to the open transmission or an explicit `transmission_id` |
| GET | `/missions/{id}/bearings?transmission=&since=&include_inactive=` | list |
| GET | `/missions/{id}/bearings/{bid}` · `/revisions` | one bearing / its revision history |
| PATCH | `/missions/{id}/bearings/{bid}` | only `is_outlier`, `is_active`, `note`; writes a revision |

There is deliberately **no DELETE**.

## Signal levels (RSSI)

| Method | Path | Purpose |
|---|---|---|
| POST | `/missions/{id}/rssi` | batch of readings (idempotent by client UUID); `receiver`: `mobile` or `omni` (omni only from `fixed`/lead), `is_calibration` |
| GET | `/missions/{id}/rssi` | list |
| PATCH | `/missions/{id}/rssi/{sample_id}` | deactivate/reactivate |

## Estimates and suggestions

| Method | Path | Purpose |
|---|---|---|
| GET | `/missions/{id}/estimate?scope=current\|all` | latest stored estimate |
| GET | `/missions/{id}/estimate/history?scope=&limit=` | history |
| GET | `/missions/{id}/estimate/query` | ad-hoc estimate (not stored): `transmission` (repeatable), `since`, `until`, `half_life_s`, `include_outliers`, `include_rssi` |
| GET | `/missions/{id}/suggestions?scope=&count=&sigma_deg=` | best places for the next bearing |

## Sensors (MQTT stations)

| Method | Path | Purpose |
|---|---|---|
| POST | `/missions/{id}/sensors` | lead; create a station or relay, the API key `fgs_…` is returned once |
| GET | `/missions/{id}/sensors` | list |
| PATCH | `/missions/{id}/sensors/{sensor_id}` | update / deactivate |

The MQTT side is documented in [MQTT interface](mqtt.md).

## Coordination

| Method | Path | Purpose |
|---|---|---|
| GET | `/missions/{id}/teams` | teams |
| GET / POST | `/missions/{id}/messages` | chat (mission channel or a team channel; team messages stay private to the team) |
| GET / POST / PATCH | `/missions/{id}/tasks` | tasks, assigned to a team or a participant |
| POST / DELETE | `/push-tokens` | register / remove the device's FCM token |

## Export and misc

| Method | Path | Purpose |
|---|---|---|
| GET | `/missions/{id}/export.gpx` · `.kml` · `.json` · `.pdf` | export bearings, track, estimate (PDF = map, bearings, result) |
| GET | `/declination?lat=&lon=&date=` | magnetic declination (WMM) |
| GET | `/healthz` | health check (outside `/api/v1`) |

## WebSocket `/ws/missions/{id}?token=<JWT>`

The handshake is refused with close code `4401` (bad token) or `4403` (not an active participant). A removed participant's socket
is closed with `4403`.

**Server → client** events have the shape `{type, mission_id, seq, ts, data}` with `seq` monotonic per mission:

| `type` | Meaning |
|---|---|
| `participant_position` | a position update |
| `participant_updated` | a participant record changed (role, status, trust) |
| `participant_removed` | a participant was removed (closes their socket) |
| `bearing_created`, `bearing_updated` | bearing changes |
| `transmission_started`, `transmission_ended` | transmission changes |
| `estimate_updated` | a new estimate was computed |
| `message` | chat message (team messages only to team members) |
| `task_updated` | task changes |
| `mission_ended` | the lead ended the mission |

**Client → server:** `{"type":"position","data":{...}}` (throttled to one per `FOXGRID_POSITION_MIN_INTERVAL_S`, default 5 s) and
`{"type":"ping"}` (answered with `{"type":"pong"}`). Invalid messages get `{"type":"error","detail":...}`.

There is no replay by sequence number yet: after a reconnect clients reload `GET /missions/{id}/snapshot`.
