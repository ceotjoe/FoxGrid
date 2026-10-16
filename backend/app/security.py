from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.config import Settings

ALGORITHM = "HS256"


def new_invite_token() -> str:
    return secrets.token_urlsafe(24)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_jwt(
    settings: Settings, participant_id: uuid.UUID, mission_id: uuid.UUID, role: str
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(participant_id),
        "mission_id": str(mission_id),
        "role": role,
        "iat": now,
        "exp": now + timedelta(hours=settings.jwt_ttl_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_jwt(settings: Settings, token: str) -> dict[str, str]:
    """Raises ``jwt.PyJWTError`` for invalid or expired tokens."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])  # type: ignore[no-any-return]
