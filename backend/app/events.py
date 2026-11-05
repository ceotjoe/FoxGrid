"""Live event fan-out over Redis Pub/Sub (works across multiple API workers)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis

EVENT_TYPES = frozenset(
    {
        "participant_position",
        "mission_ended",
        "participant_removed",
        "participant_updated",
        "bearing_created",
        "bearing_updated",
        "point_created",
        "point_updated",
        "transmission_started",
        "transmission_ended",
        "estimate_updated",
        "message",
        "task_updated",
    }
)


# Events that need more than `view.result`. Observers get neither chat nor positions of others.
EVENT_PERMISSION: dict[str, str] = {
    "participant_position": "view.positions",
    "message": "chat.read",
    "task_updated": "task.work",
}


def event_permission(type_: str) -> str:
    return EVENT_PERMISSION.get(type_, "view.result")


def channel(mission_id: uuid.UUID | str, team_id: uuid.UUID | str | None = None) -> str:
    """Mission-wide channel, or the private channel of one team."""
    base = f"mission:{mission_id}"
    return base if team_id is None else f"{base}:team:{team_id}"


async def publish(
    redis: Redis,
    mission_id: uuid.UUID,
    type_: str,
    data: dict[str, Any],
    team_id: uuid.UUID | None = None,
) -> None:
    if type_ not in EVENT_TYPES:
        raise ValueError(f"unknown event type {type_}")
    seq = await redis.incr(f"seq:{mission_id}")
    event = {
        "type": type_,
        "mission_id": str(mission_id),
        "seq": seq,
        "ts": datetime.now(UTC).isoformat(),
        "data": data,
    }
    await redis.publish(channel(mission_id, team_id), json.dumps(event, default=str))
