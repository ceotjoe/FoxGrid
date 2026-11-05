"""External bearing points: named locations whose bearings the lead enters (e.g. BNetzA)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import events
from app.api.deps import get_redis, get_scheduler, require
from app.db import get_session
from app.models import BearingPoint, Mission, Participant
from app.schemas.api import PointIn, PointOut, PointPatch
from app.services import domain
from app.services.permissions import Permission
from app.services.recompute import RecomputeScheduler
from app.services.serialize import event_json, point_out

router = APIRouter(prefix="/missions/{mission_id}")


def _same_point(existing: BearingPoint, body: PointIn) -> bool:
    return (
        existing.name == body.name.strip()
        and abs(existing.lat - body.lat) < 1e-9
        and abs(existing.lon - body.lon) < 1e-9
    )


@router.post("/points", response_model=PointOut, status_code=201)
async def create_point(
    mission_id: uuid.UUID,
    body: PointIn,
    response: Response,
    actor: Participant = Depends(require(Permission.POINT_MANAGE)),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> PointOut:
    """Idempotent on the client UUID: a retry with the same content returns 200."""
    existing = await session.get(BearingPoint, body.id)
    if existing is not None:
        if existing.mission_id != mission_id or not _same_point(existing, body):
            raise HTTPException(409, "point id already used with different content")
        response.status_code = 200
        return point_out(existing)
    if await session.get(Mission, mission_id) is None:
        raise HTTPException(404, "mission not found")
    point = BearingPoint(
        id=body.id,
        mission_id=mission_id,
        name=body.name.strip(),
        lat=body.lat,
        lon=body.lon,
        accuracy_m=body.accuracy_m,
        note=body.note,
        use_in_estimate=body.use_in_estimate,
        created_by=actor.id,
    )
    session.add(point)
    await domain.audit(
        session,
        mission_id,
        actor.id,
        "create",
        "point",
        body.id,
        name=point.name,
        lat=body.lat,
        lon=body.lon,
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "a point with this name already exists") from exc
    out = point_out(point)
    await events.publish(redis, mission_id, "point_created", event_json(out))
    return out


@router.get("/points", response_model=list[PointOut])
async def list_points(
    mission_id: uuid.UUID,
    _: Participant = Depends(require(Permission.VIEW_RESULT)),
    session: AsyncSession = Depends(get_session),
) -> list[PointOut]:
    rows = await session.scalars(
        select(BearingPoint)
        .where(BearingPoint.mission_id == mission_id)
        .order_by(BearingPoint.created_at)
    )
    return [point_out(p) for p in rows]


@router.patch("/points/{point_id}", response_model=PointOut)
async def patch_point(
    mission_id: uuid.UUID,
    point_id: uuid.UUID,
    body: PointPatch,
    actor: Participant = Depends(require(Permission.POINT_MANAGE)),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    scheduler: RecomputeScheduler = Depends(get_scheduler),
) -> PointOut:
    """Rename, switch the estimate on/off or deactivate. Points can never be deleted."""
    point = await session.get(BearingPoint, point_id)
    if point is None or point.mission_id != mission_id:
        raise HTTPException(404, "point not found")
    changes: dict[str, dict[str, object]] = {}
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is None and field != "note":
            continue
        old = getattr(point, field)
        if old != value:
            changes[field] = {"from": old, "to": value}
            setattr(point, field, value)
    if not changes:
        return point_out(point)
    await domain.audit(session, mission_id, actor.id, "update", "point", point_id, **changes)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "a point with this name already exists") from exc
    out = point_out(point)
    await events.publish(redis, mission_id, "point_updated", event_json(out))
    if "use_in_estimate" in changes or "is_active" in changes:
        scheduler.schedule(mission_id)
    return out
