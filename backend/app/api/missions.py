from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_redis, get_settings, lead, member
from app.config import Settings
from app.db import get_session
from app.models import (
    Bearing,
    Estimate,
    Invite,
    Message,
    Mission,
    Participant,
    PositionSample,
    RssiSample,
    Task,
    Team,
    Transmission,
)
from app.schemas.api import (
    InviteCreate,
    InviteOut,
    JoinIn,
    JoinOut,
    MissionCreate,
    MissionCreated,
    MissionOut,
    ParticipantOut,
    SnapshotOut,
    TeamOut,
)
from app.security import create_jwt, hash_token, new_invite_token
from app.services import domain
from app.services.serialize import (
    bearing_out,
    estimate_out,
    message_out,
    mission_out,
    participant_out,
    position_out,
    rssi_out,
    task_out,
    transmission_out,
)

router = APIRouter()


@router.post("/missions", response_model=MissionCreated, status_code=201)
async def create_mission(
    body: MissionCreate,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> MissionCreated:
    mission = Mission(
        name=body.name,
        frequency_mhz=body.frequency_mhz,
        search_area=domain.polygon_wkt(body.search_area) if body.search_area else None,
        track_retention_days=body.track_retention_days,
        engine_params=body.engine_params.model_dump(exclude_none=True),
    )
    session.add(mission)
    await session.flush()
    creator = Participant(mission_id=mission.id, callsign=body.callsign, role="lead")
    session.add(creator)
    invite_token = new_invite_token()
    session.add(
        Invite(mission_id=mission.id, token_hash=hash_token(invite_token), default_role="mobile")
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
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JoinOut:
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
    if participant is None:
        if invite.max_uses is not None and invite.uses >= invite.max_uses:
            raise HTTPException(403, "invalid or expired invite")
        role = body.role if invite.default_role == "lead" or body.role != "lead" else "mobile"
        participant = Participant(mission_id=mission.id, callsign=body.callsign, role=role)
        session.add(participant)
        invite.uses += 1
        await session.flush()
        await domain.audit(
            session, mission.id, participant.id, "join", "participant", participant.id
        )
    elif not participant.is_active:
        raise HTTPException(403, "participant deactivated")
    if body.team:
        team = await domain.get_or_create_team(session, mission.id, body.team)
        participant.team_id = team.id
    await session.commit()
    area = await domain.search_area_ring(session, mission.id)
    return JoinOut(
        mission=mission_out(mission, area),
        participant=participant_out(
            participant, await domain.team_name(session, participant.team_id)
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


@router.post("/missions/{mission_id}/end", response_model=MissionOut)
async def end_mission(
    mission_id: uuid.UUID,
    actor: Participant = Depends(lead),
    session: AsyncSession = Depends(get_session),
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
    return mission_out(mission, await domain.search_area_ring(session, mission_id))


@router.post("/missions/{mission_id}/invites", response_model=InviteOut, status_code=201)
async def create_invite(
    mission_id: uuid.UUID,
    body: InviteCreate,
    actor: Participant = Depends(lead),
    session: AsyncSession = Depends(get_session),
) -> InviteOut:
    token = new_invite_token()
    expires = (
        datetime.now(UTC) + timedelta(hours=body.expires_in_hours)
        if body.expires_in_hours
        else None
    )
    invite = Invite(
        mission_id=mission_id,
        token_hash=hash_token(token),
        default_role=body.default_role,
        max_uses=body.max_uses,
        expires_at=expires,
    )
    session.add(invite)
    await session.flush()
    await domain.audit(session, mission_id, actor.id, "create", "invite", invite.id)
    await session.commit()
    return InviteOut(
        id=invite.id,
        token=token,
        default_role=invite.default_role,
        max_uses=invite.max_uses,
        expires_at=invite.expires_at,
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
    _: Participant = Depends(member),
    session: AsyncSession = Depends(get_session),
) -> list[ParticipantOut]:
    rows = (
        await session.scalars(
            select(Participant)
            .where(Participant.mission_id == mission_id)
            .order_by(Participant.joined_at)
        )
    ).all()
    return [participant_out(p, await domain.team_name(session, p.team_id)) for p in rows]


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
            participant_out(p, await domain.team_name(session, p.team_id)) for p in participants
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
