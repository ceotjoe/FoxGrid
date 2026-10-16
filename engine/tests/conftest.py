"""Synthetic scenario helpers; truth is computed with a geodesic independent of the engine."""

from __future__ import annotations

import numpy as np
import pytest
from pyproj import Geod

from foxgrid_engine import Bearing

GEOD = Geod(ellps="WGS84")
ORIGIN = (48.137, 11.575)  # lat, lon (Munich)


def offset(lat: float, lon: float, east_m: float, north_m: float) -> tuple[float, float]:
    dist = float(np.hypot(east_m, north_m))
    az = float(np.degrees(np.arctan2(east_m, north_m)))
    lon2, lat2, _ = GEOD.fwd(lon, lat, az, dist)
    return float(lat2), float(lon2)


def true_bearing(station: tuple[float, float], target: tuple[float, float]) -> float:
    az, _, _ = GEOD.inv(station[1], station[0], target[1], target[0])
    return float(az % 360.0)


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    _, _, d = GEOD.inv(a[1], a[0], b[1], b[0])
    return float(d)


def make_bearings(
    target: tuple[float, float],
    stations: list[tuple[float, float]],
    sigma: float = 5.0,
    noise_rng: np.random.Generator | None = None,
) -> list[Bearing]:
    out = []
    for lat, lon in stations:
        az = true_bearing((lat, lon), target)
        if noise_rng is not None:
            az = (az + noise_rng.normal(0.0, sigma)) % 360.0
        out.append(Bearing(lat=lat, lon=lon, azimuth_deg=az, sigma_deg=sigma))
    return out


@pytest.fixture
def target() -> tuple[float, float]:
    return offset(*ORIGIN, 1500.0, 2500.0)


@pytest.fixture
def triangle_stations() -> list[tuple[float, float]]:
    return [
        offset(*ORIGIN, -6000.0, -3000.0),
        offset(*ORIGIN, 7000.0, -4000.0),
        offset(*ORIGIN, 500.0, 9000.0),
    ]
