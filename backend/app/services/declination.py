"""Magnetic declination from the World Magnetic Model (via pygeomag)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from functools import lru_cache

from pygeomag import GeoMag

MODEL = "WMM-2025"


@lru_cache(maxsize=1)
def _model() -> GeoMag:
    return GeoMag()


def decimal_year(d: date) -> float:
    start = datetime(d.year, 1, 1, tzinfo=UTC).date()
    end = datetime(d.year + 1, 1, 1, tzinfo=UTC).date()
    return d.year + (d - start).days / (end - start).days


def declination_deg(lat: float, lon: float, on: date | None = None) -> float:
    """Declination in degrees; positive when magnetic north is east of true north."""
    on = on or datetime.now(UTC).date()
    return float(_model().calculate(glat=lat, glon=lon, alt=0.0, time=decimal_year(on)).d)
