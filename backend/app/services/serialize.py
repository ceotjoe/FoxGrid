"""ORM -> API/event payload conversion."""

from __future__ import annotations

from typing import Any

from app.models import (
    Bearing,
    Estimate,
    Message,
    Mission,
    Participant,
    PositionSample,
    RssiSample,
    Task,
    Transmission,
)
from app.schemas.api import (
    BearingOut,
    EstimateOut,
    MessageOut,
    MissionOut,
    ParticipantOut,
    PositionOut,
    RssiFitOut,
    RssiOut,
    TaskOut,
    TransmissionOut,
)


def mission_out(m: Mission, area: list[tuple[float, float]] | None = None) -> MissionOut:
    return MissionOut(
        id=m.id,
        name=m.name,
        frequency_mhz=float(m.frequency_mhz),
        status=m.status,
        created_at=m.created_at,
        ended_at=m.ended_at,
        track_retention_days=m.track_retention_days,
        engine_params=m.engine_params,
        search_area=area,
    )


def participant_out(p: Participant, team: str | None = None) -> ParticipantOut:
    return ParticipantOut(
        id=p.id,
        callsign=p.callsign,
        role=p.role,
        team=team,
        joined_at=p.joined_at,
        last_seen_at=p.last_seen_at,
    )


def bearing_out(b: Bearing) -> BearingOut:
    return BearingOut(
        id=b.id,
        mission_id=b.mission_id,
        participant_id=b.participant_id,
        transmission_id=b.transmission_id,
        lat=b.lat,
        lon=b.lon,
        station_accuracy_m=b.station_accuracy_m,
        azimuth_true_deg=float(b.azimuth_true_deg),
        azimuth_input_ref=b.azimuth_input_ref,
        declination_deg_applied=b.declination_deg_applied,
        sigma_deg=float(b.sigma_deg),
        rssi_dbm=b.rssi_dbm,
        s_meter=b.s_meter,
        attenuation_db=b.attenuation_db,
        polarization=b.polarization,
        measured_at=b.measured_at,
        received_at=b.received_at,
        note=b.note,
        is_outlier=b.is_outlier,
        is_active=b.is_active,
        source=b.source,
    )


def position_out(p: PositionSample) -> PositionOut:
    return PositionOut.model_validate(p)


def transmission_out(t: Transmission) -> TransmissionOut:
    return TransmissionOut.model_validate(t)


def estimate_out(e: Estimate) -> EstimateOut:
    return EstimateOut(
        id=e.id,
        mission_id=e.mission_id,
        scope=e.scope,  # type: ignore[arg-type]
        transmission_id=e.transmission_id,
        computed_at=e.computed_at,
        n_bearings=e.n_bearings,
        lat=e.lat,
        lon=e.lon,
        cov_east_east=e.cov_ee,
        cov_north_north=e.cov_nn,
        cov_east_north=e.cov_en,
        ellipse_1s=e.ellipse_1s,  # type: ignore[arg-type]
        ellipse_2s=e.ellipse_2s,  # type: ignore[arg-type]
        resolution_m=float(e.params.get("resolution_m", 0.0)),
        contours=e.contours or {},
        rssi=RssiFitOut(**e.params["rssi_fit"]) if e.params.get("rssi_fit") else None,
    )


def message_out(m: Message, callsign: str) -> MessageOut:
    return MessageOut(
        id=m.id,
        mission_id=m.mission_id,
        author_id=m.author_id,
        author_callsign=callsign,
        team_id=m.team_id,
        body=m.body,
        sent_at=m.sent_at,
        received_at=m.received_at,
    )


def task_out(t: Task) -> TaskOut:
    return TaskOut(
        id=t.id,
        mission_id=t.mission_id,
        title=t.title,
        description=t.description,
        status=t.status,
        assignee_participant_id=t.assignee_participant_id,
        assignee_team_id=t.assignee_team_id,
        created_by=t.created_by,
        created_at=t.created_at,
        updated_at=t.updated_at,
        lat=t.lat,
        lon=t.lon,
    )


def event_json(model: Any) -> dict[str, Any]:
    return dict(model.model_dump(mode="json"))


def rssi_out(r: RssiSample) -> RssiOut:
    return RssiOut(
        id=r.id,
        participant_id=r.participant_id,
        transmission_id=r.transmission_id,
        lat=r.lat,
        lon=r.lon,
        accuracy_m=r.accuracy_m,
        rssi_dbm=r.rssi_dbm,
        s_meter=r.s_meter,
        attenuation_db=r.attenuation_db,
        measured_at=r.measured_at,
        source=r.source,
        is_active=r.is_active,
    )
