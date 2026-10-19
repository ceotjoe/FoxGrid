"""Fixed-window rate limits on Redis (shared by all API workers).

Humans enter a bearing every few seconds at best; a flood from one account or one address is
a bug or sabotage. Offline clients treat 429 as "retry later", so honest bursts after a
reconnect are delayed, not lost.
"""

from __future__ import annotations

from fastapi import HTTPException
from redis.asyncio import Redis

WINDOW_S = 60


async def enforce(redis: Redis, bucket: str, subject: object, limit: int, cost: int = 1) -> None:
    """Counts ``cost`` against ``bucket``/``subject``; raises 429 once over ``limit`` per minute.

    A ``limit`` of 0 switches the check off.
    """
    if limit <= 0:
        return
    key = f"rl:{bucket}:{subject}"
    used = int(await redis.incrby(key, cost))
    if used == cost:  # first hit of this window
        await redis.expire(key, WINDOW_S)
    if used > limit:
        wait = await redis.ttl(key)
        if wait < 0:  # key without expiry (crash between the two calls): heal it
            await redis.expire(key, WINDOW_S)
            wait = WINDOW_S
        raise HTTPException(
            429, f"too many {bucket} requests, retry later", headers={"Retry-After": str(wait)}
        )
