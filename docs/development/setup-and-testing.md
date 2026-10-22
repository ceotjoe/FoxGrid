# Development setup and testing

## Prerequisites

Docker, [uv](https://docs.astral.sh/uv/) and Flutter (stable). Python is pinned to 3.12 through `.python-version`.

## Start the stack

```bash
cp .env.example .env           # adjust passwords and the JWT secret
docker compose up -d --build   # API (port 8000), PostGIS, Redis; migrations run automatically
curl localhost:8000/healthz
```

On Apple silicon the default PostGIS image runs under amd64 emulation; set `FOXGRID_POSTGIS_IMAGE` for a native image.

Run the app (the default server URL is `http://localhost:8000`, in the Android emulator `http://10.0.2.2:8000`):

```bash
cd app
flutter run -d chrome          # web control room
flutter run -d emulator-5554   # Android emulator
```

Create a mission in the app (tab "Einsatz anlegen"); the person icon shows the invite (token and the link
`foxgrid://join?server=…&token=…`, also as QR code). Other devices join with the token or link.

Optional MQTT (stations and relay hook):

```bash
docker compose --profile mqtt up -d
uv run tools/sensor_client/station.py --help
uv run tools/relay_hook/hook.py --help
```

## Tests and linters

```bash
cd engine  && uv run ruff check . && uv run mypy --strict foxgrid_engine && uv run pytest
cd backend && uv run ruff check . && uv run mypy app && uv run pytest     # PostGIS + Redis via testcontainers
cd app     && flutter analyze && flutter test
uv run --with pytest --with aiomqtt pytest tools/relay_hook                 # likewise tools/sensor_client
```

Quality bars: `ruff` for backend and engine, `mypy --strict` for the engine, `flutter analyze` with zero warnings, engine
coverage above 90 %, API integration tests against real PostGIS, widget tests for the capture flow. GitHub Actions runs lint and
tests for backend, engine and app (`.github/workflows/ci.yml`).

Test conventions:

- Backend tests that join a second participant use the `Mission.join` helper, which approves automatically. The join rate limit is
  switched off in tests because all of them join from 127.0.0.1.
- Provider overrides in Flutter tests need `import 'package:flutter_riverpod/misc.dart' show Override;` (Riverpod 3).
- Lazy `ListView` widget tests need a tall viewport (`tester.view.physicalSize`), otherwise controls are not built.
- `tests/test_ingest.py` also runs the real ingest service against a Mosquitto testcontainer.

## Migrations

```bash
cd backend && FOXGRID_DATABASE_URL=... uv run alembic revision --autogenerate -m "..."
```

The generated PostGIS `geom` columns are ignored by autogenerate. Review every generated migration.

## Simulator

```bash
uv run tools/simulator/run.py --interval-s 8
```

Creates a mission, lets five simulated bearers join (one with a grossly wrong bearing), starts a transmission and, after every
bearing, reports the distance of the estimate to the true position. The invite it prints can be entered in the app to watch live.
The exit code is non-zero if the error exceeds `--max-error-m` (default 600 m). Useful options: `--bearers`, `--outliers`,
`--noise-deg`, `--sigma-deg`, `--seed`, `--homing` (a homing walk with attenuator), `--rssi-samples`, `--path-loss-n`.
`uv run tools/simulator/omni_eval.py` evaluates the accuracy of the fixed-station model (`--trials`, `--stations`, `--fading`).

## Generated files

Do not edit these by hand; regenerate them:

| Files | Command |
|---|---|
| `app/lib/core/database.g.dart` (committed) | `dart run build_runner build` in `app/` |
| App icons, favicon | `python3 tools/branding/generate_icons.py` (see [Branding](branding.md)) |
| Store graphics in `store/metadata/` | `python3 tools/store/generate_assets.py` (see [Release](../operations/release.md)) |

## Commits and pull requests

Small, traceable commits with meaningful messages (`feat(app): …`, `fix(backend): …`). See [CONTRIBUTING.md](../../CONTRIBUTING.md).
