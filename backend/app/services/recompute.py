"""Debounced background recomputation of the position estimate."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from foxgrid_engine import Bearing as EngineBearing
from foxgrid_engine import EngineError, EngineParams
from foxgrid_engine import RssiSample as EngineRssi
from foxgrid_engine import estimate as run_engine
from foxgrid_engine.rssi import usable_samples
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import events
from app.config import Settings
from app.models import (
    Bearing,
    Estimate,
    Interferer,
    Mission,
    RssiSample,
    Sensor,
    Transmission,
    utcnow,
)
from app.services.domain import trusted_only
from app.services.serialize import estimate_out, event_json

log = logging.getLogger(__name__)

MIN_BEARINGS = 2
CALIBRATION_EXPONENT = 3.0  # path loss exponent assumed towards the repeater
CALIBRATION_MIN_STATIONS = 3  # offsets are relative, so a mean needs a few stations
# Automatic stations see reflections more often than a person with a hand-held antenna (ADR 0010).
SENSOR_OUTLIER_FRACTION = 0.2


@dataclass(frozen=True)
class SensorTuning:
    """How sensor bearings enter the engine: per-sensor weight and their outlier fraction."""

    weights: dict[uuid.UUID, float] = field(default_factory=dict)
    outlier_fraction: float = SENSOR_OUTLIER_FRACTION


async def load_sensor_tuning(session: AsyncSession, mission: Mission) -> SensorTuning:
    rows = await session.execute(
        select(Sensor.id, Sensor.weight).where(Sensor.mission_id == mission.id)
    )
    eps = (mission.engine_params or {}).get("sensor_outlier_fraction")
    return SensorTuning(
        weights={sid: float(w) for sid, w in rows.all()},
        outlier_fraction=float(eps) if eps is not None else SENSOR_OUTLIER_FRACTION,
    )


def engine_params_for(mission: Mission, now: float) -> EngineParams:
    cfg = {k: v for k, v in (mission.engine_params or {}).items() if v is not None}
    cfg.pop("use_rssi", None)  # not an engine parameter: decides whether samples are passed
    cfg.pop("sensor_outlier_fraction", None)  # applied per bearing, see SensorTuning
    return EngineParams(now=now, **cfg)


def uses_rssi(mission: Mission) -> bool:
    return (mission.engine_params or {}).get("use_rssi") is not False


def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * 6_371_000.0 * math.asin(math.sqrt(a))


def calibration_offsets(mission: Mission, rows: list[RssiSample]) -> dict[uuid.UUID, float]:
    """Relative receiver offset (dB) per fixed station from readings of the repeater output.

    The repeater transmits with the same power for everyone, so after removing the path loss
    (assumed exponent) the remaining differences are the stations' antenna/receiver offsets. They
    are only known relative to each other, hence centred on their mean.
    """
    if mission.repeater_lat is None or mission.repeater_lon is None:
        return {}
    latest: dict[uuid.UUID, RssiSample] = {}
    for r in sorted(rows, key=lambda r: r.measured_at):
        if r.is_calibration and r.is_active and r.receiver == "omni":
            latest[r.participant_id] = r
    if len(latest) < CALIBRATION_MIN_STATIONS:
        return {}
    ref = {
        pid: r.rssi_dbm
        + r.attenuation_db
        + 10.0
        * CALIBRATION_EXPONENT
        * math.log10(
            max(_distance_m(r.lat, r.lon, mission.repeater_lat, mission.repeater_lon), 10.0)
        )
        for pid, r in latest.items()
    }
    mean = sum(ref.values()) / len(ref)
    return {pid: v - mean for pid, v in ref.items()}


async def load_calibration(session: AsyncSession, mission: Mission) -> dict[uuid.UUID, float]:
    """Station offsets from the mission's calibration readings (independent of any time filter)."""
    rows = (
        await session.scalars(
            trusted_only(
                select(RssiSample).where(
                    RssiSample.mission_id == mission.id,
                    RssiSample.is_calibration.is_(True),
                    RssiSample.is_active.is_(True),
                ),
                RssiSample,
            )
        )
    ).all()
    return calibration_offsets(mission, list(rows))


def _input_hash(
    bearings: list[Bearing],
    params: EngineParams,
    rssi: list[RssiSample] | None = None,
    offsets: dict[uuid.UUID, float] | None = None,
    tuning: SensorTuning | None = None,
) -> str:
    rows = sorted(
        [
            str(b.id),
            float(b.azimuth_true_deg),
            float(b.sigma_deg),
            b.lat,
            b.lon,
            *_sensor_terms(b, tuning),
        ]
        for b in bearings
    )
    offsets = offsets or {}
    rssi_rows = sorted(
        [
            str(r.id),
            r.rssi_dbm,
            r.attenuation_db,
            r.receiver,
            round(offsets.get(r.participant_id, 0.0), 3),
        ]
        for r in rssi or []
    )
    # `now` only matters for age weighting; bucket it so idle triggers stay cheap.
    now_bucket = int(params.now // 60) if params.half_life_s and params.now else None
    blob = json.dumps(
        [
            rows,
            params.resolution_m,
            params.margin_m,
            params.outlier_fraction,
            params.half_life_s,
            params.cluster_radius_m,
            now_bucket,
            rssi_rows,
            params.rssi_sigma_db,
            params.rssi_weight,
            params.rssi_station_sigma_db,
            params.rssi_omni_min_stations,
        ]
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def _sensor_terms(
    b: Bearing, tuning: SensorTuning | None
) -> tuple[str | None, float, float | None]:
    """(group, weight, outlier fraction) of a bearing; only sensor bearings are special."""
    if b.sensor_id is None:
        return None, 1.0, None
    tuning = tuning or SensorTuning()
    weight = tuning.weights.get(b.sensor_id, 1.0)
    return str(b.sensor_id), weight, tuning.outlier_fraction


def _to_engine(b: Bearing, tuning: SensorTuning | None = None) -> EngineBearing:
    group, weight, eps = _sensor_terms(b, tuning)
    return EngineBearing(
        lat=b.lat,
        lon=b.lon,
        azimuth_deg=float(b.azimuth_true_deg),
        sigma_deg=float(b.sigma_deg),
        measured_at=b.measured_at.timestamp(),
        id=str(b.id),
        group=group,
        weight=weight,
        outlier_fraction=eps,
    )


def _to_engine_rssi(r: RssiSample, offsets: dict[uuid.UUID, float]) -> EngineRssi:
    fixed = r.receiver == "omni"
    return EngineRssi(
        lat=r.lat,
        lon=r.lon,
        rssi_dbm=r.rssi_dbm,
        attenuation_db=r.attenuation_db,
        measured_at=r.measured_at.timestamp(),
        group=str(r.participant_id) if fixed else None,
        event=str(r.transmission_id) if fixed and r.transmission_id else None,
        offset_db=offsets.get(r.participant_id, 0.0) if fixed else 0.0,
    )


def rssi_fit_json(result: Any) -> dict[str, Any] | None:
    fit = result.rssi_fit
    if fit is None:
        return None
    return {
        "p0_dbm": fit.p0_dbm,
        "exponent": fit.exponent,
        "residual_db": fit.residual_db,
        "n_samples": fit.n_samples,
        "station_offsets_db": dict(fit.station_offsets_db),
    }


def _ellipse_json(geom: Any, ring: list[tuple[float, float]]) -> dict[str, Any]:
    return {
        "semi_major_m": geom.semi_major_m,
        "semi_minor_m": geom.semi_minor_m,
        "orientation_deg": geom.orientation_deg,
        "polygon": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]},
    }


def contours_json(result: Any) -> dict[str, list[dict[str, Any]]]:
    return {
        str(round(mass * 100)): [
            {"type": "Polygon", "coordinates": [[list(p) for p in ring]]} for ring in rings
        ]
        for mass, rings in result.contours.items()
    }


def build_estimate(
    mission_id: uuid.UUID,
    interferer_id: uuid.UUID,
    scope: str,
    transmission_id: uuid.UUID | None,
    digest: str,
    result: Any,
    params: EngineParams,
) -> Estimate:
    return Estimate(
        id=uuid.uuid4(),
        computed_at=utcnow(),
        mission_id=mission_id,
        interferer_id=interferer_id,
        scope=scope,
        transmission_id=transmission_id,
        input_hash=digest,
        n_bearings=result.n_bearings,
        params={
            "resolution_m": result.resolution_m,
            "grid_cells": list(result.grid_cells),
            "utm_epsg": result.utm_epsg,
            "outlier_fraction": params.outlier_fraction,
            "half_life_s": params.half_life_s,
            "n_rssi": result.n_rssi,
            "rssi_fit": rssi_fit_json(result),
        },
        lat=result.lat,
        lon=result.lon,
        cov_ee=result.cov_east_east,
        cov_nn=result.cov_north_north,
        cov_en=result.cov_east_north,
        ellipse_1s=_ellipse_json(result.ellipse_1s, result.ellipse_1s_ring),
        ellipse_2s=_ellipse_json(result.ellipse_2s, result.ellipse_2s_ring),
        contours=contours_json(result),
    )


def current_transmission(
    transmissions: dict[uuid.UUID, datetime], rows: Sequence[Bearing | RssiSample]
) -> uuid.UUID | None:
    """The newest transmission among the rows' transmissions (None when none has one)."""
    ids = {r.transmission_id for r in rows if r.transmission_id is not None}
    known = [t for t in ids if t in transmissions]
    return max(known, key=lambda t: transmissions[t], default=None)


async def compute_mission(
    session: AsyncSession, redis: Redis, mission_id: uuid.UUID, now: float | None = None
) -> list[Estimate]:
    """Recompute and persist estimates per interferer and scope; publish ``estimate_updated``.

    Each active interferer is fused from its own bearings and readings. Its ``current`` scope is
    the newest transmission that has data for *that* interferer.
    """
    now = time.time() if now is None else now
    mission = await session.get(Mission, mission_id)
    if mission is None:
        return []
    params = engine_params_for(mission, now)
    tuning = await load_sensor_tuning(session, mission)

    interferer_ids = list(
        await session.scalars(
            select(Interferer.id)
            .where(Interferer.mission_id == mission_id, Interferer.is_active.is_(True))
            .order_by(Interferer.created_at, Interferer.id)
        )
    )
    rows = (
        await session.scalars(
            trusted_only(
                select(Bearing).where(
                    Bearing.mission_id == mission_id,
                    Bearing.is_active.is_(True),
                    Bearing.is_outlier.is_(False),
                ),
                Bearing,
            )
        )
    ).all()
    rssi_rows: list[RssiSample] = []
    offsets: dict[uuid.UUID, float] = {}
    if uses_rssi(mission):
        all_rssi = list(
            (
                await session.scalars(
                    trusted_only(
                        select(RssiSample).where(
                            RssiSample.mission_id == mission_id, RssiSample.is_active.is_(True)
                        ),
                        RssiSample,
                    )
                )
            ).all()
        )
        # Calibration readings (repeater output) are independent of any interferer.
        offsets = calibration_offsets(mission, all_rssi)
        rssi_rows = [r for r in all_rssi if not r.is_calibration]
    started = {
        tx_id: started_at
        for tx_id, started_at in (
            await session.execute(
                select(Transmission.id, Transmission.started_at).where(
                    Transmission.mission_id == mission_id
                )
            )
        ).all()
    }

    created: list[Estimate] = []
    for interferer_id in interferer_ids:
        mine = [b for b in rows if b.interferer_id == interferer_id]
        mine_rssi = [r for r in rssi_rows if r.interferer_id == interferer_id]
        current_id = current_transmission(started, [*mine, *mine_rssi])
        scopes = {
            "current": (
                [b for b in mine if b.transmission_id == current_id],
                [r for r in mine_rssi if r.transmission_id == current_id],
            ),
            "all": (mine, mine_rssi),
        }
        for scope, (subset, rssi_subset) in scopes.items():
            engine_rssi = [_to_engine_rssi(r, offsets) for r in rssi_subset]
            weighted = [b for b in subset if _sensor_terms(b, tuning)[1] > 0]
            if len(weighted) < MIN_BEARINGS and not usable_samples(engine_rssi, params):
                continue  # too little to fuse (a sensor with weight 0 adds nothing)
            digest = _input_hash(subset, params, rssi_subset, offsets, tuning)
            last = await session.scalar(
                select(Estimate)
                .where(
                    Estimate.mission_id == mission_id,
                    Estimate.interferer_id == interferer_id,
                    Estimate.scope == scope,
                )
                .order_by(Estimate.computed_at.desc())
                .limit(1)
            )
            tx_id = current_id if scope == "current" else None
            if last is not None and last.input_hash == digest and last.transmission_id == tx_id:
                continue
            try:
                result = await asyncio.to_thread(
                    run_engine,
                    [_to_engine(b, tuning) for b in subset],
                    params,
                    engine_rssi,
                )
            except EngineError:
                log.exception(
                    "engine rejected input for mission %s interferer %s", mission_id, interferer_id
                )
                continue
            est = build_estimate(mission_id, interferer_id, scope, tx_id, digest, result, params)
            session.add(est)
            await session.flush()
            created.append(est)
    await session.commit()
    for est in created:
        await events.publish(redis, mission_id, "estimate_updated", event_json(estimate_out(est)))
    return created


class RecomputeScheduler:
    """Trailing-edge debounce per mission with a maximum wait so steady writes cannot starve it."""

    def __init__(
        self, sessionmaker: async_sessionmaker[AsyncSession], redis: Redis, settings: Settings
    ) -> None:
        self._sessionmaker = sessionmaker
        self._redis = redis
        self._settings = settings
        self._tasks: dict[uuid.UUID, tuple[asyncio.Task[None], float]] = {}

    def schedule(self, mission_id: uuid.UUID) -> None:
        loop_now = time.monotonic()
        existing = self._tasks.get(mission_id)
        first = loop_now
        if existing is not None and not existing[0].done():
            first = existing[1]
            if (loop_now - first) * 1000 >= self._settings.recompute_max_wait_ms:
                return  # already due soon; let it run
            existing[0].cancel()
        delay = self._settings.recompute_debounce_ms / 1000
        task = asyncio.create_task(self._run(mission_id, delay))
        self._tasks[mission_id] = (task, first)

    async def _run(self, mission_id: uuid.UUID, delay: float) -> None:
        await asyncio.sleep(delay)
        # Several workers may debounce the same mission; one computation at a time is enough.
        lock_key = f"recompute-lock:{mission_id}"
        if not await self._redis.set(lock_key, "1", nx=True, px=5000):
            await asyncio.sleep(0.25)
            if not await self._redis.set(lock_key, "1", nx=True, px=5000):
                return
        try:
            async with self._sessionmaker() as session:
                await compute_mission(session, self._redis, mission_id)
        except Exception:
            log.exception("recompute failed for mission %s", mission_id)
        finally:
            await self._redis.delete(lock_key)

    async def drain(self) -> None:
        """Wait for pending recomputations (used in tests and on shutdown)."""
        while True:
            pending = [t for t, _ in self._tasks.values() if not t.done()]
            if not pending:
                return
            await asyncio.gather(*pending, return_exceptions=True)

    async def shutdown(self) -> None:
        for task, _ in self._tasks.values():
            task.cancel()
        await asyncio.gather(*(t for t, _ in self._tasks.values()), return_exceptions=True)
