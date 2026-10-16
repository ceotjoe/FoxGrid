"""Plain data types shared by the engine and its callers."""

from __future__ import annotations

from dataclasses import dataclass, field


class EngineError(ValueError):
    """Raised when the engine cannot produce an estimate from its input."""


@dataclass(frozen=True, slots=True)
class Bearing:
    """One bearing: where it was taken and the true-north azimuth towards the emitter."""

    lat: float
    lon: float
    azimuth_deg: float  # true north, clockwise
    sigma_deg: float  # 1 sigma angular uncertainty, > 0
    measured_at: float | None = None  # POSIX seconds (UTC), used for age weighting
    id: str | None = None


@dataclass(frozen=True, slots=True)
class EngineParams:
    resolution_m: float = 50.0
    margin_m: float = 5000.0
    max_range_m: float = 100_000.0  # farthest emitter distance considered for grid extent
    max_cells: int = 250  # per axis; resolution is coarsened to respect this
    outlier_fraction: float = 0.1  # epsilon of the uniform outlier mixture
    half_life_s: float | None = None  # age weighting; None disables it
    now: float | None = None  # POSIX seconds used as "now" for age weighting
    refine_steps: int = 2
    contour_levels: tuple[float, ...] = (0.5, 0.8, 0.95)  # probability mass; () disables


@dataclass(frozen=True, slots=True)
class EllipseGeometry:
    """Error ellipse of the posterior in local metric coordinates."""

    semi_major_m: float
    semi_minor_m: float
    orientation_deg: float  # azimuth of the major axis, clockwise from north, [0, 180)


@dataclass(frozen=True, slots=True)
class Estimate:
    lat: float
    lon: float
    cov_east_east: float  # m^2
    cov_north_north: float  # m^2
    cov_east_north: float  # m^2
    ellipse_1s: EllipseGeometry
    ellipse_2s: EllipseGeometry
    ellipse_1s_ring: list[tuple[float, float]] = field(default_factory=list)  # (lon, lat)
    ellipse_2s_ring: list[tuple[float, float]] = field(default_factory=list)  # (lon, lat)
    n_bearings: int = 0
    resolution_m: float = 0.0
    grid_cells: tuple[int, int] = (0, 0)
    utm_epsg: int = 0
    # probability mass -> closed rings of (lon, lat); see foxgrid_engine.contours
    contours: dict[float, list[list[tuple[float, float]]]] = field(default_factory=dict)
