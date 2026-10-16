"""Grid based maximum-likelihood fusion of bearings."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

import numpy as np
import numpy.typing as npt
from pyproj import Transformer

from foxgrid_engine.contours import contour_rings, mass_threshold
from foxgrid_engine.likelihood import (
    bearing_log_likelihood,
    sigma_to_kappa,
    wrap_pi,
)
from foxgrid_engine.rssi import (
    RssiData,
    corrected_level,
    fit_at,
    rssi_log_likelihood,
    select_recent,
)
from foxgrid_engine.types import (
    Bearing,
    EllipseGeometry,
    EngineError,
    EngineParams,
    Estimate,
    RssiSample,
)

FloatArray = npt.NDArray[np.float64]

_RING_POINTS: Final = 72
_NORTH_PROBE_DEG: Final = 1e-4
_MIN_CROSS: Final = math.sin(math.radians(15.0))


@dataclass(frozen=True, slots=True)
class _Stations:
    east: FloatArray
    north: FloatArray
    grid_azimuth: FloatArray  # radians, clockwise from grid north
    kappa: FloatArray
    weight: FloatArray


def utm_epsg_for(lat: float, lon: float) -> int:
    zone = int((lon + 180.0) // 6.0) % 60 + 1
    return (32600 if lat >= 0 else 32700) + zone


def _prepare(bearings: list[Bearing], fwd: Transformer, params: EngineParams) -> _Stations:
    if not bearings:
        empty = np.zeros(0)
        return _Stations(empty, empty, empty, empty, empty)
    lats = np.array([b.lat for b in bearings])
    lons = np.array([b.lon for b in bearings])
    east, north = fwd.transform(lons, lats)
    # Direction of true north in the grid at each station, measured by projecting a probe point.
    east_n, north_n = fwd.transform(lons, lats + _NORTH_PROBE_DEG)
    north_in_grid = np.arctan2(east_n - east, north_n - north)
    az_true = np.radians([b.azimuth_deg for b in bearings])
    sigma = np.array([b.sigma_deg for b in bearings], dtype=np.float64)

    weight = np.ones(len(bearings))
    if params.half_life_s is not None:
        times = [b.measured_at for b in bearings]
        if params.now is not None and all(t is not None for t in times):
            age = np.maximum(params.now - np.array(times, dtype=np.float64), 0.0)
            weight = np.power(0.5, age / params.half_life_s)
    return _Stations(
        east=np.asarray(east, dtype=np.float64),
        north=np.asarray(north, dtype=np.float64),
        grid_azimuth=np.asarray(az_true + north_in_grid, dtype=np.float64),
        kappa=sigma_to_kappa(sigma),
        weight=weight,
    )


def _log_posterior(
    east: FloatArray,
    north: FloatArray,
    st: _Stations,
    params: EngineParams,
    rssi: RssiData | None = None,
) -> FloatArray:
    """Unnormalised log posterior at arbitrary points (flat prior)."""
    total = np.zeros(east.shape, dtype=np.float64)
    if len(st.east) > 0:
        dx = east[..., None] - st.east
        dy = north[..., None] - st.north
        cell_azimuth = np.arctan2(dx, dy)
        delta = wrap_pi(cell_azimuth - st.grid_azimuth)
        ll = bearing_log_likelihood(delta, st.kappa, params.outlier_fraction)
        total += np.sum(ll * st.weight, axis=-1)
    if rssi is not None:
        total += params.rssi_weight * rssi_log_likelihood(east, north, rssi, params)
    return total


def _ray_intersections(st: _Stations, params: EngineParams) -> FloatArray:
    """Intersections of well-conditioned bearing pairs in front of both stations, shape (K, 2)."""
    d_e, d_n = np.sin(st.grid_azimuth), np.cos(st.grid_azimuth)
    cross = d_e[:, None] * d_n[None, :] - d_n[:, None] * d_e[None, :]
    rel_e = st.east[None, :] - st.east[:, None]
    rel_n = st.north[None, :] - st.north[:, None]
    ok = np.abs(cross) > _MIN_CROSS
    safe = np.where(ok, cross, 1.0)
    t_i = (rel_e * d_n[None, :] - rel_n * d_e[None, :]) / safe
    t_j = (rel_e * d_n[:, None] - rel_n * d_e[:, None]) / safe
    ok &= (t_i > 0) & (t_j > 0) & (t_i < params.max_range_m) & (t_j < params.max_range_m)
    ii, jj = np.nonzero(ok)
    pts = np.column_stack(
        [st.east[ii] + t_i[ii, jj] * d_e[ii], st.north[ii] + t_i[ii, jj] * d_n[ii]]
    )
    return np.asarray(pts, dtype=np.float64)


def _bounds(
    st: _Stations, params: EngineParams, rssi: RssiData | None
) -> tuple[float, float, float, float]:
    """Grid extent: stations, RSSI track and (trimmed) ray intersections, plus the margin."""
    pts = _ray_intersections(st, params) if len(st.east) > 1 else np.zeros((0, 2))
    e_all, n_all = [st.east], [st.north]
    if rssi is not None:
        e_all.append(rssi.east)
        n_all.append(rssi.north)
    if len(pts) > 0:
        lo, hi = (10.0, 90.0) if len(pts) >= 5 else (0.0, 100.0)
        for axis, bucket in ((0, e_all), (1, n_all)):
            bucket.append(np.percentile(pts[:, axis], [lo, hi]))
    e = np.concatenate(e_all)
    n = np.concatenate(n_all)
    m = params.margin_m
    return float(e.min() - m), float(e.max() + m), float(n.min() - m), float(n.max() + m)


def _validate(bearings: list[Bearing], rssi: list[RssiSample], params: EngineParams) -> None:
    usable_rssi = len(rssi) >= params.rssi_min_samples
    if not bearings and not usable_rssi:
        raise EngineError(
            f"at least one bearing or {params.rssi_min_samples} RSSI samples are required"
        )
    if params.rssi_sigma_db <= 0 or params.rssi_weight < 0:
        raise EngineError("invalid RSSI configuration")
    lo, hi = params.rssi_exponent_bounds
    if not 0 < lo <= hi:
        raise EngineError("invalid RSSI exponent bounds")
    for r in rssi:
        if not (math.isfinite(r.rssi_dbm) and math.isfinite(r.attenuation_db)):
            raise EngineError("RSSI values must be finite")
        if not (-90.0 <= r.lat <= 90.0 and -180.0 <= r.lon <= 180.0):
            raise EngineError("RSSI position out of range")
    if not 0.0 < params.outlier_fraction < 1.0:
        raise EngineError("outlier_fraction must be in (0, 1)")
    if params.resolution_m <= 0 or params.max_cells < 2:
        raise EngineError("invalid grid configuration")
    for b in bearings:
        if not (b.sigma_deg > 0.0 and math.isfinite(b.sigma_deg)):
            raise EngineError("sigma_deg must be positive")
        if not (-90.0 <= b.lat <= 90.0 and -180.0 <= b.lon <= 180.0):
            raise EngineError("bearing position out of range")
        if not math.isfinite(b.azimuth_deg):
            raise EngineError("azimuth must be finite")


def _ellipse(cov: FloatArray, scale: float) -> tuple[EllipseGeometry, FloatArray]:
    """Return ellipse geometry and the (east, north) axis vectors scaled by ``scale``."""
    vals, vecs = np.linalg.eigh(cov)
    vals = np.maximum(vals, 0.0)
    major_vec = vecs[:, 1]
    orientation = math.degrees(math.atan2(major_vec[0], major_vec[1])) % 180.0
    geometry = EllipseGeometry(
        semi_major_m=float(scale * math.sqrt(vals[1])),
        semi_minor_m=float(scale * math.sqrt(vals[0])),
        orientation_deg=orientation,
    )
    axes = vecs * (scale * np.sqrt(vals))
    return geometry, np.asarray(axes, dtype=np.float64)


def _to_lonlat(ring: list[tuple[float, float]], inv: Transformer) -> list[tuple[float, float]]:
    xs, ys = zip(*ring, strict=True)
    lon, lat = inv.transform(list(xs), list(ys))
    return [(float(a), float(b)) for a, b in zip(lon, lat, strict=True)]


def _ring(center: FloatArray, axes: FloatArray, inv: Transformer) -> list[tuple[float, float]]:
    t = np.linspace(0.0, 2.0 * np.pi, _RING_POINTS, endpoint=True)
    offsets = np.outer(np.cos(t), axes[:, 0]) + np.outer(np.sin(t), axes[:, 1])
    lon, lat = inv.transform(center[0] + offsets[:, 0], center[1] + offsets[:, 1])
    return [(float(x), float(y)) for x, y in zip(lon, lat, strict=True)]


def _prepare_rssi(
    samples: list[RssiSample], fwd: Transformer, params: EngineParams
) -> RssiData | None:
    if len(samples) < params.rssi_min_samples:
        return None  # too few readings to say anything about a trend
    samples = select_recent(samples, params.rssi_max_samples)
    east, north = fwd.transform([s.lon for s in samples], [s.lat for s in samples])
    weight = np.ones(len(samples))
    if params.half_life_s is not None and params.now is not None:
        times = [s.measured_at for s in samples]
        if all(t is not None for t in times):
            age = np.maximum(params.now - np.array(times, dtype=np.float64), 0.0)
            weight = np.power(0.5, age / params.half_life_s)
    return RssiData(
        east=np.asarray(east, dtype=np.float64),
        north=np.asarray(north, dtype=np.float64),
        level=np.array([corrected_level(s) for s in samples], dtype=np.float64),
        weight=weight,
    )


def estimate(
    bearings: list[Bearing],
    params: EngineParams | None = None,
    rssi: list[RssiSample] | None = None,
) -> Estimate:
    """Fuse bearings (and optionally an RSSI track) into an emitter position with error ellipse."""
    params = params or EngineParams()
    rssi_samples = rssi or []
    _validate(bearings, rssi_samples, params)

    lats = [b.lat for b in bearings] + [r.lat for r in rssi_samples]
    lons = [b.lon for b in bearings] + [r.lon for r in rssi_samples]
    epsg = utm_epsg_for(float(np.mean(lats)), float(np.mean(lons)))
    fwd = Transformer.from_crs(4326, epsg, always_xy=True)
    inv = Transformer.from_crs(epsg, 4326, always_xy=True)
    st = _prepare(bearings, fwd, params)
    rssi_data = _prepare_rssi(rssi_samples, fwd, params)
    if rssi_data is None and not bearings:  # pragma: no cover - guarded by _validate
        raise EngineError("no usable input")

    # Grid: stations and ray intersections plus margin; resolution coarsened to max_cells.
    e_min, e_max, n_min, n_max = _bounds(st, params, rssi_data)
    res = max(params.resolution_m, max(e_max - e_min, n_max - n_min) / params.max_cells)
    xs = np.arange(e_min, e_max + res, res)
    ys = np.arange(n_min, n_max + res, res)
    ge, gn = np.meshgrid(xs, ys)
    lp = _log_posterior(ge, gn, st, params, rssi_data)

    post = np.exp(lp - lp.max())
    post /= post.sum()
    mean_e = float(np.sum(post * ge))
    mean_n = float(np.sum(post * gn))
    de, dn = ge - mean_e, gn - mean_n
    quant = res * res / 12.0  # cell quantisation
    cov = np.array(
        [
            [np.sum(post * de * de) + quant, np.sum(post * de * dn)],
            [np.sum(post * de * dn), np.sum(post * dn * dn) + quant],
        ]
    )

    # Refine the maximum with successively finer local grids.
    iy, ix = np.unravel_index(int(np.argmax(lp)), lp.shape)
    best_e, best_n = float(xs[ix]), float(ys[iy])
    half = res
    for _ in range(params.refine_steps):
        offs = np.linspace(-half, half, 21)
        le, ln = np.meshgrid(best_e + offs, best_n + offs)
        llp = _log_posterior(le, ln, st, params, rssi_data)
        j, i = np.unravel_index(int(np.argmax(llp)), llp.shape)
        best_e, best_n = float(le[j, i]), float(ln[j, i])
        half = 2.0 * half / 20.0

    contours: dict[float, list[list[tuple[float, float]]]] = {}
    for mass in params.contour_levels:
        level = mass_threshold(post, mass)
        contours[mass] = [_to_lonlat(r, inv) for r in contour_rings(xs, ys, post, level)]

    geom1, axes1 = _ellipse(cov, 1.0)
    geom2, axes2 = _ellipse(cov, 2.0)
    center = np.array([best_e, best_n])
    lon, lat = inv.transform(best_e, best_n)
    return Estimate(
        lat=float(lat),
        lon=float(lon),
        cov_east_east=float(cov[0, 0]),
        cov_north_north=float(cov[1, 1]),
        cov_east_north=float(cov[0, 1]),
        ellipse_1s=geom1,
        ellipse_2s=geom2,
        ellipse_1s_ring=_ring(center, axes1, inv),
        ellipse_2s_ring=_ring(center, axes2, inv),
        n_bearings=len(bearings),
        n_rssi=0 if rssi_data is None else len(rssi_data.level),
        rssi_fit=None if rssi_data is None else fit_at(best_e, best_n, rssi_data, params),
        resolution_m=float(res),
        grid_cells=(len(xs), len(ys)),
        utm_epsg=epsg,
        contours=contours,
    )
