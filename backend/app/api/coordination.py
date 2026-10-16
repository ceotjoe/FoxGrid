"""Chat, tasks, teams and push tokens."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from redis.asyncio import Redis
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import events
from app.api.deps import current_participant, get_redis, member
from app.db import get_session
from app.models import Message, Participant, PushToken, Task, TaskEvent, Team
from app.schemas.api import (
    MessageIn,
    MessageOut,
    PushTokenIn,
    TaskIn,
    TaskOut,
    TaskPatch,
    TeamOut,
)
from app.services import domain
from app.services.serialize import event_json, message_out, task_out

router = APIRouter()
mission_router = APIRouter(prefix="/missions/{mission_id}")


async def _check_team(session: AsyncSession, mission_id: uuid.UUID, team_id: uuid.UUID) -> None:
    team = await session.get(Team, team_id)
    if team is None or team.mission_id != mission_id:
        raise HTTPException(422, "unknown team")


async def _check_assignee(
    session: AsyncSession,
    mission_id: uuid.UUID,
    participant_id: uuid.UUID | None,
    team_id: uuid.UUID | None,
) -> None:
    if participant_id and team_id:
        raise HTTPException(422, "assign to a participant or a team, not both")
    if participant_id:
        p = await session.get(Participant, participant_id)
        if p is None or p.mission_id != mission_id:
            raise HTTPException(422, "unknown participant")
    if team_id:
        await _check_team(session, mission_id, team_id)


# --- teams ---------------------------------------------------------------------------------


@mission_router.get("/teams", response_model=list[TeamOut])
async def list_teams(
    mission_id: uuid.UUID,
    _: Participant = Depends(member),
    session: AsyncSession = Depends(get_session),
) -> list[Team]:
    rows = await session.scalars(select(Team).where(Team.mission_id == mission_id))
    return list(rows)


# --- chat ----------------------------------------------------------------------------------


@mission_router.post("/messages", response_model=MessageOut, status_code=201)
async def post_message(
    mission_id: uuid.UUID,
    body: MessageIn,
    response: Response,
    actor: Participant = Depends(member),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> MessageOut:
    """Idempotent on the client UUID. Team messages stay inside that team's channel."""
    existing = await session.get(Message, body.id)
    if existing is not None:
        if existing.mission_id != mission_id or existing.author_id != actor.id:
            raise HTTPException(409, "message id already used")
        response.status_code = 200
        return message_out(existing, actor.callsign)
    if body.team_id is not None:
        await _check_team(session, mission_id, body.team_id)
        if actor.team_id != body.team_id and actor.role != "lead":
            raise HTTPException(403, "not a member of this team")
    msg = Message(
        id=body.id,
        mission_id=mission_id,
        author_id=actor.id,
        team_id=body.team_id,
        body=body.body,
        sent_at=body.sent_at,
    )
    session.add(msg)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        response.status_code = 200
        existing = await session.get(Message, body.id)
        if existing is None:
            raise
        return message_out(existing, actor.callsign)
    out = message_out(msg, actor.callsign)
    await events.publish(redis, mission_id, "message", event_json(out), team_id=body.team_id)
    return out


@mission_router.get("/messages", response_model=list[MessageOut])
async def list_messages(
    mission_id: uuid.UUID,
    since: datetime | None = None,
    limit: int = Query(default=200, le=1000),
    actor: Participant = Depends(member),
    session: AsyncSession = Depends(get_session),
) -> list[MessageOut]:
    visible = domain.visible_messages(actor)
    stmt = (
        select(Message, Participant.callsign)
        .join(Participant, Participant.id == Message.author_id)
        .where(Message.mission_id == mission_id, visible)
    )
    if since:
        stmt = stmt.where(Message.received_at >= since)
    rows = (await session.execute(stmt.order_by(Message.sent_at).limit(limit))).all()
    return [message_out(m, cs) for m, cs in rows]


# --- tasks ---------------------------------------------------------------------------------


@mission_router.post("/tasks", response_model=TaskOut, status_code=201)
async def create_task(
    mission_id: uuid.UUID,
    body: TaskIn,
    response: Response,
    actor: Participant = Depends(member),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> TaskOut:
    existing = await session.get(Task, body.id)
    if existing is not None:
        if existing.mission_id != mission_id or existing.created_by != actor.id:
            raise HTTPException(409, "task id already used")
        response.status_code = 200
        return task_out(existing)
    await _check_assignee(session, mission_id, body.assignee_participant_id, body.assignee_team_id)
    task = Task(
        id=body.id,
        mission_id=mission_id,
        title=body.title,
        description=body.description,
        assignee_participant_id=body.assignee_participant_id,
        assignee_team_id=body.assignee_team_id,
        created_by=actor.id,
        lat=body.lat,
        lon=body.lon,
    )
    session.add(task)
    await session.flush()
    session.add(TaskEvent(task_id=task.id, actor_id=actor.id, change={"created": True}))
    await session.commit()
    out = task_out(task)
    await events.publish(redis, mission_id, "task_updated", event_json(out))
    return out


@mission_router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(
    mission_id: uuid.UUID,
    status: str | None = None,
    _: Participant = Depends(member),
    session: AsyncSession = Depends(get_session),
) -> list[TaskOut]:
    stmt = select(Task).where(Task.mission_id == mission_id)
    if status:
        stmt = stmt.where(Task.status == status)
    rows = await session.scalars(stmt.order_by(Task.created_at))
    return [task_out(t) for t in rows]


@mission_router.patch("/tasks/{task_id}", response_model=TaskOut)
async def patch_task(
    mission_id: uuid.UUID,
    task_id: uuid.UUID,
    body: TaskPatch,
    actor: Participant = Depends(member),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> TaskOut:
    """Tasks are never deleted; cancel them instead. Lead, creator and assignees may edit."""
    task = await session.get(Task, task_id)
    if task is None or task.mission_id != mission_id:
        raise HTTPException(404, "task not found")
    is_assignee = task.assignee_participant_id == actor.id or (
        task.assignee_team_id is not None and task.assignee_team_id == actor.team_id
    )
    if actor.role != "lead" and task.created_by != actor.id and not is_assignee:
        raise HTTPException(403, "not allowed to change this task")

    changes = body.model_dump(exclude_unset=True)
    if {"assignee_participant_id", "assignee_team_id"} & changes.keys():
        new_p = changes.get("assignee_participant_id", task.assignee_participant_id)
        new_t = changes.get("assignee_team_id", task.assignee_team_id)
        # assigning one kind replaces the other
        if "assignee_participant_id" in changes and changes["assignee_participant_id"]:
            new_t = None
            changes["assignee_team_id"] = None
        if "assignee_team_id" in changes and changes["assignee_team_id"]:
            new_p = None
            changes["assignee_participant_id"] = None
        await _check_assignee(session, mission_id, new_p, new_t)
    diff: dict[str, dict[str, object]] = {}
    for field, value in changes.items():
        old = getattr(task, field)
        if old != value:
            diff[field] = {"from": old, "to": value}
            setattr(task, field, value)
    if diff:
        task.updated_at = datetime.now(UTC)
        session.add(TaskEvent(task_id=task.id, actor_id=actor.id, change=_jsonable(diff)))
        await session.commit()
        await events.publish(redis, mission_id, "task_updated", event_json(task_out(task)))
    return task_out(task)


def _jsonable(diff: dict[str, dict[str, object]]) -> dict[str, dict[str, object]]:
    return {
        k: {a: str(b) if isinstance(b, uuid.UUID) else b for a, b in v.items()}
        for k, v in diff.items()
    }


# --- push tokens -------------------------------------------------------------------------------


@router.post("/push-tokens", status_code=204)
async def register_push_token(
    body: PushTokenIn,
    actor: Participant = Depends(current_participant),
    session: AsyncSession = Depends(get_session),
) -> None:
    existing = await session.scalar(select(PushToken).where(PushToken.token == body.token))
    if existing is None:
        session.add(PushToken(participant_id=actor.id, platform=body.platform, token=body.token))
    else:  # device handed over to another participant
        existing.participant_id = actor.id
        existing.platform = body.platform
    await session.commit()


@router.delete("/push-tokens", status_code=204)
async def unregister_push_token(
    token: str,
    actor: Participant = Depends(current_participant),
    session: AsyncSession = Depends(get_session),
) -> None:
    await session.execute(
        delete(PushToken).where(PushToken.token == token, PushToken.participant_id == actor.id)
    )
    await session.commit()
