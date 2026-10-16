from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from app.api import coordination, export, field, missions, rssi, sensors
from app.config import Settings
from app.db import make_engine, make_sessionmaker
from app.services import domain, push
from app.services.recompute import RecomputeScheduler
from app.ws import router as ws_router

log = logging.getLogger(__name__)


async def _purge_loop(app: FastAPI, interval_s: int) -> None:
    while True:
        try:
            async with app.state.sessionmaker() as session:
                deleted = await domain.purge_expired_tracks(session)
            if deleted:
                log.info("purged %s expired position samples", deleted)
        except Exception:
            log.exception("track purge failed")
        await asyncio.sleep(interval_s)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()  # type: ignore[call-arg]

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(settings.database_url)
        sessionmaker = make_sessionmaker(engine)
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        app.state.settings = settings
        app.state.sessionmaker = sessionmaker
        app.state.redis = redis
        app.state.recompute = RecomputeScheduler(sessionmaker, redis, settings)
        app.state.push = push.make_sender(settings)
        app.state.background = set()
        purge = asyncio.create_task(_purge_loop(app, settings.track_purge_interval_s))
        try:
            yield
        finally:
            purge.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await purge
            await app.state.recompute.shutdown()
            await redis.aclose()
            await engine.dispose()

    app = FastAPI(title="FoxGrid", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(missions.router, prefix="/api/v1")
    app.include_router(field.router, prefix="/api/v1")
    app.include_router(coordination.router, prefix="/api/v1")
    app.include_router(coordination.mission_router, prefix="/api/v1")
    app.include_router(sensors.router, prefix="/api/v1")
    app.include_router(rssi.router, prefix="/api/v1")
    app.include_router(export.router, prefix="/api/v1")
    app.include_router(ws_router.router)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
