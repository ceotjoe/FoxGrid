"""Protection against leaked invite links: device binding, roles, expiry, removal."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import websockets

from tests.conftest import Server
from tests.helpers import Mission, auth, device_secret


def _join(m: Mission, callsign: str, secret: str | None = None, **extra: object) -> dict:  # type: ignore[type-arg]
    return {
        "invite_token": m.invite,
        "callsign": callsign,
        "device_secret": secret or device_secret(callsign),
        **extra,
    }


async def test_callsign_cannot_be_taken_over_with_the_link(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    token, p = await m.join("DL2OWN")
    assert p["device_bound"] is True

    thief = await client.post("/join", json=_join(m, "DL2OWN", secret="x" * 20))
    assert thief.status_code == 403
    # the lead's callsign is protected as well
    lead = await client.post("/join", json=_join(m, "DL1ABC", secret="y" * 20))
    assert lead.status_code == 403
    # the real device still gets back in as the same participant
    again = await client.post("/join", json=_join(m, "DL2OWN"))
    assert again.status_code == 200 and again.json()["participant"]["id"] == p["id"]


async def test_lead_can_release_a_device(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    _, p = await m.join("DL2NEW")
    swap = _join(m, "DL2NEW", secret="n" * 20)
    assert (await client.post("/join", json=swap)).status_code == 403

    h = auth(m.lead_token)
    r = await client.patch(
        m.url(f"/participants/{p['id']}"), json={"reset_device": True}, headers=h
    )
    assert r.status_code == 200 and r.json()["device_bound"] is False
    assert (await client.post("/join", json=swap)).status_code == 200
    # ... and the old phone is now locked out
    assert (await client.post("/join", json=_join(m, "DL2NEW"))).status_code == 403


async def test_joiner_cannot_choose_a_privileged_role(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    for role in ("fixed", "lead"):
        r = await client.post("/join", json=_join(m, f"DL2R{role[0].upper()}", role=role))
        assert r.json()["participant"]["role"] == "mobile"

    # invites cannot create leads, fixed-station invites hand out `fixed`
    h = auth(m.lead_token)
    assert (
        await client.post(m.url("/invites"), json={"default_role": "lead"}, headers=h)
    ).status_code == 422
    inv = (await client.post(m.url("/invites"), json={"default_role": "fixed"}, headers=h)).json()
    r = await client.post(
        "/join",
        json={"invite_token": inv["token"], "callsign": "DL2FIX", "device_secret": "f" * 20},
    )
    assert r.json()["participant"]["role"] == "fixed"


async def test_only_the_lead_changes_participants(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    token, p = await m.join("DL2MOB")
    other_token, other = await m.join("DL2OTH")
    r = await client.patch(
        m.url(f"/participants/{other['id']}"), json={"role": "lead"}, headers=auth(token)
    )
    assert r.status_code == 403

    h = auth(m.lead_token)
    ok = await client.patch(m.url(f"/participants/{p['id']}"), json={"role": "lead"}, headers=h)
    assert ok.status_code == 200 and ok.json()["role"] == "lead"
    # the lead cannot lock themselves out
    me = await client.patch(
        m.url(f"/participants/{m.lead_id}"), json={"is_active": False}, headers=h
    )
    assert me.status_code == 409
    me = await client.patch(m.url(f"/participants/{m.lead_id}"), json={"role": "mobile"}, headers=h)
    assert me.status_code == 409
    missing = await client.patch(
        m.url("/participants/00000000-0000-0000-0000-000000000000"), json={}, headers=h
    )
    assert missing.status_code == 404
    # other missions' participants are not reachable
    foreign = await Mission.create(client, callsign="DL9FOR")
    r = await client.patch(
        foreign.url(f"/participants/{other['id']}"),
        json={"is_active": False},
        headers=auth(foreign.lead_token),
    )
    assert r.status_code == 404


async def test_removed_participant_loses_access_at_once(
    client: httpx.AsyncClient, server: Server
) -> None:
    m = await Mission.create(client)
    token, p = await m.join("DL2BAD")
    assert (await client.get(m.url("/snapshot"), headers=auth(token))).status_code == 200

    async with websockets.connect(f"{server.ws_url}/ws/missions/{m.id}?token={token}") as ws:
        r = await client.patch(
            m.url(f"/participants/{p['id']}"),
            json={"is_active": False},
            headers=auth(m.lead_token),
        )
        assert r.status_code == 200 and r.json()["is_active"] is False
        closed = None
        try:
            while True:
                await asyncio.wait_for(ws.recv(), timeout=5)
        except websockets.ConnectionClosed as exc:
            closed = exc
        assert closed is not None and closed.rcvd is not None and closed.rcvd.code == 4403

    assert (await client.get(m.url("/snapshot"), headers=auth(token))).status_code == 401
    assert (await client.post("/join", json=_join(m, "DL2BAD"))).status_code == 403

    back = await client.patch(
        m.url(f"/participants/{p['id']}"), json={"is_active": True}, headers=auth(m.lead_token)
    )
    assert back.json()["is_active"] is True
    assert (await client.get(m.url("/snapshot"), headers=auth(token))).status_code == 200


async def test_default_invite_expires_and_can_be_rotated(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    created = (await client.post(m.url("/invites"), json={}, headers=h)).json()
    expires = datetime.fromisoformat(created["expires_at"])
    assert timedelta(hours=23) < expires - datetime.now(UTC) <= timedelta(hours=24, minutes=1)
    assert created["max_uses"] == 20

    rotated = await client.post(m.url(f"/invites/{created['id']}/rotate"), headers=h)
    assert rotated.status_code == 201
    new = rotated.json()
    assert new["token"] != created["token"] and new["id"] != created["id"]
    old = await client.post(
        "/join",
        json={"invite_token": created["token"], "callsign": "DL2OLD", "device_secret": "o" * 20},
    )
    assert old.status_code == 403
    fresh = await client.post(
        "/join",
        json={"invite_token": new["token"], "callsign": "DL2OLD", "device_secret": "o" * 20},
    )
    assert fresh.status_code == 200
    # members that joined before the rotation stay in
    token, _ = await m.join("DL2STAY")
    assert (await client.get(m.url("/snapshot"), headers=auth(token))).status_code == 200


async def test_short_device_secret_is_rejected(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    assert (await client.post("/join", json=_join(m, "DL2SHT", secret="short"))).status_code == 422
    missing = {"invite_token": m.invite, "callsign": "DL2SHT"}
    assert (await client.post("/join", json=missing)).status_code == 422
