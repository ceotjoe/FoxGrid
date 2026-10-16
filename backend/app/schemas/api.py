from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

Role = Literal["lead", "fixed", "mobile"]
Polarization = Literal["h", "v", "unknown"]
AzimuthRef = Literal["true", "magnetic", "compass"]
Scope = Literal["current", "all"]

_CALLSIGN = re.compile(r"^[A-Z0-9/]{3,15}$")


def normalize_callsign(value: str) -> str:
    cs = value.strip().upper()
    if not _CALLSIGN.match(cs):
        raise ValueError("invalid callsign")
    return cs


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class EngineParamsIn(BaseModel):
    """User-tunable engine settings stored on the mission."""

    model_config = ConfigDict(extra="forbid")

    resolution_m: float | None = Field(default=None, ge=5, le=1000)
    outlier_fraction: float | None = Field(default=None, gt=0, lt=1)
    half_life_s: float | None = Field(default=None, gt=0)
    margin_m: float | None = Field(default=None, ge=1000, le=100_000)


class MissionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    frequency_mhz: float = Field(gt=0, lt=10_000)
    callsign: str  # creator, becomes lead
    # Polygon exterior ring as [[lon, lat], ...] (closed automatically)
    search_area: list[tuple[float, float]] | None = Field(default=None, min_length=3)
    track_retention_days: int = Field(default=30, ge=1, le=3650)
    engine_params: EngineParamsIn = Field(default_factory=EngineParamsIn)

    @field_validator("callsign")
    @classmethod
    def _cs(cls, v: str) -> str:
        return normalize_callsign(v)


class MissionOut(BaseModel):
    id: uuid.UUID
    name: str
    frequency_mhz: float
    status: str
    created_at: datetime
    ended_at: datetime | None
    track_retention_days: int
    engine_params: dict[str, Any]
    search_area: list[tuple[float, float]] | None = None


class ParticipantOut(ORM):
    id: uuid.UUID
    callsign: str
    role: str
    team: str | None = None
    joined_at: datetime
    last_seen_at: datetime | None


class MissionCreated(BaseModel):
    mission: MissionOut
    participant: ParticipantOut
    token: str
    invite_token: str


class JoinIn(BaseModel):
    invite_token: str
    callsign: str
    role: Role = "mobile"
    team: str | None = Field(default=None, max_length=100)

    @field_validator("callsign")
    @classmethod
    def _cs(cls, v: str) -> str:
        return normalize_callsign(v)


class JoinOut(BaseModel):
    mission: MissionOut
    participant: ParticipantOut
    token: str


class InviteCreate(BaseModel):
    default_role: Role = "mobile"
    max_uses: int | None = Field(default=None, ge=1)
    expires_in_hours: int | None = Field(default=None, ge=1, le=24 * 30)


class InviteOut(BaseModel):
    id: uuid.UUID
    token: str
    default_role: str
    max_uses: int | None
    expires_at: datetime | None


class PositionIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0)
    heading_deg: float | None = None
    speed_mps: float | None = Field(default=None, ge=0)
    recorded_at: AwareDatetime


class PositionOut(ORM):
    participant_id: uuid.UUID
    lat: float
    lon: float
    accuracy_m: float | None
    heading_deg: float | None
    speed_mps: float | None
    recorded_at: datetime


class BearingIn(BaseModel):
    id: uuid.UUID  # client generated; makes retries idempotent
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    station_accuracy_m: float | None = Field(default=None, ge=0)
    azimuth_true_deg: float = Field(ge=0, lt=360)
    azimuth_input_ref: AzimuthRef = "true"
    declination_deg_applied: float = Field(default=0.0, ge=-90, le=90)
    sigma_deg: float = Field(gt=0, le=90)  # mandatory
    rssi_dbm: float | None = None
    s_meter: float | None = Field(default=None, ge=0, le=15)
    attenuation_db: float = Field(default=0.0, ge=0)
    polarization: Polarization = "unknown"
    measured_at: AwareDatetime
    note: str | None = Field(default=None, max_length=1000)
    transmission_id: uuid.UUID | None = None


class BearingPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_outlier: bool | None = None
    is_active: bool | None = None
    note: str | None = Field(default=None, max_length=1000)


class BearingOut(ORM):
    id: uuid.UUID
    mission_id: uuid.UUID
    participant_id: uuid.UUID
    transmission_id: uuid.UUID | None
    lat: float
    lon: float
    station_accuracy_m: float | None
    azimuth_true_deg: float
    azimuth_input_ref: str
    declination_deg_applied: float
    sigma_deg: float
    rssi_dbm: float | None
    s_meter: float | None
    attenuation_db: float
    polarization: str
    measured_at: datetime
    received_at: datetime
    note: str | None
    is_outlier: bool
    is_active: bool
    source: str


class RevisionOut(ORM):
    id: int
    bearing_id: uuid.UUID
    changed_by: uuid.UUID
    changed_at: datetime
    changes: dict[str, Any]


class TransmissionStart(BaseModel):
    at: AwareDatetime | None = None
    note: str | None = Field(default=None, max_length=500)


class TransmissionStop(BaseModel):
    at: AwareDatetime | None = None


class TransmissionOut(ORM):
    id: uuid.UUID
    mission_id: uuid.UUID
    seq: int
    started_at: datetime
    ended_at: datetime | None
    source: str
    started_by: uuid.UUID | None
    ended_by: uuid.UUID | None
    note: str | None


class EllipseOut(BaseModel):
    semi_major_m: float
    semi_minor_m: float
    orientation_deg: float
    polygon: dict[str, Any]  # GeoJSON Polygon


class EstimateOut(BaseModel):
    id: uuid.UUID
    mission_id: uuid.UUID
    scope: Scope
    transmission_id: uuid.UUID | None
    computed_at: datetime
    n_bearings: int
    lat: float
    lon: float
    cov_east_east: float
    cov_north_north: float
    cov_east_north: float
    ellipse_1s: EllipseOut
    ellipse_2s: EllipseOut
    resolution_m: float


class SnapshotOut(BaseModel):
    mission: MissionOut
    participants: list[ParticipantOut]
    positions: list[PositionOut]  # latest per participant
    bearings: list[BearingOut]
    transmissions: list[TransmissionOut]
    estimates: list[EstimateOut]  # latest per scope
