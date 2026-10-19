"""Deployment hardening: secret validation, mission-creation rate limit, docs off by default."""

from __future__ import annotations

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from tests.conftest import Server


@pytest.mark.parametrize("secret", ["short", "change-me-jwt-secret-at-least-32-chars", "x" * 31])
def test_weak_jwt_secret_is_refused(secret: str) -> None:
    with pytest.raises(ValidationError):
        Settings(jwt_secret=secret)


def test_strong_jwt_secret_is_accepted() -> None:
    assert Settings(jwt_secret="a" * 32).enable_docs is False


async def test_docs_are_off_by_default(client: httpx.AsyncClient, server: Server) -> None:
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert (await client.get(f"{server.base_url}{path}")).status_code == 404


async def test_mission_creation_is_rate_limited(
    client: httpx.AsyncClient, server: Server
) -> None:
    server.settings.rate_mission_per_min = 2
    try:
        body = {
            "name": "rl",
            "frequency_mhz": 145.5,
            "callsign": "DL1RL",
            "device_secret": "s" * 20,
        }
        codes = [(await client.post("/missions", json=body)).status_code for _ in range(3)]
    finally:
        server.settings.rate_mission_per_min = 0
    assert codes[:2] == [201, 201]
    assert codes[2] == 429
