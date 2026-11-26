"""Start and stop transmissions: shared by the REST API and the MQTT ingest."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import events
from app.models import Mission, Participant, Transmission
from app.schemas.api import TransmissionOut
from app.services import domain
from app.services.permissions import Permission, has_permission
from app.services.recompute import RecomputeScheduler
from app.services.serialize import event_json, transmission_out


class AlreadyRunningError(Exception):
    """A transmission is already in progress for this mission."""


class NotRunningError(Exception):
    """There is no running transmission to stop."""


class NotAllowedError(Exception):
    """Only the participant who started the transmission, or the lead, may stop it."""


async def start_transmission(
    session: AsyncSession,
    redis: Redis,
    scheduler: RecomputeScheduler,
    mission: Mission,
    actor: Participant,
    *,
    at: datetime | None = None,
    note: str | None = None,
    source: str = "manual",
    interferer_id: uuid.UUID | None = None,
    after_commit: Callable[[Transmission], None] | None = None,
) -> TransmissionOut:
    """Start a transmission, possibly backdated (``at``) because the button was pressed late.

    A backdated start never reaches back before the end of the previous transmission.
    """
    previous = await session.scalar(
        select(Transmission)
        .where(Transmission.mission_id == mission.id)
        .order_by(Transmission.seq.desc())
        .limit(1)
    )
    seq = (previous.seq if previous is not None else 0) + 1
    started_at = at or datetime.now(UTC)
    if previous is not None and previous.ended_at is not None:
        started_at = max(started_at, previous.ended_at)
    tx = Transmission(
        mission_id=mission.id,
        seq=seq,
        started_at=started_at,
        started_by=actor.id,
        note=note,
        source=source,
        interferer_id=interferer_id,
    )
    session.add(tx)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise AlreadyRunningError from exc
    await domain.audit(session, mission.id, actor.id, "start", "transmission", tx.id, seq=seq)
    gated = await domain.evaluate_gate(session, mission.id)
    await session.commit()
    out = transmission_out(tx)
    await events.publish(redis, mission.id, "transmission_started", event_json(out))
    await domain.publish_bearings(session, redis, mission.id, gated)
    scheduler.schedule(mission.id)
    if after_commit is not None:
        after_commit(tx)
    return out


async def stop_transmission(
    session: AsyncSession,
    redis: Redis,
    scheduler: RecomputeScheduler,
    mission_id: uuid.UUID,
    actor: Participant,
    *,
    at: datetime | None = None,
) -> TransmissionOut:
    tx = await session.scalar(
        select(Transmission)
        .where(Transmission.mission_id == mission_id, Transmission.ended_at.is_(None))
        .with_for_update()
    )
    if tx is None:
        raise NotRunningError
    if not has_permission(actor, Permission.TRANSMISSION_MANAGE) and tx.started_by != actor.id:
        await domain.audit(session, mission_id, actor.id, "stop_denied", "transmission", tx.id)
        await session.commit()
        raise NotAllowedError
    tx.ended_at = max(at or datetime.now(UTC), tx.started_at)
    tx.ended_by = actor.id
    await domain.audit(session, mission_id, actor.id, "stop", "transmission", tx.id)
    gated = await domain.evaluate_gate(session, mission_id)
    await session.commit()
    out = transmission_out(tx)
    await events.publish(redis, mission_id, "transmission_ended", event_json(out))
    await domain.publish_bearings(session, redis, mission_id, gated)
    scheduler.schedule(mission_id)
    return out
