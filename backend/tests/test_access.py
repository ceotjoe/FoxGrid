"""Protection against leaked invite links: device binding, roles, expiry, removal."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import websockets

from tests.conftest import Server
from tests.helpers import Mission, auth, bearing_payload, device_secret, wait_for
from tests.test_field import STATIONS, TARGET, _full_estimate
from tests.test_rssi_api import track


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


def _fresh(m: Mission, callsign: str) -> dict:  # type: ignore[type-arg]
    return {
        "invite_token": m.invite,
        "callsign": callsign,
        "device_secret": device_secret(callsign),
    }


async def test_joiner_waits_for_approval(client: httpx.AsyncClient, server: Server) -> None:
    m = await Mission.create(client)
    r = await client.post("/join", json=_fresh(m, "DL2WAIT"))
    assert r.status_code == 200
    token, p = r.json()["token"], r.json()["participant"]
    assert p["status"] == "pending"

    # nothing but the own state is reachable
    for path in ("/snapshot", "/participants", "/bearings", "/estimate"):
        denied = await client.get(m.url(path), headers=auth(token))
        assert denied.status_code == 403, path
    post = await client.post(m.url("/transmissions/start"), headers=auth(token))
    assert post.status_code == 403
    me = await client.get(m.url("/me"), headers=auth(token))
    assert me.status_code == 200 and me.json()["status"] == "pending"
    other = await Mission.create(client, callsign="DL9OTH")
    assert (await client.get(other.url("/me"), headers=auth(token))).status_code == 403

    # a pending joiner gets no live feed: the server refuses the handshake
    with pytest.raises(websockets.exceptions.InvalidStatus):
        async with websockets.connect(f"{server.ws_url}/ws/missions/{m.id}?token={token}"):
            pass

    # joining again from the same device stays pending (and does not use up the invite)
    again = await client.post("/join", json=_fresh(m, "DL2WAIT"))
    assert again.json()["participant"]["status"] == "pending"

    h = auth(m.lead_token)
    ok = await client.patch(m.url(f"/participants/{p['id']}"), json={"status": "active"}, headers=h)
    assert ok.status_code == 200 and ok.json()["status"] == "active"
    assert (await client.get(m.url("/snapshot"), headers=auth(token))).status_code == 200


async def test_rejected_joiner_stays_out(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    r = await client.post("/join", json=_fresh(m, "DL2NOPE"))
    token, p = r.json()["token"], r.json()["participant"]
    h = auth(m.lead_token)
    rej = await client.patch(
        m.url(f"/participants/{p['id']}"), json={"status": "rejected"}, headers=h
    )
    assert rej.json()["status"] == "rejected"
    me = await client.get(m.url("/me"), headers=auth(token))
    assert me.json()["status"] == "rejected"
    assert (await client.get(m.url("/snapshot"), headers=auth(token))).status_code == 403
    assert (await client.post("/join", json=_fresh(m, "DL2NOPE"))).status_code == 403
    # the lead cannot reject themselves
    me_rej = await client.patch(
        m.url(f"/participants/{m.lead_id}"), json={"status": "rejected"}, headers=h
    )
    assert me_rej.status_code == 409


async def test_auto_approve_invite_and_rotation(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    inv = (await client.post(m.url("/invites"), json={"auto_approve": True}, headers=h)).json()
    assert inv["auto_approve"] is True
    body = {"invite_token": inv["token"], "callsign": "DL2AUT", "device_secret": "a" * 20}
    r = await client.post("/join", json=body)
    assert r.json()["participant"]["status"] == "active"
    rot = (await client.post(m.url(f"/invites/{inv['id']}/rotate"), headers=h)).json()
    assert rot["auto_approve"] is True


async def test_lead_hears_about_joiners_live(client: httpx.AsyncClient, server: Server) -> None:
    m = await Mission.create(client)
    async with websockets.connect(f"{server.ws_url}/ws/missions/{m.id}?token={m.lead_token}") as ws:
        await client.post("/join", json=_fresh(m, "DL2LIVE"))
        event = {}
        while event.get("type") != "participant_updated":
            event = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert event["data"]["callsign"] == "DL2LIVE" and event["data"]["status"] == "pending"


async def test_replace_revokes_every_open_invite(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    member_token, _ = await m.join("DL2MEM")
    h = auth(m.lead_token)
    extra = (await client.post(m.url("/invites"), json={"auto_approve": True}, headers=h)).json()
    new = await client.post(m.url("/invites/replace"), headers=h)
    assert new.status_code == 201 and new.json()["auto_approve"] is False
    for old in (m.invite, extra["token"]):
        body = {"invite_token": old, "callsign": "DL2OLD", "device_secret": "o" * 20}
        assert (await client.post("/join", json=body)).status_code == 403
    body = {"invite_token": new.json()["token"], "callsign": "DL2OLD", "device_secret": "o" * 20}
    assert (await client.post("/join", json=body)).status_code == 200
    forbidden = await client.post(m.url("/invites/replace"), headers=auth(member_token))
    assert forbidden.status_code == 403


async def _post_bearing(client: httpx.AsyncClient, m: Mission, token: str, station: int) -> dict:  # type: ignore[type-arg]
    r = await client.post(
        m.url("/bearings"),
        json=bearing_payload(STATIONS[station], TARGET),
        headers=auth(token),
    )
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


async def test_open_link_joiners_do_not_move_the_estimate(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    # a lobby-approved joiner is trusted, an auto-approved one is not
    _, approved = await m.join("DL2APP")
    assert approved["trusted"] is True
    inv = (await client.post(m.url("/invites"), json={"auto_approve": True}, headers=h)).json()
    r = await client.post(
        "/join",
        json={"invite_token": inv["token"], "callsign": "DL2OPEN", "device_secret": "p" * 20},
    )
    open_token, open_p = r.json()["token"], r.json()["participant"]
    assert open_p["status"] == "active" and open_p["trusted"] is False

    await _post_bearing(client, m, m.lead_token, 0)
    await _post_bearing(client, m, m.lead_token, 1)
    assert await wait_for(lambda: _full_estimate(client, m, 2))

    # the untrusted bearing is logged and visible, but the estimate ignores it
    mine = await _post_bearing(client, m, open_token, 2)
    listed = await client.get(m.url("/bearings"), headers=h)
    assert mine["id"] in {b["id"] for b in listed.json()}
    await asyncio.sleep(1.5)
    assert (await client.get(m.url("/estimate?scope=all"), headers=h)).json()["n_bearings"] == 2
    adhoc = await client.get(m.url("/estimate/query"), headers=h)
    assert adhoc.json()["n_bearings"] == 2

    # trusting them recomputes with their bearing
    trust = await client.patch(
        m.url(f"/participants/{open_p['id']}"), json={"trusted": True}, headers=h
    )
    assert trust.status_code == 200 and trust.json()["trusted"] is True
    assert await wait_for(lambda: _full_estimate(client, m, 3))
    # ... and withdrawing trust takes it out again
    await client.patch(m.url(f"/participants/{open_p['id']}"), json={"trusted": False}, headers=h)
    assert await wait_for(lambda: _full_estimate(client, m, 2))


async def test_promotion_implies_trust_but_not_for_yourself(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    inv = (await client.post(m.url("/invites"), json={"auto_approve": True}, headers=h)).json()
    r = await client.post(
        "/join",
        json={"invite_token": inv["token"], "callsign": "DL2PRO", "device_secret": "q" * 20},
    )
    pid = r.json()["participant"]["id"]
    assert r.json()["participant"]["trusted"] is False
    up = await client.patch(m.url(f"/participants/{pid}"), json={"role": "fixed"}, headers=h)
    assert up.json()["trusted"] is True and up.json()["role"] == "fixed"
    me = await client.patch(m.url(f"/participants/{m.lead_id}"), json={"trusted": False}, headers=h)
    assert me.status_code == 409


async def test_quarantine_pulls_everything_out_at_once(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    saboteur_token, saboteur = await m.join("DL2SAB")
    await _post_bearing(client, m, m.lead_token, 0)
    await _post_bearing(client, m, m.lead_token, 1)
    bad = await _post_bearing(client, m, saboteur_token, 2)
    samples = track(TARGET, n=3)
    uploaded = await client.post(m.url("/rssi"), json=samples, headers=auth(saboteur_token))
    assert uploaded.status_code == 200, uploaded.text
    assert await wait_for(lambda: _full_estimate(client, m, 3))

    q = await client.post(m.url(f"/participants/{saboteur['id']}/quarantine"), json={}, headers=h)
    assert q.status_code == 200, q.text
    out = q.json()
    assert out["bearings_deactivated"] == 1 and out["rssi_deactivated"] == 3
    assert out["participant"]["trusted"] is False and out["participant"]["is_active"] is True
    assert await wait_for(lambda: _full_estimate(client, m, 2))

    # nothing is deleted: the bearing is still there, inactive, with a revision that says why
    listed = {b["id"]: b for b in (await client.get(m.url("/bearings"), headers=h)).json()}
    assert listed[bad["id"]]["is_active"] is False
    revs = (await client.get(m.url(f"/bearings/{bad['id']}/revisions"), headers=h)).json()
    assert any(r["changes"].get("reason") == "quarantine" for r in revs)
    # a second run finds nothing left to do
    again = await client.post(
        m.url(f"/participants/{saboteur['id']}/quarantine"), json={}, headers=h
    )
    assert again.json()["bearings_deactivated"] == 0

    # removal can be combined, the lead cannot quarantine themselves, members cannot at all
    gone = await client.post(
        m.url(f"/participants/{saboteur['id']}/quarantine"), json={"remove": True}, headers=h
    )
    assert gone.json()["participant"]["is_active"] is False
    assert (await client.get(m.url("/snapshot"), headers=auth(saboteur_token))).status_code == 401
    own = await client.post(m.url(f"/participants/{m.lead_id}/quarantine"), json={}, headers=h)
    assert own.status_code == 409
    other_token, other = await m.join("DL2OTH")
    denied = await client.post(
        m.url(f"/participants/{saboteur['id']}/quarantine"), json={}, headers=auth(other_token)
    )
    assert denied.status_code == 403


async def test_join_code_is_for_the_joiner_and_the_lead_only(
    client: httpx.AsyncClient, server: Server
) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    member_token, _ = await m.join("DL2MEM")
    async with websockets.connect(f"{server.ws_url}/ws/missions/{m.id}?token={member_token}") as ws:
        r = await client.post("/join", json=_fresh(m, "DL2CODE"))
        token, mine = r.json()["token"], r.json()["participant"]
        code = mine["join_code"]
        assert code is not None and len(code) == 4 and code.isdigit()
        # the joiner sees it again when polling, the lead sees it in the list ...
        assert (await client.get(m.url("/me"), headers=auth(token))).json()["join_code"] == code
        lead_view = {
            p["id"]: p for p in (await client.get(m.url("/participants"), headers=h)).json()
        }
        assert lead_view[mine["id"]]["join_code"] == code
        snap = (await client.get(m.url("/snapshot"), headers=h)).json()["participants"]
        assert {p["id"]: p["join_code"] for p in snap}[mine["id"]] == code
        # ... but other members and the live feed do not
        seen = {
            p["id"]: p
            for p in (await client.get(m.url("/participants"), headers=auth(member_token))).json()
        }
        assert seen[mine["id"]]["join_code"] is None
        event = {}
        while event.get("type") != "participant_updated":
            event = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert event["data"]["callsign"] == "DL2CODE" and event["data"]["join_code"] is None

    await client.patch(m.url(f"/participants/{mine['id']}"), json={"status": "active"}, headers=h)
    after = {p["id"]: p for p in (await client.get(m.url("/participants"), headers=h)).json()}
    assert after[mine["id"]]["join_code"] is None  # decided, so the code is gone
    # open links skip the lobby and need no code
    inv = (await client.post(m.url("/invites"), json={"auto_approve": True}, headers=h)).json()
    open_join = await client.post(
        "/join",
        json={"invite_token": inv["token"], "callsign": "DL2NOCODE", "device_secret": "c" * 20},
    )
    assert open_join.json()["participant"]["join_code"] is None


async def test_audit_trail_for_the_lead(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    token, p = await m.join("DL2LOG")  # joins and is approved
    await client.post(m.url(f"/participants/{p['id']}/quarantine"), json={}, headers=h)
    await client.post(m.url("/invites/replace"), headers=h)
    await client.post("/join", json=_fresh(m, "DL2LOG"))  # revoked link: refused, not logged
    bad = _fresh(m, "DL2LOG")
    inv = (await client.post(m.url("/invites"), json={}, headers=h)).json()
    bad.update(invite_token=inv["token"], device_secret="z" * 20)
    assert (await client.post("/join", json=bad)).status_code == 403  # wrong device

    entries = (await client.get(m.url("/audit"), headers=h)).json()
    seen = [(e["entity"], e["action"], e["subject"], e["actor"]) for e in entries]
    assert ("participant", "join_denied", "DL2LOG", "DL2LOG") in seen
    assert ("participant", "quarantine", "DL2LOG", "DL1ABC") in seen
    assert ("participant", "update", "DL2LOG", "DL1ABC") in seen  # the approval
    assert ("participant", "join", "DL2LOG", "DL2LOG") in seen
    assert {e["action"] for e in entries if e["entity"] == "invite"} >= {"create", "replace"}
    ids = [e["id"] for e in entries]
    assert ids == sorted(ids, reverse=True)  # newest first
    approval = next(e for e in entries if e["action"] == "update" and e["entity"] == "participant")
    assert approval["detail"]["status"] == ["pending", "active"]

    # bearing edits only show up in the full log
    sec_entities = {e["entity"] for e in entries}
    assert sec_entities <= {"participant", "invite"}
    full = (await client.get(m.url("/audit?scope=all&limit=500"), headers=h)).json()
    assert {e["entity"] for e in full} >= {"mission", "participant", "invite"}
    assert len((await client.get(m.url("/audit?limit=2"), headers=h)).json()) == 2
    assert (await client.get(m.url("/audit"), headers=auth(token))).status_code == 403


async def test_lead_returns_without_a_valid_invite(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    # the lead's own link is dead (here: revoked by a replace; expiry behaves the same)
    await client.post(m.url("/invites/replace"), headers=h)
    assert (await client.post("/join", json=_join(m, "DL1ABC"))).status_code == 403

    body = {"callsign": "DL1ABC", "device_secret": device_secret("DL1ABC")}
    r = await client.post(f"/missions/{m.id}/rejoin", json=body)
    assert r.status_code == 200
    assert r.json()["participant"]["role"] == "lead"
    new = auth(r.json()["token"])
    assert (await client.get(m.url("/snapshot"), headers=new)).status_code == 200


async def test_rejoin_needs_the_original_device_and_never_creates(
    client: httpx.AsyncClient,
) -> None:
    m = await Mission.create(client)
    _, p = await m.join("DL2OWN")
    url = f"/missions/{m.id}/rejoin"
    good = {"callsign": "DL2OWN", "device_secret": device_secret("DL2OWN")}
    assert (await client.post(url, json=good)).status_code == 200
    # wrong device, unknown callsign: same answer
    other = await client.post(url, json={**good, "device_secret": "z" * 20})
    unknown = await client.post(url, json={**good, "callsign": "DL9NEW"})
    assert other.status_code == unknown.status_code == 403
    assert other.json() == unknown.json()
    # the other mission does not know this participant
    foreign = await Mission.create(client, callsign="DL9FOR")
    assert (await client.post(f"/missions/{foreign.id}/rejoin", json=good)).status_code == 403
    # released device: no rejoin until somebody binds again
    await client.patch(
        m.url(f"/participants/{p['id']}"), json={"reset_device": True}, headers=auth(m.lead_token)
    )
    assert (await client.post(url, json=good)).status_code == 403


async def test_rejoin_respects_removal_rejection_and_end(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    _, gone = await m.join("DL2GON")
    _, bad = await m.join("DL2BAD")
    await client.patch(m.url(f"/participants/{gone['id']}"), json={"is_active": False}, headers=h)
    await client.patch(m.url(f"/participants/{bad['id']}"), json={"status": "rejected"}, headers=h)
    for cs in ("DL2GON", "DL2BAD"):
        body = {"callsign": cs, "device_secret": device_secret(cs)}
        assert (await client.post(f"/missions/{m.id}/rejoin", json=body)).status_code == 403

    assert (await client.post(m.url("/end"), headers=h)).status_code == 200
    body = {"callsign": "DL1ABC", "device_secret": device_secret("DL1ABC")}
    assert (await client.post(f"/missions/{m.id}/rejoin", json=body)).status_code == 409
