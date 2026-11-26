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
from app.models import (
    Bearing,
    Interferer,
    Mission,
    Participant,
    RssiSample,
    Sensor,
    Transmission,
)
from app.schemas.api import PositionIn
from app.security import hash_token
from app.services import domain, push, transmissions
from app.services.recompute import RecomputeScheduler
from app.services.serialize import bearing_out, event_json

log = logging.getLogger(__name__)

MAX_PAYLOAD = 64 * 1024
SEEN_WRITE_INTERVAL = timedelta(seconds=10)
MAX_WINDOW = timedelta(minutes=10)  # longest averaging window of a sensor bearing
WINDOW_TOLERANCE = timedelta(seconds=1)  # rounding between measured_at and the window


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
    interferer: uuid.UUID | None = None  # else the sensor's default, the transmission's, mission's
    # Span of the readings averaged into the bearing; the manual gate checks it against the
    # transmissions (ADR 0010). Without it the measurement time is used.
    window_start: AwareDatetime | None = None
    window_end: AwareDatetime | None = None

    @model_validator(mode="after")
    def _window(self) -> BearingMsg:
        if (self.window_start is None) != (self.window_end is None):
            raise ValueError("window_start and window_end go together")
        start, end = self.window_start, self.window_end
        if start is not None and end is not None:
            fits = start - WINDOW_TOLERANCE <= self.measured_at <= end + WINDOW_TOLERANCE
            if not (start <= end and end - start <= MAX_WINDOW and fits):
                raise ValueError("window must contain measured_at and span at most 10 min")
        return self


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
    interferer: uuid.UUID | None = None  # for all samples of the message

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
    """Heartbeat. Mobile stations add their position, which becomes the sensor's track."""

    key: str
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    speed: float | None = Field(default=None, ge=0, le=100)  # m/s
    heading: float | None = Field(default=None, ge=0, lt=360)  # true north
    at: AwareDatetime | None = None  # time of the fix (default: time of receipt)

    @model_validator(mode="after")
    def _both_or_neither(self) -> StatusMsg:
        if (self.lat is None) != (self.lon is None):
            raise ValueError("send lat and lon together")
        return self


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
                return await _status(ctx, session, sensor, StatusMsg.model_validate(doc))
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


async def _interferer(
    session: AsyncSession,
    sensor: Sensor,
    requested: uuid.UUID | None,
    tx: Transmission | None,
) -> uuid.UUID:
    """Message > sensor default > transmission > mission default.

    A named interferer that is unknown or inactive rejects the message. A sensor default that was
    deactivated meanwhile is skipped, so the station keeps reporting.
    """
    if requested is None and sensor.interferer_id is not None:
        default = await session.get(Interferer, sensor.interferer_id)
        if default is not None and default.is_active:
            requested = default.id
    try:
        return await domain.resolve_interferer(session, sensor.mission_id, requested, tx)
    except ValueError:
        raise RejectedError("interferer") from None


async def _status(ctx: IngestContext, session: AsyncSession, sensor: Sensor, msg: StatusMsg) -> str:
    if msg.lat is None or msg.lon is None:
        return "ok"
    participant = await session.get(Participant, sensor.participant_id)
    if participant is None:
        raise RejectedError("mission")
    position = PositionIn(
        lat=msg.lat,
        lon=msg.lon,
        heading_deg=msg.heading,
        speed_mps=msg.speed,
        recorded_at=msg.at or datetime.now(UTC),
    )
    await domain.record_positions(
        session, ctx.redis, ctx.settings, participant, [position], store_all=True
    )
    return "ok"


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
    tx = await session.get(Transmission, tx_id) if tx_id is not None else None
    interferer_id = await _interferer(session, sensor, msg.interferer, tx)
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
        interferer_id=interferer_id,
        window_start=msg.window_start,
        window_end=msg.window_end,
    )
    session.add(bearing)
    await session.flush()
    if await domain.evaluate_gate(session, sensor.mission_id, [bearing.id]):
        await session.refresh(bearing, ["gate_state"])
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
        tx_id = await domain.assign_transmission(session, sensor.mission_id, item.measured_at)
        tx = await session.get(Transmission, tx_id) if tx_id is not None else None
        session.add(
            RssiSample(
                id=item.id,
                mission_id=sensor.mission_id,
                participant_id=sensor.participant_id,
                transmission_id=tx_id,
                interferer_id=await _interferer(session, sensor, msg.interferer, tx),
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
