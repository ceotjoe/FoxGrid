"""Interferers: the sources a mission is looking for. Bearings and readings belong to one each."""

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
from app.models import Interferer, Mission, Participant
from app.schemas.api import InterfererIn, InterfererOut, InterfererPatch
from app.services import domain
from app.services.permissions import Permission
from app.services.recompute import RecomputeScheduler
from app.services.serialize import event_json, interferer_out

router = APIRouter(prefix="/missions/{mission_id}")


def _same_interferer(existing: Interferer, body: InterfererIn) -> bool:
    return existing.name == body.name.strip()


@router.post("/interferers", response_model=InterfererOut, status_code=201)
async def create_interferer(
    mission_id: uuid.UUID,
    body: InterfererIn,
    response: Response,
    actor: Participant = Depends(require(Permission.INTERFERER_MANAGE)),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> InterfererOut:
    """Idempotent on the client UUID: a retry with the same name returns 200."""
    existing = await session.get(Interferer, body.id)
    if existing is not None:
        if existing.mission_id != mission_id or not _same_interferer(existing, body):
            raise HTTPException(409, "interferer id already used with different content")
        response.status_code = 200
        return interferer_out(existing)
    if await session.get(Mission, mission_id) is None:
        raise HTTPException(404, "mission not found")
    free = await domain.free_color_slot(session, mission_id)
    slot = body.color_slot if body.color_slot is not None else free
    if free is None:
        raise HTTPException(409, "the maximum number of active interferers is reached")
    taken = await session.scalar(
        select(Interferer.id).where(
            Interferer.mission_id == mission_id,
            Interferer.is_active.is_(True),
            Interferer.color_slot == slot,
        )
    )
    if taken is not None:
        raise HTTPException(409, "colour slot already used by an active interferer")
    assert slot is not None
    interferer = Interferer(
        id=body.id,
        mission_id=mission_id,
        name=body.name.strip(),
        color_slot=slot,
        note=body.note,
        frequency_mhz=body.frequency_mhz,
        created_by=actor.id,
    )
    session.add(interferer)
    await domain.audit(
        session,
        mission_id,
        actor.id,
        "create",
        "interferer",
        body.id,
        name=interferer.name,
        color_slot=slot,
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "an interferer with this name already exists") from exc
    out = interferer_out(interferer)
    await events.publish(redis, mission_id, "interferer_created", event_json(out))
    return out


@router.get("/interferers", response_model=list[InterfererOut])
async def list_interferers(
    mission_id: uuid.UUID,
    _: Participant = Depends(require(Permission.VIEW_RESULT)),
    session: AsyncSession = Depends(get_session),
) -> list[InterfererOut]:
    rows = await session.scalars(
        select(Interferer)
        .where(Interferer.mission_id == mission_id)
        .order_by(Interferer.created_at, Interferer.id)
    )
    return [interferer_out(i) for i in rows]


@router.patch("/interferers/{interferer_id}", response_model=InterfererOut)
async def patch_interferer(
    mission_id: uuid.UUID,
    interferer_id: uuid.UUID,
    body: InterfererPatch,
    actor: Participant = Depends(require(Permission.INTERFERER_MANAGE)),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    scheduler: RecomputeScheduler = Depends(get_scheduler),
) -> InterfererOut:
    """Rename, mark as resolved or deactivate. Interferers can never be deleted."""
    interferer = await session.get(Interferer, interferer_id)
    if interferer is None or interferer.mission_id != mission_id:
        raise HTTPException(404, "interferer not found")
    changes: dict[str, dict[str, object]] = {}
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is None and field not in ("note", "frequency_mhz"):
            continue
        old = getattr(interferer, field)
        if field == "frequency_mhz":
            old = None if old is None else float(old)
        if old != value:
            changes[field] = {"from": old, "to": value}
            setattr(interferer, field, value)
    if not changes:
        return interferer_out(interferer)
    if changes.get("is_active", {}).get("to") is True:
        # Reactivating needs its colour slot to be free again.
        clash = await session.scalar(
            select(Interferer.id).where(
                Interferer.mission_id == mission_id,
                Interferer.is_active.is_(True),
                Interferer.color_slot == interferer.color_slot,
                Interferer.id != interferer_id,
            )
        )
        if clash is not None:
            await session.rollback()
            raise HTTPException(409, "colour slot already used by an active interferer")
    await domain.audit(
        session, mission_id, actor.id, "update", "interferer", interferer_id, **changes
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "an interferer with this name already exists") from exc
    out = interferer_out(interferer)
    await events.publish(redis, mission_id, "interferer_updated", event_json(out))
    if "is_active" in changes:
        scheduler.schedule(mission_id)
    return out
