"""Manual gate (ADR 0010): gated sensors count only while the interferer transmits."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from app.services.ingest import IngestContext, handle_message
from tests.helpers import Mission, auth, bearing_payload, wait_for
from tests.test_field import STATIONS, TARGET
from tests.test_ingest import bearing_msg, topic
from tests.test_sensors import make_sensor

POS = {"lat": 48.1, "lon": 11.5}


def iso(t: datetime) -> str:
    return t.isoformat()


async def send(
    ctx: IngestContext,
    m: Mission,
    s: dict[str, Any],
    at: datetime,
    span_s: float = 3.0,
    **over: Any,
) -> str:
    """A sensor bearing whose averaging window ends at ``at``; returns its id."""
    msg = bearing_msg(
        s,
        measured_at=iso(at - timedelta(seconds=span_s / 2)),
        window_start=iso(at - timedelta(seconds=span_s)),
        window_end=iso(at),
        **{**POS, **over},
    )
    assert await handle_message(ctx, topic(m, s, "bearing"), msg) == "ok"
    return str(json.loads(msg)["id"])


async def states(client: httpx.AsyncClient, m: Mission) -> dict[str, tuple[Any, Any]]:
    rows = (await client.get(m.url("/bearings"), headers=auth(m.lead_token))).json()
    return {b["id"]: (b["gate_state"], b["gate_override"]) for b in rows}


async def start(client: httpx.AsyncClient, m: Mission, at: datetime | None = None) -> Any:
    body = {"at": iso(at)} if at else {}
    r = await client.post(m.url("/transmissions/start"), json=body, headers=auth(m.lead_token))
    assert r.status_code == 201, r.text
    return r.json()


async def stop(client: httpx.AsyncClient, m: Mission, at: datetime | None = None) -> Any:
    body = {"at": iso(at)} if at else {}
    r = await client.post(m.url("/transmissions/stop"), json=body, headers=auth(m.lead_token))
    assert r.status_code == 200, r.text
    return r.json()


async def test_vehicles_are_gated_by_default(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    assert (await make_sensor(client, m, "Kraken Auto"))["gated"] is True
    assert (await make_sensor(client, m, "Nord", lat=48.1, lon=11.5))["gated"] is False
    assert (await make_sensor(client, m, "Relais", kind="relay"))["gated"] is False
    assert (await make_sensor(client, m, "Kraken 2", gated=False))["gated"] is False
    assert (await make_sensor(client, m, "Fest", lat=48.1, lon=11.5, gated=True))["gated"] is True


async def test_only_bearings_inside_a_transmission_count(
    client: httpx.AsyncClient, ingest_ctx: IngestContext
) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    for station in STATIONS:
        r = await client.post(m.url("/bearings"), json=bearing_payload(station, TARGET), headers=h)
        assert r.status_code == 201
    s = await make_sensor(client, m, "Kraken Auto")
    t0 = datetime.now(UTC)

    before = await send(ingest_ctx, m, s, t0 - timedelta(seconds=60))  # a repeater user
    await start(client, m, t0 - timedelta(seconds=40))
    inside = await send(ingest_ctx, m, s, t0 - timedelta(seconds=30))
    await stop(client, m, t0 - timedelta(seconds=20))
    after = await send(ingest_ctx, m, s, t0 - timedelta(seconds=10))
    # ends inside, but the window starts 6 s before the transmission (slack 5 s): outside
    straddling = await send(ingest_ctx, m, s, t0 - timedelta(seconds=36), span_s=10.0)

    st = await states(client, m)
    assert st[before] == ("outside", None)
    assert st[inside] == ("inside", None)
    assert st[after] == ("outside", None)
    assert st[straddling] == ("outside", None)

    async def counted() -> Any:
        r = await client.get(m.url("/estimate?scope=all"), headers=h)
        return r.json() if r.status_code == 200 and r.json()["n_bearings"] == 4 else None

    await wait_for(counted)  # three hand bearings and the one inside
    q = await client.get(m.url("/estimate/query"), headers=h)
    assert q.status_code == 200 and q.json()["n_bearings"] == 4


async def test_backdated_start_counts_bearings_that_arrived_earlier(
    client: httpx.AsyncClient, ingest_ctx: IngestContext
) -> None:
    m = await Mission.create(client)
    s = await make_sensor(client, m, "Kraken Auto")
    t0 = datetime.now(UTC)
    early = await send(ingest_ctx, m, s, t0 - timedelta(seconds=2))
    assert (await states(client, m))[early] == ("outside", None)
    # the button was pressed late: "seit 10 s"
    tx = await start(client, m, t0 - timedelta(seconds=12))
    assert datetime.fromisoformat(tx["started_at"]) == t0 - timedelta(seconds=12)
    assert (await states(client, m))[early] == ("inside", None)
    # a stop backdated to the start (pressed by mistake) moves it out again
    ended = await stop(client, m, t0 - timedelta(seconds=20))
    assert ended["ended_at"] == tx["started_at"]  # a stop never precedes the start
    assert (await states(client, m))[early] == ("outside", None)


async def test_backdated_start_never_overlaps_the_previous_transmission(
    client: httpx.AsyncClient,
) -> None:
    m = await Mission.create(client)
    t0 = datetime.now(UTC)
    await start(client, m, t0 - timedelta(seconds=60))
    ended = await stop(client, m, t0 - timedelta(seconds=20))
    second = await start(client, m, t0 - timedelta(seconds=30))
    assert second["started_at"] == ended["ended_at"]


async def test_a_manual_decision_wins_and_survives_re_evaluation(
    client: httpx.AsyncClient, ingest_ctx: IngestContext
) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    s = await make_sensor(client, m, "Kraken Auto")
    t0 = datetime.now(UTC)
    forgotten = await send(ingest_ctx, m, s, t0 - timedelta(seconds=30))
    user = await send(ingest_ctx, m, s, t0 - timedelta(seconds=5))

    r = await client.patch(m.url(f"/bearings/{forgotten}"), json={"gate_override": True}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["gate_state"] == "outside" and r.json()["gate_override"] is True
    # a transmission covering the user over: the automatic state follows, the decision stays
    await start(client, m, t0 - timedelta(seconds=10))
    r = await client.patch(m.url(f"/bearings/{user}"), json={"gate_override": False}, headers=h)
    assert r.status_code == 200
    await stop(client, m)
    st = await states(client, m)
    assert st[forgotten] == ("outside", True)
    assert st[user] == ("inside", False)

    # back to automatic, with every step as a revision
    r = await client.patch(m.url(f"/bearings/{user}"), json={"gate_override": None}, headers=h)
    assert r.status_code == 200 and r.json()["gate_override"] is None
    revs = (await client.get(m.url(f"/bearings/{user}/revisions"), headers=h)).json()
    assert [x["changes"]["gate_override"] for x in revs] == [
        {"from": None, "to": False},
        {"from": False, "to": None},
    ]


async def test_gate_decision_needs_flag_permission_and_a_sensor_bearing(
    client: httpx.AsyncClient, ingest_ctx: IngestContext
) -> None:
    m = await Mission.create(client)
    s = await make_sensor(client, m, "Kraken Auto")
    sensor_bearing = await send(ingest_ctx, m, s, datetime.now(UTC))
    bearer, _ = await m.join("DL2BBB")
    r = await client.patch(
        m.url(f"/bearings/{sensor_bearing}"), json={"gate_override": True}, headers=auth(bearer)
    )
    assert r.status_code == 403
    own = await client.post(
        m.url("/bearings"), json=bearing_payload(STATIONS[0], TARGET), headers=auth(bearer)
    )
    r = await client.patch(
        m.url(f"/bearings/{own.json()['id']}"), json={"gate_override": False}, headers=auth(bearer)
    )
    assert r.status_code == 422


async def test_switching_the_gate_off_counts_everything(
    client: httpx.AsyncClient, ingest_ctx: IngestContext
) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    s = await make_sensor(client, m, "Kraken Auto")
    b = await send(ingest_ctx, m, s, datetime.now(UTC))
    assert (await states(client, m))[b] == ("outside", None)
    r = await client.patch(m.url(f"/sensors/{s['id']}"), json={"gated": False}, headers=h)
    assert r.status_code == 200 and r.json()["gated"] is False
    assert (await states(client, m))[b] == (None, None)
    r = await client.patch(m.url(f"/sensors/{s['id']}"), json={"gated": True}, headers=h)
    assert (await states(client, m))[b] == ("outside", None)
    r = await client.patch(m.url(f"/sensors/{s['id']}"), json={"gated": None}, headers=h)
    assert r.status_code == 422


async def test_sensor_bearings_without_a_window_use_the_measurement_time(
    client: httpx.AsyncClient, ingest_ctx: IngestContext
) -> None:
    m = await Mission.create(client)
    s = await make_sensor(client, m, "Kraken Auto")
    await start(client, m)
    msg = bearing_msg(s, **POS)
    assert await handle_message(ingest_ctx, topic(m, s, "bearing"), msg) == "ok"
    assert (await states(client, m))[json.loads(msg)["id"]] == ("inside", None)


@pytest.mark.parametrize(
    "window",
    [
        {"window_start": "2026-11-26T12:00:00+00:00"},  # end missing
        {  # end before start
            "window_start": "2026-11-26T12:00:05+00:00",
            "window_end": "2026-11-26T12:00:00+00:00",
        },
        {  # does not contain measured_at
            "window_start": "2026-11-26T11:00:00+00:00",
            "window_end": "2026-11-26T11:00:03+00:00",
        },
        {  # longer than 10 min
            "window_start": "2026-11-26T11:40:00+00:00",
            "window_end": "2026-11-26T12:00:05+00:00",
        },
    ],
)
async def test_invalid_windows_are_rejected(
    client: httpx.AsyncClient, ingest_ctx: IngestContext, window: dict[str, str]
) -> None:
    m = await Mission.create(client)
    s = await make_sensor(client, m, "Kraken Auto")
    msg = bearing_msg(s, measured_at="2026-11-26T12:00:01+00:00", **POS, **window)
    assert await handle_message(ingest_ctx, topic(m, s, "bearing"), msg) == "rejected:invalid"
