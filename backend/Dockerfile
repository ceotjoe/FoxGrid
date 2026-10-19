# Build context is the repository root (the backend depends on ./engine).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY engine /srv/engine
COPY backend /srv/backend
RUN pip install --no-cache-dir /srv/engine /srv/backend

WORKDIR /srv/backend
RUN useradd --system --no-create-home --uid 10001 foxgrid
USER foxgrid
EXPOSE 8000
# Apply migrations, then serve. Use --workers N for multi-worker setups (Redis fans events out).
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000"]
