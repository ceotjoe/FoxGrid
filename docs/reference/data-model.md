# Data model

PostgreSQL 16 with PostGIS; schema managed by Alembic (`backend/alembic/versions/`, migrations 0001–0009). ORM models are in
`backend/app/models/core.py`. Times are `timestamptz` (UTC), IDs `uuid` unless noted.

Bearings store `lat`/`lon` floats; the PostGIS `geom` columns are generated in SQL (migration 0001) and ignored by Alembic
autogenerate. Database triggers forbid `DELETE` on `bearings`, `bearing_revisions` and `rssi_samples`.

| Table | Purpose and notable columns |
|---|---|
| `missions` | name, `frequency_mhz`, optional `search_area` polygon, `status` (`active`/`ended`), `track_retention_days`, `engine_params` (jsonb), repeater position and input/output frequency |
| `invites` | token **hash** only, `default_role`, `max_uses`, `uses`, `expires_at`, `revoked_at`, `auto_approve` |
| `teams` | per-mission teams (chat channels, task assignment) |
| `participants` | callsign (unique per mission), `role` (`lead`/`fixed`/`mobile`), `team_id`, `status` (`pending`/`active`/`rejected`), `is_active` (false = removed), `trusted`, `device_hash`, `join_code`, `last_seen_at` |
| `position_samples` | position tracks with `recorded_at` (client) and `received_at`; purged after the retention period |
| `transmissions` | one open transmission per mission at most; `source` (`manual`/`relay`/`mqtt`), `started_by`, `ended_by`, note |
| `bearings` | client-UUID primary key, station position, `azimuth_true_deg`, `azimuth_input_ref`, `declination_deg_applied`, `sigma_deg` (NOT NULL, > 0), RSSI/attenuation, polarization, `measured_at`/`received_at`, `is_outlier`, `is_active`, `source`, `sensor_id`; never deleted |
| `bearing_revisions` | append-only change history of bearings |
| `rssi_samples` | signal readings: client UUID, position, `rssi_dbm`, `attenuation_db`, `receiver` (`mobile`/`omni`), `is_calibration`, `is_active`; never deleted |
| `estimates` | computed results per `scope` (`current`/`all`): MLE point, covariance, 1σ/2σ ellipses, `contours` (GeoJSON keyed `"50"`/`"80"`/`"95"`), `params` incl. `rssi_fit`, `input_hash` |
| `sensors` | MQTT stations and relays: name, kind, fixed position, API-key **hash**, `last_seen_at`; each owns a virtual participant (role `fixed`) |
| `messages` | chat (client UUID); `team_id` null = mission channel |
| `tasks`, `task_events` | tasks with status, assignee (team or participant) and history |
| `push_tokens` | FCM tokens per participant (registered with an atomic upsert) |
| `audit_log` | security and change log (joins, approvals, role changes, quarantine, denied attempts, bearing changes) |

Retention: only `position_samples` are purged (N days after mission end). Everything else is kept.

Design rationale and the original draft: [Phase 0 plan (archived)](../adr/archive/phase0-plan.md). Note that the draft predates
several tables and columns (sensors, RSSI, trust, join codes), which the list above reflects.
