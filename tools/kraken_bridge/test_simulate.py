"""Repeater users in the simulated drive: overs, squelch gaps, and bearings that never mix."""

from __future__ import annotations

from datetime import datetime

from geo import angle_diff_deg, initial_bearing_deg
from simulate import FOX, default_overs, place_users, route_duration
from test_bridge import EMITTER, START, make_bridge, run_drive


def test_default_overs_take_turns_with_gaps() -> None:
    overs = default_overs(200.0, users=2)
    assert [o.source for o in overs[:4]] == [FOX, "user1", "user2", FOX]
    for a, b in zip(overs, overs[1:], strict=False):
        assert b.start_s - a.end_s >= 3.0  # the squelch closes in between
    assert overs[-1].end_s <= 200.0
    assert default_overs(10.0, users=0) == [default_overs(10.0, users=0)[0]]


def test_bearings_stay_within_one_over_and_point_at_its_source() -> None:
    now = [1_800_000_000.0]
    t0 = now[0]
    users = place_users(START, 2)
    overs = default_overs(route_duration(), 2)
    sources = {FOX: EMITTER, **users}
    messages = run_drive(make_bridge(now), now, users=users, overs=overs)
    assert len(messages) >= 10
    seen = set()
    for m in messages:
        start = datetime.fromisoformat(m["window_start"]).timestamp() - t0
        end = datetime.fromisoformat(m["window_end"]).timestamp() - t0
        [over] = [o for o in overs if o.start_s - 0.3 <= start and end <= o.end_s + 0.3]
        truth = initial_bearing_deg(m["lat"], m["lon"], *sources[over.source])
        assert abs(angle_diff_deg(m["azimuth_true_deg"], truth)) < 10.0
        seen.add(over.source)
    assert seen == {FOX, "user1", "user2"}
