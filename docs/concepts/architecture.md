# Architecture

```
Flutter (iOS/Android/Web) ──REST/WS──► FastAPI (n workers) ──► PostgreSQL + PostGIS
   Drift (offline queue)                    │  ▲
                                            ▼  │ Pub/Sub
                                          Redis ──► WebSocket fan-out to all workers
                                            │
                       Recompute job (debounce 500 ms, per mission) ──► foxgrid_engine

Sensors / relay hook ──MQTT──► Mosquitto ──► ingest process ──► same services as the REST API
```

## Components

| Component | Directory | Role |
|---|---|---|
| App + web control room | `app/` | Flutter, `flutter_map`, Riverpod, Drift (local DB and outbox), Dio, WebSocket client |
| Backend | `backend/` | FastAPI, SQLAlchemy 2 + GeoAlchemy2, Alembic, Pydantic v2 |
| Engine | `engine/` | `foxgrid_engine`: the maths, no web/DB dependencies ([Engine](engine.md)) |
| Database | | PostgreSQL 16 + PostGIS |
| Live bus | | Redis Pub/Sub, locks, rate limits |
| MQTT ingest | `backend/app/mqtt_ingest`, `deploy/mosquitto` | optional automatic stations and the relay hook |
| Tools | `tools/` | simulator, sensor client, relay hook, branding and store asset generators |

## Data flow of a bearing

1. The app writes the bearing (client UUID) to the local Drift database and the outbox queue, then `POST /bearings` when online.
2. The backend stores the bearing, assigns it to the open transmission and publishes `bearing_created` on Redis.
3. A **recompute** is scheduled per mission: trailing debounce 500 ms (maximum wait 2 s) plus a Redis lock, so exactly one worker
   runs the engine in a thread pool, for both scopes (`current` and `all`).
4. The result is stored in `estimates` and announced with `estimate_updated`; all connected clients draw the new ellipse.

## Live events

Events are published on the Redis channel `mission:{id}`. Team chat messages use `mission:{id}:team:{team}`; the WebSocket
subscribes to the caller's team channel only. Each event carries a per-mission `seq`. There is no replay: after a reconnect clients
reload `GET /missions/{id}/snapshot`. Event types are listed in the [API reference](../reference/api.md#websocket-wsmissionsidtokenjwt).

## Offline-first app

All writes go to the local Drift database first, then through a sync queue (`OutboxStore` + `SyncService`) with head-of-line
processing and exponential backoff. 4xx answers mark an entry as failed and visible (409 on transmission start/stop counts as
success; 429 is retried). The sync status is always visible in the app bar. On the web the queue is in memory only. See
[App internals](../development/app.md).

## MQTT ingest

The ingest runs as its **own process** (`python -m app.mqtt_ingest`, Compose profile `mqtt`), never inside the API workers (they
would handle every message N times). Handlers live in `app/services/ingest.py`. A sensor owns a virtual participant (role
`fixed`, callsign from its name) so bearings keep their participant foreign key; `POST /join` refuses sensor callsigns. API keys
look like `fgs_` + token; only the SHA-256 is stored. Transmission start/stop logic is shared with REST in
`app/services/transmissions.py` (`source = 'relay'`; a repeated start/stop from a relay is a harmless `duplicate`).
See [MQTT interface](../reference/mqtt.md).

## Push notifications

When a transmission starts, `app/services/push.py` sends a push (FCM HTTP v1, or log-only without credentials) to all other
active participants. See [Push notifications](../operations/push-notifications.md).

## Retention and purging

The API purges position tracks past `track_retention_days` hourly. Bearings and readings are never deleted.

## Decisions

Design decisions and their reasons: [Architecture decision records](../adr/README.md).
