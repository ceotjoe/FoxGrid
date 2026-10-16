"""Where should the next bearing be taken? (position suggestions)

Every bearing taken at ``S`` with angular sigma ``s`` carries Fisher information
``J = n n^T / (s^2 d^2)`` about the emitter position (local east/north, metres), where ``d`` is
the distance from ``S`` to the estimate and ``n`` the unit vector perpendicular to the line of
sight: a bearing only pins down the lateral position. The information of the existing bearings
adds up to ``I``; one more bearing gives ``I + J``. The relative change of the error ellipse area,
``sqrt(det((I + J)^-1) / det(I^-1))``, is the expected gain.

The core (Gaussian) information is used on purpose instead of the grid posterior reported by
``estimate``: that one includes the heavy tails of the outlier mixture, which can even grow when a
good bearing is added and would make the comparison meaningless.

This linearised view is smooth and cheap, so many candidate points can be ranked in
milliseconds. A bearing never improves the position along its own line of sight, which is why the
best spots lie across the existing rays, and closer is better for a fixed angular sigma.
"""

from __future__ import annotations

import math

import numpy as np
from pyproj import Geod

from foxgrid_engine.estimate import estimate
from foxgrid_engine.types import (
    Bearing,
    EngineError,
    EngineParams,
    RssiSample,
    Suggestion,
)

_GEOD = Geod(ellps="WGS84")
_RADIUS_FACTORS = (0.5, 0.8, 1.2, 1.8, 2.6)
_ANGLES = 24
_PRIOR_SIGMA_M = 20_000.0  # weak prior along an otherwise unconstrained direction
_MIN_DISTANCE_M = 50.0


def point_in_ring(lon: float, lat: float, ring: list[tuple[float, float]]) -> bool:
    """Even-odd test; ``ring`` holds (lon, lat) vertices (closed or open)."""
    inside = False
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % n]
        if (y0 > lat) != (y1 > lat) and lon < (x1 - x0) * (lat - y0) / (y1 - y0) + x0:
            inside = not inside
    return inside


def _offset(lat: float, lon: float, east_m: float, north_m: float) -> tuple[float, float]:
    dist = math.hypot(east_m, north_m)
    az = math.degrees(math.atan2(east_m, north_m))
    lon2, lat2, _ = _GEOD.fwd(lon, lat, az, dist)
    return float(lat2), float(lon2)


def _information(bearings: list[Bearing], lat: float, lon: float) -> np.ndarray:
    """Information matrix (east, north) of the bearings about the point ``(lat, lon)``."""
    info = np.eye(2) / _PRIOR_SIGMA_M**2  # keeps a single bearing (rank one) invertible
    for b in bearings:
        az_to, _, dist = _GEOD.inv(b.lon, b.lat, lon, lat)
        d = max(float(dist), _MIN_DISTANCE_M)
        a = math.radians(float(az_to))
        normal = np.array([math.cos(a), -math.sin(a)])  # across the line of sight
        info += np.outer(normal, normal) / (math.radians(b.sigma_deg) ** 2 * d**2)
    return info


def suggest_positions(
    bearings: list[Bearing],
    params: EngineParams | None = None,
    rssi: list[RssiSample] | None = None,
    *,
    count: int = 3,
    typical_sigma_deg: float = 10.0,
    search_area: list[tuple[float, float]] | None = None,
    min_target_distance_m: float = 300.0,
) -> list[Suggestion]:
    """Return up to ``count`` places, best first, where another bearing helps most."""
    if not bearings:
        raise EngineError("at least one bearing is required to suggest positions")
    if typical_sigma_deg <= 0:
        raise EngineError("typical_sigma_deg must be positive")
    base = params or EngineParams()
    current = estimate(bearings, base, rssi)
    precision = _information(bearings, current.lat, current.lon)
    det_before = 1.0 / float(np.linalg.det(precision))
    sigma_rad = math.radians(typical_sigma_deg)
    scale = min(max(current.ellipse_2s.semi_major_m, 800.0), 6000.0)

    scored: list[tuple[float, Suggestion, float, float]] = []
    for factor in _RADIUS_FACTORS:
        radius = max(factor * scale, min_target_distance_m)
        for k in range(_ANGLES):
            angle = 360.0 / _ANGLES * k
            east = radius * math.sin(math.radians(angle))
            north = radius * math.cos(math.radians(angle))
            lat, lon = _offset(current.lat, current.lon, east, north)
            if search_area and not point_in_ring(lon, lat, search_area):
                continue
            # line of sight from the candidate to the estimate is (-east, -north)
            normal = np.array([north, -east]) / radius  # unit vector across the line of sight
            info = np.outer(normal, normal) / (sigma_rad**2 * radius**2)
            after = np.linalg.inv(precision + info)
            reduction = max(
                0.0, min(1.0, 1.0 - math.sqrt(float(np.linalg.det(after)) / det_before))
            )
            vals = np.sqrt(np.maximum(np.linalg.eigvalsh(after), 0.0))
            azimuth_to_target = math.degrees(math.atan2(-east, -north)) % 360.0
            scored.append(
                (
                    reduction,
                    Suggestion(
                        lat=lat,
                        lon=lon,
                        expected_reduction=reduction,
                        expected_semi_major_m=float(vals[1]),
                        expected_semi_minor_m=float(vals[0]),
                        azimuth_to_target_deg=azimuth_to_target,
                        distance_to_target_m=radius,
                    ),
                    radius,
                    angle,
                )
            )

    scored.sort(key=lambda item: -item[0])
    picked: list[tuple[Suggestion, float, float]] = []
    for _, sug, radius, angle in scored:
        # Keep the proposals apart so the three are real alternatives, not neighbours.
        if all(abs((angle - a + 180.0) % 360.0 - 180.0) >= 60.0 for _, _, a in picked):
            picked.append((sug, radius, angle))
        if len(picked) == count:
            break
    return [s for s, _, _ in picked]
