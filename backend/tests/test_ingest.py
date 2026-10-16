from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime, timedelta

import aiomqtt
import httpx

from app.config import Settings
from app.mqtt_ingest import run
from app.services.ingest import IngestContext, handle_message, parse_topic
from tests.conftest import FakePush, Server
from tests.helpers import Mission, auth, distance, offset, wait_for
from tests.test_field import TARGET
from tests.test_sensors import make_sensor


def now() -> str:
    return datetime.now(UTC).isoformat()


def topic(m: Mission, s: dict, kind: str) -> str:  # type: ignore[type-arg]
    return f"{s['topic_prefix']}/{kind}"


def bearing_msg(s: dict, **over) -> str:  # type: ignore[no-untyped-def, type-arg]
    return json.dumps(
        {
            "key": s["api_key"],
            "id": str(uuid.uuid4()),
            "azimuth_true_deg": 90.0,
            "sigma_deg": 8.0,
            "measured_at": now(),
            **over,
        }
    )


async def bearings(client: httpx.AsyncClient, m: Mission) -> list[dict]:  # type: ignore[type-arg]
    return (await client.get(m.url("/bearings"), headers=auth(m.lead_token))).json()


async def test_topic_parsing() -> None:
    m, s = uuid.uuid4(), uuid.uuid4()
    assert parse_topic(f"foxgrid/{m}/{s}/bearing") == (m, s, "bearing")
    for bad in (
        "",
        "foxgrid/x/y/bearing",
        f"other/{m}/{s}/bearing",
        f"foxgrid/{m}/{s}",
        f"foxgrid/{m}/{s}/a/b",
    ):
        assert parse_topic(bad) is None


async def test_bearing_from_a_fixed_station(
    client: httpx.AsyncClient, ingest_ctx: IngestContext
) -> None:
    m = await Mission.create(client)
    lat, lon = offset(-3000, 0)
    s = await make_sensor(client, m, "Nord", lat=lat, lon=lon)
    payload = bearing_msg(s, polarization="v", note="auto", rssi_dbm=-80)
    assert await handle_message(ingest_ctx, topic(m, s, "bearing"), payload) == "ok"

    [b] = await bearings(client, m)
    assert b["source"] == "sensor" and b["participant_id"] != m.lead_id
    assert b["lat"] == lat and b["lon"] == lon  # position of the registered station
    assert b["sigma_deg"] == 8.0 and b["polarization"] == "v" and b["rssi_dbm"] == -80
    snap = (await client.get(m.url("/snapshot"), headers=auth(m.lead_token))).json()
    assert {p["callsign"] for p in snap["participants"]} >= {s["callsign"]}

    # QoS 1 redelivery of the same message changes nothing
    assert await handle_message(ingest_ctx, topic(m, s, "bearing"), payload) == "duplicate"
    assert len(await bearings(client, m)) == 1
    listed = (await client.get(m.url("/sensors"), headers=auth(m.lead_token))).json()
    assert listed[0]["online"] is True and listed[0]["last_seen_at"]


async def test_two_sensors_produce_a_live_estimate(
    client: httpx.AsyncClient, ingest_ctx: IngestContext
) -> None:
    from tests.helpers import azimuth

    m = await Mission.create(client)
    for name, (east, north) in (("West", (-6000, -2000)), ("Sued", (1000, -7000))):
        pos = offset(east, north)
        s = await make_sensor(client, m, name, lat=pos[0], lon=pos[1])
        msg = bearing_msg(s, azimuth_true_deg=round(azimuth(pos, TARGET), 2), sigma_deg=5.0)
        assert await handle_message(ingest_ctx, topic(m, s, "bearing"), msg) == "ok"

    async def poll():  # type: ignore[no-untyped-def]
        r = await client.get(m.url("/estimate?scope=all"), headers=auth(m.lead_token))
        return r.json() if r.status_code == 200 and r.json()["n_bearings"] == 2 else None

    est = await wait_for(poll)
    assert distance((est["lat"], est["lon"]), TARGET) < 150


async def test_message_must_carry_a_valid_key(
    client: httpx.AsyncClient, ingest_ctx: IngestContext
) -> None:
    m = await Mission.create(client)
    other = await Mission.create(client, callsign="DL2OTH")
    s = await make_sensor(client, m, "Nord", lat=48.1, lon=11.5)
    t = topic(m, s, "bearing")
    assert (
        await handle_message(ingest_ctx, t, bearing_msg({**s, "api_key": "fgs_wrong"}))
        == "rejected:auth"
    )
    # right key, wrong mission in the topic
    wrong = f"foxgrid/{other.id}/{s['id']}/bearing"
    assert await handle_message(ingest_ctx, wrong, bearing_msg(s)) == "rejected:auth"
    unknown = f"foxgrid/{m.id}/{uuid.uuid4()}/bearing"
    assert await handle_message(ingest_ctx, unknown, bearing_msg(s)) == "rejected:auth"
    # deactivated sensors are cut off
    await client.patch(
        m.url(f"/sensors/{s['id']}"), json={"is_active": False}, headers=auth(m.lead_token)
    )
    assert await handle_message(ingest_ctx, t, bearing_msg(s)) == "rejected:auth"
    assert await bearings(client, m) == []


async def test_malformed_messages_are_rejected(
    client: httpx.AsyncClient, ingest_ctx: IngestContext
) -> None:
    m = await Mission.create(client)
    s = await make_sensor(client, m, "Nord", lat=48.1, lon=11.5)
    t = topic(m, s, "bearing")
    assert await handle_message(ingest_ctx, "foxgrid/bad", b"{}") == "rejected:topic"
    assert await handle_message(ingest_ctx, t, b"not json") == "rejected:payload"
    assert await handle_message(ingest_ctx, t, b"[1,2]") == "rejected:payload"
    assert await handle_message(ingest_ctx, t, b'{"key": 5}') == "rejected:payload"
    assert await handle_message(ingest_ctx, t, b"{}") == "rejected:payload"
    assert await handle_message(ingest_ctx, t, b"x" * 70_000) == "rejected:too_large"
    for bad in (
        {"azimuth_true_deg": 360},
        {"azimuth_true_deg": -1},
        {"sigma_deg": 0},
        {"sigma_deg": 120},
        {"measured_at": "2026-01-01T10:00:00"},
        {"polarization": "x"},
        {"id": "nope"},
        {"lat": 95},
    ):
        assert await handle_message(ingest_ctx, t, bearing_msg(s, **bad)) == "rejected:invalid", bad
    assert (
        await handle_message(ingest_ctx, topic(m, s, "nonsense"), bearing_msg(s)) == "rejected:kind"
    )
    assert await bearings(client, m) == []


async def test_a_bearing_needs_a_position(
    client: httpx.AsyncClient, ingest_ctx: IngestContext
) -> None:
    m = await Mission.create(client)
    s = await make_sensor(client, m, "Mobil")  # no fixed position registered
    t = topic(m, s, "bearing")
    assert await handle_message(ingest_ctx, t, bearing_msg(s)) == "rejected:no_position"
    assert await handle_message(ingest_ctx, t, bearing_msg(s, lat=48.2, lon=11.6)) == "ok"
    assert (await bearings(client, m))[0]["lat"] == 48.2


async def test_id_clash_between_sensors(
    client: httpx.AsyncClient, ingest_ctx: IngestContext
) -> None:
    m = await Mission.create(client)
    a = await make_sensor(client, m, "Eins", lat=48.1, lon=11.5)
    b = await make_sensor(client, m, "Zwei", lat=48.2, lon=11.5)
    shared = str(uuid.uuid4())
    assert (
        await handle_message(ingest_ctx, topic(m, a, "bearing"), bearing_msg(a, id=shared)) == "ok"
    )
    assert (
        await handle_message(ingest_ctx, topic(m, b, "bearing"), bearing_msg(b, id=shared))
        == "rejected:id_conflict"
    )


async def test_rate_limit_drops_floods(
    client: httpx.AsyncClient, ingest_ctx: IngestContext
) -> None:
    m = await Mission.create(client)
    s = await make_sensor(client, m, "Flut", lat=48.1, lon=11.5)
    ingest_ctx.settings = Settings(**{**ingest_ctx.settings.model_dump(), "mqtt_max_msgs_per_s": 3})
    results = [
        await handle_message(ingest_ctx, topic(m, s, "status"), json.dumps({"key": s["api_key"]}))
        for _ in range(6)
    ]
    assert results[:3] == ["ok"] * 3 and results[3:] == ["rejected:rate_limited"] * 3
    sid = uuid.UUID(s["id"])
    assert ingest_ctx.allow(sid, now=time.monotonic() + 5.0)  # the window slides on


async def test_rssi_samples_flat_and_batched(
    client: httpx.AsyncClient, ingest_ctx: IngestContext
) -> None:
    m = await Mission.create(client)
    s = await make_sensor(client, m, "Pegel", lat=48.1, lon=11.5)
    t = topic(m, s, "rssi")
    flat = json.dumps(
        {"key": s["api_key"], "id": str(uuid.uuid4()), "rssi_dbm": -90.5, "measured_at": now()}
    )
    assert await handle_message(ingest_ctx, t, flat) == "ok"
    ids = [str(uuid.uuid4()) for _ in range(3)]
    batch = json.dumps(
        {
            "key": s["api_key"],
            "samples": [
                {"id": i, "rssi_dbm": -70.0 - n, "attenuation_db": 10, "measured_at": now()}
                for n, i in enumerate(ids)
            ],
        }
    )
    assert await handle_message(ingest_ctx, t, batch) == "ok"
    assert await handle_message(ingest_ctx, t, batch) == "duplicate"
    rows = (await client.get(m.url("/rssi"), headers=auth(m.lead_token))).json()
    assert len(rows) == 4 and all(r["source"] == "sensor" for r in rows)
    assert {r["lat"] for r in rows} == {48.1}
    for bad in ({"key": s["api_key"]}, {"key": s["api_key"], "samples": []}):
        assert await handle_message(ingest_ctx, t, json.dumps(bad)) == "rejected:invalid"
    no_pos = await make_sensor(client, m, "Ohne")
    msg = json.dumps(
        {"key": no_pos["api_key"], "id": str(uuid.uuid4()), "rssi_dbm": -80, "measured_at": now()}
    )
    assert await handle_message(ingest_ctx, topic(m, no_pos, "rssi"), msg) == "rejected:no_position"


async def test_relay_reports_the_interferer_as_a_transmission(
    client: httpx.AsyncClient, ingest_ctx: IngestContext, server: Server
) -> None:
    m = await Mission.create(client, name="Relais DB0XYZ")
    h = auth(m.lead_token)
    relay = await make_sensor(client, m, "Relais", kind="relay")
    station = await make_sensor(client, m, "Station", lat=48.1, lon=11.5)
    token, _ = await m.join("DL4LSN")
    await client.post(
        "/push-tokens", json={"platform": "fcm", "token": "fcm-token-listener"}, headers=auth(token)
    )
    fake: FakePush = ingest_ctx.push_sender  # type: ignore[assignment]

    t = topic(m, relay, "transmission")
    start = json.dumps(
        {"key": relay["api_key"], "event": "start", "note": "Squelch offen ohne CTCSS"}
    )
    assert await handle_message(ingest_ctx, t, start) == "ok"
    assert await handle_message(ingest_ctx, t, start) == "duplicate"  # still on air
    [tx] = (await client.get(m.url("/transmissions"), headers=h)).json()
    assert tx["source"] == "relay" and tx["ended_at"] is None and tx["note"].startswith("Squelch")
    await wait_for(lambda: asyncio.sleep(0, result=bool(fake.calls)))
    assert fake.calls[0][1] == "STÖRER SENDET"

    # a bearing arriving now belongs to this transmission
    assert (
        await handle_message(ingest_ctx, topic(m, station, "bearing"), bearing_msg(station)) == "ok"
    )
    assert (await bearings(client, m))[0]["transmission_id"] == tx["id"]

    stop = json.dumps({"key": relay["api_key"], "event": "stop"})
    assert await handle_message(ingest_ctx, t, stop) == "ok"
    assert await handle_message(ingest_ctx, t, stop) == "duplicate"  # nothing left to stop
    [tx] = (await client.get(m.url("/transmissions"), headers=h)).json()
    assert tx["ended_at"]

    # only relays may report transmissions; bad events are invalid
    assert (
        await handle_message(
            ingest_ctx,
            topic(m, station, "transmission"),
            start.replace(relay["api_key"], station["api_key"]),
        )
        == "rejected:not_relay"
    )
    assert (
        await handle_message(ingest_ctx, t, json.dumps({"key": relay["api_key"], "event": "jump"}))
        == "rejected:invalid"
    )
    explicit = json.dumps(
        {
            "key": relay["api_key"],
            "event": "start",
            "at": (datetime.now(UTC) - timedelta(seconds=30)).isoformat(),
        }
    )
    assert await handle_message(ingest_ctx, t, explicit) == "ok"

    await client.post(m.url("/end"), headers=h)
    assert await handle_message(ingest_ctx, t, start) == "rejected:mission"


async def test_status_heartbeat_marks_a_sensor_online(
    client: httpx.AsyncClient, ingest_ctx: IngestContext
) -> None:
    m = await Mission.create(client)
    s = await make_sensor(client, m, "Herz", lat=48.1, lon=11.5)
    before = (await client.get(m.url("/sensors"), headers=auth(m.lead_token))).json()[0]
    assert before["online"] is False and before["last_seen_at"] is None
    assert (
        await handle_message(ingest_ctx, topic(m, s, "status"), json.dumps({"key": s["api_key"]}))
        == "ok"
    )
    after = (await client.get(m.url("/sensors"), headers=auth(m.lead_token))).json()[0]
    assert after["online"] is True


async def test_end_to_end_through_a_real_broker(
    client: httpx.AsyncClient, settings: Settings, mosquitto: tuple[str, int]
) -> None:
    host, port = mosquitto
    cfg = Settings(**{**settings.model_dump(), "mqtt_host": host, "mqtt_port": port})
    m = await Mission.create(client)
    pos = offset(-3000, 0)
    s = await make_sensor(client, m, "Funk", lat=pos[0], lon=pos[1])
    ingest = asyncio.create_task(run(cfg, reconnect_delay_s=0.2))
    try:
        await asyncio.sleep(1.5)  # let the service connect and subscribe
        msg = bearing_msg(s)
        async with aiomqtt.Client(hostname=host, port=port) as publisher:
            await publisher.publish(topic(m, s, "bearing"), msg, qos=1)
            await publisher.publish(
                topic(m, s, "bearing"), bearing_msg({**s, "api_key": "bad"}), qos=1
            )

        async def arrived():  # type: ignore[no-untyped-def]
            rows = await bearings(client, m)
            return rows if rows else None

        rows = await wait_for(arrived)
        await asyncio.sleep(0.5)
        assert len(await bearings(client, m)) == 1  # the message with the wrong key was dropped
        assert rows[0]["source"] == "sensor"
    finally:
        ingest.cancel()
        await asyncio.gather(ingest, return_exceptions=True)


async def test_the_ingest_service_survives_a_missing_broker(settings: Settings) -> None:
    cfg = Settings(**{**settings.model_dump(), "mqtt_host": "127.0.0.1", "mqtt_port": 1})
    task = asyncio.create_task(run(cfg, reconnect_delay_s=0.1))
    await asyncio.sleep(0.8)
    assert not task.done()  # keeps retrying instead of crashing
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
