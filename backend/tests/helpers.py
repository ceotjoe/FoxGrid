from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import numpy as np
from pyproj import Geod

GEOD = Geod(ellps="WGS84")
ORIGIN = (48.137, 11.575)


def offset(
    east_m: float, north_m: float, origin: tuple[float, float] = ORIGIN
) -> tuple[float, float]:
    dist = float(np.hypot(east_m, north_m))
    az = float(np.degrees(np.arctan2(east_m, north_m)))
    lon, lat, _ = GEOD.fwd(origin[1], origin[0], az, dist)
    return float(lat), float(lon)


def azimuth(src: tuple[float, float], dst: tuple[float, float]) -> float:
    az, _, _ = GEOD.inv(src[1], src[0], dst[1], dst[0])
    return float(az % 360.0)


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return float(GEOD.inv(a[1], a[0], b[1], b[0])[2])


def bearing_payload(
    station: tuple[float, float], target: tuple[float, float], sigma: float = 5.0, **extra: Any
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "lat": station[0],
        "lon": station[1],
        "azimuth_true_deg": round(azimuth(station, target), 2),
        "sigma_deg": sigma,
        "measured_at": datetime.now(UTC).isoformat(),
        **extra,
    }


def device_secret(callsign: str) -> str:
    """A stable per-callsign secret, standing in for the one the app generates."""
    return f"device-secret-{callsign.upper()}-0123456789"


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class Mission:
    """A freshly created mission with a lead and helper calls."""

    def __init__(self, client: httpx.AsyncClient, data: dict[str, Any]) -> None:
        self.client = client
        self.id: str = data["mission"]["id"]
        self.lead_token: str = data["token"]
        self.invite: str = data["invite_token"]
        self.lead_id: str = data["participant"]["id"]

    @classmethod
    async def create(cls, client: httpx.AsyncClient, **kwargs: Any) -> Mission:
        callsign = kwargs.get("callsign", "dl1abc")
        body = {
            "name": "Test hunt",
            "frequency_mhz": 433.5,
            "callsign": "dl1abc",
            "device_secret": device_secret(callsign),
            **kwargs,
        }
        r = await client.post("/missions", json=body)
        assert r.status_code == 201, r.text
        return cls(client, r.json())

    async def join(self, callsign: str, role: str = "mobile") -> tuple[str, dict[str, Any]]:
        """Joins as `mobile`; other roles are granted by the lead afterwards, as in real use."""
        r = await self.client.post(
            "/join",
            json={
                "invite_token": self.invite,
                "callsign": callsign,
                "role": role,
                "device_secret": device_secret(callsign),
            },
        )
        assert r.status_code == 200, r.text
        participant = r.json()["participant"]
        if role == "fixed":
            p = await self.client.patch(
                self.url(f"/participants/{participant['id']}"),
                json={"role": "fixed"},
                headers=auth(self.lead_token),
            )
            assert p.status_code == 200, p.text
            participant = p.json()
        return r.json()["token"], participant

    def url(self, path: str) -> str:
        return f"/missions/{self.id}{path}"


async def wait_for(predicate: Any, timeout: float = 8.0, interval: float = 0.1) -> Any:
    """Poll an async predicate until it returns a truthy value."""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        value = await predicate()
        if value:
            return value
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(interval)
