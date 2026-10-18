from __future__ import annotations

import math
import time

import numpy as np
import pytest

from foxgrid_engine import EngineError, EngineParams, RssiSample, estimate
from foxgrid_engine.rssi import corrected_level, usable_samples
from tests.conftest import ORIGIN, distance_m, make_bearings, offset

P0 = -20.0
EXPONENT = 3.0


def stations(emitter: tuple[float, float], n: int = 6, seed: int = 1) -> list[tuple[float, float]]:
    """Fixed stations scattered around the emitter at 2-9 km."""
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        ang = 2 * math.pi * i / n + rng.uniform(-0.3, 0.3)
        r = rng.uniform(2000.0, 9000.0)
        out.append(offset(*emitter, r * math.sin(ang), r * math.cos(ang)))
    return out


def readings(
    emitter: tuple[float, float],
    pos: list[tuple[float, float]],
    offsets: list[float],
    noise_db: float = 2.0,
    quantize_db: float = 0.0,
    seed: int = 5,
    events: int = 1,
) -> list[RssiSample]:
    rng = np.random.default_rng(seed)
    out = []
    for k, (p, b) in enumerate(zip(pos, offsets, strict=True)):
        d = max(distance_m(p, emitter), 1.0)
        for e in range(events):
            level = P0 + b - 10.0 * EXPONENT * math.log10(d) + rng.normal(0.0, noise_db)
            if quantize_db:
                level = round(level / quantize_db) * quantize_db
            out.append(
                RssiSample(p[0], p[1], level, group=f"st{k}", event=f"tx{e}", measured_at=100.0 + e)
            )
    return out


@pytest.fixture
def emitter() -> tuple[float, float]:
    return offset(*ORIGIN, 800.0, 1200.0)


def test_woodbury_matches_explicit_gls(emitter):  # type: ignore[no-untyped-def]
    pos = stations(emitter)
    rng = np.random.default_rng(2)
    samples = readings(emitter, pos, list(rng.normal(0, 5, len(pos))))
    params = EngineParams(rssi_exponent_bounds=(0.1, 20.0))  # no clipping: compare plain GLS
    from foxgrid_engine.estimate import _prepare_rssi, _transformers, utm_epsg_for

    fwd, _ = _transformers(utm_epsg_for(*ORIGIN))
    data = _prepare_rssi(samples, fwd, params)
    assert data is not None and data.group is not None
    from foxgrid_engine.rssi import _fit_arrays

    cand = (float(np.mean(data.east)) + 700.0, float(np.mean(data.north)) + 900.0)
    p0, n, q = _fit_arrays(np.array(cand[0]), np.array(cand[1]), data, params)

    m = len(data.level)
    x = np.log10(np.maximum(np.hypot(data.east - cand[0], data.north - cand[1]), 10.0))
    design = np.column_stack([np.ones(m), x])
    z = np.zeros((m, len(data.group_labels)))
    z[np.arange(m), data.group] = 1.0
    cov = np.diag(1.0 / data.weight) + data.tau * z @ z.T
    inv = np.linalg.inv(cov)
    beta = np.linalg.solve(design.T @ inv @ design, design.T @ inv @ data.level)
    r = data.level - design @ beta
    assert float(p0) == pytest.approx(beta[0], abs=1e-6)
    assert float(n) == pytest.approx(-beta[1] / 10.0, abs=1e-8)
    assert float(q) == pytest.approx(float(r @ inv @ r), rel=1e-6)


def test_vanishing_station_sigma_equals_plain_fit(emitter):  # type: ignore[no-untyped-def]
    pos = stations(emitter, n=6)
    samples = readings(emitter, pos, [0.0] * 6)
    plain = estimate([], EngineParams(rssi_station_sigma_db=0.0), rssi=samples)
    tiny = estimate([], EngineParams(rssi_station_sigma_db=1e-4), rssi=samples)
    assert (tiny.lat, tiny.lon) == pytest.approx((plain.lat, plain.lon), abs=1e-6)


def test_stations_with_unknown_offsets_locate_the_emitter(emitter):  # type: ignore[no-untyped-def]
    errs = []
    for seed in range(10):
        rng = np.random.default_rng(100 + seed)
        pos = stations(emitter, n=6, seed=seed)
        offs = list(rng.normal(0.0, 4.0, len(pos)))
        est = estimate([], rssi=readings(emitter, pos, offs, quantize_db=6.0, seed=seed))
        errs.append(distance_m((est.lat, est.lon), emitter))
        assert est.rssi_fit is not None and len(est.rssi_fit.station_offsets_db) == 6
    assert float(np.median(errs)) < 2500.0  # coarse area only, stations are 2-9 km away


def test_more_stations_help(emitter):  # type: ignore[no-untyped-def]
    def mean_err(n: int) -> float:
        out = []
        for seed in range(10):
            rng = np.random.default_rng(seed)
            pos = stations(emitter, n=n, seed=seed)
            est = estimate(
                [], rssi=readings(emitter, pos, list(rng.normal(0, 4, n)), quantize_db=6, seed=seed)
            )
            out.append(distance_m((est.lat, est.lon), emitter))
        return float(np.mean(out))

    assert mean_err(12) < mean_err(4)


def test_station_offsets_are_estimated(emitter):  # type: ignore[no-untyped-def]
    pos = stations(emitter, n=8)
    true = [6.0, -6.0, 0.0, 3.0, -3.0, 8.0, -8.0, 0.0]
    est = estimate([], rssi=readings(emitter, pos, true, noise_db=0.5, events=3))
    assert est.rssi_fit is not None
    got = est.rssi_fit.station_offsets_db
    corr = np.corrcoef([got[f"st{k}"] for k in range(8)], true)[0, 1]
    assert corr > 0.8


def test_fewer_than_four_stations_are_ignored(emitter, triangle_stations):  # type: ignore[no-untyped-def]
    pos = stations(emitter, n=3)
    samples = readings(emitter, pos, [0.0, 0.0, 0.0])
    with pytest.raises(EngineError):
        estimate([], rssi=samples)
    bearings = make_bearings(emitter, triangle_stations)
    est = estimate(bearings, rssi=samples)
    assert est.rssi_fit is None and est.n_rssi == 0


def test_repeats_are_aggregated_per_station_and_transmission(emitter):  # type: ignore[no-untyped-def]
    pos = stations(emitter, n=4)
    base = readings(emitter, pos, [0.0] * 4, noise_db=0.0)
    noisy = base + [
        RssiSample(s.lat, s.lon, s.rssi_dbm + d, group=s.group, event=s.event)
        for s in base
        for d in (-1.0, 1.0)
    ]
    out = usable_samples(noisy, EngineParams())
    assert len(out) == 4  # 12 readings -> one per station and transmission
    assert [o.rssi_dbm for o in out] == pytest.approx([s.rssi_dbm for s in base])
    other_tx = base + [
        RssiSample(s.lat, s.lon, s.rssi_dbm, group=s.group, event="tx9") for s in base
    ]
    assert len(usable_samples(other_tx, EngineParams())) == 8


def test_known_offset_is_subtracted(emitter):  # type: ignore[no-untyped-def]
    s = RssiSample(0, 0, -80.0, attenuation_db=10.0, offset_db=4.0)
    assert corrected_level(s) == pytest.approx(-74.0)


def test_bearings_dominate_stations(emitter, triangle_stations):  # type: ignore[no-untyped-def]
    bearings = make_bearings(emitter, triangle_stations)
    pos = stations(emitter, n=6)
    bad = readings(emitter, pos, [0.0] * 6, noise_db=6.0, seed=9)
    plain = estimate(bearings)
    fused = estimate(bearings, rssi=bad)
    assert distance_m((fused.lat, fused.lon), (plain.lat, plain.lon)) < 200.0


def test_zero_station_sigma_ignores_offsets(emitter):  # type: ignore[no-untyped-def]
    pos = stations(emitter, n=6)
    samples = readings(emitter, pos, [0.0] * 6)
    est = estimate([], EngineParams(rssi_station_sigma_db=0.0), rssi=samples)
    assert est.rssi_fit is not None and est.rssi_fit.station_offsets_db == {}
    with pytest.raises(EngineError):
        estimate([], EngineParams(rssi_station_sigma_db=-1.0), rssi=samples)


def test_mixed_track_and_stations(emitter):  # type: ignore[no-untyped-def]
    from tests.test_rssi import spiral_track

    pos = stations(emitter, n=5)
    est = estimate([], rssi=spiral_track(emitter) + readings(emitter, pos, [3, -3, 0, 5, -5]))
    assert est.rssi_fit is not None
    assert est.n_rssi == 45
    assert distance_m((est.lat, est.lon), emitter) < 1500.0


def test_perf_budget_with_stations(emitter):  # type: ignore[no-untyped-def]
    pos = stations(emitter, n=12)
    samples = readings(
        emitter, pos, [0.0] * 12, events=25
    )  # 300 raw readings, 12 per... aggregated
    params = EngineParams(resolution_m=50.0, max_cells=200)
    estimate([], params, rssi=samples)
    t0 = time.perf_counter()
    estimate([], params, rssi=samples)
    print(f"omni perf: {time.perf_counter() - t0:.3f}s")
    assert time.perf_counter() - t0 < 1.0


def test_fit_at_reports_rms_residual(emitter):  # type: ignore[no-untyped-def]
    pos = stations(emitter, n=6)
    est = estimate([], rssi=readings(emitter, pos, [0.0] * 6, noise_db=0.0))
    assert est.rssi_fit is not None and est.rssi_fit.residual_db < 3.0
