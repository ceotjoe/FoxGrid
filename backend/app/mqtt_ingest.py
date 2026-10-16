"""MQTT ingest service: ``python -m app.mqtt_ingest``.

Runs as its own process (one instance) so messages are handled once, no matter how many API
workers run. It shares the database and Redis with the API; events reach app clients through
the usual Redis fan-out.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

import aiomqtt
from redis.asyncio import Redis

from app.config import Settings
from app.db import make_engine, make_sessionmaker
from app.services import push
from app.services.ingest import IngestContext, handle_message
from app.services.recompute import RecomputeScheduler

log = logging.getLogger("foxgrid.ingest")

SUBSCRIPTION = "foxgrid/+/+/+"


async def run(settings: Settings, *, reconnect_delay_s: float = 3.0) -> None:
    engine = make_engine(settings.database_url)
    sessionmaker = make_sessionmaker(engine)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    scheduler = RecomputeScheduler(sessionmaker, redis, settings)
    ctx = IngestContext(sessionmaker, redis, scheduler, push.make_sender(settings), settings)
    try:
        while True:
            try:
                async with aiomqtt.Client(
                    hostname=settings.mqtt_host,
                    port=settings.mqtt_port,
                    username=settings.mqtt_username,
                    password=settings.mqtt_password,
                    identifier="foxgrid-ingest",
                    clean_session=False,  # QoS 1 messages published while we restart are kept
                ) as client:
                    await client.subscribe(SUBSCRIPTION, qos=1)
                    log.info(
                        "subscribed to %s on %s:%s",
                        SUBSCRIPTION,
                        settings.mqtt_host,
                        settings.mqtt_port,
                    )
                    async for message in client.messages:
                        try:
                            result = await handle_message(
                                ctx, str(message.topic), bytes(message.payload or b"")
                            )  # type: ignore[arg-type]
                            log.debug("%s -> %s", message.topic, result)
                        except Exception:
                            log.exception("failed to handle message on %s", message.topic)
            except aiomqtt.MqttError as exc:
                log.warning("MQTT connection lost (%s); retrying in %.0f s", exc, reconnect_delay_s)
                await asyncio.sleep(reconnect_delay_s)
    finally:
        await scheduler.shutdown()
        await redis.aclose()
        await engine.dispose()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run(Settings()))  # type: ignore[call-arg]


if __name__ == "__main__":
    main()
