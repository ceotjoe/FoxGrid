from __future__ import annotations

import asyncio
import math
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta

import asyncpg
import httpx

from tests.helpers import Mission, auth, bearing_payload, distance, offset, wait_for
from tests.test_field import STATIONS, TARGET

P0 = -20.0
EXPONENT = 3.0


def track(target: tuple[float, float], n: int = 40, noise: float = 1.5, att: float = 0.0):
    """Samples of a walk circling in on the emitter, as API payloads."""
    import random

    rng = random.Random(5)
    t0 = datetime.now(UTC)
    out = []
    for i in range(n):
        frac = i / max(n - 1, 1)
        radius = 5000.0 * (1 - frac) + 400.0 * frac
        ang = math.radians(270.0 * frac)
        pos = offset(radius * math.sin(ang), radius * math.cos(ang), target)
        level = P0 - 10 * EXPONENT * math.log10(max(distance(pos, target), 1.0))
        level += rng.gauss(0.0, noise) - att
        out.append(
            {
                "id": str(uuid.uuid4()),
                "lat": pos[0],
                "lon": pos[1],
                "rssi_dbm": round(level, 2),
                "attenuation_db": att,
                "measured_at": (t0 + timedelta(seconds=i)).isoformat(),
            }
        )
    return out


async def _estimate(client: httpx.AsyncClient, m: Mission, scope: str, key: str = "rssi"):
    async def poll():
        r = await client.get(m.url(f"/estimate?scope={scope}"), headers=auth(m.lead_token))
        return r.json() if r.status_code == 200 and r.json().get(key) else None

    return await wait_for(poll)


async def test_rssi_batch_is_idempotent_and_validated(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    samples = track(TARGET, n=6)
    r = await client.post(m.url("/rssi"), json=samples, headers=h)
    assert r.status_code == 200 and r.json() == {"stored": 6, "duplicates": 0}
    again = await client.post(m.url("/rssi"), json=samples, headers=h)
    assert again.json() == {"stored": 0, "duplicates": 6}
    changed = [{**samples[0], "rssi_dbm": samples[0]["rssi_dbm"] + 10}]
    assert (await client.post(m.url("/rssi"), json=changed, headers=h)).status_code == 409
    other_token, _ = await m.join("DL6RSS")
    stolen = await client.post(m.url("/rssi"), json=[samples[1]], headers=auth(other_token))
    assert stolen.status_code == 409

    assert (await client.post(m.url("/rssi"), json=[], headers=h)).status_code == 422
    dup = [samples[0], samples[0]]
    assert (await client.post(m.url("/rssi"), json=dup, headers=h)).status_code == 422
    bad = [{**track(TARGET, 1)[0], "rssi_dbm": 50}]
    assert (await client.post(m.url("/rssi"), json=bad, headers=h)).status_code == 422
    neg = [{**track(TARGET, 1)[0], "attenuation_db": -3}]
    assert (await client.post(m.url("/rssi"), json=neg, headers=h)).status_code == 422
    naive = [{**track(TARGET, 1)[0], "measured_at": "2026-01-01T10:00:00"}]
    assert (await client.post(m.url("/rssi"), json=naive, headers=h)).status_code == 422

    listed = await client.get(m.url("/rssi"), headers=h)
    assert len(listed.json()) == 6
    mine = await client.get(m.url(f"/rssi?participant={m.lead_id}"), headers=h)
    assert len(mine.json()) == 6
    assert (await client.post(m.url("/rssi"), json=samples[:1])).status_code == 401


async def test_rssi_track_alone_gives_an_estimate_with_path_loss_fit(
    client: httpx.AsyncClient,
) -> None:
    m = await Mission.create(client)
    await client.post(m.url("/rssi"), json=track(TARGET), headers=auth(m.lead_token))
    est = await _estimate(client, m, "all")
    assert est["n_bearings"] == 0
    assert est["rssi"]["n_samples"] == 40
    assert abs(est["rssi"]["exponent"] - EXPONENT) < 0.8
    assert distance((est["lat"], est["lon"]), TARGET) < 500


async def test_attenuation_is_corrected_server_side(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    plain = track(TARGET, noise=0.5)
    # the second half was recorded with a 20 dB attenuator in front of the receiver
    with_att = [
        {**s, "rssi_dbm": s["rssi_dbm"] - 20.0, "attenuation_db": 20.0} if i >= 20 else s
        for i, s in enumerate(plain)
    ]
    await client.post(m.url("/rssi"), json=with_att, headers=h)
    est = await _estimate(client, m, "all")
    assert distance((est["lat"], est["lon"]), TARGET) < 500
    assert abs(est["rssi"]["exponent"] - EXPONENT) < 0.8


async def test_rssi_fuses_with_bearings_and_can_be_switched_off(
    client: httpx.AsyncClient,
) -> None:
    m = await Mission.create(client, engine_params={"use_rssi": False})
    h = auth(m.lead_token)
    for st in STATIONS[:2]:
        await client.post(m.url("/bearings"), json=bearing_payload(st, TARGET), headers=h)
    await client.post(m.url("/rssi"), json=track(TARGET), headers=h)

    async def two_bearings():
        r = await client.get(m.url("/estimate?scope=all"), headers=h)
        return r.json() if r.status_code == 200 and r.json()["n_bearings"] == 2 else None

    est = await wait_for(two_bearings)
    assert est["rssi"] is None  # use_rssi=false: the track is stored but not fused

    on = await Mission.create(client)
    for st in STATIONS[:2]:
        await client.post(
            on.url("/bearings"), json=bearing_payload(st, TARGET), headers=auth(on.lead_token)
        )
    await client.post(on.url("/rssi"), json=track(TARGET), headers=auth(on.lead_token))
    est2 = await _estimate(client, on, "all")
    assert est2["n_bearings"] == 2 and est2["rssi"]["n_samples"] == 40


async def test_current_scope_uses_only_the_running_transmission(
    client: httpx.AsyncClient,
) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    tx = (await client.post(m.url("/transmissions/start"), headers=h)).json()
    await client.post(m.url("/rssi"), json=track(TARGET, n=12), headers=h)
    listed = (await client.get(m.url("/rssi"), headers=h)).json()
    assert {r["transmission_id"] for r in listed} == {tx["id"]}
    est = await _estimate(client, m, "current")
    assert est["rssi"]["n_samples"] == 12 and est["transmission_id"] == tx["id"]


async def test_deactivated_samples_are_excluded_but_kept(
    client: httpx.AsyncClient, settings
) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    samples = track(TARGET, n=10)
    await client.post(m.url("/rssi"), json=samples, headers=h)
    await _estimate(client, m, "all")
    for s in samples[:4]:
        r = await client.patch(m.url(f"/rssi/{s['id']}"), json={"is_active": False}, headers=h)
        assert r.status_code == 200 and r.json()["is_active"] is False

    async def six():
        r = await client.get(m.url("/estimate?scope=all"), headers=h)
        return r.json() if r.json()["rssi"]["n_samples"] == 6 else None

    await wait_for(six)
    assert len((await client.get(m.url("/rssi"), headers=h)).json()) == 10  # still in the log

    stranger, _ = await m.join("DL7XXX")
    denied = await client.patch(
        m.url(f"/rssi/{samples[5]['id']}"), json={"is_active": False}, headers=auth(stranger)
    )
    assert denied.status_code == 403
    missing = await client.patch(
        m.url(f"/rssi/{uuid.uuid4()}"), json={"is_active": False}, headers=h
    )
    assert missing.status_code == 404
    assert (await client.delete(m.url(f"/rssi/{samples[5]['id']}"), headers=h)).status_code == 405

    conn = await asyncpg.connect(settings.database_url.replace("+asyncpg", ""))
    try:
        try:
            await conn.execute(
                "DELETE FROM rssi_samples WHERE id = $1", uuid.UUID(samples[0]["id"])
            )
        except asyncpg.PostgresError as exc:
            assert "append-only" in str(exc)
        else:
            raise AssertionError("delete should have been rejected")
    finally:
        await conn.close()


async def test_estimate_query_includes_rssi_and_filters_it(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    await client.post(m.url("/rssi"), json=track(TARGET, n=30), headers=h)
    q = await client.get(m.url("/estimate/query"), headers=h)
    assert q.status_code == 200 and q.json()["rssi"]["n_samples"] == 30
    no_rssi = await client.get(
        m.url("/estimate/query"), params={"include_rssi": "false"}, headers=h
    )
    assert no_rssi.status_code == 404  # no bearings and RSSI switched off
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    none = await client.get(m.url("/estimate/query"), params={"since": future}, headers=h)
    assert none.status_code == 404


async def test_snapshot_and_exports_contain_the_rssi_track(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client, name="Homing")
    h = auth(m.lead_token)
    await client.post(m.url("/rssi"), json=track(TARGET, n=15), headers=h)
    await _estimate(client, m, "all")
    snap = (await client.get(m.url("/snapshot"), headers=h)).json()
    assert len(snap["rssi"]) == 15
    assert snap["rssi"][0]["measured_at"] <= snap["rssi"][-1]["measured_at"]

    gpx = ET.fromstring((await client.get(m.url("/export.gpx"), headers=h)).content)
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    assert len(gpx.findall("g:trk/g:trkseg/g:trkpt", ns)) == 15
    assert any("dBm" in (c.text or "") for c in gpx.iterfind(".//g:cmt", ns))
    kml = ET.fromstring((await client.get(m.url("/export.kml"), headers=h)).content)
    assert len(kml.findall(".//{http://www.opengis.net/kml/2.2}Folder")) >= 1
    assert "RSSI-Spur" in [
        n.text
        for n in kml.iterfind(
            ".//{http://www.opengis.net/kml/2.2}Folder/{http://www.opengis.net/kml/2.2}name"
        )
    ]
    js = (await client.get(m.url("/export.json"), headers=h)).json()
    assert len(js["rssi_samples"]) == 15
    pdf = await client.get(m.url("/export.pdf"), headers=h)
    assert pdf.content.startswith(b"%PDF") and len(pdf.content) > 3000


async def test_late_rssi_upload_after_mission_end(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    await client.post(m.url("/end"), headers=h)
    r = await client.post(m.url("/rssi"), json=track(TARGET, n=3), headers=h)
    assert r.status_code == 200 and r.json()["stored"] == 3


async def test_rssi_burst_is_debounced(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    samples = track(TARGET, n=30)
    for i in range(0, 30, 3):
        await client.post(m.url("/rssi"), json=samples[i : i + 3], headers=h)
    await _estimate(client, m, "all")
    await asyncio.sleep(0.8)
    hist = (await client.get(m.url("/estimate/history?scope=all"), headers=h)).json()
    assert 1 <= len(hist) < 8
