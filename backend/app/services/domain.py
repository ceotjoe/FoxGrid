"""Small domain helpers shared by API routes and the WebSocket handler."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from geoalchemy2 import WKTElement
from redis.asyncio import Redis
from sqlalchemy import ColumnElement, delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import events
from app.config import Settings
from app.models import (
    AuditLog,
    Message,
    Mission,
    Participant,
    PositionSample,
    Team,
    Transmission,
)
from app.schemas.api import PositionIn
from app.services.serialize import event_json, position_out

ASSIGN_SLACK = timedelta(seconds=5)


async def audit(
    session: AsyncSession,
    mission_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    action: str,
    entity: str,
    entity_id: object | None = None,
    **detail: object,
) -> None:
    session.add(
        AuditLog(
            mission_id=mission_id,
            actor_id=actor_id,
            action=action,
            entity=entity,
            entity_id=str(entity_id) if entity_id is not None else None,
            detail=detail,
        )
    )


def polygon_wkt(ring: list[tuple[float, float]]) -> WKTElement:
    pts = list(ring)
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    coords = ", ".join(f"{lon} {lat}" for lon, lat in pts)
    return WKTElement(f"POLYGON(({coords}))", srid=4326)


async def search_area_ring(
    session: AsyncSession, mission_id: uuid.UUID
) -> list[tuple[float, float]] | None:
    raw = await session.scalar(
        select(func.ST_AsGeoJSON(Mission.search_area)).where(Mission.id == mission_id)
    )
    if raw is None:
        return None
    import json

    coords = json.loads(raw)["coordinates"][0]
    return [(c[0], c[1]) for c in coords]


async def get_or_create_team(session: AsyncSession, mission_id: uuid.UUID, name: str) -> Team:
    team = await session.scalar(
        select(Team).where(Team.mission_id == mission_id, Team.name == name)
    )
    if team is None:
        team = Team(mission_id=mission_id, name=name)
        session.add(team)
        await session.flush()
    return team


async def team_name(session: AsyncSession, team_id: uuid.UUID | None) -> str | None:
    if team_id is None:
        return None
    return await session.scalar(select(Team.name).where(Team.id == team_id))


async def assign_transmission(
    session: AsyncSession, mission_id: uuid.UUID, measured_at: datetime
) -> uuid.UUID | None:
    """Pick the transmission whose window (with slack for clock skew) contains the bearing."""
    stmt = (
        select(Transmission.id)
        .where(
            Transmission.mission_id == mission_id,
            Transmission.started_at - ASSIGN_SLACK <= measured_at,
            (Transmission.ended_at.is_(None))
            | (Transmission.ended_at + ASSIGN_SLACK >= measured_at),
        )
        .order_by(Transmission.started_at.desc())
        .limit(1)
    )
    return await session.scalar(stmt)


async def record_positions(
    session: AsyncSession,
    redis: Redis,
    settings: Settings,
    participant: Participant,
    items: list[PositionIn],
    *,
    store_all: bool,
) -> int:
    """Store position samples and broadcast the newest one, throttled per participant.

    WebSocket updates (``store_all=False``) are dropped while the throttle key is set; REST
    batches (offline catch-up) are always stored but only broadcast when the throttle allows.
    """
    if not items:
        return 0
    allowed = bool(
        await redis.set(
            f"posthr:{participant.id}", "1", nx=True, ex=settings.position_min_interval_s
        )
    )
    if not allowed and not store_all:
        return 0
    now = datetime.now(UTC)
    rows = [
        PositionSample(
            mission_id=participant.mission_id,
            participant_id=participant.id,
            lat=i.lat,
            lon=i.lon,
            accuracy_m=i.accuracy_m,
            heading_deg=i.heading_deg,
            speed_mps=i.speed_mps,
            recorded_at=i.recorded_at,
            received_at=now,
        )
        for i in items
    ]
    session.add_all(rows)
    await session.execute(
        text("UPDATE participants SET last_seen_at = :t WHERE id = :id"),
        {"t": now, "id": participant.id},
    )
    await session.commit()
    if allowed:
        newest = max(rows, key=lambda r: r.recorded_at)
        data = event_json(position_out(newest))
        data["callsign"] = participant.callsign
        await events.publish(redis, participant.mission_id, "participant_position", data)
    return len(rows)


async def purge_expired_tracks(session: AsyncSession) -> int:
    """Delete position samples of missions that ended more than their retention period ago.

    Bearings are never touched: they stay as part of the mission log.
    """
    expired = (
        select(Mission.id)
        .where(
            Mission.status == "ended",
            Mission.ended_at.is_not(None),
            Mission.ended_at + func.make_interval(0, 0, 0, Mission.track_retention_days)
            < func.now(),
        )
        .scalar_subquery()
    )
    result = await session.execute(
        delete(PositionSample).where(PositionSample.mission_id.in_(expired))
    )
    await session.commit()
    return result.rowcount or 0  # type: ignore[attr-defined,no-any-return]


def visible_messages(actor: Participant) -> ColumnElement[bool]:
    """Mission-wide messages plus the actor's team channel (leads see every team channel)."""
    visible: ColumnElement[bool] = Message.team_id.is_(None)
    if actor.team_id is not None:
        visible = or_(visible, Message.team_id == actor.team_id)
    if actor.role == "lead":
        visible = or_(visible, Message.team_id.is_not(None))
    return visible
