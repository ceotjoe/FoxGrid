"""Endpoint permissions per authority (the matrix itself is tested in test_permissions)."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

from tests.conftest import Server
from tests.helpers import Mission, auth, bearing_payload, offset, set_authority
from tests.test_field import STATIONS, TARGET

AUTHORITIES = ("deputy", "analyst", "coordinator", "member", "observer")


class Crew:
    """A mission with one participant per authority, plus the lead."""

    def __init__(self, m: Mission, tokens: dict[str, str], ids: dict[str, str]) -> None:
        self.m, self.tokens, self.ids = m, tokens, ids

    def h(self, who: str) -> dict[str, str]:
        return auth(self.m.lead_token if who == "lead" else self.tokens[who])

    @classmethod
    async def create(cls, client: httpx.AsyncClient, database_url: str) -> Crew:
        m = await Mission.create(client)
        tokens: dict[str, str] = {}
        ids: dict[str, str] = {"lead": m.lead_id}
        for authority in AUTHORITIES:
            token, participant = await m.join(f"DL9{authority[:3].upper()}")
            await set_authority(database_url, participant["id"], authority)
            tokens[authority], ids[authority] = token, participant["id"]
        return cls(m, tokens, ids)


async def _status(
    client: httpx.AsyncClient, method: str, url: str, who_headers: dict[str, str], **kw: Any
) -> int:
    return (await client.request(method, url, headers=who_headers, **kw)).status_code


def point_body(name: str = "BNetzA") -> dict[str, Any]:
    pos = offset(100, 100)
    return {"id": str(uuid.uuid4()), "name": name, "lat": pos[0], "lon": pos[1]}


async def test_external_points_for_lead_deputy_and_analyst_only(
    client: httpx.AsyncClient, database_url: str
) -> None:
    c = await Crew.create(client, database_url)
    allowed = {"lead", "deputy", "analyst"}
    for who in ("lead", *AUTHORITIES):
        r = await client.post(c.m.url("/points"), json=point_body(f"P-{who}"), headers=c.h(who))
        assert r.status_code == (201 if who in allowed else 403), (who, r.text)
        if r.status_code == 201:
            pos = (r.json()["lat"], r.json()["lon"])
            payload = bearing_payload(pos, TARGET, point_id=r.json()["id"])
            ok = await client.post(c.m.url("/bearings"), json=payload, headers=c.h(who))
            assert ok.status_code == 201, (who, ok.text)
    # a point exists now, so the denied ones can try an external bearing against it
    point = (await client.get(c.m.url("/points"), headers=c.h("member"))).json()[0]
    pos = (point["lat"], point["lon"])
    for who in ("coordinator", "member", "observer"):
        payload = bearing_payload(pos, TARGET, point_id=point["id"])
        r = await client.post(c.m.url("/bearings"), json=payload, headers=c.h(who))
        assert r.status_code == 403, who


async def test_observer_sees_the_result_but_no_chat_or_positions(
    client: httpx.AsyncClient, database_url: str
) -> None:
    c = await Crew.create(client, database_url)
    h = c.h("lead")
    await client.post(
        c.m.url("/messages"),
        json={"id": str(uuid.uuid4()), "body": "hello", "sent_at": datetime.now(UTC).isoformat()},
        headers=h,
    )
    await client.post(
        c.m.url("/tasks"), json={"id": str(uuid.uuid4()), "title": "Wache"}, headers=h
    )
    pos = [{"lat": 48.1, "lon": 11.5, "recorded_at": datetime.now(UTC).isoformat()}]
    assert (await client.post(c.m.url("/positions"), json=pos, headers=h)).status_code == 202
    for st in STATIONS:
        await client.post(c.m.url("/bearings"), json=bearing_payload(st, TARGET), headers=h)

    obs = c.h("observer")
    snap = (await client.get(c.m.url("/snapshot"), headers=obs)).json()
    assert snap["positions"] == [] and snap["messages"] == [] and snap["tasks"] == []
    assert len(snap["bearings"]) == len(STATIONS)  # the result itself is visible
    lead_snap = (await client.get(c.m.url("/snapshot"), headers=h)).json()
    assert lead_snap["positions"] and lead_snap["messages"] and lead_snap["tasks"]

    assert (await client.get(c.m.url("/estimate"), headers=obs)).status_code in (200, 404)
    assert (await client.get(c.m.url("/bearings"), headers=obs)).status_code == 200
    denied = [
        ("GET", "/messages", {}),
        ("GET", "/positions", {}),
        ("GET", "/tasks", {}),
        ("GET", "/teams", {}),
        ("POST", "/positions", {"json": pos}),
        ("POST", "/bearings", {"json": bearing_payload(STATIONS[0], TARGET)}),
        ("POST", "/rssi", {"json": []}),
        (
            "POST",
            "/messages",
            {
                "json": {
                    "id": str(uuid.uuid4()),
                    "body": "x",
                    "sent_at": datetime.now(UTC).isoformat(),
                }
            },
        ),
    ]
    for method, path, kw in denied:
        assert await _status(client, method, c.m.url(path), obs, **kw) == 403, path


async def test_observer_export_has_no_tracks(client: httpx.AsyncClient, database_url: str) -> None:
    c = await Crew.create(client, database_url)
    pos = [{"lat": 48.1, "lon": 11.5, "recorded_at": datetime.now(UTC).isoformat()}]
    await client.post(c.m.url("/positions"), json=pos, headers=c.h("lead"))
    lead_json = (await client.get(c.m.url("/export.json"), headers=c.h("lead"))).json()
    obs_json = (await client.get(c.m.url("/export.json"), headers=c.h("observer"))).json()
    assert lead_json["positions"] and obs_json["positions"] == []
    assert (await client.get(c.m.url("/export.gpx"), headers=c.h("observer"))).status_code == 200


async def test_observer_websocket_gets_no_chat_or_positions(
    client: httpx.AsyncClient, server: Server, database_url: str
) -> None:
    c = await Crew.create(client, database_url)
    url = f"{server.ws_url}/ws/missions/{c.m.id}?token={c.tokens['observer']}"
    async with websockets.connect(url) as ws:
        h = c.h("lead")
        await client.post(
            c.m.url("/messages"),
            json={
                "id": str(uuid.uuid4()),
                "body": "secret",
                "sent_at": datetime.now(UTC).isoformat(),
            },
            headers=h,
        )
        await ws.send(json.dumps({"type": "position", "data": {"lat": 1, "lon": 1}}))
        pos = [{"lat": 48.1, "lon": 11.5, "recorded_at": datetime.now(UTC).isoformat()}]
        await client.post(c.m.url("/positions"), json=pos, headers=h)
        await client.post(
            c.m.url("/bearings"), json=bearing_payload(STATIONS[0], TARGET), headers=h
        )
        seen: list[str] = []
        while "bearing_created" not in seen:
            event = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            seen.append(event["type"])
            if event["type"] == "error":
                assert event["detail"] == "forbidden"
        assert "message" not in seen and "participant_position" not in seen


async def test_websocket_closes_when_the_authority_changes(
    client: httpx.AsyncClient, server: Server, database_url: str
) -> None:
    c = await Crew.create(client, database_url)
    url = f"{server.ws_url}/ws/missions/{c.m.id}?token={c.tokens['member']}"
    async with websockets.connect(url) as ws:
        await set_authority(database_url, c.ids["member"], "observer")
        # any announced change of that participant carries the new authority
        r = await client.patch(
            c.m.url(f"/participants/{c.ids['member']}"),
            json={"trusted": False},
            headers=c.h("lead"),
        )
        assert r.status_code == 200
        try:
            while True:
                await asyncio.wait_for(ws.recv(), timeout=5)
        except ConnectionClosed as closed:
            assert closed.rcvd is not None and closed.rcvd.code == 4409


async def test_coordinator_organises_but_does_not_administer(
    client: httpx.AsyncClient, database_url: str
) -> None:
    c = await Crew.create(client, database_url)
    h = c.h("coordinator")
    task = {"id": str(uuid.uuid4()), "title": "Wache"}
    assert (await client.post(c.m.url("/tasks"), json=task, headers=h)).status_code == 201
    # plain members cannot create tasks, but can work on theirs
    assert (
        await client.post(
            c.m.url("/tasks"), json={"id": str(uuid.uuid4()), "title": "x"}, headers=c.h("member")
        )
    ).status_code == 403
    # invites: ordinary links only, approval stays on
    assert (await client.post(c.m.url("/invites"), json={}, headers=h)).status_code == 201
    for body in ({"default_role": "fixed"}, {"auto_approve": True}):
        assert (await client.post(c.m.url("/invites"), json=body, headers=h)).status_code == 403
    for method, path, kw in (
        ("POST", "/invites/replace", {}),
        ("GET", "/audit", {}),
        ("PATCH", f"/participants/{c.ids['member']}", {"json": {"is_active": False}}),
        ("PATCH", f"/participants/{c.ids['member']}", {"json": {"trusted": False}}),
        ("POST", f"/participants/{c.ids['member']}/quarantine", {"json": {}}),
        ("POST", "/points", {"json": point_body()}),
        ("POST", "/end", {}),
    ):
        assert await _status(client, method, c.m.url(path), h, **kw) == 403, path


async def test_analyst_judges_data_but_does_not_administer(
    client: httpx.AsyncClient, database_url: str
) -> None:
    c = await Crew.create(client, database_url)
    a, lead = c.h("analyst"), c.h("lead")
    b = bearing_payload(STATIONS[0], TARGET)
    assert (
        await client.post(c.m.url("/bearings"), json=b, headers=c.h("member"))
    ).status_code == 201
    # flags on somebody else's bearing: yes; editing its note: no (deputy/lead only)
    flag = await client.patch(c.m.url(f"/bearings/{b['id']}"), json={"is_outlier": True}, headers=a)
    assert flag.status_code == 200
    note = await client.patch(c.m.url(f"/bearings/{b['id']}"), json={"note": "x"}, headers=a)
    assert note.status_code == 403
    assert (
        await client.patch(c.m.url(f"/bearings/{b['id']}"), json={"note": "x"}, headers=lead)
    ).status_code == 200
    # trust yes; approval, role, tasks, invites, audit no
    pid = c.ids["member"]
    assert (
        await client.patch(c.m.url(f"/participants/{pid}"), json={"trusted": False}, headers=a)
    ).status_code == 200
    assert (await client.get(c.m.url("/plausibility"), headers=a)).status_code == 200
    for method, path, kw in (
        ("PATCH", f"/participants/{pid}", {"json": {"status": "rejected"}}),
        ("PATCH", f"/participants/{pid}", {"json": {"role": "fixed"}}),
        ("POST", "/tasks", {"json": {"id": str(uuid.uuid4()), "title": "x"}}),
        ("POST", "/invites", {"json": {}}),
        ("GET", "/audit", {}),
        ("POST", f"/participants/{pid}/quarantine", {"json": {}}),
    ):
        assert await _status(client, method, c.m.url(path), a, **kw) == 403, (method, path)


async def test_members_cannot_flag_other_peoples_bearings(
    client: httpx.AsyncClient, database_url: str
) -> None:
    c = await Crew.create(client, database_url)
    b = bearing_payload(STATIONS[0], TARGET)
    await client.post(c.m.url("/bearings"), json=b, headers=c.h("lead"))
    r = await client.patch(
        c.m.url(f"/bearings/{b['id']}"), json={"is_outlier": True}, headers=c.h("member")
    )
    assert r.status_code == 403


async def test_deputy_administers_but_neither_assigns_roles_nor_ends_nor_touches_the_lead(
    client: httpx.AsyncClient, database_url: str
) -> None:
    c = await Crew.create(client, database_url)
    d, pid = c.h("deputy"), c.ids["member"]
    assert (
        await client.patch(c.m.url(f"/participants/{pid}"), json={"trusted": False}, headers=d)
    ).status_code == 200
    assert (await client.get(c.m.url("/audit"), headers=d)).status_code == 200
    assert (await client.post(c.m.url("/invites"), json={}, headers=d)).status_code == 201
    assert (
        await client.post(c.m.url(f"/participants/{pid}/quarantine"), json={}, headers=d)
    ).status_code == 200
    assert (
        await client.patch(c.m.url(f"/participants/{pid}"), json={"role": "fixed"}, headers=d)
    ).status_code == 403
    assert (
        await client.patch(
            c.m.url(f"/participants/{c.ids['lead']}"), json={"trusted": False}, headers=d
        )
    ).status_code == 403
    assert (
        await client.post(c.m.url(f"/participants/{c.ids['lead']}/quarantine"), json={}, headers=d)
    ).status_code == 403
    assert (await client.post(c.m.url("/end"), headers=d)).status_code == 403
    assert (await client.post(c.m.url("/end"), headers=c.h("lead"))).status_code == 200


async def test_member_is_a_plain_bearer(client: httpx.AsyncClient, database_url: str) -> None:
    c = await Crew.create(client, database_url)
    m = c.h("member")
    assert (
        await client.post(
            c.m.url("/bearings"), json=bearing_payload(STATIONS[0], TARGET), headers=m
        )
    ).status_code == 201
    assert (await client.get(c.m.url("/snapshot"), headers=m)).status_code == 200
    for method, path, kw in (
        ("POST", "/points", {"json": point_body()}),
        ("POST", "/invites", {"json": {}}),
        ("GET", "/audit", {}),
        ("GET", "/plausibility", {}),
        ("PATCH", f"/participants/{c.ids['observer']}", {"json": {"trusted": False}}),
        ("POST", "/sensors", {"json": {"name": "x"}}),
        ("POST", "/end", {}),
    ):
        assert await _status(client, method, c.m.url(path), m, **kw) == 403, path
