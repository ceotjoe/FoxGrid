from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import websockets

from tests.conftest import Server
from tests.helpers import Mission, auth, device_secret


async def test_create_join_and_roles(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client, search_area=[[11.4, 48.0], [11.8, 48.0], [11.6, 48.3]])
    r = await client.get(m.url(""), headers=auth(m.lead_token))
    assert r.status_code == 200
    assert len(r.json()["search_area"]) == 4  # ring is closed

    token, p = await m.join("dl2xyz", role="lead")
    assert p["role"] == "mobile"  # invite does not grant lead
    # rejoin with the same callsign returns the same participant
    _, again = await m.join("DL2XYZ")
    assert again["id"] == p["id"]
    r = await client.get(m.url("/participants"), headers=auth(token))
    assert {x["callsign"] for x in r.json()} == {"DL1ABC", "DL2XYZ"}


async def test_invite_rules(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    bad = await client.post(
        "/join",
        json={
            "invite_token": "nope",
            "callsign": "DL3AAA",
            "device_secret": device_secret("DL3AAA"),
        },
    )
    assert bad.status_code == 403

    r = await client.post(
        m.url("/invites"), json={"max_uses": 1, "default_role": "fixed"}, headers=auth(m.lead_token)
    )
    assert r.status_code == 201
    inv = r.json()
    ok = await client.post(
        "/join",
        json={
            "invite_token": inv["token"],
            "callsign": "DL3AAA",
            "device_secret": device_secret("DL3AAA"),
        },
    )
    assert ok.status_code == 200
    full = await client.post(
        "/join",
        json={
            "invite_token": inv["token"],
            "callsign": "DL3BBB",
            "device_secret": device_secret("DL3BBB"),
        },
    )
    assert full.status_code == 403

    rev = await client.delete(m.url(f"/invites/{inv['id']}"), headers=auth(m.lead_token))
    assert rev.status_code == 204
    after = await client.post(
        "/join",
        json={
            "invite_token": inv["token"],
            "callsign": "DL3AAA",
            "device_secret": device_secret("DL3AAA"),
        },
    )
    assert after.status_code == 403

    token, _ = await m.join("DL3CCC")
    forbidden = await client.post(m.url("/invites"), json={}, headers=auth(token))
    assert forbidden.status_code == 403


async def test_auth_required_and_mission_isolation(client: httpx.AsyncClient) -> None:
    a = await Mission.create(client)
    b = await Mission.create(client, callsign="DL9ZZZ")
    assert (await client.get(a.url(""))).status_code == 401
    assert (await client.get(a.url(""), headers=auth("garbage"))).status_code == 401
    assert (await client.get(a.url(""), headers=auth(b.lead_token))).status_code == 403


@pytest.mark.parametrize("callsign", ["x", "DL 1ABC", "DL1ABC!"])
async def test_invalid_callsign(client: httpx.AsyncClient, callsign: str) -> None:
    r = await client.post(
        "/missions", json={"name": "x", "frequency_mhz": 433.5, "callsign": callsign}
    )
    assert r.status_code == 422


async def test_end_mission_notifies_connected_members(
    client: httpx.AsyncClient, server: Server
) -> None:
    m = await Mission.create(client)
    member_token, _ = await m.join("DL2MEM")
    await client.post(m.url("/transmissions/start"), headers=auth(m.lead_token))
    async with websockets.connect(f"{server.ws_url}/ws/missions/{m.id}?token={member_token}") as ws:
        await client.post(m.url("/end"), headers=auth(m.lead_token))
        seen: dict[str, dict[str, object]] = {}
        while "mission_ended" not in seen:
            event = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            seen[event["type"]] = event
    assert seen["mission_ended"]["data"]["status"] == "ended"
    assert seen["transmission_ended"]["data"]["ended_at"] is not None
    # A repeated end is refused and must not announce again.
    assert (await client.post(m.url("/end"), headers=auth(m.lead_token))).status_code == 409


async def test_end_mission(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    r = await client.post(m.url("/end"), headers=auth(m.lead_token))
    assert r.status_code == 200 and r.json()["status"] == "ended"
    assert (await client.post(m.url("/end"), headers=auth(m.lead_token))).status_code == 409
    join = await client.post(
        "/join",
        json={
            "invite_token": m.invite,
            "callsign": "DL4NEW",
            "device_secret": device_secret("DL4NEW"),
        },
    )
    assert join.status_code == 409
    start = await client.post(m.url("/transmissions/start"), headers=auth(m.lead_token))
    assert start.status_code == 409
