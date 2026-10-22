"""Handlers for sensor messages that arrive over MQTT.

Topics (QoS 1) are ``foxgrid/<mission_id>/<sensor_id>/<kind>`` with ``kind`` one of ``bearing``,
``rssi``, ``status`` and ``transmission``. Every payload is JSON and carries the sensor's API key in
``key``; the broker credentials only decide who may talk to the broker at all.
See docs/reference/mqtt.md.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import AwareDatetime, BaseModel, Field, ValidationError, model_validator
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import events
from app.config import Settings
from app.models import Bearing, Mission, Participant, RssiSample, Sensor
from app.security import hash_token
from app.services import domain, push, transmissions
from app.services.recompute import RecomputeScheduler
from app.services.serialize import bearing_out, event_json

log = logging.getLogger(__name__)

MAX_PAYLOAD = 64 * 1024
SEEN_WRITE_INTERVAL = timedelta(seconds=10)


class BearingMsg(BaseModel):
    key: str
    id: uuid.UUID  # sensor generated; redelivered messages are ignored
    azimuth_true_deg: float = Field(ge=0, lt=360)
    sigma_deg: float = Field(gt=0, le=90)
    measured_at: AwareDatetime
    lat: float | None = Field(default=None, ge=-90, le=90)  # defaults to the fixed position
    lon: float | None = Field(default=None, ge=-180, le=180)
    rssi_dbm: float | None = Field(default=None, ge=-200, le=20)
    attenuation_db: float = Field(default=0.0, ge=0, le=100)
    polarization: str = Field(default="unknown", pattern="^(h|v|unknown)$")
    note: str | None = Field(default=None, max_length=500)


class RssiItem(BaseModel):
    id: uuid.UUID
    rssi_dbm: float = Field(ge=-200, le=20)
    attenuation_db: float = Field(default=0.0, ge=0, le=100)
    measured_at: AwareDatetime
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)


class RssiMsg(BaseModel):
    """Either a flat single sample or ``samples`` with up to 100 of them."""

    key: str
    samples: list[RssiItem] = Field(default_factory=list, max_length=100)
    id: uuid.UUID | None = None
    rssi_dbm: float | None = Field(default=None, ge=-200, le=20)
    attenuation_db: float = Field(default=0.0, ge=0, le=100)
    measured_at: AwareDatetime | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def _normalise(self) -> RssiMsg:
        if not self.samples:
            if self.id is None or self.rssi_dbm is None or self.measured_at is None:
                raise ValueError("send samples[] or id, rssi_dbm and measured_at")
            self.samples = [
                RssiItem(
                    id=self.id,
                    rssi_dbm=self.rssi_dbm,
                    attenuation_db=self.attenuation_db,
                    measured_at=self.measured_at,
                    lat=self.lat,
                    lon=self.lon,
                )
            ]
        return self


class StatusMsg(BaseModel):
    key: str


class TransmissionMsg(BaseModel):
    """From a repeater hook: the interferer keyed up (``start``) or dropped out (``stop``)."""

    key: str
    event: str = Field(pattern="^(start|stop)$")
    at: AwareDatetime | None = None
    note: str | None = Field(default=None, max_length=500)


class RejectedError(Exception):
    """The message is dropped; the reason is returned to the caller (and logged)."""


@dataclass
class IngestContext:
    sessionmaker: async_sessionmaker[AsyncSession]
    redis: Redis
    scheduler: RecomputeScheduler
    push_sender: push.PushSender
    settings: Settings
    background: set[asyncio.Task[None]] = field(default_factory=set)
    _recent: dict[uuid.UUID, deque[float]] = field(default_factory=dict)

    def allow(self, sensor_id: uuid.UUID, now: float | None = None) -> bool:
        """Sliding one second window per sensor: a runaway device must not flood the database."""
        now = time.monotonic() if now is None else now
        window = self._recent.setdefault(sensor_id, deque())
        while window and now - window[0] > 1.0:
            window.popleft()
        if len(window) >= self.settings.mqtt_max_msgs_per_s:
            return False
        window.append(now)
        return True


def parse_topic(topic: str) -> tuple[uuid.UUID, uuid.UUID, str] | None:
    parts = topic.split("/")
    if len(parts) != 4 or parts[0] != "foxgrid":
        return None
    try:
        return uuid.UUID(parts[1]), uuid.UUID(parts[2]), parts[3]
    except ValueError:
        return None


async def _authenticate(
    session: AsyncSession, mission_id: uuid.UUID, sensor_id: uuid.UUID, key: str
) -> Sensor:
    sensor = await session.get(Sensor, sensor_id)
    ok = sensor is not None and sensor.mission_id == mission_id and sensor.is_active
    # Compare against a hash even for unknown sensors so timing reveals nothing.
    expected = sensor.api_key_hash if sensor is not None else "0" * 64
    if not hmac.compare_digest(hash_token(key), expected) or not ok:
        raise RejectedError("auth")
    assert sensor is not None
    return sensor


async def handle_message(ctx: IngestContext, topic: str, payload: bytes | str) -> str:
    """Process one MQTT message. Returns ``ok``, ``duplicate`` or ``rejected:<reason>``."""
    parsed = parse_topic(topic)
    if parsed is None:
        return "rejected:topic"
    mission_id, sensor_id, kind = parsed
    raw = payload.encode() if isinstance(payload, str) else bytes(payload)
    if len(raw) > MAX_PAYLOAD:
        return "rejected:too_large"
    try:
        doc = json.loads(raw)
        key = doc["key"]
        if not isinstance(key, str):
            raise TypeError
    except (ValueError, KeyError, TypeError):
        return "rejected:payload"
    if not ctx.allow(sensor_id):
        return "rejected:rate_limited"
    try:
        async with ctx.sessionmaker() as session:
            sensor = await _authenticate(session, mission_id, sensor_id, key)
            now = datetime.now(UTC)
            if (
                kind == "status"
                or sensor.last_seen_at is None
                or (now - sensor.last_seen_at > SEEN_WRITE_INTERVAL)
            ):
                sensor.last_seen_at = now
                await session.commit()
            if kind == "status":
                StatusMsg.model_validate(doc)
                return "ok"
            if kind == "bearing":
                return await _bearing(ctx, session, sensor, BearingMsg.model_validate(doc))
            if kind == "rssi":
                return await _rssi(ctx, session, sensor, RssiMsg.model_validate(doc))
            if kind == "transmission":
                return await _transmission(
                    ctx, session, sensor, TransmissionMsg.model_validate(doc)
                )
            return "rejected:kind"
    except RejectedError as exc:
        log.warning("sensor message rejected (%s) on %s", exc, topic)
        return f"rejected:{exc}"
    except ValidationError as exc:
        log.warning("invalid sensor payload on %s: %s", topic, exc.errors()[:2])
        return "rejected:invalid"


def _position(sensor: Sensor, lat: float | None, lon: float | None) -> tuple[float, float]:
    lat = lat if lat is not None else sensor.lat
    lon = lon if lon is not None else sensor.lon
    if lat is None or lon is None:
        raise RejectedError("no_position")  # neither in the message nor registered as fixed
    return lat, lon


async def _bearing(
    ctx: IngestContext, session: AsyncSession, sensor: Sensor, msg: BearingMsg
) -> str:
    existing = await session.get(Bearing, msg.id)
    if existing is not None:
        if existing.sensor_id != sensor.id:
            raise RejectedError("id_conflict")
        return "duplicate"
    lat, lon = _position(sensor, msg.lat, msg.lon)
    if await session.get(Mission, sensor.mission_id) is None:
        raise RejectedError("mission")
    tx_id = await domain.assign_transmission(session, sensor.mission_id, msg.measured_at)
    bearing = Bearing(
        id=msg.id,
        mission_id=sensor.mission_id,
        participant_id=sensor.participant_id,
        transmission_id=tx_id,
        lat=lat,
        lon=lon,
        azimuth_true_deg=msg.azimuth_true_deg,
        azimuth_input_ref="true",
        sigma_deg=msg.sigma_deg,
        rssi_dbm=msg.rssi_dbm,
        attenuation_db=msg.attenuation_db,
        polarization=msg.polarization,
        measured_at=msg.measured_at,
        note=msg.note,
        source="sensor",
        sensor_id=sensor.id,
    )
    session.add(bearing)
    await session.commit()
    await events.publish(
        ctx.redis, sensor.mission_id, "bearing_created", event_json(bearing_out(bearing))
    )
    ctx.scheduler.schedule(sensor.mission_id)
    return "ok"


async def _rssi(ctx: IngestContext, session: AsyncSession, sensor: Sensor, msg: RssiMsg) -> str:
    ids = [s.id for s in msg.samples]
    known = set(await session.scalars(select(RssiSample.id).where(RssiSample.id.in_(ids))))
    stored = 0
    for item in msg.samples:
        if item.id in known:
            continue
        lat, lon = _position(sensor, item.lat, item.lon)
        session.add(
            RssiSample(
                id=item.id,
                mission_id=sensor.mission_id,
                participant_id=sensor.participant_id,
                transmission_id=await domain.assign_transmission(
                    session, sensor.mission_id, item.measured_at
                ),
                lat=lat,
                lon=lon,
                rssi_dbm=item.rssi_dbm,
                attenuation_db=item.attenuation_db,
                measured_at=item.measured_at,
                source="sensor",
                sensor_id=sensor.id,
                receiver="omni",  # sensors sit at a fixed position
            )
        )
        stored += 1
    if not stored:
        return "duplicate"
    await session.commit()
    ctx.scheduler.schedule(sensor.mission_id)
    return "ok"


async def _transmission(
    ctx: IngestContext, session: AsyncSession, sensor: Sensor, msg: TransmissionMsg
) -> str:
    if sensor.kind != "relay":
        raise RejectedError("not_relay")
    mission = await session.get(Mission, sensor.mission_id)
    actor = await session.get(Participant, sensor.participant_id)
    if mission is None or actor is None or mission.status != "active":
        raise RejectedError("mission")
    if msg.event == "start":

        def notify(_: Any) -> None:
            task = asyncio.create_task(
                push.notify_transmission_started(
                    ctx.push_sender, ctx.sessionmaker, mission.id, actor.id, mission.name
                )
            )
            ctx.background.add(task)
            task.add_done_callback(ctx.background.discard)

        try:
            await transmissions.start_transmission(
                session,
                ctx.redis,
                ctx.scheduler,
                mission,
                actor,
                at=msg.at,
                note=msg.note,
                source="relay",
                after_commit=notify,
            )
        except transmissions.AlreadyRunningError:
            return "duplicate"  # a repeated start while on air is not an error
        return "ok"
    try:
        await transmissions.stop_transmission(
            session, ctx.redis, ctx.scheduler, mission.id, actor, at=msg.at
        )
    except transmissions.NotRunningError:
        return "duplicate"
    except transmissions.NotAllowedError:
        raise RejectedError("not_allowed") from None
    return "ok"
