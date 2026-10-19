from __future__ import annotations

import httpx
import pytest

from tests.helpers import Mission, auth, bearing_payload, device_secret, offset
from tests.test_field import STATIONS, TARGET


async def make_sensor(
    client: httpx.AsyncClient, m: Mission, name: str = "Station Nord", **extra
) -> dict:  # type: ignore[type-arg]
    r = await client.post(
        m.url("/sensors"), json={"name": name, **extra}, headers=auth(m.lead_token)
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_sensor_lifecycle(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    lat, lon = offset(-3000, 500)
    s = await make_sensor(client, m, lat=lat, lon=lon)
    assert s["api_key"].startswith("fgs_") and len(s["api_key"]) > 20
    assert s["callsign"] == "STATIONNORD"
    assert s["topic_prefix"] == f"foxgrid/{m.id}/{s['id']}"
    assert s["online"] is False and s["kind"] == "station"

    listed = (await client.get(m.url("/sensors"), headers=auth(m.lead_token))).json()
    assert [x["id"] for x in listed] == [s["id"]]
    assert "api_key" not in listed[0]  # the key is only shown once

    # the sensor is a (virtual) participant and a fixed station shows up on the map
    snap = (await client.get(m.url("/snapshot"), headers=auth(m.lead_token))).json()
    assert "STATIONNORD" in {p["callsign"] for p in snap["participants"]}
    assert any(p["lat"] == pytest.approx(lat) for p in snap["positions"])

    moved = await client.patch(
        m.url(f"/sensors/{s['id']}"),
        json={"lat": lat + 0.01, "lon": lon},
        headers=auth(m.lead_token),
    )
    assert moved.json()["lat"] == pytest.approx(lat + 0.01)
    off = await client.patch(
        m.url(f"/sensors/{s['id']}"), json={"is_active": False}, headers=auth(m.lead_token)
    )
    assert off.json()["is_active"] is False and off.json()["online"] is False
    assert (
        await client.patch(
            m.url("/sensors/00000000-0000-0000-0000-000000000000"),
            json={},
            headers=auth(m.lead_token),
        )
    ).status_code == 404


async def test_only_leads_manage_sensors_and_names_are_unique(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    other, _ = await m.join("DL5SEN")
    denied = await client.post(m.url("/sensors"), json={"name": "Hack"}, headers=auth(other))
    assert denied.status_code == 403
    await make_sensor(client, m, "Relais Hügel", kind="relay")
    dup = await client.post(
        m.url("/sensors"), json={"name": "Relais Hügel"}, headers=auth(m.lead_token)
    )
    assert dup.status_code == 409
    # members may look, but not patch
    assert (await client.get(m.url("/sensors"), headers=auth(other))).status_code == 200
    assert (await client.patch(m.url("/sensors/x"), json={}, headers=auth(other))).status_code in (
        403,
        422,
    )


async def test_callsigns_of_sensors_cannot_be_claimed_by_humans(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    s = await make_sensor(client, m, "Nord")
    r = await client.post(
        "/join",
        json={
            "invite_token": m.invite,
            "callsign": s["callsign"],
            "device_secret": device_secret(s["callsign"]),
        },
    )
    assert r.status_code == 403
    # a clash with an existing human callsign gets a numbered callsign for the sensor
    s2 = await make_sensor(client, m, "dl1abc")
    assert s2["callsign"] == "DL1ABC2"


async def test_callsign_generation_edge_cases(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    assert (await make_sensor(client, m, "!!"))["callsign"] == "SENSOR"
    assert (await make_sensor(client, m, "ab"))["callsign"] == "AB0"
    assert len((await make_sensor(client, m, "x" * 40))["callsign"]) == 12


async def test_suggestions_for_a_weak_geometry(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    assert (await client.get(m.url("/suggestions"), headers=h)).status_code == 404
    # two bearers on the same side: both rays run roughly east
    for st in (offset(-4000, -300), offset(-4500, 500)):
        await client.post(
            m.url("/bearings"), json=bearing_payload(st, offset(0, 0), 5.0), headers=h
        )
    r = await client.get(m.url("/suggestions"), headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["n_bearings"] == 2 and body["typical_sigma_deg"] == 10.0
    sugg = body["suggestions"]
    assert len(sugg) == 3
    reductions = [x["expected_reduction"] for x in sugg]
    assert reductions == sorted(reductions, reverse=True) and reductions[0] > 0.5
    # best spots lie across the existing rays: north or south of the emitter
    assert min(abs(sugg[0]["azimuth_to_target_deg"] - a) for a in (0, 180, 360)) < 45

    one = await client.get(m.url("/suggestions?count=1&sigma_deg=5&scope=current"), headers=h)
    # no transmission: "current" holds the bearings not tied to one, as in recompute
    assert one.status_code == 200 and one.json()["n_bearings"] == 2
    only = await client.get(m.url("/suggestions?count=1&sigma_deg=5"), headers=h)
    assert len(only.json()["suggestions"]) == 1 and only.json()["typical_sigma_deg"] == 5.0
    for bad in ("count=0", "sigma_deg=0", "sigma_deg=90", "scope=nope"):
        assert (await client.get(m.url(f"/suggestions?{bad}"), headers=h)).status_code == 422


async def test_suggestions_respect_the_search_area(client: httpx.AsyncClient) -> None:
    # a search area covering only the part south of the emitter
    south = [offset(-9000, -12000), offset(9000, -12000), offset(9000, -300), offset(-9000, -300)]
    m = await Mission.create(client, search_area=[[lon, lat] for lat, lon in south])
    h = auth(m.lead_token)
    for st in (offset(-4000, -3000), offset(-4500, -2500)):
        await client.post(
            m.url("/bearings"), json=bearing_payload(st, offset(0, -1500), 5.0), headers=h
        )
    r = await client.get(m.url("/suggestions"), headers=h)
    area = (await client.get(m.url(""), headers=h)).json()["search_area"]
    lons = [p[0] for p in area]
    lats = [p[1] for p in area]
    for s in r.json()["suggestions"]:
        assert min(lons) <= s["lon"] <= max(lons) and min(lats) <= s["lat"] <= max(lats)


async def test_suggestions_ignore_outliers(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    ids = []
    for st in STATIONS:
        r = await client.post(m.url("/bearings"), json=bearing_payload(st, TARGET), headers=h)
        ids.append(r.json()["id"])
    for bid in ids[1:]:
        await client.patch(m.url(f"/bearings/{bid}"), json={"is_outlier": True}, headers=h)
    r = await client.get(m.url("/suggestions"), headers=h)
    assert r.json()["n_bearings"] == 1
