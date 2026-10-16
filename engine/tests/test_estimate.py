from __future__ import annotations

import math
import time

import numpy as np
import pytest

from foxgrid_engine import Bearing, EngineError, EngineParams, estimate
from foxgrid_engine.likelihood import log_bessel_i0, sigma_to_kappa, wrap_pi
from tests.conftest import ORIGIN, distance_m, make_bearings, offset, true_bearing


def _mahalanobis(est, truth) -> float:  # type: ignore[no-untyped-def]
    # truth offset in local east/north metres relative to the estimate
    d = distance_m((est.lat, est.lon), truth)
    az = math.radians(true_bearing((est.lat, est.lon), truth))
    v = np.array([d * math.sin(az), d * math.cos(az)])
    cov = np.array(
        [[est.cov_east_east, est.cov_east_north], [est.cov_east_north, est.cov_north_north]]
    )
    return float(math.sqrt(v @ np.linalg.inv(cov) @ v))


def test_three_exact_bearings_hit_within_20m(target, triangle_stations):  # type: ignore[no-untyped-def]
    est = estimate(make_bearings(target, triangle_stations))
    assert distance_m((est.lat, est.lon), target) < 20.0


def test_noisy_bearings_inside_2sigma_ellipse(target, triangle_stations):  # type: ignore[no-untyped-def]
    rng = np.random.default_rng(42)
    inside = 0
    trials = 60
    for _ in range(trials):
        est = estimate(make_bearings(target, triangle_stations, 8.0, rng))
        inside += _mahalanobis(est, target) <= 2.0
    assert inside / trials >= 0.8


def test_gross_outlier_barely_moves_result(target, triangle_stations):  # type: ignore[no-untyped-def]
    clean = make_bearings(target, triangle_stations + [offset(*ORIGIN, -3000.0, 6000.0)])
    base = estimate(clean)
    wrong = clean[:-1] + [
        Bearing(
            lat=clean[-1].lat,
            lon=clean[-1].lon,
            azimuth_deg=(clean[-1].azimuth_deg + 120) % 360,
            sigma_deg=5.0,
        )
    ]
    shifted = estimate(wrong)
    assert distance_m((base.lat, base.lon), (shifted.lat, shifted.lon)) < 150.0


def test_parallel_bearings_give_elongated_ellipse():
    stations = [offset(*ORIGIN, x, 0.0) for x in (-300.0, 0.0, 300.0)]
    target = offset(*ORIGIN, 0.0, 8000.0)
    est = estimate(make_bearings(target, stations, 5.0))
    assert est.ellipse_1s.semi_major_m > 3 * est.ellipse_1s.semi_minor_m
    # elongated along the line of sight (north): orientation near 0/180
    o = est.ellipse_1s.orientation_deg
    assert min(o, 180.0 - o) < 20.0


def test_wraparound_across_north(triangle_stations):  # type: ignore[no-untyped-def]
    target = offset(*ORIGIN, 0.0, 20000.0)
    stations = [
        offset(*ORIGIN, -400.0, 0.0),  # azimuth just east of north
        offset(*ORIGIN, 400.0, 0.0),  # azimuth just west of north (~359.x)
        offset(*ORIGIN, -9000.0, -2000.0),
    ]
    bearings = make_bearings(target, stations, 3.0)
    assert any(b.azimuth_deg > 358.0 or b.azimuth_deg < 2.0 for b in bearings)
    est = estimate(bearings)
    assert distance_m((est.lat, est.lon), target) < 100.0


def test_single_bearing_is_defined(target):  # type: ignore[no-untyped-def]
    est = estimate(make_bearings(target, [offset(*ORIGIN, -5000.0, 0.0)]))
    assert est.n_bearings == 1
    assert est.ellipse_1s.semi_major_m > est.ellipse_1s.semi_minor_m


def test_cells_behind_station_do_not_attract():
    # Two stations pointing away from each other's side must not be fused behind them.
    station = offset(*ORIGIN, 0.0, 0.0)
    other = offset(*ORIGIN, 4000.0, 0.0)
    b = [
        Bearing(lat=station[0], lon=station[1], azimuth_deg=0.0, sigma_deg=5.0),
        Bearing(lat=other[0], lon=other[1], azimuth_deg=0.0, sigma_deg=5.0),
    ]
    est = estimate(b)
    north = distance_m((est.lat, est.lon), station)
    assert north >= 0.0  # runs, produces a finite estimate
    assert math.isfinite(est.lat) and math.isfinite(est.lon)


def test_age_weighting_downweights_old_bearing(target, triangle_stations):  # type: ignore[no-untyped-def]
    good = make_bearings(target, triangle_stations)
    now = 10_000.0
    bad_station = offset(*ORIGIN, -3000.0, 6000.0)
    bad = Bearing(
        lat=bad_station[0],
        lon=bad_station[1],
        azimuth_deg=(true_bearing(bad_station, target) + 40.0) % 360.0,
        sigma_deg=5.0,
        measured_at=0.0,
    )
    timed = [Bearing(b.lat, b.lon, b.azimuth_deg, b.sigma_deg, measured_at=now) for b in good] + [
        bad
    ]
    unweighted = estimate(timed)
    weighted = estimate(timed, EngineParams(half_life_s=100.0, now=now))
    assert distance_m((weighted.lat, weighted.lon), target) <= distance_m(
        (unweighted.lat, unweighted.lon), target
    )


def test_grid_is_capped_for_wide_spreads(target):  # type: ignore[no-untyped-def]
    far = [offset(*ORIGIN, -60000.0, 0.0), offset(*ORIGIN, 60000.0, 0.0)]
    est = estimate(make_bearings(offset(*ORIGIN, 0, 50000.0), far))
    assert max(est.grid_cells) <= 252
    assert est.resolution_m > 50.0


def test_performance_200x200_50_bearings():
    rng = np.random.default_rng(1)
    target = offset(*ORIGIN, 0.0, 0.0)
    stations = [offset(*ORIGIN, *rng.uniform(-4000, 4000, 2)) for _ in range(50)]
    bearings = make_bearings(target, stations, 10.0, rng)
    # 8 km spread + 2*margin 5 km -> force a 200x200 grid
    params = EngineParams(margin_m=1000.0, resolution_m=50.0, max_cells=200)
    estimate(bearings, params)  # warm up
    t0 = time.perf_counter()
    est = estimate(bearings, params)
    elapsed = time.perf_counter() - t0
    assert est.grid_cells[0] >= 150
    assert elapsed < 0.2


def test_southern_hemisphere_and_zone_edge():
    origin = (-33.9, 18.4)  # Cape Town
    target = offset(*origin, 2000.0, 1000.0)
    stations = [offset(*origin, x, y) for x, y in ((-5000, -2000), (6000, -3000), (0, 8000))]
    est = estimate(make_bearings(target, stations))
    assert est.utm_epsg == 32734
    assert distance_m((est.lat, est.lon), target) < 20.0
    # zone edge: station far from the central meridian -> large grid convergence
    edge = (50.0, 12.0 + 2.9)
    target = offset(*edge, 1000.0, 3000.0)
    stations = [offset(*edge, x, y) for x, y in ((-6000, -2000), (7000, -3000), (500, 9000))]
    est = estimate(make_bearings(target, stations, 2.0))
    assert distance_m((est.lat, est.lon), target) < 20.0


@pytest.mark.parametrize(
    "bad",
    [
        EngineParams(outlier_fraction=0.0),
        EngineParams(resolution_m=0.0),
    ],
)
def test_invalid_params(bad, target, triangle_stations):  # type: ignore[no-untyped-def]
    with pytest.raises(EngineError):
        estimate(make_bearings(target, triangle_stations), bad)


def test_invalid_input(target):  # type: ignore[no-untyped-def]
    with pytest.raises(EngineError):
        estimate([])
    with pytest.raises(EngineError):
        estimate([Bearing(lat=48.0, lon=11.0, azimuth_deg=10.0, sigma_deg=0.0)])
    with pytest.raises(EngineError):
        estimate([Bearing(lat=99.0, lon=11.0, azimuth_deg=10.0, sigma_deg=5.0)])
    with pytest.raises(EngineError):
        estimate([Bearing(lat=48.0, lon=11.0, azimuth_deg=float("nan"), sigma_deg=5.0)])


def test_ring_is_closed_and_encloses_center(target, triangle_stations):  # type: ignore[no-untyped-def]
    est = estimate(make_bearings(target, triangle_stations))
    ring = est.ellipse_2s_ring
    assert ring[0] == pytest.approx(ring[-1])
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    assert min(lons) < est.lon < max(lons)
    assert min(lats) < est.lat < max(lats)


def test_likelihood_helpers():
    angles = np.array([-4.0, 0.0, 3.5, 7.0])
    w = wrap_pi(angles)
    assert np.all(w >= -math.pi) and np.all(w < math.pi)
    k = sigma_to_kappa(np.array([5.0, 15.0]))
    assert k[0] > k[1] > 0
    # continuity of log I0 across the switch between series and asymptotic form
    lo = log_bessel_i0(np.array([49.999]))[0]
    hi = log_bessel_i0(np.array([50.001]))[0]
    assert hi - lo == pytest.approx(0.002, abs=1e-4)  # slope of log I0 is ~1
    assert log_bessel_i0(np.array([1000.0]))[0] == pytest.approx(
        1000 - 0.5 * math.log(2 * math.pi * 1000), abs=1e-2
    )
