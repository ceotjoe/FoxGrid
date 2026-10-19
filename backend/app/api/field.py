"""Positions, bearings, transmissions and estimates."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import replace
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from foxgrid_engine import Bearing as EngineBearing
from foxgrid_engine import EngineError
from foxgrid_engine import estimate as run_engine
from foxgrid_engine.rssi import usable_samples
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import events
from app.api.deps import get_redis, get_scheduler, get_settings, member
from app.config import Settings
from app.db import get_session
from app.models import (
    Bearing,
    BearingRevision,
    Estimate,
    Mission,
    Participant,
    PositionSample,
    RssiSample,
    Transmission,
)
from app.schemas.api import (
    BearingIn,
    BearingOut,
    BearingPatch,
    EstimateOut,
    PositionIn,
    PositionOut,
    RevisionOut,
    Scope,
    TransmissionOut,
    TransmissionStart,
    TransmissionStop,
)
from app.services import domain, push, ratelimit, transmissions
from app.services.recompute import (
    MIN_BEARINGS,
    RecomputeScheduler,
    _input_hash,
    _to_engine,
    _to_engine_rssi,
    build_estimate,
    engine_params_for,
    load_calibration,
    uses_rssi,
)
from app.services.serialize import (
    bearing_out,
    estimate_out,
    event_json,
    position_out,
    transmission_out,
)

router = APIRouter(prefix="/missions/{mission_id}")


async def _active_mission(session: AsyncSession, mission_id: uuid.UUID) -> Mission:
    mission = await session.get(Mission, mission_id)
    if mission is None:
        raise HTTPException(404, "mission not found")
    if mission.status != "active":
        raise HTTPException(409, "mission has ended")
    return mission


# --- positions ---------------------------------------------------------------------------


@router.post("/positions", status_code=202)
async def post_positions(
    mission_id: uuid.UUID,
    body: list[PositionIn],
    actor: Participant = Depends(member),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> dict[str, int]:
    if len(body) > 500:
        raise HTTPException(422, "at most 500 samples per request")
    await _active_mission(session, mission_id)
    stored = await domain.record_positions(session, redis, settings, actor, body, store_all=True)
    return {"stored": stored}


@router.get("/positions", response_model=list[PositionOut])
async def list_positions(
    mission_id: uuid.UUID,
    participant: uuid.UUID | None = None,
    since: datetime | None = None,
    limit: int = Query(default=2000, le=10_000),
    _: Participant = Depends(member),
    session: AsyncSession = Depends(get_session),
) -> list[PositionOut]:
    stmt = select(PositionSample).where(PositionSample.mission_id == mission_id)
    if participant:
        stmt = stmt.where(PositionSample.participant_id == participant)
    if since:
        stmt = stmt.where(PositionSample.recorded_at >= since)
    rows = (await session.scalars(stmt.order_by(PositionSample.recorded_at).limit(limit))).all()
    return [position_out(r) for r in rows]


# --- transmissions -----------------------------------------------------------------------


@router.post("/transmissions/start", response_model=TransmissionOut, status_code=201)
async def start_transmission(
    request: Request,
    mission_id: uuid.UUID,
    body: TransmissionStart | None = None,
    actor: Participant = Depends(member),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    scheduler: RecomputeScheduler = Depends(get_scheduler),
) -> TransmissionOut:
    mission = await _active_mission(session, mission_id)
    body = body or TransmissionStart()
    app = request.app

    def notify(_: Transmission) -> None:
        task = asyncio.create_task(
            push.notify_transmission_started(
                app.state.push, app.state.sessionmaker, mission_id, actor.id, mission.name
            )
        )
        app.state.background.add(task)  # keep a reference until done
        task.add_done_callback(app.state.background.discard)

    try:
        return await transmissions.start_transmission(
            session,
            redis,
            scheduler,
            mission,
            actor,
            at=body.at,
            note=body.note,
            after_commit=notify,
        )
    except transmissions.AlreadyRunningError as exc:
        raise HTTPException(409, "a transmission is already running") from exc


@router.post("/transmissions/stop", response_model=TransmissionOut)
async def stop_transmission(
    mission_id: uuid.UUID,
    body: TransmissionStop | None = None,
    actor: Participant = Depends(member),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    scheduler: RecomputeScheduler = Depends(get_scheduler),
) -> TransmissionOut:
    await _active_mission(session, mission_id)
    try:
        return await transmissions.stop_transmission(
            session, redis, scheduler, mission_id, actor, at=body.at if body else None
        )
    except transmissions.NotRunningError as exc:
        raise HTTPException(409, "no transmission is running") from exc


@router.get("/transmissions", response_model=list[TransmissionOut])
async def list_transmissions(
    mission_id: uuid.UUID,
    _: Participant = Depends(member),
    session: AsyncSession = Depends(get_session),
) -> list[TransmissionOut]:
    rows = (
        await session.scalars(
            select(Transmission)
            .where(Transmission.mission_id == mission_id)
            .order_by(Transmission.seq)
        )
    ).all()
    return [transmission_out(t) for t in rows]


# --- bearings ----------------------------------------------------------------------------


def _same_bearing(existing: Bearing, body: BearingIn, actor: Participant) -> bool:
    return (
        existing.participant_id == actor.id
        and round(float(existing.azimuth_true_deg), 2) == round(body.azimuth_true_deg, 2)
        and round(float(existing.sigma_deg), 2) == round(body.sigma_deg, 2)
        and abs(existing.lat - body.lat) < 1e-9
        and abs(existing.lon - body.lon) < 1e-9
        and existing.measured_at == body.measured_at
    )


@router.post("/bearings", response_model=BearingOut, status_code=201)
async def create_bearing(
    mission_id: uuid.UUID,
    body: BearingIn,
    response: Response,
    actor: Participant = Depends(member),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    scheduler: RecomputeScheduler = Depends(get_scheduler),
    settings: Settings = Depends(get_settings),
) -> BearingOut:
    """Idempotent on the client UUID: a retry returns 200 with the stored bearing."""
    await ratelimit.enforce(redis, "bearing", actor.id, settings.rate_bearing_per_min)
    existing = await session.get(Bearing, body.id)
    if existing is not None:
        return _duplicate(existing, body, actor, mission_id, response)

    if await session.get(Mission, mission_id) is None:
        raise HTTPException(404, "mission not found")
    tx_id = body.transmission_id
    if tx_id is not None:
        tx = await session.get(Transmission, tx_id)
        if tx is None or tx.mission_id != mission_id:
            raise HTTPException(422, "unknown transmission")
    else:
        tx_id = await domain.assign_transmission(session, mission_id, body.measured_at)

    bearing = Bearing(
        id=body.id,
        mission_id=mission_id,
        participant_id=actor.id,
        transmission_id=tx_id,
        lat=body.lat,
        lon=body.lon,
        station_accuracy_m=body.station_accuracy_m,
        azimuth_true_deg=body.azimuth_true_deg,
        azimuth_input_ref=body.azimuth_input_ref,
        declination_deg_applied=body.declination_deg_applied,
        sigma_deg=body.sigma_deg,
        rssi_dbm=body.rssi_dbm,
        s_meter=body.s_meter,
        attenuation_db=body.attenuation_db,
        polarization=body.polarization,
        measured_at=body.measured_at,
        note=body.note,
    )
    session.add(bearing)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await session.get(Bearing, body.id)
        if existing is None:
            raise
        return _duplicate(existing, body, actor, mission_id, response)
    out = bearing_out(bearing)
    await events.publish(redis, mission_id, "bearing_created", event_json(out))
    scheduler.schedule(mission_id)
    return out


def _duplicate(
    existing: Bearing,
    body: BearingIn,
    actor: Participant,
    mission_id: uuid.UUID,
    response: Response,
) -> BearingOut:
    if existing.mission_id != mission_id or not _same_bearing(existing, body, actor):
        raise HTTPException(409, "bearing id already used with different content")
    response.status_code = 200
    return bearing_out(existing)


@router.get("/bearings", response_model=list[BearingOut])
async def list_bearings(
    mission_id: uuid.UUID,
    transmission: uuid.UUID | None = None,
    since: datetime | None = None,
    include_inactive: bool = True,
    _: Participant = Depends(member),
    session: AsyncSession = Depends(get_session),
) -> list[BearingOut]:
    stmt = select(Bearing).where(Bearing.mission_id == mission_id)
    if transmission:
        stmt = stmt.where(Bearing.transmission_id == transmission)
    if since:
        stmt = stmt.where(Bearing.received_at >= since)
    if not include_inactive:
        stmt = stmt.where(Bearing.is_active.is_(True))
    rows = (await session.scalars(stmt.order_by(Bearing.measured_at))).all()
    return [bearing_out(b) for b in rows]


async def _bearing_or_404(session: AsyncSession, mission_id: uuid.UUID, bid: uuid.UUID) -> Bearing:
    bearing = await session.get(Bearing, bid)
    if bearing is None or bearing.mission_id != mission_id:
        raise HTTPException(404, "bearing not found")
    return bearing


@router.get("/bearings/{bearing_id}", response_model=BearingOut)
async def get_bearing(
    mission_id: uuid.UUID,
    bearing_id: uuid.UUID,
    _: Participant = Depends(member),
    session: AsyncSession = Depends(get_session),
) -> BearingOut:
    return bearing_out(await _bearing_or_404(session, mission_id, bearing_id))


@router.get("/bearings/{bearing_id}/revisions", response_model=list[RevisionOut])
async def bearing_revisions(
    mission_id: uuid.UUID,
    bearing_id: uuid.UUID,
    _: Participant = Depends(member),
    session: AsyncSession = Depends(get_session),
) -> list[RevisionOut]:
    await _bearing_or_404(session, mission_id, bearing_id)
    rows = (
        await session.scalars(
            select(BearingRevision)
            .where(BearingRevision.bearing_id == bearing_id)
            .order_by(BearingRevision.id)
        )
    ).all()
    return [RevisionOut.model_validate(r) for r in rows]


@router.patch("/bearings/{bearing_id}", response_model=BearingOut)
async def patch_bearing(
    mission_id: uuid.UUID,
    bearing_id: uuid.UUID,
    body: BearingPatch,
    actor: Participant = Depends(member),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    scheduler: RecomputeScheduler = Depends(get_scheduler),
) -> BearingOut:
    """Flag/deactivate a bearing or edit its note. Bearings can never be deleted."""
    bearing = await _bearing_or_404(session, mission_id, bearing_id)
    if actor.role != "lead" and bearing.participant_id != actor.id:
        raise HTTPException(403, "only the owner or a lead may change this bearing")
    changes: dict[str, dict[str, object]] = {}
    for field, value in body.model_dump(exclude_unset=True).items():
        old = getattr(bearing, field)
        if old != value:
            changes[field] = {"from": old, "to": value}
            setattr(bearing, field, value)
    if changes:
        session.add(BearingRevision(bearing_id=bearing_id, changed_by=actor.id, changes=changes))
        await domain.audit(
            session, mission_id, actor.id, "update", "bearing", bearing_id, **changes
        )
        await session.commit()
        out = bearing_out(bearing)
        await events.publish(redis, mission_id, "bearing_updated", event_json(out))
        if "is_outlier" in changes or "is_active" in changes:
            scheduler.schedule(mission_id)
        return out
    return bearing_out(bearing)


# --- estimates ---------------------------------------------------------------------------


@router.get("/estimate", response_model=EstimateOut)
async def get_estimate(
    mission_id: uuid.UUID,
    scope: Scope = "current",
    _: Participant = Depends(member),
    session: AsyncSession = Depends(get_session),
) -> EstimateOut:
    est = await session.scalar(
        select(Estimate)
        .where(Estimate.mission_id == mission_id, Estimate.scope == scope)
        .order_by(Estimate.computed_at.desc())
        .limit(1)
    )
    if est is None:
        raise HTTPException(404, "no estimate yet (needs at least two usable bearings)")
    return estimate_out(est)


@router.get("/estimate/history", response_model=list[EstimateOut])
async def estimate_history(
    mission_id: uuid.UUID,
    scope: Scope = "all",
    limit: int = Query(default=100, le=1000),
    _: Participant = Depends(member),
    session: AsyncSession = Depends(get_session),
) -> list[EstimateOut]:
    rows = (
        await session.scalars(
            select(Estimate)
            .where(Estimate.mission_id == mission_id, Estimate.scope == scope)
            .order_by(Estimate.computed_at.desc())
            .limit(limit)
        )
    ).all()
    return [estimate_out(e) for e in rows]


@router.get("/estimate/query", response_model=EstimateOut)
async def query_estimate(
    mission_id: uuid.UUID,
    transmission: list[uuid.UUID] = Query(default=[]),
    since: datetime | None = None,
    until: datetime | None = None,
    half_life_s: float | None = Query(default=None, gt=0),
    include_outliers: bool = False,
    include_rssi: bool = True,
    _: Participant = Depends(member),
    session: AsyncSession = Depends(get_session),
) -> EstimateOut:
    """Ad-hoc estimate for a time window and/or selected transmissions (not stored)."""
    mission = await session.get(Mission, mission_id)
    if mission is None:
        raise HTTPException(404, "mission not found")
    stmt = domain.trusted_only(
        select(Bearing).where(Bearing.mission_id == mission_id, Bearing.is_active.is_(True)),
        Bearing,
    )
    if not include_outliers:
        stmt = stmt.where(Bearing.is_outlier.is_(False))
    if transmission:
        stmt = stmt.where(Bearing.transmission_id.in_(transmission))
    if since:
        stmt = stmt.where(Bearing.measured_at >= since)
    if until:
        stmt = stmt.where(Bearing.measured_at <= until)
    bearings = list((await session.scalars(stmt)).all())
    rssi_rows: list[RssiSample] = []
    if include_rssi and uses_rssi(mission):
        rstmt = domain.trusted_only(
            select(RssiSample).where(
                RssiSample.mission_id == mission_id, RssiSample.is_active.is_(True)
            ),
            RssiSample,
        )
        if transmission:
            rstmt = rstmt.where(RssiSample.transmission_id.in_(transmission))
        if since:
            rstmt = rstmt.where(RssiSample.measured_at >= since)
        if until:
            rstmt = rstmt.where(RssiSample.measured_at <= until)
        rssi_rows = [r for r in (await session.scalars(rstmt)).all() if not r.is_calibration]
    offsets = await load_calibration(session, mission) if rssi_rows else {}
    params = engine_params_for(mission, time.time())
    engine_rssi = [_to_engine_rssi(r, offsets) for r in rssi_rows]
    if len(bearings) < MIN_BEARINGS and not usable_samples(engine_rssi, params):
        raise HTTPException(404, "too few bearings or RSSI samples match the filter")
    if half_life_s is not None:
        params = replace(params, half_life_s=half_life_s)
    engine_bearings: list[EngineBearing] = [_to_engine(b) for b in bearings]
    try:
        result = await asyncio.to_thread(run_engine, engine_bearings, params, engine_rssi)
    except EngineError as exc:
        raise HTTPException(422, str(exc)) from exc
    est = build_estimate(
        mission_id, "all", None, _input_hash(bearings, params, rssi_rows, offsets), result, params
    )
    return estimate_out(est)
