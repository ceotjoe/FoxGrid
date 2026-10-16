from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta

import httpx
import websockets

from app.services import exporter
from app.services.push import FcmPushSender, PushTarget
from tests.conftest import BACKEND_DIR, Server
from tests.helpers import Mission, auth, bearing_payload, offset, wait_for
from tests.test_field import STATIONS, TARGET, _full_estimate


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def _join_team(m: Mission, callsign: str, team: str) -> tuple[str, dict]:
    r = await m.client.post(
        "/join",
        json={"invite_token": m.invite, "callsign": callsign, "role": "mobile", "team": team},
    )
    assert r.status_code == 200, r.text
    return r.json()["token"], r.json()["participant"]


async def _seed_estimate(client: httpx.AsyncClient, m: Mission) -> None:
    h = auth(m.lead_token)
    await client.post(m.url("/transmissions/start"), headers=h)
    for st in STATIONS:
        await client.post(m.url("/bearings"), json=bearing_payload(st, TARGET), headers=h)
    await wait_for(lambda: _full_estimate(client, m, 3))


# --- chat & teams ------------------------------------------------------------------------


async def test_chat_idempotent_and_team_channels_are_private(
    client: httpx.AsyncClient, server: Server
) -> None:
    m = await Mission.create(client)
    a_token, a = await _join_team(m, "DL1TMA", "Alpha")
    b_token, b = await _join_team(m, "DL1TMB", "Bravo")
    teams = (await client.get(m.url("/teams"), headers=auth(a_token))).json()
    team_a = next(t["id"] for t in teams if t["name"] == "Alpha")

    async with websockets.connect(f"{server.ws_url}/ws/missions/{m.id}?token={b_token}") as ws_b:
        msg = {"id": str(uuid.uuid4()), "body": "alle: Aussendung gehört", "sent_at": now_iso()}
        r = await client.post(m.url("/messages"), json=msg, headers=auth(a_token))
        assert r.status_code == 201 and r.json()["author_callsign"] == "DL1TMA"
        again = await client.post(m.url("/messages"), json=msg, headers=auth(a_token))
        assert again.status_code == 200
        stolen = await client.post(m.url("/messages"), json=msg, headers=auth(b_token))
        assert stolen.status_code == 409

        secret = {
            "id": str(uuid.uuid4()),
            "body": "nur Team Alpha",
            "sent_at": now_iso(),
            "team_id": team_a,
        }
        assert (
            await client.post(m.url("/messages"), json=secret, headers=auth(a_token))
        ).status_code == 201
        # Bravo may not post into Alpha's channel
        forbidden = await client.post(
            m.url("/messages"), json={**secret, "id": str(uuid.uuid4())}, headers=auth(b_token)
        )
        assert forbidden.status_code == 403

        event = json.loads(await asyncio.wait_for(ws_b.recv(), timeout=3))
        assert event["type"] == "message" and event["data"]["body"] == "alle: Aussendung gehört"
        # the team-only message must never reach Bravo's socket
        try:
            leaked = await asyncio.wait_for(ws_b.recv(), timeout=1.0)
        except TimeoutError:
            leaked = None
        assert leaked is None

    bravo_view = (await client.get(m.url("/messages"), headers=auth(b_token))).json()
    assert [x["body"] for x in bravo_view] == ["alle: Aussendung gehört"]
    alpha_view = (await client.get(m.url("/messages"), headers=auth(a_token))).json()
    assert len(alpha_view) == 2
    lead_view = (await client.get(m.url("/messages"), headers=auth(m.lead_token))).json()
    assert len(lead_view) == 2  # lead sees team channels


# --- tasks -------------------------------------------------------------------------------


async def test_tasks_assign_update_and_event(client: httpx.AsyncClient, server: Server) -> None:
    m = await Mission.create(client)
    p_token, p = await _join_team(m, "DL2TSK", "Alpha")
    other_token, _ = await m.join("DL2OTH")
    teams = (await client.get(m.url("/teams"), headers=auth(p_token))).json()
    team_id = teams[0]["id"]

    async with websockets.connect(f"{server.ws_url}/ws/missions/{m.id}?token={p_token}") as ws:
        task = {"id": str(uuid.uuid4()), "title": "Peilung Nordost", "assignee_team_id": team_id}
        r = await client.post(m.url("/tasks"), json=task, headers=auth(m.lead_token))
        assert r.status_code == 201 and r.json()["status"] == "open"
        assert (
            await client.post(m.url("/tasks"), json=task, headers=auth(m.lead_token))
        ).status_code == 200
        event = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
        assert event["type"] == "task_updated" and event["data"]["title"] == "Peilung Nordost"

        # team member can progress the task; an unrelated participant cannot
        tid = task["id"]
        ok = await client.patch(
            m.url(f"/tasks/{tid}"), json={"status": "in_progress"}, headers=auth(p_token)
        )
        assert ok.status_code == 200 and ok.json()["status"] == "in_progress"
        denied = await client.patch(
            m.url(f"/tasks/{tid}"), json={"status": "done"}, headers=auth(other_token)
        )
        assert denied.status_code == 403

    # assigning a participant replaces the team assignment
    re = await client.patch(
        m.url(f"/tasks/{tid}"),
        json={"assignee_participant_id": p["id"]},
        headers=auth(m.lead_token),
    )
    assert re.json()["assignee_participant_id"] == p["id"]
    assert re.json()["assignee_team_id"] is None
    both = await client.post(
        m.url("/tasks"),
        json={
            "id": str(uuid.uuid4()),
            "title": "x",
            "assignee_team_id": team_id,
            "assignee_participant_id": p["id"],
        },
        headers=auth(m.lead_token),
    )
    assert both.status_code == 422
    assert (
        await client.delete(m.url(f"/tasks/{tid}"), headers=auth(m.lead_token))
    ).status_code == 405
    listed = await client.get(m.url("/tasks?status=in_progress"), headers=auth(m.lead_token))
    assert [t["id"] for t in listed.json()] == [tid]


# --- push ---------------------------------------------------------------------------------


class FakeSender:
    def __init__(self) -> None:
        self.calls: list[tuple[list[PushTarget], str, str, dict[str, str]]] = []
        self.invalid: list[str] = []

    async def send(self, targets, title, body, data):  # type: ignore[no-untyped-def]
        self.calls.append((targets, title, body, data))
        return self.invalid


async def test_push_on_transmission_start(client: httpx.AsyncClient, server: Server) -> None:
    m = await Mission.create(client)
    t_token, _ = await m.join("DL3PSH")
    gone_token, _ = await m.join("DL3OLD")
    fake = FakeSender()
    server.app.state.push = fake  # type: ignore[attr-defined]
    for token, push_token in ((t_token, "fcm-token-participant"), (gone_token, "fcm-token-stale0")):
        r = await client.post(
            "/push-tokens", json={"platform": "fcm", "token": push_token}, headers=auth(token)
        )
        assert r.status_code == 204
    own = await client.post(
        "/push-tokens",
        json={"platform": "fcm", "token": "fcm-token-starter"},
        headers=auth(m.lead_token),
    )
    assert own.status_code == 204
    fake.invalid = ["fcm-token-stale0"]

    await client.post(m.url("/transmissions/start"), headers=auth(m.lead_token))
    await wait_for(lambda: asyncio.sleep(0, result=bool(fake.calls)))
    targets, title, body, data = fake.calls[0]
    assert title == "STÖRER SENDET" and data["type"] == "transmission_started"
    assert {t.token for t in targets} == {
        "fcm-token-participant",
        "fcm-token-stale0",
    }  # not the starter

    # stale token was removed: a second transmission only targets the live one
    await client.post(m.url("/transmissions/stop"), headers=auth(m.lead_token))
    fake.invalid = []
    await client.post(m.url("/transmissions/start"), headers=auth(m.lead_token))
    await wait_for(lambda: asyncio.sleep(0, result=len(fake.calls) == 2))
    assert {t.token for t in fake.calls[1][0]} == {"fcm-token-participant"}

    un = await client.delete(
        "/push-tokens", params={"token": "fcm-token-participant"}, headers=auth(t_token)
    )
    assert un.status_code == 204


async def test_fcm_sender_builds_messages_and_flags_invalid_tokens() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        assert request.headers["authorization"] == "Bearer abc"
        assert request.url.path == "/v1/projects/proj/messages:send"
        if body["message"]["token"] == "dead":
            return httpx.Response(404, json={"error": {"status": "NOT_FOUND"}})
        if body["message"]["token"] == "weird":
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json={"name": "ok"})

    class Sender(FcmPushSender):
        async def _access_token(self) -> str:
            return "abc"

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    sender = Sender("proj", "unused.json", client=client)
    invalid = await sender.send(
        [PushTarget("good", "fcm"), PushTarget("dead", "fcm"), PushTarget("weird", "fcm")],
        "t",
        "b",
        {"type": "x"},
    )
    assert invalid == ["dead"]
    assert seen[0]["message"]["android"]["priority"] == "HIGH"
    assert seen[0]["message"]["data"] == {"type": "x"}


# --- declination -----------------------------------------------------------------------------


async def test_declination(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    r = await client.get(
        "/declination",
        params={"lat": 48.137, "lon": 11.575, "date": "2026-10-16"},
        headers=auth(m.lead_token),
    )
    assert r.status_code == 200
    assert 3.0 < r.json()["declination_deg"] < 6.0  # Munich is a few degrees east
    west = await client.get(
        "/declination", params={"lat": 40.7, "lon": -74.0}, headers=auth(m.lead_token)
    )
    assert west.json()["declination_deg"] < -8.0  # New York is west
    assert (await client.get("/declination", params={"lat": 1, "lon": 1})).status_code == 401
    bad = await client.get("/declination", params={"lat": 99, "lon": 1}, headers=auth(m.lead_token))
    assert bad.status_code == 422


# --- contours and filters ------------------------------------------------------------------------


async def test_estimate_has_nested_contours(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    await _seed_estimate(client, m)
    est = (await client.get(m.url("/estimate?scope=all"), headers=auth(m.lead_token))).json()
    assert set(est["contours"]) == {"50", "80", "95"}
    assert all(p["type"] == "Polygon" for polys in est["contours"].values() for p in polys)


async def test_estimate_query_filters(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    assert (await client.get(m.url("/estimate/query"), headers=h)).status_code == 404

    tx1 = (await client.post(m.url("/transmissions/start"), headers=h)).json()
    for st in STATIONS[:2]:
        await client.post(m.url("/bearings"), json=bearing_payload(st, TARGET), headers=h)
    await client.post(m.url("/transmissions/stop"), headers=h)
    await asyncio.sleep(0.2)
    cut = datetime.now(UTC)
    await asyncio.sleep(0.2)
    tx2 = (await client.post(m.url("/transmissions/start"), headers=h)).json()
    for st in STATIONS:
        await client.post(m.url("/bearings"), json=bearing_payload(st, TARGET), headers=h)

    only1 = await client.get(
        m.url("/estimate/query"), params={"transmission": tx1["id"]}, headers=h
    )
    assert only1.status_code == 200 and only1.json()["n_bearings"] == 2
    only2 = await client.get(
        m.url("/estimate/query"), params={"transmission": tx2["id"]}, headers=h
    )
    assert only2.json()["n_bearings"] == 3
    after = await client.get(m.url("/estimate/query"), params={"since": cut.isoformat()}, headers=h)
    assert after.json()["n_bearings"] == 3
    before = await client.get(
        m.url("/estimate/query"), params={"until": cut.isoformat()}, headers=h
    )
    assert before.json()["n_bearings"] == 2
    weighted = await client.get(m.url("/estimate/query"), params={"half_life_s": 60}, headers=h)
    assert weighted.status_code == 200 and weighted.json()["n_bearings"] == 5
    none = await client.get(
        m.url("/estimate/query"), params={"since": (cut + timedelta(days=1)).isoformat()}, headers=h
    )
    assert none.status_code == 404
    # ad-hoc queries are not stored
    hist = await client.get(m.url("/estimate/history?scope=all"), headers=h)
    assert all(e["n_bearings"] in (2, 3, 5) for e in hist.json())


# --- exports --------------------------------------------------------------------------------------


async def test_exports(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client, name="Export & <Test>")
    h = auth(m.lead_token)
    await client.post(
        m.url("/positions"),
        json=[
            {"lat": 48.1, "lon": 11.5, "recorded_at": now_iso()},
            {"lat": 48.11, "lon": 11.51, "recorded_at": now_iso()},
        ],
        headers=h,
    )
    await _seed_estimate(client, m)
    bad = bearing_payload(offset(-3000, 6000), TARGET, note="Reflexion <b>")
    bid = (await client.post(m.url("/bearings"), json=bad, headers=h)).json()["id"]
    await client.patch(m.url(f"/bearings/{bid}"), json={"is_outlier": True}, headers=h)

    gpx = await client.get(m.url("/export.gpx"), headers=h)
    assert gpx.status_code == 200 and "attachment" in gpx.headers["content-disposition"]
    root = ET.fromstring(gpx.content)
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    assert len(root.findall("g:wpt", ns)) == 1 + 4  # estimate + 4 bearings
    assert len(root.findall("g:rte", ns)) == 4
    assert len(root.findall("g:trk/g:trkseg/g:trkpt", ns)) == 2
    assert any("[Ausreißer]" in (n.text or "") for n in root.iterfind(".//g:wpt/g:name", ns))

    kml = await client.get(m.url("/export.kml"), headers=h)
    kroot = ET.fromstring(kml.content)
    k = {"k": "http://www.opengis.net/kml/2.2"}
    assert len(kroot.findall(".//k:Folder/k:Placemark/k:LineString", k)) >= 4
    names = [n.text for n in kroot.iterfind(".//k:Placemark/k:name", k)]
    assert "Ellipse 1σ" in names and any((n or "").startswith("95 %") for n in names)

    js = (await client.get(m.url("/export.json"), headers=h)).json()
    assert js["format"] == "foxgrid-export/1" and len(js["bearings"]) == 4
    assert js["bearing_revisions"][0]["changes"]["is_outlier"]["to"] is True
    assert js["mission"]["name"] == "Export & <Test>" and len(js["positions"]) == 2
    assert js["estimates"]

    pdf = await client.get(m.url("/export.pdf"), headers=h)
    assert pdf.content.startswith(b"%PDF") and len(pdf.content) > 3000
    assert pdf.headers["content-type"] == "application/pdf"

    other = await Mission.create(client, callsign="DL8OTH")
    assert (
        await client.get(m.url("/export.gpx"), headers=auth(other.lead_token))
    ).status_code == 403
    assert (await client.get(m.url("/export.txt"), headers=h)).status_code == 422


async def test_exports_work_for_an_empty_mission(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    h = auth(m.lead_token)
    for fmt in ("gpx", "kml", "json", "pdf"):
        r = await client.get(m.url(f"/export.{fmt}"), headers=h)
        assert r.status_code == 200, fmt
    assert (await client.get(m.url("/export.pdf"), headers=h)).content.startswith(b"%PDF")


def test_clip_segment_and_scale_helpers() -> None:
    box = (0.0, 0.0, 10.0, 10.0)
    assert exporter._clip_segment((-5, 5), (15, 5), box) == ((0.0, 5.0), (10.0, 5.0))
    assert exporter._clip_segment((-5, -5), (-1, -1), box) is None
    assert exporter._clip_segment((2, 2), (4, 4), box) == ((2, 2), (4, 4))
    assert exporter._clip_segment((5, 20), (5, 30), box) is None  # parallel and outside
    assert exporter._nice_length(730) == 1000.0
    assert exporter._nice_length(1400) == 2000.0
    assert exporter._nice_length(3200) == 5000.0


# --- schema drift --------------------------------------------------------------------


def test_models_match_migrations(database_url: str) -> None:
    """`alembic check` fails when the ORM models drift from the migrations."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        cwd=BACKEND_DIR,
        env={**os.environ, "FOXGRID_DATABASE_URL": database_url},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


async def test_snapshot_contains_chat_tasks_and_teams(client: httpx.AsyncClient) -> None:
    m = await Mission.create(client)
    a_token, _ = await _join_team(m, "DL4SNA", "Alpha")
    b_token, _ = await _join_team(m, "DL4SNB", "Bravo")
    team_a = next(
        t["id"]
        for t in (await client.get(m.url("/teams"), headers=auth(a_token))).json()
        if t["name"] == "Alpha"
    )
    for body, team in (("public", None), ("alpha only", team_a)):
        await client.post(
            m.url("/messages"),
            json={"id": str(uuid.uuid4()), "body": body, "sent_at": now_iso(), "team_id": team},
            headers=auth(a_token),
        )
    await client.post(
        m.url("/tasks"), json={"id": str(uuid.uuid4()), "title": "Wache"}, headers=auth(a_token)
    )
    snap_b = (await client.get(m.url("/snapshot"), headers=auth(b_token))).json()
    assert [x["body"] for x in snap_b["messages"]] == ["public"]
    assert len(snap_b["tasks"]) == 1 and {t["name"] for t in snap_b["teams"]} == {"Alpha", "Bravo"}
    snap_a = (await client.get(m.url("/snapshot"), headers=auth(a_token))).json()
    assert [x["body"] for x in snap_a["messages"]] == ["public", "alpha only"]
