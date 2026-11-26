"""Small spherical-earth helpers and circular statistics (no dependencies).

The bridge only needs distances of a few hundred metres and bearing averages, so a sphere is
plenty; the engine does the exact geodesy on the server.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

EARTH_RADIUS_M = 6_371_000.0


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def initial_bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """True azimuth from point 1 to point 2, 0 <= az < 360."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(y, x)) % 360.0


def destination(lat: float, lon: float, azimuth_deg: float, dist_m: float) -> tuple[float, float]:
    """Point reached from (lat, lon) after ``dist_m`` metres on ``azimuth_deg``."""
    d = dist_m / EARTH_RADIUS_M
    az = math.radians(azimuth_deg)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(az))
    l2 = l1 + math.atan2(
        math.sin(az) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2)
    )
    return math.degrees(p2), (math.degrees(l2) + 540.0) % 360.0 - 180.0


def angle_diff_deg(a: float, b: float) -> float:
    """Signed smallest difference a - b in (-180, 180]."""
    d = (a - b) % 360.0
    return d - 360.0 if d > 180.0 else d


def circular_mean_deg(angles: Sequence[float]) -> float:
    s = sum(math.sin(math.radians(a)) for a in angles)
    c = sum(math.cos(math.radians(a)) for a in angles)
    return math.degrees(math.atan2(s, c)) % 360.0


def circular_std_deg(angles: Sequence[float]) -> float:
    """Circular standard deviation sqrt(-2 ln R), in degrees (0 for a single angle)."""
    n = len(angles)
    if n < 2:
        return 0.0
    s = sum(math.sin(math.radians(a)) for a in angles) / n
    c = sum(math.cos(math.radians(a)) for a in angles) / n
    r = min(1.0, math.hypot(s, c))
    if r <= 1e-12:
        return 180.0
    return math.degrees(math.sqrt(-2.0 * math.log(r)))
