# Backend orientation

```
backend/
  app/
    api/        routers: missions, field (positions, transmissions, bearings, estimates), rssi, coordination, sensors, export
    ws/         WebSocket endpoint
    models/     SQLAlchemy models (core.py)
    schemas/    Pydantic v2 request/response models (api.py)
    services/   domain logic: domain, recompute, transmissions, ingest, plausibility, ratelimit, push, exporter, declination, serialize
    config.py   settings (FOXGRID_*)
    events.py   Redis Pub/Sub publishing
    mqtt_ingest separate MQTT ingest process
  alembic/      migrations 0001–0009
  tests/        integration tests against PostGIS + Redis (testcontainers)
```

## Conventions worth knowing

- **Trust filter.** Every query that feeds an estimate must go through `domain.trusted_only(stmt, Bearing | RssiSample)`. See
  [Domain rules](../concepts/domain-rules.md).
- **Recompute.** Per-mission trailing debounce (500 ms, max wait 2 s) plus a Redis lock; both scopes (`current`, `all`). Calibration
  readings (repeater **output**, known position) never enter the fit: `calibration_offsets` in `services/recompute.py` turns them into
  relative station offsets (assumed exponent 3, needs 3 stations, centred on the mean) which are passed to the engine as `offset_db`.
- **Stations.** Omnidirectional readings are accepted only from role `fixed`/`lead`; sensor RSSI is stored as `omni`. A mission has
  `repeater_lat/lon/input_mhz/output_mhz` (set at creation or `PATCH /missions/{id}`, lead only).
- **Rate limits.** `services/ratelimit.enforce(redis, bucket, subject, limit, cost)` is a fixed one-minute window in Redis; 429 with
  `Retry-After`. Settings `rate_*_per_min` (0 = off).
- **Plausibility.** `services/plausibility.py` has pure functions (plain haversine, no pyproj). Thresholds are constants at the top of
  the module. Hints only, never automatic actions.
- **Join code.** `participants.join_code` (4 digits) exists only for pending joiners of non-`auto_approve` invites and is cleared on
  approve/reject. `participant_out(..., show_code=True)` only for the joiner and the lead; events and other members never carry it.
- **Transmission start/stop** logic is shared by REST and the relay path in `services/transmissions.py`.
- **Proxies.** Mind `FORWARDED_ALLOW_IPS` behind a reverse proxy, otherwise join rate limits count the proxy address.
- **Privacy docs.** The device-secret hash, join code and security log are listed in the privacy policy; keep it in sync.

Further reading: [Architecture](../concepts/architecture.md), [API reference](../reference/api.md), [Data model](../reference/data-model.md).
