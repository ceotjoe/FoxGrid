"""ORM models. Point columns store lat/lon; PostGIS `geom` columns are generated in SQL."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


_UUID = UUID(as_uuid=True)
_TS = DateTime(timezone=True)


class Mission(Base):
    __tablename__ = "missions"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    frequency_mhz: Mapped[float] = mapped_column(Numeric(8, 4))
    search_area: Mapped[Any] = mapped_column(Geography("POLYGON", 4326), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="active")
    created_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(_TS, nullable=True)
    track_retention_days: Mapped[int] = mapped_column(Integer, default=30)
    engine_params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    __table_args__ = (CheckConstraint("status in ('active','ended')", name="ck_mission_status"),)


class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, default=uuid.uuid4)
    mission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("missions.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    default_role: Mapped[str] = mapped_column(String(10), default="mobile")
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(_TS, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(_TS, nullable=True)
    created_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, default=uuid.uuid4)
    mission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("missions.id"))
    name: Mapped[str] = mapped_column(String(100))

    __table_args__ = (UniqueConstraint("mission_id", "name", name="uq_team_name"),)


class Participant(Base):
    __tablename__ = "participants"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, default=uuid.uuid4)
    mission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("missions.id"), index=True)
    callsign: Mapped[str] = mapped_column(String(20))
    role: Mapped[str] = mapped_column(String(10))
    team_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    joined_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(_TS, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        UniqueConstraint("mission_id", "callsign", name="uq_participant_callsign"),
        CheckConstraint("role in ('lead','fixed','mobile')", name="ck_participant_role"),
    )


class PositionSample(Base):
    __tablename__ = "position_samples"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    mission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("missions.id"))
    participant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("participants.id"))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    heading_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    speed_mps: Mapped[float | None] = mapped_column(Float, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(_TS)
    received_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)

    __table_args__ = (
        Index("ix_position_mission_time", "mission_id", "recorded_at"),
        Index("ix_position_participant_time", "participant_id", "recorded_at"),
    )


class Transmission(Base):
    __tablename__ = "transmissions"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, default=uuid.uuid4)
    mission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("missions.id"))
    seq: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(_TS)
    ended_at: Mapped[datetime | None] = mapped_column(_TS, nullable=True)
    source: Mapped[str] = mapped_column(String(10), default="manual")
    started_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("participants.id"), nullable=True
    )
    ended_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("participants.id"), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("mission_id", "seq", name="uq_transmission_seq"),
        Index(
            "uq_one_open_transmission",
            "mission_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
        CheckConstraint("source in ('manual','relay','mqtt')", name="ck_transmission_source"),
    )


class Bearing(Base):
    __tablename__ = "bearings"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)  # client generated
    mission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("missions.id"), index=True)
    participant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("participants.id"))
    transmission_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transmissions.id"), nullable=True
    )
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    station_accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    azimuth_true_deg: Mapped[float] = mapped_column(Numeric(5, 2))
    azimuth_input_ref: Mapped[str] = mapped_column(String(10), default="true")
    declination_deg_applied: Mapped[float] = mapped_column(Float, default=0.0)
    sigma_deg: Mapped[float] = mapped_column(Numeric(5, 2))
    rssi_dbm: Mapped[float | None] = mapped_column(Float, nullable=True)
    s_meter: Mapped[float | None] = mapped_column(Float, nullable=True)
    attenuation_db: Mapped[float] = mapped_column(Float, default=0.0)
    polarization: Mapped[str] = mapped_column(String(10), default="unknown")
    measured_at: Mapped[datetime] = mapped_column(_TS)
    received_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_outlier: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(10), default="manual")
    sensor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sensors.id"), nullable=True)

    __table_args__ = (
        CheckConstraint("azimuth_true_deg >= 0 AND azimuth_true_deg < 360", name="ck_bearing_az"),
        CheckConstraint("sigma_deg > 0 AND sigma_deg <= 90", name="ck_bearing_sigma"),
        CheckConstraint(
            "azimuth_input_ref in ('true','magnetic','compass')", name="ck_bearing_ref"
        ),
        CheckConstraint("polarization in ('h','v','unknown')", name="ck_bearing_pol"),
        CheckConstraint("source in ('manual','sensor')", name="ck_bearing_source"),
        Index("ix_bearing_mission_measured", "mission_id", "measured_at"),
    )


class BearingRevision(Base):
    __tablename__ = "bearing_revisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bearing_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bearings.id"), index=True)
    changed_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("participants.id"))
    changed_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)
    changes: Mapped[dict[str, Any]] = mapped_column(JSONB)


class Estimate(Base):
    __tablename__ = "estimates"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, default=uuid.uuid4)
    mission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("missions.id"))
    computed_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)
    scope: Mapped[str] = mapped_column(String(10))
    transmission_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transmissions.id"), nullable=True
    )
    input_hash: Mapped[str] = mapped_column(String(64))
    n_bearings: Mapped[int] = mapped_column(Integer)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    cov_ee: Mapped[float] = mapped_column(Float)
    cov_nn: Mapped[float] = mapped_column(Float)
    cov_en: Mapped[float] = mapped_column(Float)
    ellipse_1s: Mapped[dict[str, Any]] = mapped_column(JSONB)
    ellipse_2s: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # probability mass ("50"/"80"/"95") -> list of closed GeoJSON polygons
    contours: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        CheckConstraint("scope in ('current','all')", name="ck_estimate_scope"),
        Index("ix_estimate_mission_scope_time", "mission_id", "scope", "computed_at"),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    mission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("missions.id"), index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("participants.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(50))
    entity: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    at: Mapped[datetime] = mapped_column(_TS, default=utcnow)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)  # client generated
    mission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("missions.id"))
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("participants.id"))
    team_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(_TS)
    received_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)

    __table_args__ = (Index("ix_message_mission_sent", "mission_id", "sent_at"),)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)  # client generated
    mission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("missions.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(15), default="open")
    assignee_participant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("participants.id"), nullable=True
    )
    assignee_team_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("teams.id"), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("participants.id"))
    created_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status in ('open','in_progress','done','cancelled')", name="ck_task_status"
        ),
        CheckConstraint(
            "assignee_participant_id IS NULL OR assignee_team_id IS NULL", name="ck_task_assignee"
        ),
    )


class TaskEvent(Base):
    __tablename__ = "task_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("participants.id"))
    at: Mapped[datetime] = mapped_column(_TS, default=utcnow)
    change: Mapped[dict[str, Any]] = mapped_column(JSONB)


class PushToken(Base):
    __tablename__ = "push_tokens"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, default=uuid.uuid4)
    participant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("participants.id"), index=True)
    platform: Mapped[str] = mapped_column(String(10))
    token: Mapped[str] = mapped_column(String(512), unique=True)
    created_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)

    __table_args__ = (
        CheckConstraint("platform in ('fcm','apns','webpush')", name="ck_push_platform"),
    )


class RssiSample(Base):
    """One signal strength reading of the homing track. Append-only like bearings."""

    __tablename__ = "rssi_samples"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)  # client generated
    mission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("missions.id"), index=True)
    participant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("participants.id"))
    transmission_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transmissions.id"), nullable=True
    )
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    rssi_dbm: Mapped[float] = mapped_column(Float)
    s_meter: Mapped[float | None] = mapped_column(Float, nullable=True)  # informational
    attenuation_db: Mapped[float] = mapped_column(Float, default=0.0)
    measured_at: Mapped[datetime] = mapped_column(_TS)
    received_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)
    source: Mapped[str] = mapped_column(String(10), default="manual")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sensor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sensors.id"), nullable=True)

    __table_args__ = (
        CheckConstraint("source in ('manual','cat','sensor')", name="ck_rssi_source"),
        CheckConstraint("attenuation_db >= 0", name="ck_rssi_attenuation"),
        Index("ix_rssi_mission_measured", "mission_id", "measured_at"),
    )


class Sensor(Base):
    """An automatic station (bearings/RSSI) or a repeater hook that reports over MQTT.

    Every sensor owns a virtual participant so its data fits the normal model (bearings need a
    participant). That participant can never be joined by a human.
    """

    __tablename__ = "sensors"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, default=uuid.uuid4)
    mission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("missions.id"), index=True)
    participant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("participants.id"), unique=True)
    name: Mapped[str] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(String(10), default="station")
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)  # fixed position
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(_TS, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        CheckConstraint("kind in ('station','relay')", name="ck_sensor_kind"),
        UniqueConstraint("mission_id", "name", name="uq_sensor_name"),
    )
