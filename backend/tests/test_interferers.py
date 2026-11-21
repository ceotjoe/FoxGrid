"""Several interferers per mission: assignment, separate estimates, reassignment, migration."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from typing import Any

import asyncpg
import httpx
from testcontainers.community.postgres import PostgresContainer

from tests.conftest import BACKEND_DIR
from tests.helpers import Mission, auth, bearing_payload, distance, offset, set_authority, wait_for
from tests.test_field import STATIONS, TARGET

TARGET_B = offset(-2500, 3500)


async def add_interferer(
    client: httpx.AsyncClient, m: Mission, name: str, token: str | None = None, **extra: Any
) -> httpx.Response:
    body = {"id": str(uuid.uuid4()), "name": name, **extra}
    return await client.post(m.url("/interferers"), json=body, headers=auth(token or m.lead_token))


async def post_bearings(
    client: httpx.AsyncClient,
    m: Mission,
    target: tuple[float, float],
    interferer: str | None = None,
    token: str | None = None,
) -> list[dict[str, Any]]:
    out = []
    for station in STATIONS:
        extra = {"interferer_id": interferer} if interferer else {}
        r = await client.post(
            m.url("/bearings"),
            json=bearing_payload(station, target, **extra),
            headers=auth(token or m.lead_token),
        )
        assert r.status_code == 201, r.text
        out.append(r.json())
    return out


async def estimate(
    client: httpx.AsyncClient, m: Mission, interferer: str | None = None, n: int = 3
) -> dict[str, Any]:
    query = "?scope=all" + (f"&interferer={interferer}" if interferer else "")

    async def poll() -> dict[str, Any] | None:
        r = await client.get(m.url(f"/estimate{query}"), headers=auth(m.lead_token))
        if r.status_code == 200 and r.json()["n_bearings"] == n:
            return r.json()  # type: ignore[no-any-return]
        return None

    return await wait_for(poll)  # type: ignore[no-any-return]


async def test_a_mission_starts_with_one_interferer(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    snap = (await client.get(m.url("/snapshot"), headers=auth(m.lead_token))).json()
    assert [(i["name"], i["color_slot"], i["is_active"]) for i in snap["interferers"]] == [
        ("Störer 1", 0, True)
    ]


async def test_interferer_management(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    member, _ = await m.join("DL5MEM")
    body = {"id": str(uuid.uuid4()), "name": "Störer B", "frequency_mhz": 438.5}

    assert (
        await client.post(m.url("/interferers"), json=body, headers=auth(member))
    ).status_code == 403
    first = await client.post(m.url("/interferers"), json=body, headers=auth(m.lead_token))
    assert first.status_code == 201
    assert first.json()["color_slot"] == 1  # the lowest free slot
    again = await client.post(m.url("/interferers"), json=body, headers=auth(m.lead_token))
    assert again.status_code == 200
    assert (
        await client.post(
            m.url("/interferers"),
            json={**body, "name": "other"},
            headers=auth(m.lead_token),
        )
    ).status_code == 409  # same id, different content
    assert (await add_interferer(client, m, "Störer B")).status_code == 409  # same name

    listed = await client.get(m.url("/interferers"), headers=auth(member))
    assert [i["name"] for i in listed.json()] == ["Störer 1", "Störer B"]

    iid = body["id"]
    patched = await client.patch(
        m.url(f"/interferers/{iid}"),
        json={"name": "Brummer", "status": "resolved"},
        headers=auth(m.lead_token),
    )
    assert patched.status_code == 200
    assert (patched.json()["name"], patched.json()["status"]) == ("Brummer", "resolved")
    assert (
        await client.patch(m.url(f"/interferers/{iid}"), json={"name": "x"}, headers=auth(member))
    ).status_code == 403
    # The colour slot cannot be edited.
    assert (
        await client.patch(
            m.url(f"/interferers/{iid}"), json={"color_slot": 3}, headers=auth(m.lead_token)
        )
    ).status_code == 422


async def test_at_most_six_active_interferers(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    for n in range(2, 7):
        assert (await add_interferer(client, m, f"Störer {n}")).status_code == 201
    seventh = await add_interferer(client, m, "Störer 7")
    assert seventh.status_code == 409

    # Deactivating one frees its slot for a new interferer.
    listed = (await client.get(m.url("/interferers"), headers=auth(m.lead_token))).json()
    victim = listed[2]
    await client.patch(
        m.url(f"/interferers/{victim['id']}"),
        json={"is_active": False},
        headers=auth(m.lead_token),
    )
    again = await add_interferer(client, m, "Störer 7")
    assert again.status_code == 201 and again.json()["color_slot"] == victim["color_slot"]


async def test_bearings_default_to_the_first_interferer_and_validate(
    client: httpx.AsyncClient,
) -> None:
    m = await Mission.create(client)
    other = await Mission.create(client, callsign="dl9xyz")
    default = (await client.get(m.url("/interferers"), headers=auth(m.lead_token))).json()[0]
    b_id = (await add_interferer(client, m, "B")).json()["id"]
    foreign = (await client.get(other.url("/interferers"), headers=auth(other.lead_token))).json()
    h = auth(m.lead_token)

    plain = await client.post(
        m.url("/bearings"), json=bearing_payload(STATIONS[0], TARGET), headers=h
    )
    assert plain.json()["interferer_id"] == default["id"]
    explicit = await client.post(
        m.url("/bearings"),
        json=bearing_payload(STATIONS[1], TARGET, interferer_id=b_id),
        headers=h,
    )
    assert explicit.json()["interferer_id"] == b_id
    # a retry with the same content is a duplicate, a different interferer is a conflict
    dup = await client.post(
        m.url("/bearings"),
        json={**explicit.json(), "measured_at": explicit.json()["measured_at"]},
        headers=h,
    )
    assert dup.status_code == 200
    clash = await client.post(
        m.url("/bearings"),
        json={**explicit.json(), "interferer_id": default["id"]},
        headers=h,
    )
    assert clash.status_code == 409
    for bad in (str(uuid.uuid4()), foreign[0]["id"]):
        r = await client.post(
            m.url("/bearings"),
            json=bearing_payload(STATIONS[2], TARGET, interferer_id=bad),
            headers=h,
        )
        assert r.status_code == 422


async def test_transmission_interferer_is_the_default_for_its_bearings(
    client: httpx.AsyncClient,
) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    b_id = (await add_interferer(client, m, "B")).json()["id"]
    started = await client.post(
        m.url("/transmissions/start"), json={"interferer_id": b_id}, headers=h
    )
    assert started.status_code == 201 and started.json()["interferer_id"] == b_id
    inherited = await client.post(
        m.url("/bearings"), json=bearing_payload(STATIONS[0], TARGET_B), headers=h
    )
    assert inherited.json()["interferer_id"] == b_id
    assert (await client.post(m.url("/transmissions/stop"), json={}, headers=h)).status_code == 200
    bad = await client.post(
        m.url("/transmissions/start"), json={"interferer_id": str(uuid.uuid4())}, headers=h
    )
    assert bad.status_code == 422


async def test_each_interferer_gets_its_own_estimate(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    b_id = (await add_interferer(client, m, "B")).json()["id"]
    await post_bearings(client, m, TARGET)  # default interferer
    await post_bearings(client, m, TARGET_B, interferer=b_id)

    est_a = await estimate(client, m)  # no parameter: the default interferer
    est_b = await estimate(client, m, interferer=b_id)
    assert distance((est_a["lat"], est_a["lon"]), TARGET) < 300
    assert distance((est_b["lat"], est_b["lon"]), TARGET_B) < 300
    assert est_a["interferer_id"] != est_b["interferer_id"]

    snap = (await client.get(m.url("/snapshot"), headers=auth(m.lead_token))).json()
    assert {(e["interferer_id"], e["scope"]) for e in snap["estimates"]} >= {
        (est_a["interferer_id"], "all"),
        (b_id, "all"),
    }
    assert len(snap["interferers"]) == 2

    # ad-hoc query and suggestions respect the interferer too
    q = await client.get(m.url(f"/estimate/query?interferer={b_id}"), headers=auth(m.lead_token))
    assert q.status_code == 200 and q.json()["n_bearings"] == 3
    assert distance((q.json()["lat"], q.json()["lon"]), TARGET_B) < 300
    s = await client.get(m.url(f"/suggestions?interferer={b_id}"), headers=auth(m.lead_token))
    assert s.status_code == 200 and s.json()["n_bearings"] == 3
    bad = await client.get(
        m.url(f"/estimate?interferer={uuid.uuid4()}"), headers=auth(m.lead_token)
    )
    assert bad.status_code == 422


async def test_a_new_bearing_leaves_the_other_estimate_alone(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    b_id = (await add_interferer(client, m, "B")).json()["id"]
    await post_bearings(client, m, TARGET)
    await post_bearings(client, m, TARGET_B, interferer=b_id)
    first = await estimate(client, m)
    await post_bearings(client, m, TARGET_B, interferer=b_id)
    await estimate(client, m, interferer=b_id, n=6)
    again = await estimate(client, m)
    assert again["id"] == first["id"]  # unchanged input: no new estimate for A


async def test_reassigning_a_bearing_is_a_revision(
    client: httpx.AsyncClient, database_url: str
) -> None:
    m = await Mission.create(client)
    member, member_p = await m.join("DL5MEM")
    analyst, analyst_p = await m.join("DL5ANA")
    third, _ = await m.join("DL5THR")
    await set_authority(database_url, analyst_p["id"], "analyst")
    b_id = (await add_interferer(client, m, "B")).json()["id"]
    mine = (await post_bearings(client, m, TARGET, token=member))[0]
    await post_bearings(client, m, TARGET)
    path = m.url(f"/bearings/{mine['id']}")

    # a stranger without interferer.manage cannot move it; the owner and the analyst can
    assert (
        await client.patch(path, json={"interferer_id": b_id}, headers=auth(third))
    ).status_code == 403
    nope = await client.patch(path, json={"interferer_id": str(uuid.uuid4())}, headers=auth(member))
    assert nope.status_code == 422
    moved = await client.patch(path, json={"interferer_id": b_id}, headers=auth(member))
    assert moved.status_code == 200 and moved.json()["interferer_id"] == b_id
    back = await client.patch(
        path, json={"interferer_id": mine["interferer_id"]}, headers=auth(analyst)
    )
    assert back.status_code == 200

    revisions = (await client.get(path + "/revisions", headers=auth(member))).json()
    assert [r["changes"]["interferer_id"]["to"] for r in revisions] == [
        b_id,
        mine["interferer_id"],
    ]
    # the interferer cannot be cleared
    keep = await client.patch(path, json={"interferer_id": None}, headers=auth(member))
    assert keep.status_code == 200 and keep.json()["interferer_id"] == mine["interferer_id"]


async def test_reassigning_moves_the_data_between_estimates(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    b_id = (await add_interferer(client, m, "B")).json()["id"]
    placed = await post_bearings(client, m, TARGET_B)  # entered for the default by mistake
    await post_bearings(client, m, TARGET_B, interferer=b_id)
    for b in placed:
        r = await client.patch(
            m.url(f"/bearings/{b['id']}"),
            json={"interferer_id": b_id},
            headers=auth(m.lead_token),
        )
        assert r.status_code == 200
    est_b = await estimate(client, m, interferer=b_id, n=6)
    assert distance((est_b["lat"], est_b["lon"]), TARGET_B) < 300


async def test_observers_and_untrusted_data_stay_out_per_interferer(
    client: httpx.AsyncClient,
) -> None:
    m = await Mission.create(client)
    b_id = (await add_interferer(client, m, "B")).json()["id"]
    liar, liar_p = await m.join("DL5BAD")
    await post_bearings(client, m, TARGET_B, interferer=b_id)
    await post_bearings(client, m, TARGET, interferer=b_id, token=liar)
    assert (await estimate(client, m, interferer=b_id, n=6))["n_bearings"] == 6
    await m.patch_participant(liar_p["id"], trusted=False)
    assert (await estimate(client, m, interferer=b_id, n=3))["n_bearings"] == 3


async def test_exports_carry_the_interferers(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    b_id = (await add_interferer(client, m, "Brummer")).json()["id"]
    await post_bearings(client, m, TARGET)
    await post_bearings(client, m, TARGET_B, interferer=b_id)
    await estimate(client, m)
    await estimate(client, m, interferer=b_id)
    doc = (await client.get(m.url("/export.json"), headers=auth(m.lead_token))).json()
    assert {i["name"] for i in doc["interferers"]} == {"Störer 1", "Brummer"}
    assert {e["interferer_id"] for e in doc["estimates"]} >= {b_id}
    assert {b["interferer_id"] for b in doc["bearings"]} >= {b_id}
    for fmt in ("gpx", "kml", "pdf"):
        r = await client.get(m.url(f"/export.{fmt}"), headers=auth(m.lead_token))
        assert r.status_code == 200, fmt


async def test_migration_assigns_existing_data_to_a_default_interferer(
    postgres: PostgresContainer,
) -> None:
    """Missions from before interferers get "Störer 1" with all of their bearings."""
    host, port = postgres.get_container_host_ip(), postgres.get_exposed_port(5432)
    admin = await asyncpg.connect(f"postgresql://foxgrid:foxgrid@{host}:{port}/foxgrid")
    name = f"migration_{uuid.uuid4().hex[:8]}"
    await admin.execute(f'CREATE DATABASE "{name}"')
    await admin.close()
    env = {
        **os.environ,
        "FOXGRID_DATABASE_URL": f"postgresql+asyncpg://foxgrid:foxgrid@{host}:{port}/{name}",
    }

    def alembic(*args: str) -> None:
        subprocess.run(
            [sys.executable, "-m", "alembic", *args], cwd=BACKEND_DIR, env=env, check=True
        )

    alembic("upgrade", "0012")
    conn = await asyncpg.connect(f"postgresql://foxgrid:foxgrid@{host}:{port}/{name}")
    try:
        mission_id, participant_id, bearing_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        await conn.execute(
            "INSERT INTO missions (id, name, frequency_mhz, status, created_at, "
            "track_retention_days, engine_params) "
            "VALUES ($1, 'old', 433.5, 'active', now(), 30, '{}')",
            mission_id,
        )
        await conn.execute(
            "INSERT INTO participants (id, mission_id, callsign, role, authority, joined_at, "
            "is_active) VALUES ($1, $2, 'DL1OLD', 'lead', 'lead', now(), true)",
            participant_id,
            mission_id,
        )
        await conn.execute(
            "INSERT INTO bearings (id, mission_id, participant_id, lat, lon, azimuth_true_deg, "
            "azimuth_input_ref, declination_deg_applied, sigma_deg, attenuation_db, polarization, "
            "measured_at, received_at, is_outlier, is_active, source) "
            "VALUES ($1, $2, $3, 48.1, 11.5, 90, 'true', 0, 5, 0, 'unknown', now(), now(), "
            "false, true, 'manual')",
            bearing_id,
            mission_id,
            participant_id,
        )
        alembic("upgrade", "head")
        interferers = await conn.fetch(
            "SELECT * FROM interferers WHERE mission_id = $1", mission_id
        )
        assert [(i["name"], i["color_slot"], i["is_active"]) for i in interferers] == [
            ("Störer 1", 0, True)
        ]
        assert interferers[0]["created_by"] == participant_id
        owner = await conn.fetchval("SELECT interferer_id FROM bearings WHERE id = $1", bearing_id)
        assert owner == interferers[0]["id"]
        # interferers, like bearings, can never be deleted
        try:
            await conn.execute("DELETE FROM interferers WHERE id = $1", owner)
        except asyncpg.PostgresError:
            pass
        else:
            raise AssertionError("an interferer could be deleted")
        alembic("downgrade", "0012")
    finally:
        await conn.close()
