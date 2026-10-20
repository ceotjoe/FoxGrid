from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime, timedelta

import asyncpg
import httpx
import websockets
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.services.domain import purge_expired_tracks
from tests.conftest import Server
from tests.helpers import (
    Mission,
    auth,
    bearing_payload,
    distance,
    offset,
    wait_for,
)

TARGET = offset(1500, 2500)
STATIONS = [offset(-6000, -3000), offset(7000, -4000), offset(500, 9000)]


async def _estimate(client: httpx.AsyncClient, m: Mission, token: str, scope: str = "all"):
    async def poll():
        r = await client.get(m.url(f"/estimate?scope={scope}"), headers=auth(token))
        return r.json() if r.status_code == 200 else None

    return await wait_for(poll)


async def test_bearing_idempotency_and_validation(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    payload = bearing_payload(STATIONS[0], TARGET)
    first = await client.post(m.url("/bearings"), json=payload, headers=h)
    assert first.status_code == 201
    again = await client.post(m.url("/bearings"), json=payload, headers=h)
    assert again.status_code == 200 and again.json()["id"] == first.json()["id"]
    changed = {**payload, "azimuth_true_deg": (payload["azimuth_true_deg"] + 30) % 360}
    assert (await client.post(m.url("/bearings"), json=changed, headers=h)).status_code == 409
    listed = await client.get(m.url("/bearings"), headers=h)
    assert len(listed.json()) == 1

    no_sigma = {k: v for k, v in bearing_payload(STATIONS[1], TARGET).items() if k != "sigma_deg"}
    assert (await client.post(m.url("/bearings"), json=no_sigma, headers=h)).status_code == 422
    naive_time = {**bearing_payload(STATIONS[1], TARGET), "measured_at": "2026-01-01T10:00:00"}
    assert (await client.post(m.url("/bearings"), json=naive_time, headers=h)).status_code == 422
    bad_az = {**bearing_payload(STATIONS[1], TARGET), "azimuth_true_deg": 360}
    assert (await client.post(m.url("/bearings"), json=bad_az, headers=h)).status_code == 422


async def test_bearings_are_flagged_never_deleted(client: httpx.AsyncClient, settings) -> None:
    m = await Mission.create(client)
    other_token, _ = await m.join("DL5OWN")
    stranger_token, _ = await m.join("DL5OTH")
    payload = bearing_payload(STATIONS[0], TARGET)
    r = await client.post(m.url("/bearings"), json=payload, headers=auth(other_token))
    bid = r.json()["id"]

    denied = await client.patch(
        m.url(f"/bearings/{bid}"), json={"is_outlier": True}, headers=auth(stranger_token)
    )
    assert denied.status_code == 403
    ok = await client.patch(
        m.url(f"/bearings/{bid}"),
        json={"is_outlier": True, "note": "reflection"},
        headers=auth(m.lead_token),
    )
    assert ok.status_code == 200 and ok.json()["is_outlier"] is True
    revs = await client.get(m.url(f"/bearings/{bid}/revisions"), headers=auth(m.lead_token))
    assert revs.json()[0]["changes"]["is_outlier"] == {"from": False, "to": True}
    # editing azimuth is not allowed
    bad = await client.patch(
        m.url(f"/bearings/{bid}"), json={"azimuth_true_deg": 1}, headers=auth(m.lead_token)
    )
    assert bad.status_code == 422
    assert (
        await client.delete(m.url(f"/bearings/{bid}"), headers=auth(m.lead_token))
    ).status_code == 405

    # The database itself refuses deletes.
    dsn = settings.database_url.replace("+asyncpg", "")
    conn = await asyncpg.connect(dsn)
    try:
        try:
            await conn.execute("DELETE FROM bearings WHERE id = $1", uuid.UUID(bid))
        except asyncpg.PostgresError as exc:
            assert "append-only" in str(exc)
        else:
            raise AssertionError("delete should have been rejected")
    finally:
        await conn.close()


async def test_estimate_from_three_bearings(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    assert (await client.get(m.url("/estimate"), headers=h)).status_code == 404
    for st in STATIONS:
        r = await client.post(m.url("/bearings"), json=bearing_payload(st, TARGET), headers=h)
        assert r.status_code == 201
    est = await wait_for(lambda: _full_estimate(client, m, 3))
    assert distance((est["lat"], est["lon"]), TARGET) < 30
    assert est["ellipse_2s"]["polygon"]["type"] == "Polygon"
    assert est["ellipse_1s"]["semi_major_m"] <= est["ellipse_2s"]["semi_major_m"]


async def _full_estimate(client: httpx.AsyncClient, m: Mission, n: int):
    r = await client.get(m.url("/estimate?scope=all"), headers=auth(m.lead_token))
    if r.status_code == 200 and r.json()["n_bearings"] == n:
        return r.json()
    return None


async def test_outlier_flag_excludes_bearing(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    for st in STATIONS:
        await client.post(m.url("/bearings"), json=bearing_payload(st, TARGET), headers=h)
    bad = bearing_payload(offset(-3000, 6000), TARGET)
    bad["azimuth_true_deg"] = (bad["azimuth_true_deg"] + 90) % 360
    bid = (await client.post(m.url("/bearings"), json=bad, headers=h)).json()["id"]
    await wait_for(lambda: _full_estimate(client, m, 4))
    await client.patch(m.url(f"/bearings/{bid}"), json={"is_outlier": True}, headers=h)
    est = await wait_for(lambda: _full_estimate(client, m, 3))
    assert distance((est["lat"], est["lon"]), TARGET) < 30
    # the flagged bearing is still in the log
    listed = await client.get(m.url("/bearings"), headers=h)
    assert len(listed.json()) == 4


async def test_transmissions_and_assignment(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    assert (await client.post(m.url("/transmissions/stop"), headers=h)).status_code == 409
    tx = await client.post(m.url("/transmissions/start"), headers=h)
    assert tx.status_code == 201 and tx.json()["seq"] == 1
    assert (await client.post(m.url("/transmissions/start"), headers=h)).status_code == 409

    during = await client.post(
        m.url("/bearings"), json=bearing_payload(STATIONS[0], TARGET), headers=h
    )
    assert during.json()["transmission_id"] == tx.json()["id"]

    stopped = await client.post(m.url("/transmissions/stop"), headers=h)
    assert stopped.status_code == 200 and stopped.json()["ended_at"]
    late = bearing_payload(STATIONS[1], TARGET)
    late["measured_at"] = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    after = await client.post(m.url("/bearings"), json=late, headers=h)
    assert after.json()["transmission_id"] is None

    tx2 = await client.post(m.url("/transmissions/start"), headers=h)
    assert tx2.json()["seq"] == 2
    listed = await client.get(m.url("/transmissions"), headers=h)
    assert [t["seq"] for t in listed.json()] == [1, 2]


async def test_only_starter_or_lead_can_stop_transmission(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    lead = auth(m.lead_token)
    token_a, _ = await m.join("DL1AAA")
    token_b, _ = await m.join("DL1BBB")
    a, b = auth(token_a), auth(token_b)

    await client.post(m.url("/transmissions/start"), headers=a)
    denied = await client.post(m.url("/transmissions/stop"), headers=b)
    assert denied.status_code == 403
    running = [t for t in (await client.get(m.url("/transmissions"), headers=lead)).json()]
    assert running[-1]["ended_at"] is None
    assert (await client.post(m.url("/transmissions/stop"), headers=a)).status_code == 200

    # the lead may stop a transmission started by someone else
    await client.post(m.url("/transmissions/start"), headers=b)
    assert (await client.post(m.url("/transmissions/stop"), headers=lead)).status_code == 200

    # and a participant cannot stop one the lead started
    await client.post(m.url("/transmissions/start"), headers=lead)
    assert (await client.post(m.url("/transmissions/stop"), headers=a)).status_code == 403


async def test_current_scope_follows_latest_transmission(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    await client.post(m.url("/transmissions/start"), headers=h)
    for st in STATIONS[:2]:
        await client.post(m.url("/bearings"), json=bearing_payload(st, TARGET), headers=h)
    await client.post(m.url("/transmissions/stop"), headers=h)
    await client.post(m.url("/transmissions/start"), headers=h)
    for st in STATIONS[1:]:
        await client.post(m.url("/bearings"), json=bearing_payload(st, TARGET), headers=h)

    async def both():
        cur = await client.get(m.url("/estimate?scope=current"), headers=h)
        allr = await client.get(m.url("/estimate?scope=all"), headers=h)
        both_ok = cur.status_code == 200 and allr.status_code == 200
        if both_ok and cur.json()["n_bearings"] == 2 and allr.json()["n_bearings"] == 4:
            return cur.json()
        return None

    assert await wait_for(both)


async def test_websocket_live_events_within_two_seconds(
    client: httpx.AsyncClient, server: Server
) -> None:
    m = await Mission.create(client)
    other_token, other = await m.join("DL6LIVE")
    async with websockets.connect(f"{server.ws_url}/ws/missions/{m.id}?token={other_token}") as ws:
        h = auth(m.lead_token)
        sent = time.monotonic()
        await client.post(m.url("/transmissions/start"), headers=h)
        for st in STATIONS:
            await client.post(m.url("/bearings"), json=bearing_payload(st, TARGET), headers=h)
        seen: dict[str, float] = {}
        seqs: list[int] = []
        while "estimate_updated" not in seen:
            event = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            seen.setdefault(event["type"], time.monotonic() - sent)
            seqs.append(event["seq"])
            assert event["mission_id"] == m.id
        assert {"transmission_started", "bearing_created", "estimate_updated"} <= seen.keys()
        assert seen["bearing_created"] < 2.0
        assert seen["estimate_updated"] < 2.0
        assert seqs == sorted(seqs)

        # client -> server: position update, throttled
        pos = {
            "type": "position",
            "data": {"lat": 48.1, "lon": 11.5, "recorded_at": datetime.now(UTC).isoformat()},
        }
        await ws.send(json.dumps(pos))
        await ws.send(json.dumps(pos))  # within throttle window -> dropped
        event = None
        while event is None or event["type"] != "participant_position":
            event = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
        assert event["data"]["callsign"] == "DL6LIVE"
        await ws.send(json.dumps({"type": "nonsense"}))
        err = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
        assert err["type"] == "error"
        await ws.send(json.dumps({"type": "ping"}))
        assert json.loads(await asyncio.wait_for(ws.recv(), timeout=3))["type"] == "pong"

    stored = await client.get(
        m.url(f"/positions?participant={other['id']}"), headers=auth(m.lead_token)
    )
    assert len(stored.json()) == 1


async def test_websocket_rejects_bad_tokens(client: httpx.AsyncClient, server: Server) -> None:
    a = await Mission.create(client)
    b = await Mission.create(client, callsign="DL7BBB")
    for token in ("", "bad", b.lead_token):
        try:
            async with websockets.connect(
                f"{server.ws_url}/ws/missions/{a.id}?token={token}"
            ) as ws:
                await asyncio.wait_for(ws.recv(), timeout=3)
        except (websockets.exceptions.InvalidStatus, websockets.exceptions.ConnectionClosed):
            continue
        raise AssertionError("connection should have been refused")


async def test_events_reach_other_workers_via_redis(
    client: httpx.AsyncClient, server: Server
) -> None:
    """A subscriber that talks only to Redis (like another worker) sees API events."""
    from redis.asyncio import Redis

    m = await Mission.create(client)
    redis = Redis.from_url(server.settings.redis_url, decode_responses=True)
    pubsub = redis.pubsub()
    await pubsub.subscribe(f"mission:{m.id}")
    await client.post(m.url("/transmissions/start"), headers=auth(m.lead_token))
    msg = None
    for _ in range(50):
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.2)
        if msg:
            break
    await pubsub.aclose()
    await redis.aclose()
    assert msg and json.loads(msg["data"])["type"] == "transmission_started"


async def test_recompute_is_debounced(client: httpx.AsyncClient, server: Server) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    stations = [offset(-6000 + 300 * i, -3000 + 200 * i) for i in range(8)]
    for st in stations:
        await client.post(m.url("/bearings"), json=bearing_payload(st, TARGET), headers=h)
    await wait_for(lambda: _full_estimate(client, m, 8))
    history = await client.get(m.url("/estimate/history?scope=all"), headers=h)
    assert 1 <= len(history.json()) < 8  # 8 rapid writes collapsed into few computations


async def test_snapshot(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    await client.post(m.url("/transmissions/start"), headers=h)
    for st in STATIONS:
        await client.post(m.url("/bearings"), json=bearing_payload(st, TARGET), headers=h)
    await client.post(
        m.url("/positions"),
        json=[{"lat": 48.2, "lon": 11.6, "recorded_at": datetime.now(UTC).isoformat()}],
        headers=h,
    )
    await wait_for(lambda: _full_estimate(client, m, 3))
    snap = (await client.get(m.url("/snapshot"), headers=h)).json()
    assert len(snap["bearings"]) == 3 and len(snap["participants"]) == 1
    assert snap["transmissions"][0]["ended_at"] is None
    assert len(snap["positions"]) == 1
    assert {e["scope"] for e in snap["estimates"]} == {"current", "all"}


async def test_position_purge_keeps_bearings(client: httpx.AsyncClient, settings) -> None:
    m = await Mission.create(client, track_retention_days=1)
    h = auth(m.lead_token)
    await client.post(m.url("/bearings"), json=bearing_payload(STATIONS[0], TARGET), headers=h)
    await client.post(
        m.url("/positions"),
        json=[{"lat": 48.2, "lon": 11.6, "recorded_at": datetime.now(UTC).isoformat()}],
        headers=h,
    )
    await client.post(m.url("/end"), headers=h)
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE missions SET ended_at = now() - interval '2 days' WHERE id = :i"),
                {"i": m.id},
            )
        from sqlalchemy.ext.asyncio import AsyncSession

        async with AsyncSession(engine) as session:
            assert await purge_expired_tracks(session) >= 1
    finally:
        await engine.dispose()
    assert (await client.get(m.url("/positions"), headers=h)).json() == []
    assert len((await client.get(m.url("/bearings"), headers=h)).json()) == 1


async def test_late_bearing_allowed_after_mission_end(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    await client.post(m.url("/end"), headers=h)
    r = await client.post(m.url("/bearings"), json=bearing_payload(STATIONS[0], TARGET), headers=h)
    assert r.status_code == 201  # offline sync must not lose log entries
