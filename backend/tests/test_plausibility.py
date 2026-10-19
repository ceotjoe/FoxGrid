"""Plausibility hints (pure geometry) and rate limits (Redis)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from redis.asyncio import Redis

from app.services import plausibility as pl
from tests.conftest import Server
from tests.helpers import Mission, auth, bearing_payload, device_secret, offset, wait_for
from tests.test_field import STATIONS, TARGET, _full_estimate
from tests.test_rssi_api import track

T0 = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
LAT, LON = 48.137, 11.575


def _bearing(station: tuple[float, float], target: tuple[float, float], error: float = 0.0):
    return pl.BearingFact(
        station[0],
        station[1],
        (pl.azimuth_deg(*station, *target) + error) % 360,
        10.0,
        T0,
    )


def test_azimuth_and_distance_basics() -> None:
    assert pl.azimuth_deg(LAT, LON, LAT + 0.1, LON) == pytest.approx(0, abs=0.01)
    assert pl.azimuth_deg(LAT, LON, LAT, LON + 0.1) == pytest.approx(90, abs=0.2)
    assert pl.distance_m(LAT, LON, LAT + 0.01, LON) == pytest.approx(1112, rel=0.01)
    b = pl.BearingFact(LAT, LON, 359.0, 10.0, T0)
    # wrap-around: 359° vs a target due north is -1°, not 359°
    assert pl.residual_deg(b, LAT + 0.1, LON) == pytest.approx(-1.0, abs=0.1)


def test_disagreement_needs_most_bearings_to_miss() -> None:
    good = [_bearing(s, TARGET, e) for s, e in zip(STATIONS, (2.0, -4.0, 5.0), strict=True)]
    assert pl.disagreement(good, *TARGET) is None
    wrong = [_bearing(s, TARGET, 120.0) for s in STATIONS[:2]]
    flag = pl.disagreement(wrong, *TARGET)
    assert flag is not None and flag.code == "bearings_disagree" and "2 von 2" in flag.detail
    # one slip among three honest bearings is not enough
    assert pl.disagreement([*good[:2], _bearing(STATIONS[2], TARGET, 120.0)], *TARGET) is None
    assert pl.disagreement(wrong[:1], *TARGET) is None  # too little to judge


def test_wide_sigma_tolerates_large_misses() -> None:
    sloppy = pl.BearingFact(*STATIONS[0], pl.azimuth_deg(*STATIONS[0], *TARGET) + 50, 30.0, T0)
    assert pl.disagreement([sloppy, sloppy], *TARGET) is None  # 50° < 3 * 30°


def test_impossible_speed_ignores_jitter_and_poor_fixes() -> None:
    far = offset(0, 12_000, (LAT, LON))
    jump = [pl.Fix(LAT, LON, T0), pl.Fix(*far, T0 + timedelta(seconds=30))]
    flag = pl.impossible_speed(jump)
    assert flag is not None and flag.code == "impossible_speed"
    drive = [pl.Fix(LAT, LON, T0), pl.Fix(*far, T0 + timedelta(minutes=10))]  # 72 km/h
    assert pl.impossible_speed(drive) is None
    jitter = [pl.Fix(LAT, LON, T0), pl.Fix(*offset(0, 300, (LAT, LON)), T0 + timedelta(seconds=2))]
    assert pl.impossible_speed(jitter) is None
    poor = [pl.Fix(LAT, LON, T0, 800.0), pl.Fix(*far, T0 + timedelta(seconds=30), 800.0)]
    assert pl.impossible_speed(poor) is None
    assert pl.impossible_speed([pl.Fix(LAT, LON, T0), pl.Fix(*far, T0)]) is not None


def test_bearings_must_match_the_own_track() -> None:
    here = pl.Fix(LAT, LON, T0)
    at_home = [pl.BearingFact(LAT, LON, 10.0, 10.0, T0 + timedelta(minutes=i)) for i in range(3)]
    assert pl.off_track(at_home, [here]) is None
    elsewhere = [
        pl.BearingFact(LAT + 0.1, LON, 10.0, 10.0, T0 + timedelta(minutes=i)) for i in range(3)
    ]
    flag = pl.off_track(elsewhere, [here])
    assert flag is not None and flag.code == "bearing_off_track"
    no_track = pl.off_track(at_home, [])
    assert no_track is not None and no_track.code == "no_track"
    assert pl.off_track(at_home[:2], []) is None  # two bearings without a track are normal indoors
    # a bearing without a nearby fix in time cannot be judged
    late = [pl.BearingFact(LAT + 0.1, LON, 10.0, 10.0, T0 + timedelta(hours=3))] * 3
    assert pl.off_track(late, [here]) is None


def test_assess_skips_disagreement_when_the_estimate_is_too_thin() -> None:
    wrong = [_bearing(s, TARGET, 120.0) for s in STATIONS[:2]]
    assert pl.assess(wrong, [], (*TARGET, 2)) == []
    assert [f.code for f in pl.assess(wrong, [], (*TARGET, 5))] == ["bearings_disagree"]


async def test_lead_sees_hints_about_a_saboteur(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    honest_token, honest = await m.join("DL2HON")
    sab_token, sab = await m.join("DL2SAB")
    for token, station in ((m.lead_token, 0), (honest_token, 1), (honest_token, 2)):
        r = await client.post(
            m.url("/bearings"), json=bearing_payload(STATIONS[station], TARGET), headers=auth(token)
        )
        assert r.status_code == 201
    for station in (0, 1):  # the saboteur points the wrong way
        wrong = bearing_payload(STATIONS[station], TARGET)
        wrong["azimuth_true_deg"] = (wrong["azimuth_true_deg"] + 130) % 360
        assert (
            await client.post(m.url("/bearings"), json=wrong, headers=auth(sab_token))
        ).status_code == 201
    # ... and the GPS jumps by 12 km within seconds
    now = datetime.now(UTC)
    far = offset(0, 12_000, (LAT, LON))
    fixes = [
        {"lat": LAT, "lon": LON, "recorded_at": now.isoformat()},
        {"lat": far[0], "lon": far[1], "recorded_at": (now + timedelta(seconds=20)).isoformat()},
    ]
    assert (
        await client.post(m.url("/positions"), json=fixes, headers=auth(sab_token))
    ).status_code == 202
    assert await wait_for(lambda: _full_estimate(client, m, 5))

    r = await client.get(m.url("/plausibility"), headers=h)
    assert r.status_code == 200, r.text
    by_id = {x["participant_id"]: x for x in r.json()}
    # the claimed stations are also km away from where their own track says they were
    assert {f["code"] for f in by_id[sab["id"]]["flags"]} == {
        "bearings_disagree",
        "impossible_speed",
        "bearing_off_track",
    }
    assert by_id[sab["id"]]["bearings"] == 2
    assert by_id[honest["id"]]["flags"] == []
    assert by_id[m.lead_id]["flags"] == []
    # hints only: nobody was removed or distrusted by it
    me = await client.get(m.url("/participants"), headers=h)
    assert all(p["trusted"] and p["is_active"] for p in me.json())
    # members cannot ask
    assert (await client.get(m.url("/plausibility"), headers=auth(sab_token))).status_code == 403


@asynccontextmanager
async def _limit(server: Server, name: str, value: int) -> AsyncIterator[Redis]:
    redis = Redis.from_url(server.settings.redis_url)
    old = getattr(server.settings, name)
    setattr(server.settings, name, value)
    try:
        yield redis
    finally:
        setattr(server.settings, name, old)
        async for key in redis.scan_iter("rl:*"):
            await redis.delete(key)
        await redis.aclose()


async def test_joins_are_limited_per_address(client: httpx.AsyncClient, server: Server) -> None:
    m = await Mission.create(client)
    async with _limit(server, "rate_join_per_min", 3):
        codes = []
        for i in range(5):
            r = await client.post(
                "/join",
                json={
                    "invite_token": m.invite,
                    "callsign": f"DL3R{i}",
                    "device_secret": device_secret(f"DL3R{i}"),
                },
            )
            codes.append(r.status_code)
        assert codes == [200, 200, 200, 429, 429]
        assert int(r.headers["Retry-After"]) > 0


async def test_bearing_flood_is_limited_per_participant(
    client: httpx.AsyncClient, server: Server
) -> None:
    m = await Mission.create(client)
    other_token, _ = await m.join("DL3OTH")
    async with _limit(server, "rate_bearing_per_min", 3):
        codes = [
            (
                await client.post(
                    m.url("/bearings"),
                    json=bearing_payload(STATIONS[0], TARGET),
                    headers=auth(m.lead_token),
                )
            ).status_code
            for _ in range(5)
        ]
        assert codes == [201, 201, 201, 429, 429]
        # somebody else is not affected by the flood
        ok = await client.post(
            m.url("/bearings"),
            json=bearing_payload(STATIONS[1], TARGET),
            headers=auth(other_token),
        )
        assert ok.status_code == 201


async def test_rssi_counts_every_reading_and_messages_are_limited(
    client: httpx.AsyncClient, server: Server
) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    samples = track(TARGET, n=6)
    async with _limit(server, "rate_rssi_per_min", 8):
        assert (await client.post(m.url("/rssi"), json=samples[:4], headers=h)).status_code == 200
        assert (await client.post(m.url("/rssi"), json=samples[:4], headers=h)).status_code == 200
        assert (await client.post(m.url("/rssi"), json=samples[:4], headers=h)).status_code == 429

    def message(i: int) -> dict[str, str]:
        import uuid

        return {
            "id": str(uuid.uuid4()),
            "body": f"hi {i}",
            "sent_at": datetime.now(UTC).isoformat(),
        }

    async with _limit(server, "rate_message_per_min", 2):
        codes: list[int] = []
        for i in range(3):
            r = await client.post(m.url("/messages"), json=message(i), headers=h)
            codes.append(r.status_code)
        assert codes == [201, 201, 429]
