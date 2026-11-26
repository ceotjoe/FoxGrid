from __future__ import annotations

from heading import DRIVING, PARKED, Fix, HeadingTracker


def run(
    tracker: HeadingTracker,
    t0: float,
    seconds: int,
    speed: float,
    track: float | None,
    turn: float = 0.0,
) -> float:
    """Feed one fix per second; returns the next time."""
    t = t0
    for i in range(seconds):
        tr = None if track is None else (track + turn * i) % 360
        tracker.update(Fix(t, 48.1, 11.5, speed, tr))
        t += 1.0
    return t


def test_no_heading_before_driving_straight_long_enough() -> None:
    tr = HeadingTracker()
    t = run(tr, 0, 5, 10.0, 90.0)
    assert tr.current is None  # 4 s of history
    run(tr, t, 1, 10.0, 90.0)
    assert tr.current is not None
    assert tr.current.mode == DRIVING
    assert tr.current.heading_deg == 90.0
    assert tr.current.sigma_deg == 2.0


def test_slow_driving_has_larger_sigma() -> None:
    tr = HeadingTracker()
    run(tr, 0, 8, 3.0, 180.0)
    assert tr.current is not None and tr.current.sigma_deg == 4.0


def test_turning_gives_no_heading() -> None:
    tr = HeadingTracker()
    t = run(tr, 0, 8, 10.0, 0.0)
    assert tr.current is not None
    run(tr, t, 5, 10.0, 0.0, turn=8.0)
    assert tr.current is None


def test_parking_after_braking_freezes_a_valid_heading() -> None:
    tr = HeadingTracker()
    t = run(tr, 0, 10, 10.0, 270.0)
    t = run(tr, t, 3, 1.2, 275.0)  # braking through the manoeuvring band
    assert tr.current is None
    run(tr, t, 30, 0.1, None)  # parked; the receiver's course is meaningless
    assert tr.current is not None
    assert tr.current.mode == PARKED
    assert tr.current.heading_deg == 270.0
    assert tr.current.sigma_deg == 3.0
    assert tr.current.certain


def test_parking_after_manoeuvring_is_uncertain() -> None:
    tr = HeadingTracker()
    t = run(tr, 0, 10, 10.0, 270.0)
    t = run(tr, t, 15, 1.0, 120.0)  # 15 s of parking manoeuvres
    run(tr, t, 5, 0.0, 33.0)
    assert tr.current is not None
    assert tr.current.sigma_deg == 12.0
    assert not tr.current.certain


def test_parking_right_after_a_turn_is_uncertain() -> None:
    tr = HeadingTracker()
    t = run(tr, 0, 10, 10.0, 0.0)
    t = run(tr, t, 3, 8.0, 0.0, turn=20.0)
    run(tr, t, 5, 0.0, None)
    assert tr.current is not None and not tr.current.certain


def test_parked_without_any_heading_yields_nothing() -> None:
    tr = HeadingTracker()
    run(tr, 0, 10, 0.0, 12.0)
    assert tr.current is None


def test_gap_in_fixes_restarts_the_straight_check() -> None:
    tr = HeadingTracker()
    t = run(tr, 0, 4, 10.0, 90.0)
    run(tr, t + 10, 2, 10.0, 90.0)
    assert tr.current is None


def test_out_of_order_fix_is_ignored() -> None:
    tr = HeadingTracker()
    run(tr, 0, 10, 10.0, 90.0)
    before = tr.current
    tr.update(Fix(3.0, 48.1, 11.5, 0.0, None))
    assert tr.current == before
