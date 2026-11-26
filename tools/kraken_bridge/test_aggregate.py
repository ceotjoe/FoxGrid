from __future__ import annotations

import itertools
import math

from aggregate import AggregationParams, Aggregator, Sample, combined_sigma
from geo import destination
from heading import DRIVING, PARKED


def sample(
    t: float,
    az: float,
    *,
    mode: str = DRIVING,
    pos: tuple[float, float] = (48.1, 11.5),
    sh: float = 2.0,
) -> Sample:
    return Sample(t, az, pos[0], pos[1], mode, sh, confidence=5.0, power_db=-50.0)


def test_sigma_is_root_sum_square_and_clamped() -> None:
    p = AggregationParams(sigma_env=5.0)
    assert math.isclose(combined_sigma(0.0, 2.0, p), math.sqrt(4 + 4 + 4 + 25))
    assert combined_sigma(0.0, 0.0, AggregationParams(sigma_env=0.0, sigma_mount=0.0)) == 5.0
    assert combined_sigma(80.0, 2.0, p) == 30.0


def test_driving_emits_once_per_interval_and_distance() -> None:
    agg = Aggregator()
    out = []
    pos = (48.1, 11.5)
    for i in range(160):  # 40 s at 4 readings/s and 10 m/s
        t = i * 0.25
        pos = destination(*pos, 90.0, 2.5)
        e = agg.add(sample(t, 30.0, pos=pos))
        if e is not None:
            out.append(e)
    assert 3 <= len(out) <= 4  # 400 m: one bearing every 100 m at most
    for a, b in itertools.pairwise(out):
        assert b.t - a.t >= 5.0
    assert all(abs(e.azimuth_true_deg - 30.0) < 1e-6 for e in out)


def test_standing_still_while_driving_mode_does_not_repeat() -> None:
    agg = Aggregator()
    out = [agg.add(sample(i * 0.25, 30.0)) for i in range(200)]
    assert len([e for e in out if e is not None]) == 1


def test_parked_waits_for_the_window_then_every_interval() -> None:
    agg = Aggregator()
    emissions = [
        (i * 0.25, agg.add(sample(i * 0.25, 100.0, mode=PARKED, sh=3.0))) for i in range(4 * 150)
    ]
    times = [t for t, e in emissions if e is not None]
    assert times[0] >= 10.0
    assert len(times) == 3  # at 10 s, 70 s, 130 s
    assert all(b - a >= 60.0 for a, b in itertools.pairwise(times))


def test_mode_change_starts_a_new_window() -> None:
    agg = Aggregator()
    for i in range(10):
        agg.add(sample(i * 0.25, 30.0))
    assert agg.add(sample(3.0, 30.0, mode=PARKED)) is None


def test_outliers_are_dropped_and_counted() -> None:
    agg = Aggregator(AggregationParams(drive_min_samples=12))
    noise = [0.5, -0.5, 1.0, -1.0, 0.0, 0.3, -0.3, 0.8, -0.8, 0.2, -0.2]
    e = None
    for i, n in enumerate(noise):
        assert agg.add(sample(i * 0.2, 50.0 + n)) is None
    e = agg.add(sample(2.3, 230.0))  # a reflection from behind
    assert e is not None
    assert e.rejected == 1
    assert abs(e.azimuth_true_deg - 50.0) < 0.5
    assert e.sigma_deg < 7.0


def test_mostly_scattered_window_keeps_everything() -> None:
    agg = Aggregator()
    out = [agg.add(sample(i * 0.5, az)) for i, az in enumerate([0.0, 120.0, 240.0])]
    e = out[-1]
    assert e is not None
    assert e.rejected == 0
    assert e.sigma_deg == 30.0


def test_reset_forgets_the_window() -> None:
    agg = Aggregator()
    agg.add(sample(0.0, 30.0))
    agg.add(sample(0.25, 30.0))
    agg.reset()
    assert agg.add(sample(0.5, 30.0)) is None


def test_bearing_carries_its_window() -> None:
    agg = Aggregator()
    out = [agg.add(sample(10.0 + i * 0.25, 30.0)) for i in range(3)]
    e = out[-1]
    assert e is not None
    assert (e.window_start, e.window_end) == (10.0, 10.5)
    assert e.window_start <= e.t <= e.window_end


def test_a_gap_splits_the_window_between_two_overs() -> None:
    """A repeater user and then the interferer: the bearings never mix the two directions."""
    agg = Aggregator()
    user = [agg.add(sample(i * 0.25, 200.0, mode=PARKED, sh=3.0)) for i in range(60)]  # 15 s
    # squelch closed for 3 s, then the interferer from 30 degrees
    fox = [agg.add(sample(18.0 + i * 0.25, 30.0, mode=PARKED, sh=3.0)) for i in range(60)]
    first = [e for e in user if e is not None]
    second = [e for e in fox if e is not None]
    assert [round(e.azimuth_true_deg) for e in first] == [200]
    # the new over gets its own bearing after a fresh averaging window, despite the 60 s interval
    assert [round(e.azimuth_true_deg) for e in second] == [30]
    assert second[0].window_start == 18.0
    assert second[0].window_end - second[0].window_start >= 10.0 - 0.25


def test_short_pauses_keep_the_window() -> None:
    agg = Aggregator(AggregationParams(gap_s=1.5))
    times = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0]
    out = [agg.add(sample(t, 100.0, mode=PARKED, sh=3.0)) for t in times]
    e = next(e for e in out if e is not None)
    assert e.window_start == 0.0
