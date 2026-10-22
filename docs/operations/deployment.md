# Running a FoxGrid server (deployment)

This guide describes how to run the backend in production on your own server: a Linux host with Docker Compose and Caddy as
a TLS reverse proxy. For local development see [Development setup](../development/setup-and-testing.md).

Components (see `docker-compose.yml`):

| Service | Purpose | Required |
|--------|---------|---------|
| `api` | FastAPI/uvicorn, runs the Alembic migrations on start | yes |
| `db` | PostgreSQL + PostGIS (volume `dbdata`) | yes |
| `redis` | Live events between workers, locks, rate limits | yes |
| `mosquitto`, `ingest` | MQTT broker and ingest process for sensors (profile `mqtt`) | optional |
| Caddy (outside Compose) | HTTPS, certificates, reverse proxy | yes, for release builds |

## 1. Prerequisites

- A Linux server with Docker (Compose v2). 1 GB RAM is enough for small missions; 2 GB is comfortable.
- A DNS name pointing at the server (for example `foxgrid.example.org`) and open ports **80/443**. All other ports stay closed.
- The store apps accept **HTTPS** only (`serverUrlError` in `join_screen.dart`). Cleartext is possible in debug builds only.

## 2. Installation

```bash
git clone https://github.com/ceotjoe/FoxGrid.git && cd FoxGrid
cp .env.example .env
```

Edit `.env` (never commit it). At minimum:

| Variable | Meaning |
|----------|-----------|
| `POSTGRES_PASSWORD`, `REDIS_PASSWORD` | your own random values; Compose aborts without them |
| `FOXGRID_JWT_SECRET` | at least 32 characters, no "change-me"; the API refuses to start otherwise. Generate with `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `FOXGRID_CORS_ORIGINS` | restrict to the web origin in production, e.g. `["https://foxgrid.example.org"]`; the default is `*` |
| `FOXGRID_POSTGIS_IMAGE` | PostGIS image. **With an existing data volume never change the major version** (see section 7) |

All other settings are listed in the [configuration reference](../reference/configuration.md). **Note:** Compose passes only the
JWT and FCM variables from `.env` into the `api` container. To change any other setting (CORS, invites, rate limits, docs), add it
to the `environment:` section of the `api` service in a `docker-compose.override.yml` (the same file used for `FORWARDED_ALLOW_IPS`
below). The ones you will most likely touch:

- `FOXGRID_JWT_TTL_HOURS` (72): session lifetime.
- `FOXGRID_INVITE_TTL_HOURS` (24) and `FOXGRID_INVITE_MAX_USES` (20): defaults for invite links.
- `FOXGRID_RATE_*_PER_MIN`: rate limits; `0` switches a limit off.
- `FOXGRID_ENABLE_DOCS` (off): exposes `/docs` and `/openapi.json`. Leave off in production.
- `FOXGRID_API_BIND` (`127.0.0.1`): binds the API locally so that the proxy is the only way in. Use `0.0.0.0` for LAN tests only.

Start:

```bash
docker compose up -d --build
docker compose logs -f api          # watch migrations and startup
curl http://127.0.0.1:8000/healthz  # {"status":"ok"}
```

API, database and Redis listen on `127.0.0.1` only. Never open the database ports to the outside.

## 3. HTTPS with Caddy

`deploy/Caddyfile` is a ready-made template: automatic Let's Encrypt certificates, security headers and a log in which the
WebSocket `?token=` is masked.

1. Install Caddy on the host (distribution package or [caddyserver.com](https://caddyserver.com/docs/install)).
2. Copy `deploy/Caddyfile` to `/etc/caddy/Caddyfile` and replace `foxgrid.example.org` with your own name.
3. Create the log directory (`/var/log/caddy`, owner `caddy`) and run `systemctl reload caddy`.
4. Check: `curl https://foxgrid.example.org/healthz`.

WebSockets pass through `reverse_proxy` without further settings.

### Real client address for rate limits

Joins are counted per client address. Behind the proxy uvicorn would otherwise only see the proxy's address, and all users would
share one limit. Therefore `FORWARDED_ALLOW_IPS` must be set to the address the proxy connects from. Never `*`, otherwise any
client can forge `X-Forwarded-For` and bypass the limits.

Compose does not pass this variable through by itself. Add it to the `api` service, preferably in a `docker-compose.override.yml`
next to the main file:

```yaml
services:
  api:
    environment:
      FORWARDED_ALLOW_IPS: "172.17.0.1"   # gateway address of the Docker network, see below
```

The address the API sees for Caddy appears in the log, or read it with `docker network inspect` (field `Gateway`).
Then run `docker compose up -d api`. To check that it works, join with two devices that have different addresses and look at the
security log (`GET /missions/{id}/audit`).

## 4. Multiple workers

By default the container starts a single uvicorn process. For more load add `--workers N`; Redis distributes the live events
between workers. Override `command` in the `api` service:

```yaml
    command: ["sh", "-c", "alembic upgrade head && uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --workers 4"]
```

For an amateur radio mission with dozens of participants one worker is usually enough.

## 5. Optional: MQTT sensors

For measurement stations and the relay hook (see [MQTT interface](../reference/mqtt.md)):

```bash
# set FOXGRID_MQTT_PASSWORD in .env
docker compose --profile mqtt up -d --build
```

- The ingest process (`ingest`) must run **exactly once**, not once per API worker.
- The password is optional in `.env` so that `docker compose up` works without MQTT. The broker does not start without one, though.
- The broker listens on `127.0.0.1:1883` only. For external sensors set up a TLS listener following `deploy/mosquitto/mosquitto.conf`;
  do not expose the cleartext port.

## 6. Optional: push notifications

See [Push notifications](push-notifications.md) for the Firebase and APNs side. On the server two values in `.env` are enough:
`FOXGRID_FCM_PROJECT_ID` and `FOXGRID_FCM_CREDENTIALS_FILE`. The service-account key file must exist at this path inside the `api`
container (for example mount it read-only to `/run/secrets/…` and never put it in the repository). The container runs as UID 10001
and the file must be readable for it (`chmod 644`, or `chown 10001` + `chmod 400`); otherwise `PermissionError` appears in the API
log. Without configuration pushes are only logged.

## 7. Operation

### Backups

All data lives in PostgreSQL. Bearings are never deleted (a database trigger forbids `DELETE`), so they are the audit trail of a mission
and should be backed up. Redis only holds transient state and needs no backup.

```bash
# Backup (daily via cron, copy the output to another medium)
docker compose exec -T db pg_dump -U foxgrid -d foxgrid --format=custom > foxgrid-$(date +%F).dump

# Restore into an empty database
docker compose stop api
docker compose exec -T db dropdb -U foxgrid foxgrid && docker compose exec -T db createdb -U foxgrid foxgrid
docker compose exec -T db psql -U foxgrid -d foxgrid -c "CREATE EXTENSION IF NOT EXISTS postgis;"
docker compose exec -T db pg_restore -U foxgrid -d foxgrid --no-owner < foxgrid-2026-01-01.dump
docker compose start api
```

User and database name correspond to `POSTGRES_USER` and `POSTGRES_DB` in `.env`. Rehearse the restore once on a test system before you
need it.

### Update

```bash
git pull
docker compose up -d --build     # rebuilds; the API runs "alembic upgrade head" on start
docker compose logs --tail=50 api
```

- Take a backup first. Migrations cannot be reverted automatically.
- With several workers the migrations run in the same start command; on an update start the API with one worker first.
- Do not simply change the PostGIS **major version** (for example 16 → 17) in the image: an existing data directory will not start with it.
  Use `pg_dump` with the old image and `pg_restore` with the new one.
- Note: `.env.example` sets `postgis/postgis:16-3.4`, while the default in `docker-compose.yml` without that variable is `17-3.5`. On a
  running system the value must never change.

### Retention

A mission has `track_retention_days` (default 30). Position tracks are deleted automatically afterwards; the API checks hourly
(`FOXGRID_TRACK_PURGE_INTERVAL_S`, 3600) and logs `purged … expired position samples`. Bearings and RSSI readings are kept.
The [privacy policy](../privacy/privacy.md) must match the retention periods you choose.

### Monitoring and logs

- Health check: `GET /healthz` (also suitable for an external monitor such as Uptime Kuma).
- Logs: `docker compose logs -f api`; access log in `/var/log/caddy/foxgrid.log` (tokens are masked). Limit Docker logs with
  `logging: { driver: local }` or a `daemon.json` rotation, otherwise they grow without bound.
- Restart after a crash: the `api` service has `restart: on-failure`. With `restart: unless-stopped` in the override it also survives a
  reboot of the host, provided Docker starts at boot (`systemctl enable docker`).

## 8. Checklist before the first mission

- [ ] All `change-me` values in `.env` replaced, `.env` not in the repository
- [ ] `FOXGRID_CORS_ORIGINS` set to the web origin
- [ ] HTTPS reachable, `curl https://…/healthz` returns `ok`
- [ ] Ports 5432, 6379, 8000 and 1883 are not reachable from outside (check from a foreign machine)
- [ ] `FORWARDED_ALLOW_IPS` set to the proxy address (not `*`)
- [ ] Daily backup configured and a restore tested
- [ ] Invite links expire and are limited (check the defaults), see [Access control](../user-guide/mission-lead-security.md)
- [ ] A test mission played through with two devices (join, bearing, estimate appears live)
