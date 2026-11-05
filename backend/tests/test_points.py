"""External bearing points: entered by the lead on behalf of a third party (e.g. BNetzA)."""

from __future__ import annotations

import uuid
from typing import Any

import asyncpg
import httpx

from tests.helpers import Mission, auth, bearing_payload, distance, offset, wait_for
from tests.test_field import STATIONS, TARGET


def point_payload(name: str, pos: tuple[float, float], **extra: Any) -> dict[str, Any]:
    return {"id": str(uuid.uuid4()), "name": name, "lat": pos[0], "lon": pos[1], **extra}


async def add_point(client: httpx.AsyncClient, m: Mission, name: str, pos: tuple[float, float]):
    r = await client.post(
        m.url("/points"), json=point_payload(name, pos), headers=auth(m.lead_token)
    )
    assert r.status_code == 201, r.text
    return r.json()


async def add_external(
    client: httpx.AsyncClient, m: Mission, point: dict[str, Any], target=TARGET, **extra: Any
):
    pos = (point["lat"], point["lon"])
    payload = bearing_payload(pos, target, point_id=point["id"], **extra)
    return await client.post(m.url("/bearings"), json=payload, headers=auth(m.lead_token))


async def n_bearings(client: httpx.AsyncClient, m: Mission) -> int | None:
    r = await client.get(m.url("/estimate?scope=all"), headers=auth(m.lead_token))
    return r.json()["n_bearings"] if r.status_code == 200 else None


async def test_points_are_lead_only_and_idempotent(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    other, _ = await m.join("DL5OWN")
    body = point_payload("BNetzA Muenchen", STATIONS[0])

    denied = await client.post(m.url("/points"), json=body, headers=auth(other))
    assert denied.status_code == 403
    first = await client.post(m.url("/points"), json=body, headers=auth(m.lead_token))
    assert first.status_code == 201
    assert first.json()["use_in_estimate"] is True and first.json()["is_active"] is True
    again = await client.post(m.url("/points"), json=body, headers=auth(m.lead_token))
    assert again.status_code == 200 and again.json()["id"] == body["id"]
    moved = {**body, "lat": body["lat"] + 0.01}
    assert (
        await client.post(m.url("/points"), json=moved, headers=auth(m.lead_token))
    ).status_code == 409
    same_name = point_payload("BNetzA Muenchen", STATIONS[1])
    assert (
        await client.post(m.url("/points"), json=same_name, headers=auth(m.lead_token))
    ).status_code == 409

    listed = await client.get(m.url("/points"), headers=auth(other))
    assert [p["name"] for p in listed.json()] == ["BNetzA Muenchen"]
    snap = await client.get(m.url("/snapshot"), headers=auth(other))
    assert [p["id"] for p in snap.json()["points"]] == [body["id"]]

    # The position cannot be edited, and a participant cannot patch.
    pid = body["id"]
    bad = await client.patch(m.url(f"/points/{pid}"), json={"lat": 1}, headers=auth(m.lead_token))
    assert bad.status_code == 422
    nope = await client.patch(m.url(f"/points/{pid}"), json={"name": "x"}, headers=auth(other))
    assert nope.status_code == 403
    renamed = await client.patch(
        m.url(f"/points/{pid}"), json={"name": "BNetzA"}, headers=auth(m.lead_token)
    )
    assert renamed.status_code == 200 and renamed.json()["name"] == "BNetzA"
    assert (
        await client.delete(m.url(f"/points/{pid}"), headers=auth(m.lead_token))
    ).status_code == 405


async def test_external_bearings_need_lead_and_matching_point(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    other, _ = await m.join("DL5OWN")
    point = await add_point(client, m, "BNetzA", STATIONS[0])
    pos = (point["lat"], point["lon"])

    payload = bearing_payload(pos, TARGET, point_id=point["id"])
    denied = await client.post(m.url("/bearings"), json=payload, headers=auth(other))
    assert denied.status_code == 403

    first = await client.post(m.url("/bearings"), json=payload, headers=auth(m.lead_token))
    assert first.status_code == 201
    assert first.json()["source"] == "external" and first.json()["point_id"] == point["id"]
    again = await client.post(m.url("/bearings"), json=payload, headers=auth(m.lead_token))
    assert again.status_code == 200

    off = bearing_payload(STATIONS[1], TARGET, point_id=point["id"])
    r = await client.post(m.url("/bearings"), json=off, headers=auth(m.lead_token))
    assert r.status_code == 422
    unknown = bearing_payload(pos, TARGET, point_id=str(uuid.uuid4()))
    r = await client.post(m.url("/bearings"), json=unknown, headers=auth(m.lead_token))
    assert r.status_code == 422

    # Ordinary bearings stay `manual`.
    plain = await client.post(
        m.url("/bearings"), json=bearing_payload(STATIONS[1], TARGET), headers=auth(m.lead_token)
    )
    assert plain.json()["source"] == "manual" and plain.json()["point_id"] is None

    await client.patch(
        m.url(f"/points/{point['id']}"), json={"is_active": False}, headers=auth(m.lead_token)
    )
    late = bearing_payload(pos, TARGET, point_id=point["id"])
    r = await client.post(m.url("/bearings"), json=late, headers=auth(m.lead_token))
    assert r.status_code == 422


async def test_external_bearings_feed_the_estimate_and_can_be_switched_off(
    client: httpx.AsyncClient,
) -> None:
    m = await Mission.create(client)
    points = [await add_point(client, m, f"Point {i}", pos) for i, pos in enumerate(STATIONS)]
    for p in points:
        assert (await add_external(client, m, p)).status_code == 201

    async def three() -> int | None:
        n = await n_bearings(client, m)
        return n if n == 3 else None

    await wait_for(three)
    est = await client.get(m.url("/estimate?scope=all"), headers=auth(m.lead_token))
    assert distance((est.json()["lat"], est.json()["lon"]), TARGET) < 1500.0

    off = await client.patch(
        m.url(f"/points/{points[0]['id']}"),
        json={"use_in_estimate": False},
        headers=auth(m.lead_token),
    )
    assert off.status_code == 200 and off.json()["use_in_estimate"] is False

    async def two() -> int | None:
        n = await n_bearings(client, m)
        return n if n == 2 else None

    await wait_for(two)
    # The switched-off bearings stay listed.
    listed = await client.get(m.url("/bearings"), headers=auth(m.lead_token))
    assert len(listed.json()) == 3

    on = await client.patch(
        m.url(f"/points/{points[0]['id']}"),
        json={"use_in_estimate": True},
        headers=auth(m.lead_token),
    )
    assert on.status_code == 200
    await wait_for(three)


async def test_points_are_never_deleted(client: httpx.AsyncClient, settings) -> None:
    m = await Mission.create(client)
    point = await add_point(client, m, "BNetzA", offset(100, 100))
    conn = await asyncpg.connect(settings.database_url.replace("+asyncpg", ""))
    try:
        try:
            await conn.execute("DELETE FROM bearing_points WHERE id = $1", uuid.UUID(point["id"]))
        except asyncpg.PostgresError as exc:
            assert "append-only" in str(exc)
        else:
            raise AssertionError("delete should have been rejected")
    finally:
        await conn.close()


async def test_external_bearings_do_not_trigger_plausibility_flags(
    client: httpx.AsyncClient,
) -> None:
    m = await Mission.create(client)
    far = offset(40_000, 40_000)
    point = await add_point(client, m, "BNetzA", far)
    assert (await add_external(client, m, point)).status_code == 201
    r = await client.get(m.url("/plausibility"), headers=auth(m.lead_token))
    lead_row = next(p for p in r.json() if p["participant_id"] == m.lead_id)
    assert lead_row["bearings"] == 0 and lead_row["flags"] == []


async def test_exports_name_external_points(client: httpx.AsyncClient) -> None:
    from xml.etree import ElementTree as ET

    m = await Mission.create(client)
    h = auth(m.lead_token)
    on = await add_point(client, m, "BNetzA Köln", STATIONS[0])
    off = await add_point(client, m, "Alt & <Neu>", STATIONS[1])
    assert (await add_external(client, m, on, note="per Telefon")).status_code == 201
    assert (await add_external(client, m, off)).status_code == 201
    await client.patch(m.url(f"/points/{off['id']}"), json={"use_in_estimate": False}, headers=h)

    gpx = ET.fromstring((await client.get(m.url("/export.gpx"), headers=h)).content)
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    names = [n.text or "" for n in gpx.iterfind(".//g:wpt/g:name", ns)]
    assert "Peilpunkt BNetzA Köln" in names
    assert any(n.startswith("extern: BNetzA Köln") for n in names)
    assert any("extern: Alt & <Neu>" in n and "[nicht in Schätzung]" in n for n in names)

    kml = ET.fromstring((await client.get(m.url("/export.kml"), headers=h)).content)
    k = {"k": "http://www.opengis.net/kml/2.2"}
    knames = [n.text or "" for n in kml.iterfind(".//k:Placemark/k:name", k)]
    assert "BNetzA Köln" in knames  # point folder
    assert any(n.startswith("extern: BNetzA Köln") for n in knames)

    js = (await client.get(m.url("/export.json"), headers=h)).json()
    assert {p["name"] for p in js["points"]} == {"BNetzA Köln", "Alt & <Neu>"}
    assert sum(1 for b in js["bearings"] if b["point_id"] is not None) == 2

    pdf = await client.get(m.url("/export.pdf"), headers=h)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
