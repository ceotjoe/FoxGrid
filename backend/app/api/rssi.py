"""Signal strength samples of the homing track."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_scheduler, member
from app.db import get_session
from app.models import Participant, RssiSample
from app.schemas.api import RssiBatchResult, RssiIn, RssiOut, RssiPatch
from app.services import domain
from app.services.recompute import RecomputeScheduler
from app.services.serialize import rssi_out

router = APIRouter(prefix="/missions/{mission_id}")

MAX_BATCH = 500


def _same(existing: RssiSample, body: RssiIn, actor: Participant, mission_id: uuid.UUID) -> bool:
    return (
        existing.mission_id == mission_id
        and existing.participant_id == actor.id
        and abs(existing.rssi_dbm - body.rssi_dbm) < 1e-6
        and abs(existing.lat - body.lat) < 1e-9
        and abs(existing.lon - body.lon) < 1e-9
    )


@router.post("/rssi", response_model=RssiBatchResult)
async def post_rssi(
    mission_id: uuid.UUID,
    body: list[RssiIn],
    actor: Participant = Depends(member),
    session: AsyncSession = Depends(get_session),
    scheduler: RecomputeScheduler = Depends(get_scheduler),
) -> RssiBatchResult:
    """Idempotent batch upload. Allowed after the mission ended so offline logs are not lost."""
    if not 1 <= len(body) <= MAX_BATCH:
        raise HTTPException(422, f"between 1 and {MAX_BATCH} samples per request")
    ids = [s.id for s in body]
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "duplicate ids in one request")
    existing = {
        r.id: r for r in await session.scalars(select(RssiSample).where(RssiSample.id.in_(ids)))
    }
    stored = duplicates = 0
    for sample in body:
        found = existing.get(sample.id)
        if found is not None:
            if not _same(found, sample, actor, mission_id):
                raise HTTPException(409, "sample id already used with different content")
            duplicates += 1
            continue
        tx_id = sample.transmission_id or await domain.assign_transmission(
            session, mission_id, sample.measured_at
        )
        session.add(
            RssiSample(
                id=sample.id,
                mission_id=mission_id,
                participant_id=actor.id,
                transmission_id=tx_id,
                lat=sample.lat,
                lon=sample.lon,
                accuracy_m=sample.accuracy_m,
                rssi_dbm=sample.rssi_dbm,
                s_meter=sample.s_meter,
                attenuation_db=sample.attenuation_db,
                measured_at=sample.measured_at,
                source=sample.source,
            )
        )
        stored += 1
    if stored:
        await session.commit()
        scheduler.schedule(mission_id)
    return RssiBatchResult(stored=stored, duplicates=duplicates)


@router.get("/rssi", response_model=list[RssiOut])
async def list_rssi(
    mission_id: uuid.UUID,
    participant: uuid.UUID | None = None,
    transmission: uuid.UUID | None = None,
    since: datetime | None = None,
    limit: int = Query(default=1000, le=5000),
    _: Participant = Depends(member),
    session: AsyncSession = Depends(get_session),
) -> list[RssiOut]:
    stmt = select(RssiSample).where(RssiSample.mission_id == mission_id)
    if participant:
        stmt = stmt.where(RssiSample.participant_id == participant)
    if transmission:
        stmt = stmt.where(RssiSample.transmission_id == transmission)
    if since:
        stmt = stmt.where(RssiSample.measured_at >= since)
    rows = await session.scalars(stmt.order_by(RssiSample.measured_at).limit(limit))
    return [rssi_out(r) for r in rows]


@router.patch("/rssi/{sample_id}", response_model=RssiOut)
async def patch_rssi(
    mission_id: uuid.UUID,
    sample_id: uuid.UUID,
    body: RssiPatch,
    actor: Participant = Depends(member),
    session: AsyncSession = Depends(get_session),
    scheduler: RecomputeScheduler = Depends(get_scheduler),
) -> RssiOut:
    """Deactivate (or re-activate) a reading, e.g. a spike. Samples are never deleted."""
    sample = await session.get(RssiSample, sample_id)
    if sample is None or sample.mission_id != mission_id:
        raise HTTPException(404, "sample not found")
    if actor.role != "lead" and sample.participant_id != actor.id:
        raise HTTPException(403, "only the owner or a lead may change this sample")
    if sample.is_active != body.is_active:
        sample.is_active = body.is_active
        await domain.audit(
            session,
            mission_id,
            actor.id,
            "update",
            "rssi_sample",
            sample_id,
            is_active=body.is_active,
        )
        await session.commit()
        scheduler.schedule(mission_id)
    return rssi_out(sample)
