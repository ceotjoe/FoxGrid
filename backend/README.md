# FoxGrid backend

FastAPI + SQLAlchemy 2 / GeoAlchemy2 + Alembic on PostgreSQL/PostGIS, live updates via WebSocket and Redis Pub/Sub.
Orientation: [docs/development/backend.md](../docs/development/backend.md). API: [docs/reference/api.md](../docs/reference/api.md).

```bash
uv run ruff check . && uv run mypy app && uv run pytest   # PostGIS + Redis via testcontainers
FOXGRID_DATABASE_URL=... uv run alembic revision --autogenerate -m "..."
```
