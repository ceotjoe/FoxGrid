"""Managing many sensor bearings (ADR 0010, step 5): filters, paging and the bulk endpoint."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.services.ingest import IngestContext
from tests.helpers import Mission, auth, bearing_payload, wait_for
from tests.test_field import STATIONS, TARGET
from tests.test_interferers import add_interferer
from tests.test_manual_gate import send, start, stop
from tests.test_sensors import make_sensor


async def drive(
    client: httpx.AsyncClient, ctx: IngestContext, m: Mission, n: int = 6
) -> tuple[dict[str, Any], list[str], datetime]:
    """A gated Kraken with ``n`` bearings 10 s apart; the middle third inside a transmission."""
    s = await make_sensor(client, m, "Kraken Auto")
    t0 = datetime.now(UTC) - timedelta(seconds=10 * n + 30)
    ids = []
    for i in range(n):
        if i == n // 3:
            await start(client, m, t0 + timedelta(seconds=10 * i - 6))
        if i == 2 * n // 3:
            await stop(client, m, t0 + timedelta(seconds=10 * i - 9))  # beyond the slack
        ids.append(await send(ctx, m, s, t0 + timedelta(seconds=10 * i)))
    return s, ids, t0


async def listed(client: httpx.AsyncClient, m: Mission, **params: Any) -> httpx.Response:
    r = await client.get(m.url("/bearings"), params=params, headers=auth(m.lead_token))
    assert r.status_code == 200, r.text
    return r


def ids_of(r: httpx.Response) -> list[str]:
    return [b["id"] for b in r.json()]


async def test_filters(client: httpx.AsyncClient, ingest_ctx: IngestContext) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    hand = await client.post(
        m.url("/bearings"), json=bearing_payload(STATIONS[0], TARGET), headers=h
    )
    s, ids, t0 = await drive(client, ingest_ctx, m)

    assert ids_of(await listed(client, m, sensor=s["id"])) == ids
    assert ids_of(await listed(client, m, sensors_only=True)) == ids
    assert hand.json()["id"] in ids_of(await listed(client, m))
    assert ids_of(await listed(client, m, state="counted", sensors_only=True)) == ids[2:4]
    assert ids_of(await listed(client, m, state="stored")) == ids[:2] + ids[4:]
    assert (
        ids_of(
            await listed(
                client,
                m,
                sensor=s["id"],
                **{"from": (t0 + timedelta(seconds=15)).isoformat()},
                to=(t0 + timedelta(seconds=35)).isoformat(),
            )
        )
        == ids[2:4]
    )
    other = (await add_interferer(client, m, "Störer B")).json()
    assert ids_of(await listed(client, m, interferer=other["id"])) == []
    assert (
        await client.get(m.url("/bearings"), params={"state": "x"}, headers=h)
    ).status_code == 422


async def test_paging(client: httpx.AsyncClient, ingest_ctx: IngestContext) -> None:
    m = await Mission.create(client)
    _, ids, _ = await drive(client, ingest_ctx, m, n=7)
    seen: list[str] = []
    cursor = None
    while True:
        params: dict[str, Any] = {"limit": 3, "sensors_only": True}
        if cursor:
            params["cursor"] = cursor
        r = await listed(client, m, **params)
        assert r.headers["X-Total-Count"] == "7"
        seen += ids_of(r)
        cursor = r.headers.get("X-Next-Cursor")
        if cursor is None:
            break
    assert seen == ids
    bad = await client.get(
        m.url("/bearings"), params={"limit": 3, "cursor": "nonsense"}, headers=auth(m.lead_token)
    )
    assert bad.status_code == 422


async def test_bulk_assigns_and_gates_with_one_revision_each(
    client: httpx.AsyncClient, ingest_ctx: IngestContext
) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    for station in STATIONS:
        await client.post(m.url("/bearings"), json=bearing_payload(station, TARGET), headers=h)
    _, ids, _ = await drive(client, ingest_ctx, m)
    b = (await add_interferer(client, m, "Störer B")).json()

    r = await client.post(
        m.url("/bearings/bulk"),
        json={"ids": ids[:2], "interferer_id": b["id"], "gate_override": True},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"updated": 2, "unchanged": 0}
    rows = {x["id"]: x for x in (await listed(client, m, sensors_only=True)).json()}
    assert all(rows[i]["interferer_id"] == b["id"] and rows[i]["gate_override"] for i in ids[:2])
    revs = (await client.get(m.url(f"/bearings/{ids[0]}/revisions"), headers=h)).json()
    assert len(revs) == 1 and set(revs[0]["changes"]) == {"interferer_id", "gate_override"}

    # the same again changes nothing; "automatic" clears the decision
    r = await client.post(
        m.url("/bearings/bulk"), json={"ids": ids[:2], "gate_override": True}, headers=h
    )
    assert r.json() == {"updated": 0, "unchanged": 2}
    r = await client.post(
        m.url("/bearings/bulk"), json={"ids": ids, "gate_override": None}, headers=h
    )
    assert r.json() == {"updated": 2, "unchanged": 4}

    # counting everything by hand reaches the estimate of the default interferer: 3 + 6
    r = await client.post(
        m.url("/bearings/bulk"),
        json={"ids": ids, "gate_override": True, "interferer_id": None} | {},
        headers=h,
    )
    assert r.status_code == 422  # an interferer cannot be cleared
    default = next(
        i["id"]
        for i in (await client.get(m.url("/interferers"), headers=h)).json()
        if i["name"] == "Störer 1"
    )
    r = await client.post(
        m.url("/bearings/bulk"),
        json={"ids": ids, "gate_override": True, "interferer_id": default},
        headers=h,
    )
    assert r.status_code == 200

    async def counted() -> Any:
        e = await client.get(m.url("/estimate?scope=all"), headers=h)
        return e.json() if e.status_code == 200 and e.json()["n_bearings"] == 9 else None

    await wait_for(counted)


async def test_bulk_is_all_or_nothing(client: httpx.AsyncClient, ingest_ctx: IngestContext) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    _, ids, _ = await drive(client, ingest_ctx, m, n=3)
    hand = (
        await client.post(m.url("/bearings"), json=bearing_payload(STATIONS[0], TARGET), headers=h)
    ).json()["id"]

    def bulk(body: dict[str, Any], token: str | None = None) -> Any:
        return client.post(m.url("/bearings/bulk"), json=body, headers=auth(token or m.lead_token))

    # a hand bearing has no gate decision: nothing changes
    assert (await bulk({"ids": [*ids, hand], "gate_override": True})).status_code == 422
    assert all(x["gate_override"] is None for x in (await listed(client, m)).json())
    # unknown or foreign ids
    other = await Mission.create(client)
    _, foreign, _ = await drive(client, ingest_ctx, other, n=1)
    assert (await bulk({"ids": [ids[0], foreign[0]], "gate_override": True})).status_code == 404
    assert (await bulk({"ids": [str(uuid.uuid4())], "gate_override": True})).status_code == 404
    # malformed requests
    for body in (
        {"ids": [], "gate_override": True},
        {"ids": [ids[0], ids[0]], "gate_override": True},
        {"ids": [str(uuid.uuid4()) for _ in range(501)], "gate_override": True},
        {"ids": ids},
        {"ids": ids, "is_active": False},
    ):
        assert (await bulk(body)).status_code == 422, body
    # a plain bearer may neither gate nor reassign the station's bearings
    token, _ = await m.join("DL2BBB")
    assert (await bulk({"ids": ids, "gate_override": True}, token)).status_code == 403
    b = (await add_interferer(client, m, "B")).json()
    assert (await bulk({"ids": ids, "interferer_id": b["id"]}, token)).status_code == 403
