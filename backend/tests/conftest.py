"""Integration fixtures: real PostGIS + Redis (testcontainers) and a real uvicorn server."""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
import uvicorn
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.redis import RedisContainer

from app.config import Settings
from app.main import create_app

BACKEND_DIR = Path(__file__).resolve().parents[1]
POSTGIS_IMAGE = os.environ.get("FOXGRID_TEST_POSTGIS_IMAGE", "postgis/postgis:16-3.4")


@pytest.fixture(scope="session")
def postgres() -> Iterator[PostgresContainer]:
    with PostgresContainer(
        POSTGIS_IMAGE, username="foxgrid", password="foxgrid", dbname="foxgrid", driver=None
    ) as pg:
        yield pg


@pytest.fixture(scope="session")
def redis_container() -> Iterator[RedisContainer]:
    with RedisContainer("redis:7-alpine") as r:
        yield r


@pytest.fixture(scope="session")
def database_url(postgres: PostgresContainer) -> str:
    host, port = postgres.get_container_host_ip(), postgres.get_exposed_port(5432)
    url = f"postgresql+asyncpg://foxgrid:foxgrid@{host}:{port}/foxgrid"
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env={**os.environ, "FOXGRID_DATABASE_URL": url},
        check=True,
    )
    return url


@pytest.fixture(scope="session")
def settings(database_url: str, redis_container: RedisContainer) -> Settings:
    host, port = redis_container.get_container_host_ip(), redis_container.get_exposed_port(6379)
    return Settings(
        database_url=database_url,
        redis_url=f"redis://{host}:{port}/0",
        jwt_secret="test-secret-not-for-production-use-0123456789",
        recompute_debounce_ms=200,
        recompute_max_wait_ms=1000,
        position_min_interval_s=1,
        rate_join_per_min=0,  # all tests join from one address; the limit has its own test
    )


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Server:
    def __init__(self, base_url: str, app_obj: object, settings: Settings) -> None:
        self.base_url = base_url
        self.ws_url = base_url.replace("http", "ws", 1)
        self.app = app_obj
        self.settings = settings


@pytest_asyncio.fixture(scope="session")
async def server(settings: Settings) -> AsyncIterator[Server]:
    app = create_app(settings)
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", ws="auto")
    uv = uvicorn.Server(config)
    task = asyncio.create_task(uv.serve())
    base = f"http://127.0.0.1:{port}"
    async with httpx.AsyncClient() as probe:
        for _ in range(100):
            try:
                if (await probe.get(f"{base}/healthz")).status_code == 200:
                    break
            except httpx.TransportError:
                await asyncio.sleep(0.1)
        else:
            raise RuntimeError("server did not start")
    yield Server(base, app, settings)
    uv.should_exit = True
    await task


@pytest_asyncio.fixture
async def client(server: Server) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(base_url=f"{server.base_url}/api/v1", timeout=10) as c:
        yield c


class FakePush:
    def __init__(self) -> None:
        self.calls: list[tuple[list[object], str, str, dict[str, str]]] = []

    async def send(self, targets, title, body, data):  # type: ignore[no-untyped-def]
        self.calls.append((targets, title, body, data))
        return []


@pytest_asyncio.fixture
async def ingest_ctx(settings: Settings, server: Server):  # type: ignore[no-untyped-def]
    """An ingest context on its own connections (the handlers are called directly)."""
    from redis.asyncio import Redis

    from app.db import make_engine, make_sessionmaker
    from app.services.ingest import IngestContext
    from app.services.recompute import RecomputeScheduler

    engine = make_engine(settings.database_url)
    sessionmaker = make_sessionmaker(engine)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    scheduler = RecomputeScheduler(sessionmaker, redis, settings)
    ctx = IngestContext(sessionmaker, redis, scheduler, FakePush(), settings)
    yield ctx
    await scheduler.shutdown()
    await redis.aclose()
    await engine.dispose()


@pytest.fixture(scope="session")
def mosquitto(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    """A real MQTT broker (anonymous, for tests only)."""
    import re

    from testcontainers.core.container import DockerContainer
    from testcontainers.core.wait_strategies import LogMessageWaitStrategy

    conf = tmp_path_factory.mktemp("mosquitto") / "mosquitto.conf"
    conf.write_text("listener 1883\nallow_anonymous true\n")
    container = (
        DockerContainer("eclipse-mosquitto:2")
        .with_exposed_ports(1883)
        .with_volume_mapping(str(conf), "/mosquitto/config/mosquitto.conf", "ro")
        .waiting_for(LogMessageWaitStrategy(re.compile(r"mosquitto version .* running")))
    )
    with container:
        yield container.get_container_host_ip(), int(container.get_exposed_port(1883))
