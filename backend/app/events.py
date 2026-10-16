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
        "bearing_created",
        "bearing_updated",
        "transmission_started",
        "transmission_ended",
        "estimate_updated",
        "message",
        "task_updated",
    }
)


def channel(mission_id: uuid.UUID | str) -> str:
    return f"mission:{mission_id}"


async def publish(redis: Redis, mission_id: uuid.UUID, type_: str, data: dict[str, Any]) -> None:
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
    await redis.publish(channel(mission_id), json.dumps(event, default=str))
