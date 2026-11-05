from __future__ import annotations

import asyncio
import contextlib
import json
import uuid

import jwt
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app import events
from app.models import Participant
from app.schemas.api import PositionIn
from app.security import decode_jwt
from app.services import domain
from app.services.permissions import Permission, has_permission, permissions_of

router = APIRouter()


async def _forward(
    ws: WebSocket, pubsub: object, participant_id: uuid.UUID, authority: str
) -> None:
    granted = {p.value for p in permissions_of(authority)}
    async for message in pubsub.listen():  # type: ignore[attr-defined]
        if message["type"] != "message":
            continue
        if _is_own_removal(message["data"], participant_id):
            await ws.close(code=4403)
            return
        if _is_own_authority_change(message["data"], participant_id, authority):
            await ws.close(code=4409)  # permissions changed: the client reconnects
            return
        # Filter by permission: e.g. an observer never receives chat or other people's positions.
        if events.event_permission(_event_type(message["data"])) in granted:
            await ws.send_text(message["data"])


def _is_own_authority_change(raw: str | bytes, participant_id: uuid.UUID, current: str) -> bool:
    try:
        event = json.loads(raw)
    except ValueError:
        return False
    data = event.get("data", {})
    return (
        event.get("type") == "participant_updated"
        and data.get("id") == str(participant_id)
        and data.get("authority", current) != current
    )


def _event_type(raw: str | bytes) -> str:
    try:
        return str(json.loads(raw).get("type", ""))
    except (ValueError, AttributeError):
        return ""


def _is_own_removal(raw: str | bytes, participant_id: uuid.UUID) -> bool:
    try:
        event = json.loads(raw)
    except ValueError:
        return False
    return event.get("type") == "participant_removed" and event.get("data", {}).get(
        "participant_id"
    ) == str(participant_id)


@router.websocket("/ws/missions/{mission_id}")
async def mission_socket(
    ws: WebSocket, mission_id: uuid.UUID, token: str | None = Query(default=None)
) -> None:
    app = ws.app
    settings, sessionmaker, redis = app.state.settings, app.state.sessionmaker, app.state.redis
    try:
        claims = decode_jwt(settings, token or "")
        pid = uuid.UUID(claims["sub"])
        if claims["mission_id"] != str(mission_id):
            raise ValueError("wrong mission")
    except (jwt.PyJWTError, KeyError, ValueError):
        await ws.close(code=4401)
        return
    async with sessionmaker() as session:
        participant = await session.get(Participant, pid)
    if (
        participant is None
        or not participant.is_active
        or participant.status != "active"
        or participant.mission_id != mission_id
        or not has_permission(participant, Permission.VIEW_RESULT)
    ):
        await ws.close(code=4403)
        return

    await ws.accept()
    pubsub = redis.pubsub()
    await pubsub.subscribe(events.channel(mission_id))
    if participant.team_id is not None:
        await pubsub.subscribe(events.channel(mission_id, participant.team_id))
    forwarder = asyncio.create_task(_forward(ws, pubsub, participant.id, participant.authority))
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
                kind = msg.get("type")
                if kind == "ping":
                    await ws.send_text(json.dumps({"type": "pong"}))
                elif kind == "position":
                    if not has_permission(participant, Permission.POSITION_SHARE):
                        await ws.send_text(json.dumps({"type": "error", "detail": "forbidden"}))
                        continue
                    item = PositionIn.model_validate(msg.get("data", {}))
                    async with sessionmaker() as session:
                        await domain.record_positions(
                            session, redis, settings, participant, [item], store_all=False
                        )
                else:
                    await ws.send_text(json.dumps({"type": "error", "detail": "unknown type"}))
            except (ValueError, ValidationError, AttributeError):
                await ws.send_text(json.dumps({"type": "error", "detail": "invalid message"}))
    except WebSocketDisconnect:
        pass
    finally:
        forwarder.cancel()
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe()
            await pubsub.aclose()
