from __future__ import annotations

import math
import time

import pytest

from foxgrid_engine import (
    Bearing,
    EngineError,
    EngineParams,
    RssiSample,
    estimate,
    suggest_positions,
)
from foxgrid_engine.suggest import point_in_ring
from tests.conftest import ORIGIN, distance_m, make_bearings, offset, true_bearing


@pytest.fixture
def emitter() -> tuple[float, float]:
    return offset(*ORIGIN, 0.0, 0.0)


@pytest.fixture
def one_sided(emitter):  # type: ignore[no-untyped-def]
    """Two stations on the same side: both rays run east, so the position is smeared east-west."""
    stations = [offset(*ORIGIN, -4000.0, -300.0), offset(*ORIGIN, -4500.0, 500.0)]
    return make_bearings(emitter, stations, 5.0)


def _area(e) -> float:  # type: ignore[no-untyped-def]
    return math.pi * e.ellipse_1s.semi_major_m * e.ellipse_1s.semi_minor_m


def test_best_spot_is_across_the_existing_rays(one_sided):  # type: ignore[no-untyped-def]
    suggestions = suggest_positions(one_sided)
    assert len(suggestions) == 3
    best = suggestions[0]
    # existing rays point east (~90 deg); a bearing from north or south crosses them at ~90 deg
    diff = abs(((best.azimuth_to_target_deg - 90.0) + 90.0) % 180.0 - 90.0)
    assert diff > 45.0
    assert best.expected_reduction > 0.5
    assert best.expected_semi_major_m > 0 and best.expected_semi_minor_m > 0
    assert best.distance_to_target_m > 300.0


def test_results_are_sorted_distinct_and_bounded(one_sided):  # type: ignore[no-untyped-def]
    s = suggest_positions(one_sided)
    reductions = [x.expected_reduction for x in s]
    assert reductions == sorted(reductions, reverse=True)
    assert all(0.0 <= r <= 1.0 for r in reductions)
    for i in range(len(s)):
        for j in range(i + 1, len(s)):
            assert distance_m((s[i].lat, s[i].lon), (s[j].lat, s[j].lon)) > 500.0
    assert len(suggest_positions(one_sided, count=1)) == 1
    assert len(suggest_positions(one_sided, count=2)) == 2


def test_following_the_advice_really_shrinks_the_ellipse(one_sided, emitter):  # type: ignore[no-untyped-def]
    # Compare against the engine in its Gaussian limit (almost no outlier mixture), which is the
    # model the information based prediction describes.
    core = EngineParams(outlier_fraction=0.001, resolution_m=25.0)
    before = estimate(one_sided, core)
    best = suggest_positions(one_sided, core)[0]
    new = Bearing(
        lat=best.lat,
        lon=best.lon,
        azimuth_deg=true_bearing((best.lat, best.lon), emitter),
        sigma_deg=10.0,
    )
    after = estimate([*one_sided, new], core)
    real_reduction = 1.0 - _area(after) / _area(before)
    assert real_reduction > 0.4
    assert real_reduction == pytest.approx(best.expected_reduction, abs=0.2)


def test_search_area_limits_the_candidates(one_sided):  # type: ignore[no-untyped-def]
    # a box covering only the area south of the estimate
    south = [
        offset(*ORIGIN, -9000.0, -12000.0),
        offset(*ORIGIN, 9000.0, -12000.0),
        offset(*ORIGIN, 9000.0, -200.0),
        offset(*ORIGIN, -9000.0, -200.0),
    ]
    ring = [(lon, lat) for lat, lon in south]
    for s in suggest_positions(one_sided, search_area=ring):
        assert point_in_ring(s.lon, s.lat, ring)
    nothing = [
        (lon, lat)
        for lat, lon in (
            offset(*ORIGIN, 50000.0, 50000.0),
            offset(*ORIGIN, 51000.0, 50000.0),
            offset(*ORIGIN, 50500.0, 51000.0),
        )
    ]
    assert suggest_positions(one_sided, search_area=nothing) == []


def test_point_in_ring():
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    assert point_in_ring(5.0, 5.0, square)
    assert not point_in_ring(11.0, 5.0, square)
    assert not point_in_ring(5.0, -1.0, square)
    assert point_in_ring(5.0, 5.0, [*square, square[0]])  # closed ring works too


def test_a_single_bearing_still_gets_advice(emitter):  # type: ignore[no-untyped-def]
    one = make_bearings(emitter, [offset(*ORIGIN, -3000.0, 0.0)], 5.0)
    s = suggest_positions(one)
    assert s and s[0].expected_reduction > 0.5


def test_works_with_an_rssi_track(one_sided, emitter):  # type: ignore[no-untyped-def]
    track = [
        RssiSample(*offset(*emitter, 1500.0 - 100.0 * i, 800.0), rssi_dbm=-60.0 - i)
        for i in range(10)
    ]
    assert suggest_positions(one_sided, rssi=track)


def test_good_geometry_gains_little(emitter, triangle_stations):  # type: ignore[no-untyped-def]
    # three very sharp bearings already pin the emitter down to a few tens of metres
    good = make_bearings(emitter, triangle_stations, 0.3)
    poor = make_bearings(emitter, triangle_stations[:1], 5.0)
    assert suggest_positions(good)[0].expected_reduction < 0.3
    assert suggest_positions(poor)[0].expected_reduction > 0.8


def test_respects_engine_params(one_sided):  # type: ignore[no-untyped-def]
    assert suggest_positions(one_sided, EngineParams(outlier_fraction=0.2), typical_sigma_deg=5.0)


def test_input_validation(one_sided):  # type: ignore[no-untyped-def]
    with pytest.raises(EngineError):
        suggest_positions([])
    with pytest.raises(EngineError):
        suggest_positions(one_sided, typical_sigma_deg=0.0)


def test_runs_fast_enough_for_an_api_call(one_sided):  # type: ignore[no-untyped-def]
    suggest_positions(one_sided)  # warm up the projection cache
    t0 = time.perf_counter()
    suggest_positions(one_sided)
    assert time.perf_counter() - t0 < 3.0
