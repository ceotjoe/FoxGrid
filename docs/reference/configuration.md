# Configuration reference

The backend reads `FOXGRID_*` environment variables (or `.env`) via `backend/app/config.py`. Docker Compose reads additional
unprefixed variables. Copy `.env.example` to `.env` and adjust; never commit `.env`.

## Compose (unprefixed)

| Variable | Meaning |
|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | database credentials; the password has no default |
| `REDIS_PASSWORD` | Redis password; no default |
| `FOXGRID_API_PORT`, `FOXGRID_DB_PORT`, `FOXGRID_REDIS_PORT`, `FOXGRID_MQTT_PORT` | host port mappings |
| `FOXGRID_API_BIND` | interface the API port binds to (default `127.0.0.1`) |
| `FOXGRID_POSTGIS_IMAGE` | PostGIS image; never change the major version of an existing data volume |
| `FORWARDED_ALLOW_IPS` | uvicorn: addresses allowed to set `X-Forwarded-For`; set to the proxy address, never `*` |

## Backend (`FOXGRID_` prefix)

> **Compose forwards only some variables.** The `api` service in `docker-compose.yml` passes just `FOXGRID_JWT_SECRET`,
> `FOXGRID_JWT_TTL_HOURS`, `FOXGRID_FCM_PROJECT_ID` and `FOXGRID_FCM_CREDENTIALS_FILE` (plus the database and Redis URLs it builds
> itself) from `.env` into the container. Every other setting below (`CORS_ORIGINS`, `INVITE_*`, `RATE_*`, `ENABLE_DOCS`, …) must be
> added to the `environment:` section of the `api` service, best in a `docker-compose.override.yml`, otherwise the default applies.
> The `ingest` service forwards the MQTT variables.

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | local asyncpg URL | SQLAlchemy URL (Compose sets it for you) |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis URL |
| `JWT_SECRET` | **required** | ≥ 32 characters, not starting with `change-me` |
| `JWT_TTL_HOURS` | 72 | session lifetime |
| `INVITE_TTL_HOURS` | 24 | default invite expiry |
| `INVITE_MAX_USES` | 20 | default invite use limit |
| `RATE_JOIN_PER_MIN` | 20 | joins per client address and minute (0 = off) |
| `RATE_MISSION_PER_MIN` | 5 | mission creation per client address |
| `RATE_BEARING_PER_MIN` | 120 | bearings per participant |
| `RATE_RSSI_PER_MIN` | 600 | readings per participant (counted per item) |
| `RATE_MESSAGE_PER_MIN` | 30 | chat messages per participant |
| `POSITION_MIN_INTERVAL_S` | 5 | minimum interval between stored positions per participant |
| `RECOMPUTE_DEBOUNCE_MS` | 500 | trailing debounce of the estimate recompute |
| `RECOMPUTE_MAX_WAIT_MS` | 2000 | maximum delay before a recompute runs |
| `TRACK_PURGE_INTERVAL_S` | 3600 | how often expired position tracks are purged |
| `CORS_ORIGINS` | `["*"]` | JSON list; restrict to your web origin in production |
| `ENABLE_DOCS` | false | expose `/docs`, `/redoc`, `/openapi.json` |
| `FCM_PROJECT_ID`, `FCM_CREDENTIALS_FILE` | unset | Firebase push (HTTP v1); unset = pushes are only logged |
| `MQTT_HOST`, `MQTT_PORT` | `localhost`, 1883 | broker for the ingest process |
| `MQTT_USERNAME`, `MQTT_PASSWORD` | unset | broker login; the broker refuses to start without a password |
| `MQTT_MAX_MSGS_PER_S` | 30 | per sensor; floods are dropped |

Engine parameters are per mission, not environment settings: see [Engine](../concepts/engine.md#tunable-parameters).
