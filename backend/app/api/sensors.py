"""Sensor management (leads) and position suggestions."""

from __future__ import annotations

import asyncio
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from foxgrid_engine import Bearing as EngineBearing
from foxgrid_engine import EngineError, suggest_positions
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import lead, member
from app.db import get_session
from app.models import Bearing, Mission, Participant, PositionSample, Sensor, Transmission
from app.schemas.api import (
    Scope,
    SensorCreate,
    SensorCreated,
    SensorOut,
    SensorPatch,
    SuggestionOut,
    SuggestionsOut,
)
from app.security import hash_token
from app.services import domain
from app.services.recompute import _to_engine, engine_params_for

router = APIRouter(prefix="/missions/{mission_id}")

ONLINE_WINDOW = timedelta(minutes=2)
KEY_PREFIX = "fgs_"


def topic_prefix(mission_id: uuid.UUID, sensor_id: uuid.UUID) -> str:
    return f"foxgrid/{mission_id}/{sensor_id}"


def sensor_out(sensor: Sensor, callsign: str, now: datetime | None = None) -> SensorOut:
    now = now or datetime.now(UTC)
    seen = sensor.last_seen_at
    return SensorOut(
        id=sensor.id,
        name=sensor.name,
        kind=sensor.kind,
        callsign=callsign,
        lat=sensor.lat,
        lon=sensor.lon,
        is_active=sensor.is_active,
        last_seen_at=seen,
        online=sensor.is_active and seen is not None and now - seen <= ONLINE_WINDOW,
        topic_prefix=topic_prefix(sensor.mission_id, sensor.id),
    )


def _callsign_for(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^A-Z0-9]", "", name.upper())[:12] or "SENSOR"
    base = base.ljust(3, "0")
    candidate, n = base, 1
    while candidate in taken:
        n += 1
        candidate = f"{base[: 15 - len(str(n))]}{n}"
    return candidate


@router.post("/sensors", response_model=SensorCreated, status_code=201)
async def create_sensor(
    mission_id: uuid.UUID,
    body: SensorCreate,
    actor: Participant = Depends(lead),
    session: AsyncSession = Depends(get_session),
) -> SensorCreated:
    """Registers a station or relay hook. The API key is returned exactly once."""
    taken = set(
        await session.scalars(
            select(Participant.callsign).where(Participant.mission_id == mission_id)
        )
    )
    callsign = _callsign_for(body.name, taken)
    virtual = Participant(mission_id=mission_id, callsign=callsign, role="fixed")
    session.add(virtual)
    await session.flush()
    key = KEY_PREFIX + secrets.token_urlsafe(24)
    sensor = Sensor(
        mission_id=mission_id,
        participant_id=virtual.id,
        name=body.name,
        kind=body.kind,
        lat=body.lat,
        lon=body.lon,
        api_key_hash=hash_token(key),
    )
    session.add(sensor)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "a sensor with this name already exists") from exc
    if body.lat is not None and body.lon is not None:  # fixed stations show up on the map
        session.add(
            PositionSample(
                mission_id=mission_id,
                participant_id=virtual.id,
                lat=body.lat,
                lon=body.lon,
                recorded_at=datetime.now(UTC),
            )
        )
    await domain.audit(session, mission_id, actor.id, "create", "sensor", sensor.id, name=body.name)
    await session.commit()
    return SensorCreated(**sensor_out(sensor, callsign).model_dump(), api_key=key)


@router.get("/sensors", response_model=list[SensorOut])
async def list_sensors(
    mission_id: uuid.UUID,
    _: Participant = Depends(member),
    session: AsyncSession = Depends(get_session),
) -> list[SensorOut]:
    rows = (
        await session.execute(
            select(Sensor, Participant.callsign)
            .join(Participant, Participant.id == Sensor.participant_id)
            .where(Sensor.mission_id == mission_id)
            .order_by(Sensor.created_at)
        )
    ).all()
    now = datetime.now(UTC)
    return [sensor_out(s, cs, now) for s, cs in rows]


@router.patch("/sensors/{sensor_id}", response_model=SensorOut)
async def patch_sensor(
    mission_id: uuid.UUID,
    sensor_id: uuid.UUID,
    body: SensorPatch,
    actor: Participant = Depends(lead),
    session: AsyncSession = Depends(get_session),
) -> SensorOut:
    """Deactivate a sensor (its data stays in the log) or move a fixed station."""
    sensor = await session.get(Sensor, sensor_id)
    if sensor is None or sensor.mission_id != mission_id:
        raise HTTPException(404, "sensor not found")
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(sensor, field, value)
    if changes:
        await domain.audit(session, mission_id, actor.id, "update", "sensor", sensor_id, **changes)
        await session.commit()
    callsign = await session.scalar(
        select(Participant.callsign).where(Participant.id == sensor.participant_id)
    )
    return sensor_out(sensor, callsign or "?")


@router.get("/suggestions", response_model=SuggestionsOut)
async def get_suggestions(
    mission_id: uuid.UUID,
    scope: Scope = "all",
    count: int = Query(default=3, ge=1, le=10),
    sigma_deg: float = Query(default=10.0, gt=0, le=45),
    _: Participant = Depends(member),
    session: AsyncSession = Depends(get_session),
) -> SuggestionsOut:
    """Where one more bearing (with a typical sigma) would shrink the error ellipse the most."""
    mission = await session.get(Mission, mission_id)
    if mission is None:
        raise HTTPException(404, "mission not found")
    stmt = select(Bearing).where(
        Bearing.mission_id == mission_id,
        Bearing.is_active.is_(True),
        Bearing.is_outlier.is_(False),
    )
    if scope == "current":
        current = await session.scalar(
            select(Transmission.id)
            .where(Transmission.mission_id == mission_id)
            .order_by(Transmission.started_at.desc())
            .limit(1)
        )
        stmt = stmt.where(Bearing.transmission_id == current)
    bearings = list((await session.scalars(stmt)).all())
    if not bearings:
        raise HTTPException(404, "no bearings yet")
    ring = await domain.search_area_ring(session, mission_id)
    params = engine_params_for(mission, datetime.now(UTC).timestamp())
    engine_bearings: list[EngineBearing] = [_to_engine(b) for b in bearings]
    # RSSI samples are not passed on: the suggestion is about bearing geometry.
    try:
        result = await asyncio.to_thread(
            suggest_positions,
            engine_bearings,
            params,
            None,
            count=count,
            typical_sigma_deg=sigma_deg,
            search_area=ring,
        )
    except EngineError as exc:
        raise HTTPException(422, str(exc)) from exc
    return SuggestionsOut(
        scope=scope,
        n_bearings=len(bearings),
        typical_sigma_deg=sigma_deg,
        suggestions=[SuggestionOut(**vars_of(s)) for s in result],
    )


def vars_of(s: object) -> dict[str, float]:
    return {name: float(getattr(s, name)) for name in SuggestionOut.model_fields}
