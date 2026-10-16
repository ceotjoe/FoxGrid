from __future__ import annotations

import uuid

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import get_session
from app.models import Participant
from app.security import decode_jwt
from app.services.recompute import RecomputeScheduler

bearer = HTTPBearer(auto_error=False)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def get_redis(request: Request) -> Redis:
    return request.app.state.redis  # type: ignore[no-any-return]


def get_scheduler(request: Request) -> RecomputeScheduler:
    return request.app.state.recompute  # type: ignore[no-any-return]


async def current_participant(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> Participant:
    if creds is None:
        raise HTTPException(401, "missing bearer token")
    try:
        claims = decode_jwt(settings, creds.credentials)
        pid = uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(401, "invalid token") from exc
    participant = await session.get(Participant, pid)
    if participant is None or not participant.is_active:
        raise HTTPException(401, "unknown participant")
    return participant


async def member(
    mission_id: uuid.UUID, participant: Participant = Depends(current_participant)
) -> Participant:
    if participant.mission_id != mission_id:
        raise HTTPException(403, "not a member of this mission")
    return participant


async def lead(participant: Participant = Depends(member)) -> Participant:
    if participant.role != "lead":
        raise HTTPException(403, "lead role required")
    return participant
