# 0001 – Stack, and an engine without web/DB dependencies

**Status:** accepted

**Context.** FoxGrid needs a mobile app plus web control room, a live multi-user backend and a numerically demanding fusion
step. The fusion is the highest technical risk and must be testable in isolation.

**Decision.** Flutter for the app and web (one code base), FastAPI + SQLAlchemy 2 + PostgreSQL/PostGIS for the backend, Redis
Pub/Sub for multi-worker live fan-out. The maths lives in its own package `foxgrid_engine` (numpy and pyproj only) that takes plain
data structures and returns dataclasses.

**Consequences.** The engine has isolated tests, `mypy --strict` and >90 % coverage, and could be reused outside FoxGrid. The backend
adapts DB rows to engine inputs and runs the engine in a thread pool. Docker Compose is the development and deployment baseline.
