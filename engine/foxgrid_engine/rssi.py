"""Log-distance path loss likelihood for RSSI readings (homing track and fixed stations).

The level at distance ``d`` is modelled as ``p0 + b_k - 10 * n * log10(d)`` with *unknown* ``p0``
and ``n``. For every candidate emitter position both are fitted by weighted least squares (and
``n`` is clipped to physically sensible bounds), then the residual sum of squares gives a Gaussian
log-likelihood. Fitting per candidate makes the likelihood independent of the unknown transmit
power and environment, so only the *shape* of the signal strength trend matters.

Readings of fixed omnidirectional stations carry an additional unknown receiver offset ``b_k``
(antenna, cable, receiver), modelled as a random effect ``N(0, sigma_b^2)`` per station. That is a
generalised least squares fit with covariance ``sigma^2 (W^-1 + tau Z Z^T)``; the Woodbury identity
turns it into sums over stations, so the cost stays linear in the number of readings. With a single
group (one moving device) the offset is absorbed by ``p0`` and the result equals the plain fit.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from foxgrid_engine.types import EngineParams, RssiFit, RssiSample

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]


@dataclass(frozen=True, slots=True)
class RssiData:
    east: FloatArray
    north: FloatArray
    level: FloatArray  # attenuation-corrected dBm
    weight: FloatArray
    # station index per reading (0..K-1); ``None`` = one group, i.e. the plain fit
    group: IntArray | None = None
    # label per group index; the moving device is labelled ``""`` and not reported
    group_labels: tuple[str, ...] = ()
    tau: float = 0.0  # (sigma_b / sigma)^2


def corrected_level(sample: RssiSample) -> float:
    """The attenuator reduced the level seen by the receiver, so add it back."""
    return sample.rssi_dbm + sample.attenuation_db - sample.offset_db


def select_recent(samples: list[RssiSample], limit: int) -> list[RssiSample]:
    """Keep the most recent ``limit`` samples (by time if known, else by order)."""
    if len(samples) <= limit:
        return list(samples)
    if all(s.measured_at is not None for s in samples):
        ordered = sorted(samples, key=lambda s: s.measured_at or 0.0)
        return ordered[-limit:]
    return list(samples[-limit:])


def _aggregate_stations(samples: list[RssiSample]) -> list[RssiSample]:
    """One reading per (station, transmission): the median level (repeats are not independent)."""
    buckets: dict[tuple[str, str | None], list[RssiSample]] = {}
    for s in samples:
        assert s.group is not None
        buckets.setdefault((s.group, s.event), []).append(s)
    out = []
    for (group, event), items in buckets.items():
        times = [i.measured_at for i in items if i.measured_at is not None]
        out.append(
            RssiSample(
                lat=float(np.mean([i.lat for i in items])),
                lon=float(np.mean([i.lon for i in items])),
                rssi_dbm=float(np.median([corrected_level(i) for i in items])),
                measured_at=max(times) if times else None,
                group=group,
                event=event,
            )
        )
    return out


def usable_samples(samples: list[RssiSample], params: EngineParams) -> list[RssiSample]:
    """Readings that enter the fit: aggregated stations and a long enough homing track.

    The homing track needs ``rssi_min_samples`` readings, fixed stations need
    ``rssi_omni_min_stations`` distinct stations (with fewer the solution is ambiguous).
    """
    track = [s for s in samples if s.group is None]
    fixed = [s for s in samples if s.group is not None]
    if len(track) < params.rssi_min_samples:
        track = []
    fixed = _aggregate_stations(fixed) if fixed else []
    if len({s.group for s in fixed}) < params.rssi_omni_min_stations:
        fixed = []
    return select_recent(track, params.rssi_max_samples) + select_recent(
        fixed, params.rssi_max_samples
    )


def _station_terms(
    data: RssiData,
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """One-hot group matrix, group weight sums and the Woodbury coefficients ``c_k``."""
    assert data.group is not None
    k = len(data.group_labels)
    onehot = np.zeros((len(data.group), k))
    onehot[np.arange(len(data.group)), data.group] = 1.0
    sums = data.weight @ onehot
    coef = data.tau / (1.0 + data.tau * sums)
    return onehot, sums, coef


def _fit_arrays(
    east: FloatArray, north: FloatArray, data: RssiData, params: EngineParams
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Per-point (generalised) weighted LS fit: (intercept p0, exponent n, residual form)."""
    dx = east[..., None] - data.east
    dy = north[..., None] - data.north
    dist = np.maximum(np.hypot(dx, dy), params.rssi_min_distance_m)
    x = np.log10(dist)
    w = data.weight
    y = data.level
    sw = float(np.sum(w))
    mx = np.sum(w * x, axis=-1, keepdims=True) / sw
    my = float(np.sum(w * y) / sw)
    n_lo, n_hi = params.rssi_exponent_bounds
    if data.group is None or len(data.group_labels) < 2 or data.tau <= 0.0:
        sxx = np.sum(w * (x - mx) ** 2, axis=-1)
        sxy = np.sum(w * (x - mx) * (y - my), axis=-1)
        slope = sxy / np.maximum(sxx, 1e-12)
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

    onehot, sums, coef = _station_terms(data)
    xc = x - mx
    yc = y - my
    wx = w * xc
    ax = wx @ onehot  # (..., K) station sums of w*x
    ay = (w * yc) @ onehot  # (K,)
    i11 = sw - float(np.sum(coef * sums**2))
    i1x = np.sum(wx, axis=-1) - ax @ (coef * sums)
    ixx = np.sum(wx * xc, axis=-1) - (ax**2) @ coef
    i1y = float(np.sum(w * yc) - np.sum(coef * sums * ay))
    ixy = np.sum(wx * yc, axis=-1) - ax @ (coef * ay)
    iyy = float(np.sum(w * yc**2) - np.sum(coef * ay**2))
    # profile out p0, then clip the slope (the profile is a convex quadratic in the slope)
    denom = np.maximum(ixx - i1x**2 / i11, 1e-12)
    slope = (ixy - i1x * i1y / i11) / denom
    exponent = np.clip(-slope / 10.0, n_lo, n_hi)
    slope_c = -10.0 * exponent
    p0 = (i1y - slope_c * i1x) / i11
    q = iyy - 2.0 * p0 * i1y - 2.0 * slope_c * ixy + p0**2 * i11 + 2.0 * p0 * slope_c * i1x
    q = np.maximum(q + slope_c**2 * ixx, 0.0)
    intercept = p0 + my - slope_c * mx[..., 0]
    return (
        np.asarray(intercept, dtype=np.float64),
        np.asarray(exponent, dtype=np.float64),
        np.asarray(q, dtype=np.float64),
    )


def rssi_log_likelihood(
    east: FloatArray, north: FloatArray, data: RssiData, params: EngineParams
) -> FloatArray:
    _, _, rss = _fit_arrays(east, north, data, params)
    return np.asarray(-rss / (2.0 * params.rssi_sigma_db**2), dtype=np.float64)


def fit_at(east: float, north: float, data: RssiData, params: EngineParams) -> RssiFit:
    """Path loss parameters of the best fit for an emitter at ``(east, north)``."""
    p0, n, _ = _fit_arrays(np.array(east), np.array(north), data, params)
    dist = np.maximum(np.hypot(data.east - east, data.north - north), params.rssi_min_distance_m)
    resid = data.level - (float(p0) - 10.0 * float(n) * np.log10(dist))
    sw = float(np.sum(data.weight))
    offsets: dict[str, float] = {}
    if data.group is not None and len(data.group_labels) >= 2 and data.tau > 0.0:
        onehot, _, coef = _station_terms(data)
        blup = coef * ((data.weight * resid) @ onehot)  # best linear unbiased offset per group
        resid = resid - blup[data.group]
        offsets = {
            label: float(b) for label, b in zip(data.group_labels, blup, strict=True) if label
        }
    return RssiFit(
        p0_dbm=float(p0),
        exponent=float(n),
        residual_db=float(np.sqrt(float(np.sum(data.weight * resid**2)) / sw)),
        n_samples=len(data.level),
        station_offsets_db=offsets,
    )
