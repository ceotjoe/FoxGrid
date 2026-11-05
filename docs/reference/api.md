# API reference

The REST API lives under `/api/v1`; the live channel is a WebSocket. This page is an overview. For exact request and response
schemas enable the generated OpenAPI documentation with `FOXGRID_ENABLE_DOCS=true` (`/docs`, `/openapi.json`; off by default in
production). Source of truth: `backend/app/api/` and `backend/app/schemas/api.py`.

## Authentication

`Authorization: Bearer <JWT>`. The token carries `sub` (participant ID), `mission_id` and `role`; it only identifies, **permissions are read from the database on
every request**. Lifetime `FOXGRID_JWT_TTL_HOURS`
(72 h). A JWT is obtained from `POST /missions` (creator becomes lead), `POST /join` (invite token + callsign) or
`POST /missions/{id}/rejoin` (callsign + device secret). `role` (`lead`, `fixed`, `mobile`) is the data source; `authority` (`lead`, `deputy`, `analyst`, `coordinator`, `member`, `station`,
`observer`) is what a participant may do, see [Roles and permissions](../user-guide/roles.md). Participant records carry both
and the effective `permissions`. A missing permission answers `403 permission required: <name>`.

Participants whose `status` is `pending` or `rejected` are refused (403) on everything except `GET /missions/{id}/me`.
Rate-limited endpoints answer `429` with a `Retry-After` header. Creating a bearing with an existing ID and identical content
returns 200 (idempotent), with different content 409.

## Missions, invites, participants

| Method | Path | Who | Purpose |
|---|---|---|---|
| POST | `/missions` | anyone (rate limited) | create a mission; returns the lead JWT and first invite |
| POST | `/join` | invite holder | invite token, callsign, device secret → participant + JWT (status `pending` unless auto-approved) |
| POST | `/missions/{id}/rejoin` | known device | callsign + device secret → new JWT without an invite |
| GET / PATCH | `/missions/{id}` | `view.result` / `estimate.configure` | read; PATCH sets the repeater (`repeater.lat/lon/input_mhz/output_mhz`) |
| POST | `/missions/{id}/end` | `mission.end` | end the mission (event `mission_ended`) |
| GET | `/missions/{id}/me` | any participant incl. pending | own participant record (also the join code for a pending joiner) |
| GET | `/missions/{id}/snapshot` | `view.result` | everything a client needs after (re)connect: mission, participants, bearings, transmissions, estimate, and, depending on permissions, positions (`view.positions`), messages the caller may see (`chat.read`), tasks and teams (`task.work`) |
| POST | `/missions/{id}/invites` | `invite.create` | new invite (`default_role`, `default_authority`, `max_uses`, `expires_in_hours`, `auto_approve`). Without `invite.manage` only ordinary links (`mobile`, `member`, no `auto_approve`); `default_authority: observer` needs `invite.manage` and `mobile` |
| POST | `/missions/{id}/invites/replace` | `invite.manage` | revoke all open invites and issue one default link |
| POST | `/missions/{id}/invites/{invite_id}/rotate` | `invite.manage` | revoke and replace a single invite (keeps its role) |
| DELETE | `/missions/{id}/invites/{invite_id}` | `invite.manage` | revoke an invite (no data is deleted) |
| GET | `/missions/{id}/participants` | `view.result`; join codes need `participant.manage` | participant list |
| PATCH | `/missions/{id}/participants/{pid}` | per field | `authority` and `role` need `role.assign` (lead only; active participants only; a mission keeps at least one lead); `is_active` (remove/restore), `reset_device`, `status` (`active`/`rejected`) need `participant.manage`; `trusted` (and approving) needs `trust.set`. Only a lead may change a lead. Observers cannot be trusted into the estimate (they never count) |
| POST | `/missions/{id}/participants/{pid}/quarantine` | `quarantine` | deactivate all bearings and readings of a participant, withdraw trust; body `{"remove": bool}` |
| GET | `/missions/{id}/audit?scope=security\|all&limit=` | `audit.view` | security log |
| GET | `/missions/{id}/plausibility` | `trust.set` | plausibility hints per participant |

## Positions and transmissions

| Method | Path | Purpose |
|---|---|---|
| POST | `/missions/{id}/positions` | batch of position samples (throttled; 202); needs `position.share` |
| GET | `/missions/{id}/positions?participant=&since=&limit=` | tracks; needs `view.positions` (not for observers) |
| POST | `/missions/{id}/transmissions/start` · `/stop` | start/stop a transmission (409 on a repeated start/stop is treated as success by the app); needs `bearing.create`; only the starter and holders of `transmission.manage` (lead, deputy, analyst) may stop |
| GET | `/missions/{id}/transmissions` | list |

## Bearings

| Method | Path | Purpose |
|---|---|---|
| POST | `/missions/{id}/bearings` | create (client UUID, idempotent); assigned to the open transmission or an explicit `transmission_id`. Needs `bearing.create`. With `point_id` (needs `bearing.external`: lead, deputy, analyst; lat/lon must equal the point) it is an external bearing, `source: external` |
| GET | `/missions/{id}/bearings?transmission=&since=&include_inactive=` | list |
| GET | `/missions/{id}/bearings/{bid}` · `/revisions` | one bearing / its revision history |
| POST | `/missions/{id}/points` | `point.manage` | create an external bearing point (client UUID, idempotent; 409 on a duplicate name) |
| GET | `/missions/{id}/points` | `view.result` | list points |
| PATCH | `/missions/{id}/points/{pid}` | `point.manage` | only `name`, `note`, `use_in_estimate`, `is_active`; position is immutable |
| PATCH | `/missions/{id}/bearings/{bid}` | only `is_outlier`, `is_active`, `note`; writes a revision. The owner may always; others need `bearing.flag` for the flags (lead, deputy, analyst) and `bearing.edit_any` for the note (lead, deputy) |

There is deliberately **no DELETE**.

## Signal levels (RSSI)

| Method | Path | Purpose |
|---|---|---|
| POST | `/missions/{id}/rssi` | batch of readings (idempotent by client UUID); `receiver`: `mobile` or `omni` (omni only from `fixed`/lead), `is_calibration`; needs `rssi.submit` |
| GET | `/missions/{id}/rssi` | list |
| PATCH | `/missions/{id}/rssi/{sample_id}` | deactivate/reactivate; the owner, or `bearing.flag` |

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
| POST | `/missions/{id}/sensors` | `sensor.manage`; create a station or relay, the API key `fgs_…` is returned once |
| GET | `/missions/{id}/sensors` | list |
| PATCH | `/missions/{id}/sensors/{sensor_id}` | update / deactivate |

The MQTT side is documented in [MQTT interface](mqtt.md).

## Coordination

| Method | Path | Purpose |
|---|---|---|
| GET | `/missions/{id}/teams` | teams; needs `task.work` |
| GET / POST | `/missions/{id}/messages` | chat (mission channel or a team channel; team messages stay private to the team, except for holders of `chat.moderate`); `chat.read` / `chat.write` |
| GET / POST / PATCH | `/missions/{id}/tasks` | tasks, assigned to a team or a participant; GET and PATCH (own or assigned) need `task.work`, POST and editing any task need `task.manage` |
| POST / DELETE | `/push-tokens` | register / remove the device's FCM token |

## Export and misc

| Method | Path | Purpose |
|---|---|---|
| GET | `/missions/{id}/export.gpx` · `.kml` · `.json` · `.pdf` | needs `export`; the position tracks only with `export.tracks` (not for observers). Exports bearings, track, estimate (PDF = map, bearings, result); external points appear as "Peilpunkt …" / folder "Peilpunkte", their bearings as "extern: <name>" (JSON: `points` and `point_id`), flagged "nicht in Schätzung" when the point is off or inactive |
| GET | `/declination?lat=&lon=&date=` | magnetic declination (WMM) |
| GET | `/healthz` | health check (outside `/api/v1`) |

## WebSocket `/ws/missions/{id}?token=<JWT>`

The handshake is refused with close code `4401` (bad token) or `4403` (not an active participant, or without `view.result`). A
removed participant's socket is closed with `4403`. When the participant's own `authority` changes the socket is closed with
`4409`: reconnect and reload the snapshot to learn the new permissions.

Events are **filtered per permission**: `participant_position` needs `view.positions`, `message` needs `chat.read`,
`task_updated` needs `task.work`, everything else `view.result`. An observer therefore never receives chat or positions.

**Server → client** events have the shape `{type, mission_id, seq, ts, data}` with `seq` monotonic per mission:

| `type` | Meaning |
|---|---|
| `participant_position` | a position update |
| `participant_updated` | a participant record changed (role, status, trust) |
| `participant_removed` | a participant was removed (closes their socket) |
| `bearing_created`, `bearing_updated` | bearing changes |
| `point_created`, `point_updated` | external bearing point changes |
| `transmission_started`, `transmission_ended` | transmission changes |
| `estimate_updated` | a new estimate was computed |
| `message` | chat message (team messages only to team members) |
| `task_updated` | task changes |
| `mission_ended` | the lead ended the mission |

**Client → server:** `{"type":"position","data":{...}}` (throttled to one per `FOXGRID_POSITION_MIN_INTERVAL_S`, default 5 s) and
`{"type":"ping"}` (answered with `{"type":"pong"}`). A position needs `position.share`, otherwise it is answered with
`{"type":"error","detail":"forbidden"}`. Invalid messages get `{"type":"error","detail":...}`.

There is no replay by sequence number yet: after a reconnect clients reload `GET /missions/{id}/snapshot`.

## Permission names

Used in the tables above and carried in every participant record (`permissions`). The assignment to authorities is the table in
[Roles and permissions](../user-guide/roles.md); the source of truth is `backend/app/services/permissions.py`.

`view.result`, `view.positions`, `chat.read`, `bearing.create`, `bearing.external`, `rssi.submit`, `position.share`,
`bearing.flag`, `bearing.edit_any`, `transmission.manage`, `trust.set`, `quarantine`, `estimate.configure`, `point.manage`,
`chat.write`, `chat.moderate`, `task.manage`, `task.work`, `team.manage`, `invite.create`, `invite.manage`,
`participant.manage`, `sensor.manage`, `audit.view`, `role.assign`, `mission.end`, `export`, `export.tracks`.
