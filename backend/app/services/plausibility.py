"""Hints for the lead about participants whose data does not fit together.

These are hints, never verdicts: nothing is changed automatically (bearings are never deleted
and the lead decides about trust and quarantine). The checks are plain geometry on the data the
server already has, so they work without any extra input from the participants.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

EARTH_RADIUS_M = 6_371_000.0

# A bearing is "off" when it misses the estimate by more than this many sigma and degrees.
OFF_SIGMAS = 3.0
OFF_MIN_DEG = 30.0
OFF_SHARE = 0.5
MIN_BEARINGS = 2
MIN_ESTIMATE_BEARINGS = 3  # with two bearings the estimate fits both by construction

MAX_SPEED_MPS = 70.0  # about 250 km/h: faster than anyone drives on a hunt
MIN_JUMP_M = 500.0  # ignore ordinary GPS jitter
MAX_FIX_ACCURACY_M = 100.0
TRACK_WINDOW = timedelta(minutes=15)
OFF_TRACK_M = 2000.0
MIN_OFF_TRACK = 2


@dataclass(frozen=True)
class Flag:
    code: str
    detail: str


@dataclass(frozen=True)
class BearingFact:
    lat: float
    lon: float
    azimuth_deg: float
    sigma_deg: float
    measured_at: datetime


@dataclass(frozen=True)
class Fix:
    lat: float
    lon: float
    at: datetime
    accuracy_m: float | None = None


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def azimuth_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial great-circle bearing from point 1 to point 2, degrees clockwise from north."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(y, x)) % 360.0


def residual_deg(b: BearingFact, target_lat: float, target_lon: float) -> float:
    """Signed angle (-180..180) between the measured azimuth and the direction to the target."""
    expected = azimuth_deg(b.lat, b.lon, target_lat, target_lon)
    return (b.azimuth_deg - expected + 180.0) % 360.0 - 180.0


def disagreement(
    bearings: Sequence[BearingFact], target_lat: float, target_lon: float
) -> Flag | None:
    """Most of the participant's bearings point clearly away from the fused estimate."""
    if len(bearings) < MIN_BEARINGS:
        return None
    off = sum(
        1
        for b in bearings
        if abs(residual_deg(b, target_lat, target_lon)) > max(OFF_SIGMAS * b.sigma_deg, OFF_MIN_DEG)
    )
    if off / len(bearings) < OFF_SHARE:
        return None
    return Flag(
        "bearings_disagree",
        f"{off} von {len(bearings)} Peilungen weichen deutlich vom Ergebnis der anderen ab",
    )


def impossible_speed(fixes: Sequence[Fix]) -> Flag | None:
    """The position jumps farther than anyone can travel in that time (spoofed or broken GPS)."""
    ordered = sorted(fixes, key=lambda f: f.at)
    for a, b in zip(ordered, ordered[1:], strict=False):
        if any(f.accuracy_m is not None and f.accuracy_m > MAX_FIX_ACCURACY_M for f in (a, b)):
            continue
        jump = distance_m(a.lat, a.lon, b.lat, b.lon)
        seconds = (b.at - a.at).total_seconds()
        if jump >= MIN_JUMP_M and (seconds <= 0 or jump / seconds > MAX_SPEED_MPS):
            kmh = "sofort" if seconds <= 0 else f"{jump / seconds * 3.6:.0f} km/h"
            return Flag("impossible_speed", f"Positionssprung von {jump / 1000:.1f} km ({kmh})")
    return None


def off_track(bearings: Sequence[BearingFact], fixes: Sequence[Fix]) -> Flag | None:
    """Bearings claim a station far from where the participant's own track was at that time."""
    if len(bearings) >= MIN_OFF_TRACK + 1 and not fixes:
        return Flag("no_track", "Peilungen, aber keine einzige Positionsmeldung")
    far = 0
    for b in bearings:
        near = [f for f in fixes if abs(f.at - b.measured_at) <= TRACK_WINDOW]
        if not near:
            continue
        nearest = min(near, key=lambda f: abs(f.at - b.measured_at))
        if distance_m(b.lat, b.lon, nearest.lat, nearest.lon) > OFF_TRACK_M:
            far += 1
    if far >= MIN_OFF_TRACK:
        return Flag(
            "bearing_off_track",
            f"{far} Peilungen weit weg vom eigenen Positionsverlauf "
            f"(> {OFF_TRACK_M / 1000:.0f} km)",
        )
    return None


def assess(
    bearings: Sequence[BearingFact],
    fixes: Sequence[Fix],
    estimate: tuple[float, float, int] | None,
) -> list[Flag]:
    """All hints for one participant; ``estimate`` is (lat, lon, number of bearings) or None."""
    flags: list[Flag | None] = []
    if estimate is not None and estimate[2] >= MIN_ESTIMATE_BEARINGS:
        flags.append(disagreement(bearings, estimate[0], estimate[1]))
    flags.append(impossible_speed(fixes))
    flags.append(off_track(bearings, fixes))
    return [f for f in flags if f is not None]
