from __future__ import annotations

import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app import events
from app.api.deps import current_participant, get_redis, get_scheduler, get_settings, lead, member
from app.config import Settings
from app.db import get_session
from app.models import (
    AuditLog,
    Bearing,
    BearingRevision,
    Estimate,
    Invite,
    Message,
    Mission,
    Participant,
    PositionSample,
    RssiSample,
    Sensor,
    Task,
    Team,
    Transmission,
)
from app.schemas.api import (
    AuditOut,
    InviteCreate,
    InviteOut,
    JoinIn,
    JoinOut,
    MissionCreate,
    MissionCreated,
    MissionOut,
    MissionPatch,
    ParticipantOut,
    ParticipantPatch,
    PlausibilityFlag,
    PlausibilityOut,
    QuarantineIn,
    QuarantineOut,
    RejoinIn,
    RepeaterIn,
    SnapshotOut,
    TeamOut,
)
from app.security import create_jwt, hash_token, new_invite_token
from app.services import domain, plausibility, ratelimit
from app.services.recompute import RecomputeScheduler
from app.services.serialize import (
    bearing_out,
    estimate_out,
    event_json,
    message_out,
    mission_out,
    participant_out,
    position_out,
    rssi_out,
    task_out,
    transmission_out,
)

router = APIRouter()


def _set_repeater(mission: Mission, repeater: RepeaterIn | None) -> None:
    mission.repeater_lat = None if repeater is None else repeater.lat
    mission.repeater_lon = None if repeater is None else repeater.lon
    mission.repeater_input_mhz = None if repeater is None else repeater.input_mhz
    mission.repeater_output_mhz = None if repeater is None else repeater.output_mhz


@router.post("/missions", response_model=MissionCreated, status_code=201)
async def create_mission(
    body: MissionCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    redis: Redis = Depends(get_redis),
) -> MissionCreated:
    client = request.client.host if request.client else "unknown"
    await ratelimit.enforce(redis, "mission", client, settings.rate_mission_per_min)
    mission = Mission(
        name=body.name,
        frequency_mhz=body.frequency_mhz,
        search_area=domain.polygon_wkt(body.search_area) if body.search_area else None,
        track_retention_days=body.track_retention_days,
        engine_params=body.engine_params.model_dump(exclude_none=True),
    )
    _set_repeater(mission, body.repeater)
    session.add(mission)
    await session.flush()
    creator = Participant(
        mission_id=mission.id,
        callsign=body.callsign,
        role="lead",
        device_hash=hash_token(body.device_secret) if body.device_secret else None,
    )
    session.add(creator)
    invite_token = new_invite_token()
    session.add(
        Invite(
            mission_id=mission.id,
            token_hash=hash_token(invite_token),
            default_role="mobile",
            max_uses=settings.invite_max_uses,
            expires_at=datetime.now(UTC) + timedelta(hours=settings.invite_ttl_hours),
        )
    )
    await session.flush()
    await domain.audit(session, mission.id, creator.id, "create", "mission", mission.id)
    await session.commit()
    area = await domain.search_area_ring(session, mission.id)
    return MissionCreated(
        mission=mission_out(mission, area),
        participant=participant_out(creator),
        token=create_jwt(settings, creator.id, mission.id, creator.role),
        invite_token=invite_token,
    )


@router.post("/join", response_model=JoinOut)
async def join(
    body: JoinIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    redis: Redis = Depends(get_redis),
) -> JoinOut:
    client = request.client.host if request.client else "unknown"
    await ratelimit.enforce(redis, "join", client, settings.rate_join_per_min)
    invite = await session.scalar(
        select(Invite).where(Invite.token_hash == hash_token(body.invite_token)).with_for_update()
    )
    now = datetime.now(UTC)
    if (
        invite is None
        or invite.revoked_at is not None
        or (invite.expires_at is not None and invite.expires_at < now)
    ):
        raise HTTPException(403, "invalid or expired invite")
    mission = await session.get(Mission, invite.mission_id)
    assert mission is not None
    if mission.status != "active":
        raise HTTPException(409, "mission has ended")

    participant = await session.scalar(
        select(Participant).where(
            Participant.mission_id == mission.id, Participant.callsign == body.callsign
        )
    )
    if participant is not None and await session.scalar(
        select(Sensor.id).where(Sensor.participant_id == participant.id)
    ):
        raise HTTPException(403, "this callsign belongs to a sensor")
    device_hash = hash_token(body.device_secret)
    joined_new = False
    if participant is None:
        if invite.max_uses is not None and invite.uses >= invite.max_uses:
            raise HTTPException(403, "invalid or expired invite")
        # The invite decides the role; a joiner cannot pick `fixed` or `lead` for themselves.
        participant = Participant(
            mission_id=mission.id,
            callsign=body.callsign,
            role=invite.default_role,
            device_hash=device_hash,
            status="active" if invite.auto_approve else "pending",
            # An open link says nothing about the person; the lead has to trust them first.
            trusted=not invite.auto_approve,
            join_code=None if invite.auto_approve else f"{secrets.randbelow(10_000):04d}",
        )
        session.add(participant)
        joined_new = True
        invite.uses += 1
        await session.flush()
        await domain.audit(
            session, mission.id, participant.id, "join", "participant", participant.id
        )
    elif participant.device_hash is None:
        participant.device_hash = device_hash  # created before device binding existed
    elif not hmac.compare_digest(participant.device_hash, device_hash):
        await domain.audit(
            session, mission.id, participant.id, "join_denied", "participant", participant.id
        )
        await session.commit()
        raise HTTPException(403, "callsign is bound to another device; ask the lead to release it")
    if not participant.is_active:
        raise HTTPException(403, "participant deactivated")
    if participant.status == "rejected":
        raise HTTPException(403, "participant rejected")
    if body.team:
        team = await domain.get_or_create_team(session, mission.id, body.team)
        participant.team_id = team.id
    await session.commit()
    if joined_new:
        await _announce(redis, mission.id, participant)
    area = await domain.search_area_ring(session, mission.id)
    return JoinOut(
        mission=mission_out(mission, area),
        participant=participant_out(
            participant, await domain.team_name(session, participant.team_id), show_code=True
        ),
        token=create_jwt(settings, participant.id, mission.id, participant.role),
    )


@router.post("/missions/{mission_id}/rejoin", response_model=JoinOut)
async def rejoin(
    mission_id: uuid.UUID,
    body: RejoinIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    redis: Redis = Depends(get_redis),
) -> JoinOut:
    """New JWT for a participant already bound to this device (e.g. expired session).

    Needs no invite: the device secret is the proof. Never creates a participant.
    """
    client = request.client.host if request.client else "unknown"
    await ratelimit.enforce(redis, "join", client, settings.rate_join_per_min)
    participant = await session.scalar(
        select(Participant).where(
            Participant.mission_id == mission_id, Participant.callsign == body.callsign
        )
    )
    # One answer for every reason, so nobody can probe which callsigns exist.
    denied = HTTPException(403, "cannot rejoin; use an invite or ask the lead")
    if (
        participant is None
        or participant.device_hash is None
        or not hmac.compare_digest(participant.device_hash, hash_token(body.device_secret))
        or not participant.is_active
        or participant.status == "rejected"
        or await session.scalar(select(Sensor.id).where(Sensor.participant_id == participant.id))
    ):
        raise denied
    mission = await session.get(Mission, mission_id)
    assert mission is not None
    if mission.status != "active":
        raise HTTPException(409, "mission has ended")
    await domain.audit(session, mission_id, participant.id, "rejoin", "participant", participant.id)
    await session.commit()
    area = await domain.search_area_ring(session, mission_id)
    return JoinOut(
        mission=mission_out(mission, area),
        participant=participant_out(
            participant, await domain.team_name(session, participant.team_id), show_code=True
        ),
        token=create_jwt(settings, participant.id, mission.id, participant.role),
    )


@router.get("/missions/{mission_id}", response_model=MissionOut)
async def get_mission(
    mission_id: uuid.UUID,
    _: Participant = Depends(member),
    session: AsyncSession = Depends(get_session),
) -> MissionOut:
    mission = await session.get(Mission, mission_id)
    if mission is None:
        raise HTTPException(404, "mission not found")
    return mission_out(mission, await domain.search_area_ring(session, mission_id))


@router.patch("/missions/{mission_id}", response_model=MissionOut)
async def patch_mission(
    mission_id: uuid.UUID,
    body: MissionPatch,
    actor: Participant = Depends(lead),
    session: AsyncSession = Depends(get_session),
    scheduler: RecomputeScheduler = Depends(get_scheduler),
) -> MissionOut:
    """Set the repeater reference (position and frequencies); calibration depends on it."""
    mission = await session.get(Mission, mission_id)
    if mission is None:
        raise HTTPException(404, "mission not found")
    if "repeater" in body.model_fields_set:
        _set_repeater(mission, body.repeater)
        await domain.audit(session, mission_id, actor.id, "update", "mission", mission_id)
        await session.commit()
        scheduler.schedule(mission_id)
    return mission_out(mission, await domain.search_area_ring(session, mission_id))


@router.post("/missions/{mission_id}/end", response_model=MissionOut)
async def end_mission(
    mission_id: uuid.UUID,
    actor: Participant = Depends(lead),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> MissionOut:
    mission = await session.get(Mission, mission_id)
    if mission is None:
        raise HTTPException(404, "mission not found")
    if mission.status == "ended":
        raise HTTPException(409, "mission already ended")
    open_tx = (
        await session.scalars(
            select(Transmission).where(
                Transmission.mission_id == mission_id, Transmission.ended_at.is_(None)
            )
        )
    ).all()
    now = datetime.now(UTC)
    for tx in open_tx:
        tx.ended_at = now
        tx.ended_by = actor.id
    mission.status = "ended"
    mission.ended_at = now
    await domain.audit(session, mission_id, actor.id, "end", "mission", mission_id)
    await session.commit()
    out = mission_out(mission, await domain.search_area_ring(session, mission_id))
    for tx in open_tx:
        await events.publish(
            redis, mission_id, "transmission_ended", event_json(transmission_out(tx))
        )
    await events.publish(redis, mission_id, "mission_ended", event_json(out))
    return out


@router.post("/missions/{mission_id}/invites", response_model=InviteOut, status_code=201)
async def create_invite(
    mission_id: uuid.UUID,
    body: InviteCreate,
    actor: Participant = Depends(lead),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> InviteOut:
    return await _issue_invite(
        session,
        settings,
        mission_id,
        actor,
        role=body.default_role,
        max_uses=body.max_uses,
        ttl_hours=body.expires_in_hours,
        auto_approve=body.auto_approve,
    )


async def _issue_invite(
    session: AsyncSession,
    settings: Settings,
    mission_id: uuid.UUID,
    actor: Participant,
    *,
    role: str,
    max_uses: int | None,
    ttl_hours: int | None,
    auto_approve: bool = False,
    action: str = "create",
) -> InviteOut:
    """New invite; omitted limits fall back to the server defaults, so links always expire."""
    token = new_invite_token()
    invite = Invite(
        mission_id=mission_id,
        token_hash=hash_token(token),
        default_role=role,
        auto_approve=auto_approve,
        max_uses=max_uses if max_uses is not None else settings.invite_max_uses,
        expires_at=datetime.now(UTC)
        + timedelta(hours=ttl_hours if ttl_hours is not None else settings.invite_ttl_hours),
    )
    session.add(invite)
    await session.flush()
    await domain.audit(session, mission_id, actor.id, action, "invite", invite.id)
    await session.commit()
    return InviteOut(
        id=invite.id,
        token=token,
        default_role=invite.default_role,
        max_uses=invite.max_uses,
        expires_at=invite.expires_at,
        auto_approve=invite.auto_approve,
    )


@router.post("/missions/{mission_id}/invites/replace", response_model=InviteOut, status_code=201)
async def replace_invites(
    mission_id: uuid.UUID,
    actor: Participant = Depends(lead),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> InviteOut:
    """Leak response: revokes every open invite and issues one fresh default link."""
    now = datetime.now(UTC)
    open_invites = (
        await session.scalars(
            select(Invite).where(Invite.mission_id == mission_id, Invite.revoked_at.is_(None))
        )
    ).all()
    for invite in open_invites:
        invite.revoked_at = now
        await domain.audit(session, mission_id, actor.id, "revoke", "invite", invite.id)
    return await _issue_invite(
        session,
        settings,
        mission_id,
        actor,
        role="mobile",
        max_uses=None,
        ttl_hours=None,
        action="replace",
    )


@router.post(
    "/missions/{mission_id}/invites/{invite_id}/rotate", response_model=InviteOut, status_code=201
)
async def rotate_invite(
    mission_id: uuid.UUID,
    invite_id: uuid.UUID,
    actor: Participant = Depends(lead),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> InviteOut:
    """Replaces a leaked link: the old one stops working, joined participants stay in."""
    old = await session.get(Invite, invite_id)
    if old is None or old.mission_id != mission_id:
        raise HTTPException(404, "invite not found")
    if old.revoked_at is None:
        old.revoked_at = datetime.now(UTC)
        await domain.audit(session, mission_id, actor.id, "revoke", "invite", invite_id)
    return await _issue_invite(
        session,
        settings,
        mission_id,
        actor,
        role=old.default_role,
        max_uses=old.max_uses,
        ttl_hours=None,
        auto_approve=old.auto_approve,
        action="rotate",
    )


@router.delete("/missions/{mission_id}/invites/{invite_id}", status_code=204)
async def revoke_invite(
    mission_id: uuid.UUID,
    invite_id: uuid.UUID,
    actor: Participant = Depends(lead),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Revokes the invite; the row is kept for the audit trail."""
    invite = await session.get(Invite, invite_id)
    if invite is None or invite.mission_id != mission_id:
        raise HTTPException(404, "invite not found")
    if invite.revoked_at is None:
        invite.revoked_at = datetime.now(UTC)
        await domain.audit(session, mission_id, actor.id, "revoke", "invite", invite_id)
        await session.commit()


@router.get("/missions/{mission_id}/participants", response_model=list[ParticipantOut])
async def list_participants(
    mission_id: uuid.UUID,
    actor: Participant = Depends(member),
    session: AsyncSession = Depends(get_session),
) -> list[ParticipantOut]:
    rows = (
        await session.scalars(
            select(Participant)
            .where(Participant.mission_id == mission_id)
            .order_by(Participant.joined_at)
        )
    ).all()
    show = actor.role == "lead"
    return [
        participant_out(p, await domain.team_name(session, p.team_id), show_code=show) for p in rows
    ]


@router.patch("/missions/{mission_id}/participants/{participant_id}", response_model=ParticipantOut)
async def patch_participant(
    mission_id: uuid.UUID,
    participant_id: uuid.UUID,
    body: ParticipantPatch,
    actor: Participant = Depends(lead),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    scheduler: RecomputeScheduler = Depends(get_scheduler),
) -> ParticipantOut:
    """Lead only: change the role, remove (or reinstate) a participant, release the device."""
    target = await session.get(Participant, participant_id)
    if target is None or target.mission_id != mission_id:
        raise HTTPException(404, "participant not found")
    if await session.scalar(select(Sensor.id).where(Sensor.participant_id == target.id)):
        raise HTTPException(409, "sensors are managed under /sensors")
    if target.id == actor.id and (
        body.is_active is False
        or body.status == "rejected"
        or body.trusted is False
        or (body.role is not None and body.role != "lead")
    ):
        raise HTTPException(409, "the lead cannot remove or demote themselves")

    changes: dict[str, object] = {}
    if body.role is not None and body.role != target.role:
        changes["role"] = [target.role, body.role]
        target.role = body.role
    if body.is_active is not None and body.is_active != target.is_active:
        changes["is_active"] = body.is_active
        target.is_active = body.is_active
    trusted = body.trusted
    if trusted is None and (
        (body.status == "active" and target.status == "pending") or body.role in ("fixed", "lead")
    ):
        trusted = True  # the lead let them in or gave them a post: that is trust
    if body.status is not None and body.status != target.status:
        changes["status"] = [target.status, body.status]
        target.status = body.status
        target.join_code = None  # decided: the code has served its purpose
    if trusted is not None and trusted != target.trusted:
        changes["trusted"] = trusted
        target.trusted = trusted
    if body.reset_device and target.device_hash is not None:
        changes["device_released"] = True
        target.device_hash = None
    if changes:
        await domain.audit(
            session, mission_id, actor.id, "update", "participant", target.id, **changes
        )
        await session.commit()
        if changes.get("is_active") is False or (
            changes.get("status") and target.status != "active"
        ):
            # Closes the participant's open WebSockets on every worker.
            await events.publish(
                redis, mission_id, "participant_removed", {"participant_id": str(target.id)}
            )
        await _announce(redis, mission_id, target)
        if "trusted" in changes:
            scheduler.schedule(mission_id)
    return participant_out(target, await domain.team_name(session, target.team_id))


SECURITY_ENTITIES = ("participant", "invite")


@router.get("/missions/{mission_id}/audit", response_model=list[AuditOut])
async def get_audit(
    mission_id: uuid.UUID,
    scope: Literal["security", "all"] = "security",
    limit: int = Query(default=200, ge=1, le=1000),
    _: Participant = Depends(lead),
    session: AsyncSession = Depends(get_session),
) -> list[AuditOut]:
    """Lead only: who did what, newest first. ``security`` = joins, approvals, roles, invites."""
    stmt = select(AuditLog).where(AuditLog.mission_id == mission_id)
    if scope == "security":
        stmt = stmt.where(AuditLog.entity.in_(SECURITY_ENTITIES))
    rows = (await session.scalars(stmt.order_by(AuditLog.id.desc()).limit(limit))).all()
    callsigns = {
        p.id: p.callsign
        for p in (
            await session.scalars(select(Participant).where(Participant.mission_id == mission_id))
        ).all()
    }
    out = []
    for r in rows:
        subject = None
        if r.entity == "participant" and r.entity_id:
            try:
                subject = callsigns.get(uuid.UUID(r.entity_id))
            except ValueError:
                subject = None
        out.append(
            AuditOut(
                id=r.id,
                at=r.at,
                actor_id=r.actor_id,
                actor=callsigns.get(r.actor_id) if r.actor_id else None,
                action=r.action,
                entity=r.entity,
                entity_id=r.entity_id,
                subject=subject,
                detail=r.detail,
            )
        )
    return out


@router.get("/missions/{mission_id}/plausibility", response_model=list[PlausibilityOut])
async def get_plausibility(
    mission_id: uuid.UUID,
    _: Participant = Depends(lead),
    session: AsyncSession = Depends(get_session),
) -> list[PlausibilityOut]:
    """Lead only: which participants' data does not fit (hints only, nothing is changed)."""
    est = await session.scalar(
        select(Estimate)
        .where(Estimate.mission_id == mission_id, Estimate.scope == "all")
        .order_by(Estimate.computed_at.desc())
        .limit(1)
    )
    estimate = (est.lat, est.lon, est.n_bearings) if est is not None else None
    sensor_ids = select(Sensor.participant_id).where(Sensor.mission_id == mission_id)
    people = (
        await session.scalars(
            select(Participant).where(
                Participant.mission_id == mission_id,
                Participant.is_active.is_(True),
                Participant.status == "active",
                Participant.id.not_in(sensor_ids),
            )
        )
    ).all()
    facts: dict[uuid.UUID, list[plausibility.BearingFact]] = {p.id: [] for p in people}
    for b in (
        await session.scalars(
            select(Bearing).where(Bearing.mission_id == mission_id, Bearing.is_active.is_(True))
        )
    ).all():
        if b.participant_id in facts:
            facts[b.participant_id].append(
                plausibility.BearingFact(
                    b.lat, b.lon, float(b.azimuth_true_deg), float(b.sigma_deg), b.measured_at
                )
            )
    fixes: dict[uuid.UUID, list[plausibility.Fix]] = {p.id: [] for p in people}
    for s in (
        await session.scalars(
            select(PositionSample).where(PositionSample.mission_id == mission_id).limit(50_000)
        )
    ).all():
        if s.participant_id in fixes:
            fixes[s.participant_id].append(
                plausibility.Fix(s.lat, s.lon, s.recorded_at, s.accuracy_m)
            )
    return [
        PlausibilityOut(
            participant_id=p.id,
            bearings=len(facts[p.id]),
            flags=[
                PlausibilityFlag(code=f.code, detail=f.detail)
                for f in plausibility.assess(facts[p.id], fixes[p.id], estimate)
            ],
        )
        for p in people
    ]


@router.post(
    "/missions/{mission_id}/participants/{participant_id}/quarantine",
    response_model=QuarantineOut,
)
async def quarantine_participant(
    mission_id: uuid.UUID,
    participant_id: uuid.UUID,
    body: QuarantineIn,
    actor: Participant = Depends(lead),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    scheduler: RecomputeScheduler = Depends(get_scheduler),
) -> QuarantineOut:
    """Takes everything a participant contributed out of the estimate at once.

    Their data stays in the log: bearings are deactivated through revisions (like a manual flag),
    readings are deactivated, and the participant is no longer trusted. Optionally the
    participant is removed as well.
    """
    target = await session.get(Participant, participant_id)
    if target is None or target.mission_id != mission_id:
        raise HTTPException(404, "participant not found")
    if target.id == actor.id:
        raise HTTPException(409, "the lead cannot quarantine themselves")
    if await session.scalar(select(Sensor.id).where(Sensor.participant_id == target.id)):
        raise HTTPException(409, "sensors are managed under /sensors")

    bearings = (
        await session.scalars(
            select(Bearing).where(Bearing.participant_id == target.id, Bearing.is_active.is_(True))
        )
    ).all()
    for b in bearings:
        b.is_active = False
        session.add(
            BearingRevision(
                bearing_id=b.id,
                changed_by=actor.id,
                changes={"is_active": {"from": True, "to": False}, "reason": "quarantine"},
            )
        )
    samples = (
        await session.scalars(
            select(RssiSample).where(
                RssiSample.participant_id == target.id, RssiSample.is_active.is_(True)
            )
        )
    ).all()
    for r in samples:
        r.is_active = False
    target.trusted = False
    if body.remove:
        target.is_active = False
    await domain.audit(
        session,
        mission_id,
        actor.id,
        "quarantine",
        "participant",
        target.id,
        bearings=len(bearings),
        rssi_samples=len(samples),
        removed=body.remove,
    )
    await session.commit()
    for b in bearings:
        await events.publish(redis, mission_id, "bearing_updated", event_json(bearing_out(b)))
    if body.remove:
        await events.publish(
            redis, mission_id, "participant_removed", {"participant_id": str(target.id)}
        )
    await _announce(redis, mission_id, target)
    scheduler.schedule(mission_id)
    return QuarantineOut(
        participant=participant_out(target, await domain.team_name(session, target.team_id)),
        bearings_deactivated=len(bearings),
        rssi_deactivated=len(samples),
    )


async def _announce(redis: Redis, mission_id: uuid.UUID, p: Participant) -> None:
    """Tells the connected members (the lead's participant list) about a new or changed one."""
    out = participant_out(p)
    await events.publish(redis, mission_id, "participant_updated", out.model_dump(mode="json"))


@router.get("/missions/{mission_id}/me", response_model=ParticipantOut)
async def whoami(
    mission_id: uuid.UUID,
    me: Participant = Depends(current_participant),
    session: AsyncSession = Depends(get_session),
) -> ParticipantOut:
    """Own state, also for joiners still waiting for approval (they cannot use anything else)."""
    if me.mission_id != mission_id:
        raise HTTPException(403, "not a member of this mission")
    return participant_out(me, await domain.team_name(session, me.team_id), show_code=True)


@router.get("/missions/{mission_id}/snapshot", response_model=SnapshotOut)
async def snapshot(
    mission_id: uuid.UUID,
    actor: Participant = Depends(member),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> SnapshotOut:
    """Full current state; clients load this on start and after every WebSocket reconnect."""
    mission = await session.get(Mission, mission_id)
    if mission is None:
        raise HTTPException(404, "mission not found")
    participants = (
        await session.scalars(select(Participant).where(Participant.mission_id == mission_id))
    ).all()
    latest = (
        await session.scalars(
            select(PositionSample)
            .where(PositionSample.mission_id == mission_id)
            .ext(distinct_on(PositionSample.participant_id))
            .order_by(PositionSample.participant_id, PositionSample.recorded_at.desc())
        )
    ).all()
    bearings = (
        await session.scalars(
            select(Bearing).where(Bearing.mission_id == mission_id).order_by(Bearing.measured_at)
        )
    ).all()
    transmissions = (
        await session.scalars(
            select(Transmission)
            .where(Transmission.mission_id == mission_id)
            .order_by(Transmission.seq)
        )
    ).all()
    estimates = []
    for scope in ("current", "all"):
        est = await session.scalar(
            select(Estimate)
            .where(Estimate.mission_id == mission_id, Estimate.scope == scope)
            .order_by(Estimate.computed_at.desc())
            .limit(1)
        )
        if est is not None:
            estimates.append(estimate_out(est))
    message_rows = (
        await session.execute(
            select(Message, Participant.callsign)
            .join(Participant, Participant.id == Message.author_id)
            .where(Message.mission_id == mission_id, domain.visible_messages(actor))
            .order_by(Message.sent_at.desc())
            .limit(200)
        )
    ).all()
    tasks = (
        await session.scalars(
            select(Task).where(Task.mission_id == mission_id).order_by(Task.created_at)
        )
    ).all()
    teams = (await session.scalars(select(Team).where(Team.mission_id == mission_id))).all()
    rssi_rows = (
        await session.scalars(
            select(RssiSample)
            .where(RssiSample.mission_id == mission_id)
            .order_by(RssiSample.measured_at.desc())
            .limit(1000)
        )
    ).all()
    return SnapshotOut(
        mission=mission_out(mission, await domain.search_area_ring(session, mission_id)),
        participants=[
            participant_out(
                p, await domain.team_name(session, p.team_id), show_code=actor.role == "lead"
            )
            for p in participants
        ],
        positions=[position_out(p) for p in latest],
        bearings=[bearing_out(b) for b in bearings],
        transmissions=[transmission_out(t) for t in transmissions],
        estimates=estimates,
        messages=[message_out(m, cs) for m, cs in reversed(message_rows)],
        tasks=[task_out(t) for t in tasks],
        teams=[TeamOut.model_validate(t) for t in teams],
        rssi=[rssi_out(r) for r in reversed(rssi_rows)],
    )
