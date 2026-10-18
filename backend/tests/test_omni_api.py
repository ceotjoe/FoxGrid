from __future__ import annotations

import math
import random
import uuid
from datetime import UTC, datetime

import httpx
import pytest

from app.models import Mission as MissionRow
from app.models import RssiSample
from app.services.recompute import calibration_offsets
from tests.helpers import Mission, auth, distance, offset
from tests.test_field import TARGET
from tests.test_rssi_api import EXPONENT, P0, _estimate

REPEATER = offset(500.0, -800.0, TARGET)


def reading(pos: tuple[float, float], level: float, **extra: object) -> dict[str, object]:
    return {
        "id": str(uuid.uuid4()),
        "lat": pos[0],
        "lon": pos[1],
        "rssi_dbm": round(level, 2),
        "measured_at": datetime.now(UTC).isoformat(),
        "receiver": "omni",
        **extra,
    }


def level_at(pos: tuple[float, float], bias: float = 0.0) -> float:
    return P0 + bias - 10 * EXPONENT * math.log10(max(distance(pos, TARGET), 1.0))


async def fixed_station(m: Mission, name: str, east: float, north: float):
    token, _ = await m.join(name, role="fixed")
    return token, offset(east, north, TARGET)


RING = [(-6000, -2000), (5000, -5000), (7000, 3000), (-1000, 8000), (-7000, 5000), (2000, -9000)]


async def test_omni_requires_fixed_role_and_is_idempotent(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    mobile, _ = await m.join("dl2mob", role="mobile")
    pos = offset(3000.0, 1000.0, TARGET)
    r = await client.post(m.url("/rssi"), json=[reading(pos, -90.0)], headers=auth(mobile))
    assert r.status_code == 403
    token, _ = await m.join("dl3fix", role="fixed")
    payload = [reading(pos, -90.0)]
    ok = await client.post(m.url("/rssi"), json=payload, headers=auth(token))
    assert ok.json() == {"stored": 1, "duplicates": 0}
    again = await client.post(m.url("/rssi"), json=payload, headers=auth(token))
    assert again.json() == {"stored": 0, "duplicates": 1}
    changed = [{**payload[0], "is_calibration": False, "receiver": "mobile"}]
    assert (await client.post(m.url("/rssi"), json=changed, headers=auth(token))).status_code == 409
    listed = await client.get(m.url("/rssi"), headers=auth(token))
    assert listed.json()[0]["receiver"] == "omni"


async def test_calibration_needs_repeater_and_omni(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    token, _ = await m.join("dl3fix", role="fixed")
    pos = offset(2000.0, 0.0, TARGET)
    cal = [reading(pos, -80.0, is_calibration=True)]
    assert (await client.post(m.url("/rssi"), json=cal, headers=auth(token))).status_code == 422
    bad = [{**cal[0], "receiver": "mobile"}]
    assert (await client.post(m.url("/rssi"), json=bad, headers=auth(token))).status_code == 422

    assert (
        await client.patch(m.url(""), json={"repeater": {"lat": 1, "lon": 2}}, headers=auth(token))
    ).status_code == 403
    r = await client.patch(
        m.url(""),
        json={
            "repeater": {
                "lat": REPEATER[0],
                "lon": REPEATER[1],
                "input_mhz": 145.0,
                "output_mhz": 145.6,
            }
        },
        headers=auth(m.lead_token),
    )
    assert r.status_code == 200 and r.json()["repeater"]["input_mhz"] == 145.0
    stored = await client.post(m.url("/rssi"), json=cal, headers=auth(token))
    assert stored.json()["stored"] == 1
    assert (await client.get(m.url(""), headers=auth(token))).json()["repeater"]["lat"] == REPEATER[
        0
    ]


async def test_fixed_stations_produce_an_estimate(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    rng = random.Random(4)
    biases = []
    for i, (e, n) in enumerate(RING):
        token, pos = await fixed_station(m, f"dl{i}fix", e, n)
        bias = rng.gauss(0.0, 3.0)
        biases.append(bias)
        r = await client.post(
            m.url("/rssi"),
            json=[reading(pos, level_at(pos, bias) + rng.gauss(0.0, 1.5))],
            headers=auth(token),
        )
        assert r.status_code == 200
    est = await _estimate(client, m, "all")
    assert est is not None
    assert est["rssi"]["n_samples"] == len(RING)
    assert len(est["rssi"]["station_offsets_db"]) == len(RING)
    assert distance((est["lat"], est["lon"]), TARGET) < 4000.0


async def test_three_stations_are_not_enough(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    for i, (e, n) in enumerate(RING[:3]):
        token, pos = await fixed_station(m, f"dl{i}fix", e, n)
        await client.post(m.url("/rssi"), json=[reading(pos, level_at(pos))], headers=auth(token))
    r = await client.get(m.url("/estimate?scope=all"), headers=auth(m.lead_token))
    assert r.status_code == 404


async def test_calibration_readings_do_not_enter_the_fit(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    await client.patch(
        m.url(""),
        json={"repeater": {"lat": REPEATER[0], "lon": REPEATER[1]}},
        headers=auth(m.lead_token),
    )
    for i, (e, n) in enumerate(RING):
        token, pos = await fixed_station(m, f"dl{i}fix", e, n)
        body = [
            reading(pos, level_at(pos)),
            reading(pos, -70.0 - 3.0 * i, is_calibration=True),
        ]
        assert (
            await client.post(m.url("/rssi"), json=body, headers=auth(token))
        ).status_code == 200
    est = await _estimate(client, m, "all")
    assert est is not None and est["rssi"]["n_samples"] == len(RING)


def _row(pid: uuid.UUID, pos: tuple[float, float], level: float, cal: bool = True) -> RssiSample:
    return RssiSample(
        id=uuid.uuid4(),
        participant_id=pid,
        lat=pos[0],
        lon=pos[1],
        rssi_dbm=level,
        attenuation_db=0.0,
        measured_at=datetime.now(UTC),
        receiver="omni",
        is_calibration=cal,
        is_active=True,
    )


def test_calibration_offsets_remove_the_path_loss() -> None:
    mission = MissionRow(repeater_lat=REPEATER[0], repeater_lon=REPEATER[1])
    biases = [5.0, -5.0, 2.0, -2.0]
    rows, pids = [], [uuid.uuid4() for _ in biases]
    for pid, bias, (e, n) in zip(pids, biases, RING, strict=False):
        pos = offset(e, n, TARGET)
        d = distance(pos, REPEATER)
        rows.append(_row(pid, pos, -30.0 + bias - 30.0 * math.log10(d)))
    got = calibration_offsets(mission, rows)
    assert [got[p] for p in pids] == pytest.approx([5.0, -5.0, 2.0, -2.0], abs=0.1)
    assert calibration_offsets(mission, rows[:2]) == {}  # too few stations for a mean
    assert calibration_offsets(MissionRow(), rows) == {}  # no repeater position
    rows[0].is_active = rows[1].is_active = False
    assert calibration_offsets(mission, rows) == {}  # inactive readings do not count
