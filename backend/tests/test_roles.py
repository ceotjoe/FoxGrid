"""Assigning authorities: who may, the guards, observers and invites."""

from __future__ import annotations

from typing import Any

import httpx

from tests.helpers import Mission, auth, bearing_payload, device_secret, wait_for
from tests.test_authorities import Crew
from tests.test_field import STATIONS, TARGET

ASSIGNABLE = ("lead", "deputy", "analyst", "coordinator", "member", "observer")


async def _patch(
    client: httpx.AsyncClient, m: Mission, pid: str, token: str, **body: Any
) -> httpx.Response:
    return await client.patch(m.url(f"/participants/{pid}"), json=body, headers=auth(token))


async def test_lead_assigns_every_authority_and_it_is_audited(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    _, p = await m.join("DL1ROL")
    for authority in ("deputy", "analyst", "coordinator", "observer", "member"):
        r = await _patch(client, m, p["id"], m.lead_token, authority=authority)
        assert r.status_code == 200, r.text
        assert r.json()["authority"] == authority
        assert r.json()["role"] == "mobile"
        assert isinstance(r.json()["permissions"], list) and r.json()["permissions"]
    me = (await client.get(m.url("/me"), headers=auth(m.lead_token))).json()
    assert me["authority"] == "lead" and "role.assign" in me["permissions"]
    audit = (await client.get(m.url("/audit"), headers=auth(m.lead_token))).json()
    assert any("authority" in str(row) for row in audit)


async def test_only_the_lead_assigns_and_never_a_station(
    client: httpx.AsyncClient, database_url: str
) -> None:
    c = await Crew.create(client, database_url)
    pid = c.ids["member"]
    for who in ("deputy", "analyst", "coordinator", "member", "observer"):
        r = await _patch(client, c.m, pid, c.tokens[who], authority="analyst")
        assert r.status_code == 403, who
    assert (await _patch(client, c.m, pid, c.m.lead_token, authority="station")).status_code == 422
    assert (await _patch(client, c.m, pid, c.m.lead_token, authority="root")).status_code == 422


async def test_lead_role_and_authority_stay_in_step(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    _, p = await m.join("DL2SYN")
    up = (await _patch(client, m, p["id"], m.lead_token, authority="lead")).json()
    assert up["authority"] == "lead" and up["role"] == "lead"
    down = (await _patch(client, m, p["id"], m.lead_token, authority="analyst")).json()
    assert down["authority"] == "analyst" and down["role"] == "mobile"
    # the legacy role field still works and drags the authority along
    legacy = (await _patch(client, m, p["id"], m.lead_token, role="lead")).json()
    assert legacy["authority"] == "lead"
    back = (await _patch(client, m, p["id"], m.lead_token, role="fixed")).json()
    assert back["authority"] == "member" and back["role"] == "fixed"


async def test_a_mission_always_keeps_a_lead(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    tok, p = await m.join("DL3TWO")
    # the only lead cannot step down
    assert (await _patch(client, m, m.lead_id, m.lead_token, authority="member")).status_code == 409
    assert (await _patch(client, m, p["id"], m.lead_token, authority="lead")).status_code == 200
    # with a second lead they can
    assert (
        await _patch(client, m, m.lead_id, m.lead_token, authority="analyst")
    ).status_code == 200
    # ...and now the remaining lead is the last one
    assert (await _patch(client, m, p["id"], tok, authority="member")).status_code == 409
    # a former lead no longer manages roles
    assert (await _patch(client, m, p["id"], m.lead_token, authority="member")).status_code == 403


async def test_only_active_participants_get_a_role(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    r = await client.post(
        "/join",
        json={
            "invite_token": m.invite,
            "callsign": "DL4PEN",
            "device_secret": device_secret("DL4PEN"),
        },
    )
    assert r.json()["participant"]["status"] == "pending"
    pid = r.json()["participant"]["id"]
    assert (await _patch(client, m, pid, m.lead_token, authority="analyst")).status_code == 409


async def test_observers_never_move_the_estimate(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    tok, p = await m.join("DL5OBS")
    await client.post(
        m.url("/bearings"), json=bearing_payload(STATIONS[0], TARGET), headers=auth(tok)
    )
    for st in STATIONS[1:3]:
        await client.post(
            m.url("/bearings"), json=bearing_payload(st, TARGET), headers=auth(m.lead_token)
        )

    async def n_bearings() -> int | None:
        r = await client.get(m.url("/estimate?scope=all"), headers=auth(m.lead_token))
        return r.json()["n_bearings"] if r.status_code == 200 else None

    async def counts(n: int) -> bool:
        return await n_bearings() == n

    async def wait_count(n: int) -> None:
        async def check() -> bool:
            return await counts(n)

        await wait_for(check)

    await wait_count(3)
    await _patch(client, m, p["id"], m.lead_token, authority="observer")
    await wait_count(2)  # the bearing stays in the log, it just stops counting
    bearings = (await client.get(m.url("/bearings"), headers=auth(m.lead_token))).json()
    assert len(bearings) == 3
    await _patch(client, m, p["id"], m.lead_token, authority="member")
    await wait_count(3)


async def test_observer_invites(client: httpx.AsyncClient, database_url: str) -> None:
    c = await Crew.create(client, database_url)
    body = {"default_authority": "observer"}
    # only whoever manages invites hands out observer links
    assert (
        await client.post(c.m.url("/invites"), json=body, headers=c.h("coordinator"))
    ).status_code == 403
    assert (
        await client.post(
            c.m.url("/invites"),
            json={**body, "default_role": "fixed"},
            headers=c.h("lead"),
        )
    ).status_code == 422
    r = await client.post(c.m.url("/invites"), json=body, headers=c.h("deputy"))
    assert r.status_code == 201 and r.json()["default_authority"] == "observer"
    plain = await client.post(c.m.url("/invites"), json={}, headers=c.h("coordinator"))
    assert plain.json()["default_authority"] == "member"

    joined = await client.post(
        "/join",
        json={
            "invite_token": r.json()["token"],
            "callsign": "DL6GST",
            "device_secret": device_secret("DL6GST"),
        },
    )
    assert joined.status_code == 200
    assert joined.json()["participant"]["authority"] == "observer"
    assert joined.json()["participant"]["status"] == "pending"  # still needs the lead's OK

    rotated = await client.post(c.m.url(f"/invites/{r.json()['id']}/rotate"), headers=c.h("lead"))
    assert rotated.status_code == 201 and rotated.json()["default_authority"] == "observer"
    other = await client.post(
        "/join",
        json={
            "invite_token": plain.json()["token"],
            "callsign": "DL6MEM",
            "device_secret": device_secret("DL6MEM"),
        },
    )
    assert other.json()["participant"]["authority"] == "member"


async def test_websocket_reconnects_on_a_role_change_via_the_api(
    client: httpx.AsyncClient, database_url: str, server: Any
) -> None:
    import asyncio

    import websockets
    from websockets.exceptions import ConnectionClosed

    c = await Crew.create(client, database_url)
    url = f"{server.ws_url}/ws/missions/{c.m.id}?token={c.tokens['member']}"
    async with websockets.connect(url) as ws:
        r = await _patch(client, c.m, c.ids["member"], c.m.lead_token, authority="observer")
        assert r.status_code == 200
        try:
            while True:
                await asyncio.wait_for(ws.recv(), timeout=5)
        except ConnectionClosed as closed:
            assert closed.rcvd is not None and closed.rcvd.code == 4409
