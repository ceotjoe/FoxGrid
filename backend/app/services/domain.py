"""Small domain helpers shared by API routes and the WebSocket handler."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from geoalchemy2 import WKTElement
from redis.asyncio import Redis
from sqlalchemy import (
    ColumnElement,
    Select,
    case,
    delete,
    exists,
    false,
    func,
    null,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app import events
from app.config import Settings
from app.models import (
    AuditLog,
    Bearing,
    BearingPoint,
    Interferer,
    Message,
    Mission,
    Participant,
    PositionSample,
    Sensor,
    Team,
    Transmission,
)
from app.schemas.api import MAX_INTERFERERS, PositionIn
from app.services.permissions import Permission, has_permission
from app.services.serialize import bearing_out, event_json, position_out

ASSIGN_SLACK = timedelta(seconds=5)
DEFAULT_INTERFERER_NAME = "Störer 1"
EVENT_CHUNK = 500  # bearings per `bearings_updated` event


def trusted_only[S: Select[Any]](stmt: S, model: type) -> S:
    """Restrict a Bearing/RssiSample query to data that may move the estimate.

    Participants must be trusted and not observers. External bearings (``point_id`` set) also
    need their point to be active and switched on for the estimate. Bearings of gated sensors
    count only inside a transmission, unless a person decided otherwise (`gate_counts`).
    """
    # Observers never count, whatever their trust flag says.
    trusted = select(Participant.id).where(
        Participant.trusted.is_(True), Participant.authority != "observer"
    )
    stmt = stmt.where(model.participant_id.in_(trusted))  # type: ignore[attr-defined]
    if model is Bearing:
        counted = select(BearingPoint.id).where(
            BearingPoint.use_in_estimate.is_(True), BearingPoint.is_active.is_(True)
        )
        stmt = stmt.where(or_(Bearing.point_id.is_(None), Bearing.point_id.in_(counted)))
        stmt = stmt.where(gate_counts())
    return stmt


def gate_counts() -> ColumnElement[bool]:
    """SQL: the manual decision if there is one, else everything not outside a transmission."""
    return func.coalesce(  # type: ignore[no-any-return]
        Bearing.gate_override, Bearing.gate_state.is_distinct_from("outside")
    ).is_(True)


def bearing_gate_counts(b: Bearing) -> bool:
    """Python twin of `gate_counts` for a loaded bearing."""
    return b.gate_override if b.gate_override is not None else b.gate_state != "outside"


async def evaluate_gate(
    session: AsyncSession,
    mission_id: uuid.UUID,
    bearing_ids: list[uuid.UUID] | None = None,
) -> list[uuid.UUID]:
    """Recompute ``gate_state`` of sensor bearings; returns the ids that changed (not committed).

    A bearing of a gated sensor is 'inside' if its whole averaging window (or its measurement
    time) lies within one transmission, with `ASSIGN_SLACK` at both ends; else 'outside'.
    Bearings of other sensors get NULL. Manual decisions (``gate_override``) are left alone.
    Called when a bearing arrives, when transmissions start or stop and when a sensor's gate
    setting changes, so late bearings and late (backdated) starts both end up right.
    """
    window_start = func.coalesce(Bearing.window_start, Bearing.measured_at)
    window_end = func.coalesce(Bearing.window_end, Bearing.measured_at)
    inside = exists().where(
        Transmission.mission_id == Bearing.mission_id,
        Transmission.started_at - ASSIGN_SLACK <= window_start,
        or_(Transmission.ended_at.is_(None), Transmission.ended_at + ASSIGN_SLACK >= window_end),
    )
    gated = select(Sensor.id).where(Sensor.mission_id == mission_id, Sensor.gated.is_(True))
    state = case(
        (Bearing.sensor_id.in_(gated), case((inside, "inside"), else_="outside")),
        else_=null(),
    )
    stmt = (
        update(Bearing)
        .where(
            Bearing.mission_id == mission_id,
            Bearing.sensor_id.is_not(None),
            Bearing.gate_state.is_distinct_from(state),
        )
        .values(gate_state=state)
        .returning(Bearing.id)
        .execution_options(synchronize_session=False)
    )
    if bearing_ids is not None:
        stmt = stmt.where(Bearing.id.in_(bearing_ids))
    return list((await session.scalars(stmt)).all())


async def publish_bearings(
    session: AsyncSession, redis: Redis, mission_id: uuid.UUID, bearing_ids: list[uuid.UUID]
) -> None:
    """Send changed bearings as ``bearings_updated`` events (after the commit)."""
    for i in range(0, len(bearing_ids), EVENT_CHUNK):
        rows = (
            await session.scalars(
                select(Bearing)
                .where(Bearing.id.in_(bearing_ids[i : i + EVENT_CHUNK]))
                .order_by(Bearing.measured_at)
                .execution_options(populate_existing=True)
            )
        ).all()
        data = {"bearings": [event_json(bearing_out(b)) for b in rows]}
        await events.publish(redis, mission_id, "bearings_updated", data)


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


async def default_interferer_id(session: AsyncSession, mission_id: uuid.UUID) -> uuid.UUID:
    """The mission's default interferer: the oldest active one, created on demand.

    Used when a client does not name an interferer (old clients, sensors) and as the target of
    estimate endpoints called without one.
    """
    found = await session.scalar(
        select(Interferer.id)
        .where(Interferer.mission_id == mission_id, Interferer.is_active.is_(True))
        .order_by(Interferer.created_at, Interferer.id)
        .limit(1)
    )
    if found is not None:
        return found
    # All deactivated (or a mission from before interferers existed): keep the data flowing.
    anything = await session.scalar(
        select(Interferer.id)
        .where(Interferer.mission_id == mission_id)
        .order_by(Interferer.created_at, Interferer.id)
        .limit(1)
    )
    if anything is not None:
        return anything
    return (await create_default_interferer(session, mission_id, None)).id


async def create_default_interferer(
    session: AsyncSession, mission_id: uuid.UUID, creator_id: uuid.UUID | None
) -> Interferer:
    interferer = Interferer(
        id=uuid.uuid4(),
        mission_id=mission_id,
        name=DEFAULT_INTERFERER_NAME,
        color_slot=0,
        created_by=creator_id,
    )
    session.add(interferer)
    await session.flush()
    return interferer


async def free_color_slot(session: AsyncSession, mission_id: uuid.UUID) -> int | None:
    """Lowest colour slot no active interferer uses; None when all are taken."""
    used = set(
        await session.scalars(
            select(Interferer.color_slot).where(
                Interferer.mission_id == mission_id, Interferer.is_active.is_(True)
            )
        )
    )
    return next((s for s in range(MAX_INTERFERERS) if s not in used), None)


async def resolve_interferer(
    session: AsyncSession,
    mission_id: uuid.UUID,
    interferer_id: uuid.UUID | None,
    transmission: Transmission | None = None,
) -> uuid.UUID:
    """The interferer a new bearing or reading belongs to.

    An explicit id must exist in the mission and be active (``ValueError`` otherwise). Without
    one the transmission's interferer applies, then the mission's default.
    """
    if interferer_id is None and transmission is not None:
        interferer_id = transmission.interferer_id
    if interferer_id is None:
        return await default_interferer_id(session, mission_id)
    found = await session.get(Interferer, interferer_id)
    if found is None or found.mission_id != mission_id or not found.is_active:
        raise ValueError("unknown or inactive interferer")
    return interferer_id


async def read_interferer(
    session: AsyncSession, mission_id: uuid.UUID, interferer_id: uuid.UUID | None
) -> uuid.UUID:
    """The interferer a read endpoint refers to: the given one (also if deactivated) or default.

    ``ValueError`` when the id is not an interferer of the mission.
    """
    if interferer_id is None:
        return await default_interferer_id(session, mission_id)
    found = await session.get(Interferer, interferer_id)
    if found is None or found.mission_id != mission_id:
        raise ValueError("unknown interferer")
    return interferer_id


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
    if not has_permission(actor, Permission.CHAT_READ):
        return false()  # observers and stations read no chat
    visible: ColumnElement[bool] = Message.team_id.is_(None)
    if actor.team_id is not None:
        visible = or_(visible, Message.team_id == actor.team_id)
    if has_permission(actor, Permission.CHAT_MODERATE):
        visible = or_(visible, Message.team_id.is_not(None))
    return visible
