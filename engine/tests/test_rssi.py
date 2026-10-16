from __future__ import annotations

import math
import time

import numpy as np
import pytest

from foxgrid_engine import Bearing, EngineError, EngineParams, RssiSample, estimate
from foxgrid_engine.rssi import RssiData, corrected_level, fit_at, select_recent
from tests.conftest import ORIGIN, distance_m, make_bearings, offset

P0 = -20.0  # dBm at 1 m
EXPONENT = 3.0


def level_at(station: tuple[float, float], target: tuple[float, float]) -> float:
    return P0 - 10.0 * EXPONENT * math.log10(max(distance_m(station, target), 1.0))


def spiral_track(
    target: tuple[float, float],
    n: int = 40,
    noise_db: float = 2.0,
    seed: int = 3,
    attenuation_for=None,  # type: ignore[no-untyped-def]
) -> list[RssiSample]:
    """A walk that closes in on the emitter while circling it (radial and tangential variation)."""
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        frac = i / (n - 1)
        radius = 5000.0 * (1 - frac) + 400.0 * frac
        angle = math.radians(270.0 * frac)
        pos = offset(*target, radius * math.sin(angle), radius * math.cos(angle))
        true = level_at(pos, target) + rng.normal(0.0, noise_db)
        att = attenuation_for(i) if attenuation_for else 0.0
        out.append(
            RssiSample(
                lat=pos[0],
                lon=pos[1],
                rssi_dbm=true - att,
                attenuation_db=att,
                measured_at=1000.0 + 10.0 * i,
            )
        )
    return out


@pytest.fixture
def emitter() -> tuple[float, float]:
    return offset(*ORIGIN, 800.0, 1200.0)


def test_rssi_only_locates_emitter_and_fits_path_loss(emitter):  # type: ignore[no-untyped-def]
    est = estimate([], rssi=spiral_track(emitter))
    assert distance_m((est.lat, est.lon), emitter) < 400.0
    assert est.n_bearings == 0 and est.n_rssi == 40
    assert est.rssi_fit is not None
    assert est.rssi_fit.exponent == pytest.approx(EXPONENT, abs=0.7)
    assert est.rssi_fit.p0_dbm == pytest.approx(P0, abs=15.0)
    assert 0.5 < est.rssi_fit.residual_db < 5.0


def test_attenuation_is_added_back_before_fitting(emitter):  # type: ignore[no-untyped-def]
    def att(i: int) -> float:
        return 0.0 if i < 12 else 20.0 if i < 26 else 30.0  # switched in on the way

    track = spiral_track(emitter, noise_db=1.0, attenuation_for=att)
    plain = spiral_track(emitter, noise_db=1.0)
    with_att = estimate([], rssi=track)
    without_att = estimate([], rssi=plain)
    # same physical situation: the corrected result matches the attenuator-free run
    assert distance_m((with_att.lat, with_att.lon), (without_att.lat, without_att.lon)) < 100.0
    # ignoring the attenuator distorts the trend and costs accuracy
    ignored = [RssiSample(s.lat, s.lon, s.rssi_dbm, 0.0, s.measured_at) for s in track]
    wrong = estimate([], rssi=ignored)
    assert distance_m((wrong.lat, wrong.lon), emitter) > distance_m(
        (with_att.lat, with_att.lon), emitter
    )
    assert corrected_level(track[20]) == pytest.approx(plain[20].rssi_dbm, abs=3.0)


def test_rssi_tightens_a_weak_bearing_geometry(emitter):  # type: ignore[no-untyped-def]
    stations = [offset(*ORIGIN, x, -2500.0) for x in (-300.0, 0.0, 300.0)]  # almost parallel
    rng = np.random.default_rng(7)
    err_b, err_f, shrink = [], [], []
    for seed in range(12):
        bearings = make_bearings(emitter, stations, 5.0, rng)
        only = estimate(bearings)
        fused = estimate(bearings, rssi=spiral_track(emitter, seed=seed))
        err_b.append(distance_m((only.lat, only.lon), emitter))
        err_f.append(distance_m((fused.lat, fused.lon), emitter))
        shrink.append(fused.ellipse_1s.semi_major_m / only.ellipse_1s.semi_major_m)
    assert max(shrink) < 0.7  # the ellipse always gets much shorter
    assert np.mean(err_f) < 0.5 * np.mean(err_b)  # and the position gets better on average


def test_zero_weight_equals_bearings_only(emitter, triangle_stations):  # type: ignore[no-untyped-def]
    bearings = make_bearings(emitter, triangle_stations)
    plain = estimate(bearings)
    zero = estimate(bearings, EngineParams(rssi_weight=0.0), rssi=spiral_track(emitter))
    assert (zero.lat, zero.lon) == pytest.approx((plain.lat, plain.lon), abs=1e-6)


def test_too_few_samples_are_ignored(emitter, triangle_stations):  # type: ignore[no-untyped-def]
    bearings = make_bearings(emitter, triangle_stations)
    est = estimate(bearings, rssi=spiral_track(emitter, n=4))
    assert est.rssi_fit is None and est.n_rssi == 0
    with pytest.raises(EngineError):
        estimate([], rssi=spiral_track(emitter, n=4))


def test_flat_signal_clips_the_exponent_to_its_lower_bound(emitter):  # type: ignore[no-untyped-def]
    flat = [
        RssiSample(*offset(*emitter, 200.0 * i, 100.0 * i), rssi_dbm=-80.0) for i in range(1, 10)
    ]
    est = estimate([], rssi=flat)
    assert est.rssi_fit is not None
    assert est.rssi_fit.exponent == pytest.approx(1.5)


def test_age_weighting_prefers_recent_samples(emitter):  # type: ignore[no-untyped-def]
    track = spiral_track(emitter)
    # corrupt the oldest third heavily; with a short half-life they barely count
    bad = [
        RssiSample(s.lat, s.lon, s.rssi_dbm + (35.0 if i < 13 else 0.0), 0.0, s.measured_at)
        for i, s in enumerate(track)
    ]
    now = 1000.0 + 10.0 * 39
    plain = estimate([], rssi=bad)
    aged = estimate([], EngineParams(half_life_s=60.0, now=now), rssi=bad)
    assert distance_m((aged.lat, aged.lon), emitter) < distance_m((plain.lat, plain.lon), emitter)


def test_select_recent_by_time_and_by_order():
    samples = [RssiSample(0, 0, -50.0, 0.0, float(t)) for t in (5, 1, 4, 2, 3)]
    assert [s.measured_at for s in select_recent(samples, 3)] == [3.0, 4.0, 5.0]
    untimed = [RssiSample(0, 0, float(-i)) for i in range(5)]
    assert [s.rssi_dbm for s in select_recent(untimed, 2)] == [-3.0, -4.0]
    assert len(select_recent(untimed, 10)) == 5


def test_rssi_validation(emitter):  # type: ignore[no-untyped-def]
    track = spiral_track(emitter)
    with pytest.raises(EngineError):
        estimate([], EngineParams(rssi_sigma_db=0.0), rssi=track)
    with pytest.raises(EngineError):
        estimate([], EngineParams(rssi_exponent_bounds=(4.0, 2.0)), rssi=track)
    with pytest.raises(EngineError):
        estimate([], rssi=[*track[:-1], RssiSample(1.0, 1.0, float("nan"))])
    with pytest.raises(EngineError):
        estimate([], rssi=[*track[:-1], RssiSample(95.0, 1.0, -70.0)])


def test_fit_at_reports_a_perfect_model(emitter):  # type: ignore[no-untyped-def]
    exact = spiral_track(emitter, noise_db=0.0)
    est = estimate([], EngineParams(contour_levels=()), rssi=exact)
    assert est.rssi_fit is not None and est.rssi_fit.residual_db < 1.5
    data = RssiData(
        east=np.array([0.0, 100.0, 300.0]),
        north=np.zeros(3),
        level=np.array([-40.0, -50.0, -60.0]),
        weight=np.ones(3),
    )
    fit = fit_at(-10.0, 0.0, data, EngineParams())
    assert fit.n_samples == 3 and fit.exponent >= 1.5


def test_performance_with_bearings_and_rssi(emitter):  # type: ignore[no-untyped-def]
    rng = np.random.default_rng(1)
    stations = [offset(*ORIGIN, *rng.uniform(-4000, 4000, 2)) for _ in range(50)]
    bearings = make_bearings(emitter, stations, 10.0, rng)
    params = EngineParams(margin_m=1000.0, max_cells=200)
    track = spiral_track(emitter, n=300)
    estimate(bearings, params, rssi=track)  # warm up
    t0 = time.perf_counter()
    estimate(bearings, params, rssi=track)
    assert time.perf_counter() - t0 < 0.6


def test_bearings_still_required_to_be_valid_with_rssi(emitter):  # type: ignore[no-untyped-def]
    with pytest.raises(EngineError):
        estimate(
            [Bearing(lat=48.0, lon=11.0, azimuth_deg=10.0, sigma_deg=0.0)],
            rssi=spiral_track(emitter),
        )
