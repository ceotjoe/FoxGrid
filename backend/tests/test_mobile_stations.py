"""Mobile stations (ADR 0010): position in the heartbeat, sensor weight, default interferer."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from foxgrid_engine import EngineParams

from app.models import Bearing
from app.models import Mission as MissionModel
from app.services.ingest import IngestContext, handle_message
from app.services.recompute import (
    SENSOR_OUTLIER_FRACTION,
    SensorTuning,
    _input_hash,
    _to_engine,
    engine_params_for,
)
from tests.helpers import Mission, auth, azimuth, bearing_payload, distance, offset, wait_for
from tests.test_field import STATIONS, TARGET
from tests.test_ingest import bearing_msg, bearings, now, topic
from tests.test_interferers import add_interferer
from tests.test_sensors import make_sensor


async def participant_id(client: httpx.AsyncClient, m: Mission, callsign: str) -> str:
    snap = (await client.get(m.url("/snapshot"), headers=auth(m.lead_token))).json()
    [p] = [p for p in snap["participants"] if p["callsign"] == callsign]
    return str(p["id"])


async def status(ctx: IngestContext, m: Mission, s: dict[str, Any], **fields: Any) -> str:
    return await handle_message(
        ctx, topic(m, s, "status"), json.dumps({"key": s["api_key"], **fields})
    )


async def test_heartbeat_position_becomes_the_sensor_track(
    client: httpx.AsyncClient, ingest_ctx: IngestContext
) -> None:
    m = await Mission.create(client)
    s = await make_sensor(client, m, "Kraken Auto")  # mobile: no fixed position
    pid = await participant_id(client, m, s["callsign"])
    fix_time = datetime.now(UTC) - timedelta(seconds=2)

    assert await status(ingest_ctx, m, s) == "ok"  # a plain heartbeat stores nothing
    assert (
        await status(
            ingest_ctx, m, s, lat=48.1, lon=11.5, speed=12.5, heading=91.0, at=fix_time.isoformat()
        )
        == "ok"
    )
    assert await status(ingest_ctx, m, s, lat=48.101, lon=11.5) == "ok"

    track = (
        await client.get(
            m.url("/positions"), params={"participant": pid}, headers=auth(m.lead_token)
        )
    ).json()
    assert len(track) == 2
    first = track[0]
    assert first["lat"] == 48.1 and first["speed_mps"] == 12.5 and first["heading_deg"] == 91.0
    assert datetime.fromisoformat(first["recorded_at"]) == fix_time
    snap = (await client.get(m.url("/snapshot"), headers=auth(m.lead_token))).json()
    assert any(p["participant_id"] == pid for p in snap["positions"])
    listed = (await client.get(m.url("/sensors"), headers=auth(m.lead_token))).json()
    assert listed[0]["online"] is True


@pytest.mark.parametrize(
    "fields",
    [
        {"lat": 48.1},  # lon missing
        {"lon": 11.5},
        {"lat": 48.1, "lon": 11.5, "heading": 360},
        {"lat": 48.1, "lon": 11.5, "speed": -1},
        {"lat": 91, "lon": 11.5},
        {"lat": 48.1, "lon": 11.5, "at": "2026-11-26T12:00:00"},  # without time zone
    ],
)
async def test_invalid_heartbeat_positions_are_rejected(
    client: httpx.AsyncClient, ingest_ctx: IngestContext, fields: dict[str, Any]
) -> None:
    m = await Mission.create(client)
    s = await make_sensor(client, m, "Kraken Auto")
    assert await status(ingest_ctx, m, s, **fields) == "rejected:invalid"


async def test_sensor_weight_and_default_interferer_via_api(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    b = (await add_interferer(client, m, "Störer B")).json()

    s = await make_sensor(client, m, "Kraken Auto", weight=0.5, interferer_id=b["id"])
    assert s["weight"] == 0.5 and s["interferer_id"] == b["id"]
    plain = await make_sensor(client, m, "Nord", lat=48.1, lon=11.5)
    assert plain["weight"] == 1.0 and plain["interferer_id"] is None

    url = m.url(f"/sensors/{s['id']}")
    changed = await client.patch(url, json={"weight": 2.0, "interferer_id": None}, headers=h)
    assert changed.status_code == 200, changed.text
    assert changed.json()["weight"] == 2.0 and changed.json()["interferer_id"] is None

    for body in (
        {"weight": 2.5},
        {"weight": -0.1},
        {"weight": None},
        {"is_active": None},
        {"interferer_id": str(uuid.uuid4())},
    ):
        r = await client.patch(url, json=body, headers=h)
        assert r.status_code == 422, (body, r.text)
    bad = await client.post(
        m.url("/sensors"), json={"name": "X1", "interferer_id": str(uuid.uuid4())}, headers=h
    )
    assert bad.status_code == 422

    other = await Mission.create(client)
    foreign = (await add_interferer(client, other, "Fremd")).json()
    r = await client.patch(url, json={"interferer_id": foreign["id"]}, headers=h)
    assert r.status_code == 422


async def test_interferer_resolution_for_sensor_data(
    client: httpx.AsyncClient, ingest_ctx: IngestContext
) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    b = (await add_interferer(client, m, "Störer B")).json()
    c = (await add_interferer(client, m, "Störer C")).json()
    s = await make_sensor(client, m, "Kraken Auto", interferer_id=b["id"])
    t = topic(m, s, "bearing")
    pos = {"lat": 48.1, "lon": 11.5}

    first = bearing_msg(s, **pos)
    assert await handle_message(ingest_ctx, t, first) == "ok"  # sensor default
    named = bearing_msg(s, interferer=c["id"], **pos)
    assert await handle_message(ingest_ctx, t, named) == "ok"  # the message wins
    unknown = bearing_msg(s, interferer=str(uuid.uuid4()), **pos)
    assert await handle_message(ingest_ctx, t, unknown) == "rejected:interferer"

    rssi = json.dumps(
        {
            "key": s["api_key"],
            "interferer": c["id"],
            "samples": [{"id": str(uuid.uuid4()), "rssi_dbm": -70, "measured_at": now(), **pos}],
        }
    )
    assert await handle_message(ingest_ctx, topic(m, s, "rssi"), rssi) == "ok"
    [reading] = (await client.get(m.url("/rssi"), headers=h)).json()
    assert reading["interferer_id"] == c["id"]

    # a deactivated default is skipped: the station keeps reporting for the mission default
    off = await client.patch(m.url(f"/interferers/{b['id']}"), json={"is_active": False}, headers=h)
    assert off.status_code == 200, off.text
    assert await handle_message(ingest_ctx, t, bearing_msg(s, **pos)) == "ok"

    by_id = {x["id"]: x["interferer_id"] for x in await bearings(client, m)}
    default_id = next(
        i["id"]
        for i in (await client.get(m.url("/interferers"), headers=h)).json()
        if i["name"] == "Störer 1"
    )
    assert by_id[json.loads(first)["id"]] == b["id"]
    assert by_id[json.loads(named)["id"]] == c["id"]
    assert sorted(by_id.values()).count(default_id) == 1


async def test_merging_interferers_moves_the_sensor_default(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    a = (await add_interferer(client, m, "A")).json()
    b = (await add_interferer(client, m, "B")).json()
    s = await make_sensor(client, m, "Kraken Auto", interferer_id=b["id"])
    merged = await client.post(
        m.url(f"/interferers/{b['id']}/merge"), json={"into": a["id"]}, headers=h
    )
    assert merged.status_code == 200, merged.text
    [listed] = (await client.get(m.url("/sensors"), headers=h)).json()
    assert listed["id"] == s["id"] and listed["interferer_id"] == a["id"]


async def test_sensor_weight_and_grouping_reach_the_engine(
    client: httpx.AsyncClient, ingest_ctx: IngestContext
) -> None:
    m = await Mission.create(
        client, engine_params={"sensor_outlier_fraction": 0.25, "cluster_radius_m": 60}
    )
    h = auth(m.lead_token)
    for station in STATIONS:
        r = await client.post(m.url("/bearings"), json=bearing_payload(station, TARGET), headers=h)
        assert r.status_code == 201
    s = await make_sensor(client, m, "Kraken Auto", gated=False)  # count without transmissions
    spot = offset(-2000, 6000)
    biased = (azimuth(spot, TARGET) + 25.0) % 360.0
    for i in range(20):  # a long stop with a consistent multipath error
        msg = bearing_msg(
            s, lat=spot[0], lon=spot[1] + i * 1e-6, azimuth_true_deg=round(biased, 2), sigma_deg=6.0
        )
        assert await handle_message(ingest_ctx, topic(m, s, "bearing"), msg) == "ok"

    async def estimate_with(pred: Any) -> Any:
        async def poll() -> Any:
            r = await client.get(m.url("/estimate?scope=all"), headers=h)
            if r.status_code != 200:
                return None
            e = r.json()
            return e if pred(e) and e["n_bearings"] == 23 else None

        return await wait_for(poll)

    pulled = await estimate_with(lambda e: distance((e["lat"], e["lon"]), TARGET) > 100)
    # weight 0 removes the station from the estimate; the change triggers a recompute
    r = await client.patch(m.url(f"/sensors/{s['id']}"), json={"weight": 0}, headers=h)
    assert r.status_code == 200
    clean = await estimate_with(lambda e: distance((e["lat"], e["lon"]), TARGET) < 30)
    assert distance((clean["lat"], clean["lon"]), TARGET) < distance(
        (pulled["lat"], pulled["lon"]), TARGET
    )


def test_sensor_bearings_carry_group_weight_and_epsilon() -> None:
    sensor_id = uuid.uuid4()
    common = {
        "lat": 48.1,
        "lon": 11.5,
        "azimuth_true_deg": 90.0,
        "sigma_deg": 8.0,
        "measured_at": datetime.now(UTC),
    }
    hand = Bearing(id=uuid.uuid4(), **common)
    auto = Bearing(id=uuid.uuid4(), sensor_id=sensor_id, **common)
    tuning = SensorTuning(weights={sensor_id: 0.5}, outlier_fraction=0.3)

    e_hand, e_auto = _to_engine(hand, tuning), _to_engine(auto, tuning)
    assert (e_hand.group, e_hand.weight, e_hand.outlier_fraction) == (None, 1.0, None)
    assert (e_auto.group, e_auto.weight, e_auto.outlier_fraction) == (str(sensor_id), 0.5, 0.3)
    assert _to_engine(auto).outlier_fraction == SENSOR_OUTLIER_FRACTION

    params = EngineParams()
    base = _input_hash([hand, auto], params, tuning=tuning)
    assert base == _input_hash([hand, auto], params, tuning=tuning)
    assert base != _input_hash(
        [hand, auto], params, tuning=SensorTuning({sensor_id: 1.0}, 0.3)
    )  # a new weight must trigger a new estimate
    assert base != _input_hash([hand, auto], EngineParams(cluster_radius_m=10), tuning=tuning)


def test_engine_params_keep_sensor_settings_apart() -> None:
    mission = MissionModel(engine_params={"sensor_outlier_fraction": 0.3, "cluster_radius_m": 40})
    params = engine_params_for(mission, 0.0)
    assert params.cluster_radius_m == 40
    assert not hasattr(params, "sensor_outlier_fraction")
