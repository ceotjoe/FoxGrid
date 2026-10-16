"""Debounced background recomputation of the position estimate."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from typing import Any

from foxgrid_engine import Bearing as EngineBearing
from foxgrid_engine import EngineError, EngineParams
from foxgrid_engine import RssiSample as EngineRssi
from foxgrid_engine import estimate as run_engine
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import events
from app.config import Settings
from app.models import Bearing, Estimate, Mission, RssiSample, Transmission, utcnow
from app.services.serialize import estimate_out, event_json

log = logging.getLogger(__name__)

MIN_BEARINGS = 2


def engine_params_for(mission: Mission, now: float) -> EngineParams:
    cfg = {k: v for k, v in (mission.engine_params or {}).items() if v is not None}
    cfg.pop("use_rssi", None)  # not an engine parameter: decides whether samples are passed
    return EngineParams(now=now, **cfg)


def uses_rssi(mission: Mission) -> bool:
    return (mission.engine_params or {}).get("use_rssi") is not False


def _input_hash(
    bearings: list[Bearing], params: EngineParams, rssi: list[RssiSample] | None = None
) -> str:
    rows = sorted(
        [str(b.id), float(b.azimuth_true_deg), float(b.sigma_deg), b.lat, b.lon] for b in bearings
    )
    rssi_rows = sorted([str(r.id), r.rssi_dbm, r.attenuation_db] for r in rssi or [])
    # `now` only matters for age weighting; bucket it so idle triggers stay cheap.
    now_bucket = int(params.now // 60) if params.half_life_s and params.now else None
    blob = json.dumps(
        [
            rows,
            params.resolution_m,
            params.margin_m,
            params.outlier_fraction,
            params.half_life_s,
            now_bucket,
            rssi_rows,
            params.rssi_sigma_db,
            params.rssi_weight,
        ]
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def _to_engine(b: Bearing) -> EngineBearing:
    return EngineBearing(
        lat=b.lat,
        lon=b.lon,
        azimuth_deg=float(b.azimuth_true_deg),
        sigma_deg=float(b.sigma_deg),
        measured_at=b.measured_at.timestamp(),
        id=str(b.id),
    )


def _to_engine_rssi(r: RssiSample) -> EngineRssi:
    return EngineRssi(
        lat=r.lat,
        lon=r.lon,
        rssi_dbm=r.rssi_dbm,
        attenuation_db=r.attenuation_db,
        measured_at=r.measured_at.timestamp(),
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


async def compute_mission(
    session: AsyncSession, redis: Redis, mission_id: uuid.UUID, now: float | None = None
) -> list[Estimate]:
    """Recompute and persist estimates for both scopes; publish ``estimate_updated``."""
    now = time.time() if now is None else now
    mission = await session.get(Mission, mission_id)
    if mission is None:
        return []
    params = engine_params_for(mission, now)

    rows = (
        await session.scalars(
            select(Bearing).where(
                Bearing.mission_id == mission_id,
                Bearing.is_active.is_(True),
                Bearing.is_outlier.is_(False),
            )
        )
    ).all()
    rssi_rows: list[RssiSample] = []
    if uses_rssi(mission):
        rssi_rows = list(
            (
                await session.scalars(
                    select(RssiSample).where(
                        RssiSample.mission_id == mission_id, RssiSample.is_active.is_(True)
                    )
                )
            ).all()
        )
    current_tx = await session.scalar(
        select(Transmission)
        .where(Transmission.mission_id == mission_id)
        .order_by(Transmission.started_at.desc())
        .limit(1)
    )
    current_id = current_tx.id if current_tx else None
    scopes = {
        "current": (
            [b for b in rows if b.transmission_id == current_id],
            [r for r in rssi_rows if r.transmission_id == current_id],
        ),
        "all": (list(rows), list(rssi_rows)),
    }

    created: list[Estimate] = []
    for scope, (subset, rssi_subset) in scopes.items():
        if len(subset) < MIN_BEARINGS and len(rssi_subset) < params.rssi_min_samples:
            continue
        digest = _input_hash(subset, params, rssi_subset)
        last = await session.scalar(
            select(Estimate)
            .where(Estimate.mission_id == mission_id, Estimate.scope == scope)
            .order_by(Estimate.computed_at.desc())
            .limit(1)
        )
        tx_id = current_id if scope == "current" else None
        if last is not None and last.input_hash == digest and last.transmission_id == tx_id:
            continue
        try:
            result = await asyncio.to_thread(
                run_engine,
                [_to_engine(b) for b in subset],
                params,
                [_to_engine_rssi(r) for r in rssi_subset],
            )
        except EngineError:
            log.exception("engine rejected input for mission %s", mission_id)
            continue
        est = build_estimate(mission_id, scope, tx_id, digest, result, params)
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
