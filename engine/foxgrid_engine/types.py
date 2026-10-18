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
class RssiSample:
    """One signal strength reading taken at a known position (homing track)."""

    lat: float
    lon: float
    rssi_dbm: float  # as read from the receiver
    attenuation_db: float = 0.0  # attenuator in front of the receiver; added back before fitting
    measured_at: float | None = None  # POSIX seconds (UTC)
    # Fixed (omnidirectional) stations: all readings of one station share ``group``. Each station
    # gets its own unknown receiver offset (antenna, cable, receiver). ``None`` = the single
    # moving homing device, whose offset is absorbed by the reference level.
    group: str | None = None
    event: str | None = None  # transmission id; one reading per (group, event) is used
    offset_db: float = 0.0  # known receiver offset (calibration), subtracted from the level


@dataclass(frozen=True, slots=True)
class RssiFit:
    """Log-distance path loss ``level = p0 - 10 * n * log10(distance_m)`` at the best point."""

    p0_dbm: float  # extrapolated level at 1 m
    exponent: float  # path loss exponent n
    residual_db: float  # rms residual of the fit
    n_samples: int
    # estimated receiver offset per fixed station (dB, relative to the reference level)
    station_offsets_db: dict[str, float] = field(default_factory=dict)


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
    # RSSI fusion (homing): path loss model with unknown exponent and reference level
    rssi_sigma_db: float = 6.0  # fading/measurement scatter around the model
    rssi_weight: float = 1.0  # scales the RSSI log-likelihood against the bearings
    rssi_exponent_bounds: tuple[float, float] = (1.5, 6.0)
    rssi_min_distance_m: float = 10.0  # distances are floored to keep log10 finite
    rssi_max_samples: int = 300  # only the most recent samples are used
    rssi_min_samples: int = 5  # fewer samples are ignored; needed for an RSSI-only estimate
    # Fixed stations: unknown per-station offset ~ N(0, sigma_b^2); needs enough distinct stations
    rssi_station_sigma_db: float = 6.0
    rssi_omni_min_stations: int = 4


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
    rssi_fit: RssiFit | None = None
    n_rssi: int = 0
    # probability mass -> closed rings of (lon, lat); see foxgrid_engine.contours
    contours: dict[float, list[list[tuple[float, float]]]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Suggestion:
    """A place where one more bearing would shrink the error ellipse the most."""

    lat: float
    lon: float
    expected_reduction: float  # fraction of the 1 sigma ellipse area that disappears, 0..1
    expected_semi_major_m: float
    expected_semi_minor_m: float
    azimuth_to_target_deg: float  # true bearing from here to the current estimate
    distance_to_target_m: float
