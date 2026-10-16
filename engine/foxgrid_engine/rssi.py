"""Log-distance path loss likelihood for RSSI tracks (homing).

The level at distance ``d`` is modelled as ``p0 - 10 * n * log10(d)`` with *unknown* ``p0`` and
``n``. For every candidate emitter position both are fitted by weighted least squares (and ``n``
is clipped to physically sensible bounds), then the residual sum of squares gives a Gaussian
log-likelihood. Fitting per candidate makes the likelihood independent of the unknown transmit
power and environment, so only the *shape* of the signal strength trend matters.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from foxgrid_engine.types import EngineParams, RssiFit, RssiSample

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class RssiData:
    east: FloatArray
    north: FloatArray
    level: FloatArray  # attenuation-corrected dBm
    weight: FloatArray


def corrected_level(sample: RssiSample) -> float:
    """The attenuator reduced the level seen by the receiver, so add it back."""
    return sample.rssi_dbm + sample.attenuation_db


def select_recent(samples: list[RssiSample], limit: int) -> list[RssiSample]:
    """Keep the most recent ``limit`` samples (by time if known, else by order)."""
    if len(samples) <= limit:
        return list(samples)
    if all(s.measured_at is not None for s in samples):
        ordered = sorted(samples, key=lambda s: s.measured_at or 0.0)
        return ordered[-limit:]
    return list(samples[-limit:])


def _fit_arrays(
    east: FloatArray, north: FloatArray, data: RssiData, params: EngineParams
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Per-point weighted LS fit; returns (intercept p0, exponent n, weighted RSS)."""
    dx = east[..., None] - data.east
    dy = north[..., None] - data.north
    dist = np.maximum(np.hypot(dx, dy), params.rssi_min_distance_m)
    x = np.log10(dist)
    w = data.weight
    y = data.level
    sw = float(np.sum(w))
    mx = np.sum(w * x, axis=-1, keepdims=True) / sw
    my = float(np.sum(w * y) / sw)
    sxx = np.sum(w * (x - mx) ** 2, axis=-1)
    sxy = np.sum(w * (x - mx) * (y - my), axis=-1)
    slope = sxy / np.maximum(sxx, 1e-12)
    n_lo, n_hi = params.rssi_exponent_bounds
    exponent = np.clip(-slope / 10.0, n_lo, n_hi)
    slope_c = -10.0 * exponent
    intercept = my - slope_c * mx[..., 0]
    resid = y - (intercept[..., None] + slope_c[..., None] * x)
    rss = np.sum(w * resid**2, axis=-1)
    return (
        np.asarray(intercept, dtype=np.float64),
        np.asarray(exponent, dtype=np.float64),
        np.asarray(rss, dtype=np.float64),
    )


def rssi_log_likelihood(
    east: FloatArray, north: FloatArray, data: RssiData, params: EngineParams
) -> FloatArray:
    _, _, rss = _fit_arrays(east, north, data, params)
    return np.asarray(-rss / (2.0 * params.rssi_sigma_db**2), dtype=np.float64)


def fit_at(east: float, north: float, data: RssiData, params: EngineParams) -> RssiFit:
    """Path loss parameters of the best fit for an emitter at ``(east, north)``."""
    p0, n, rss = _fit_arrays(np.array(east), np.array(north), data, params)
    count = len(data.level)
    return RssiFit(
        p0_dbm=float(p0),
        exponent=float(n),
        residual_db=float(np.sqrt(float(rss) / float(np.sum(data.weight)))),
        n_samples=count,
    )
