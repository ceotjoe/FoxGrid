"""Thinning, averaging and sigma of Kraken bearings (ADR 0010).

The Kraken delivers several bearings per second whose errors are strongly correlated (same
multipath, same heading error). FoxGrid's engine treats bearings as independent, so the bridge sends
few, averaged ones:

* driving: the circular mean over the last ``drive_window_s``, at most every
  ``drive_min_interval_s`` and only ``drive_min_distance_m`` away from the previous bearing,
* parked: the first one after ``park_window_s`` of averaging, then at most every
  ``park_interval_s``.

A gap in the readings (``gap_s``, the squelch closing between two overs) ends the window: it
starts afresh and the interval and distance limits restart, so one bearing never mixes a repeater
user with the interferer and the next over gets its own bearing. Every bearing carries the time span
of its readings (``window_start``/``window_end``), which the backend compares with the
transmissions (ADR 0010, manual gate).

Sigma is the root-sum-square of the spread in the window, the heading part, the mount calibration
residual and an environment preset, clamped to ``sigma_min``..``sigma_max``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from geo import angle_diff_deg, circular_mean_deg, circular_std_deg, distance_m
from heading import PARKED

ENVIRONMENTS = {"open": 3.0, "mixed": 5.0, "urban": 8.0}


@dataclass(frozen=True)
class Sample:
    t: float
    azimuth_true_deg: float
    lat: float
    lon: float
    mode: str  # DRIVING or PARKED
    sigma_heading_deg: float
    confidence: float
    power_db: float


@dataclass(frozen=True)
class Emission:
    t: float  # mean time of the window
    azimuth_true_deg: float
    sigma_deg: float
    lat: float
    lon: float
    mode: str
    samples: int
    confidence: float  # mean
    power_db: float  # mean
    spread_deg: float  # circular std of the window (inliers)
    rejected: int = 0  # readings dropped as outliers
    window_start: float = 0.0  # time of the first and last reading in the window
    window_end: float = 0.0


@dataclass(frozen=True)
class AggregationParams:
    drive_window_s: float = 3.0
    drive_min_interval_s: float = 5.0
    drive_min_distance_m: float = 100.0
    drive_min_samples: int = 3
    park_window_s: float = 10.0
    park_interval_s: float = 60.0
    park_min_samples: int = 10
    gap_s: float = 1.5  # a longer pause between readings starts a new window (new over)
    reject_deg: float = 25.0  # readings this far from the window mean are dropped as outliers
    sigma_doa_min: float = 2.0
    sigma_mount: float = 2.0
    sigma_env: float = ENVIRONMENTS["mixed"]
    sigma_min: float = 5.0
    sigma_max: float = 30.0


def combined_sigma(spread_deg: float, sigma_heading_deg: float, p: AggregationParams) -> float:
    parts = (max(p.sigma_doa_min, spread_deg), sigma_heading_deg, p.sigma_mount, p.sigma_env)
    return min(p.sigma_max, max(p.sigma_min, math.sqrt(sum(x * x for x in parts))))


class Aggregator:
    def __init__(self, params: AggregationParams | None = None) -> None:
        self.p = params or AggregationParams()
        self.last: Emission | None = None
        self._last_at = 0.0  # time of the reading that completed the last emission
        self._samples: list[Sample] = []
        self._mode: str | None = None
        self._mode_since = 0.0
        self._over = 0  # counts gaps; the limits only apply within the same over
        self._last_over = 0

    def reset(self) -> None:
        """Forget the current window, e.g. when the heading became invalid."""
        self._samples.clear()
        self._mode = None

    def add(self, sample: Sample) -> Emission | None:
        p = self.p
        if self._samples and sample.t - self._samples[-1].t > p.gap_s:
            self._samples.clear()
            self._over += 1
            self._mode_since = sample.t  # averaging starts again, like after a mode change
        if sample.mode != self._mode:
            self._samples.clear()
            self._mode = sample.mode
            self._mode_since = sample.t
        parked = sample.mode == PARKED
        window = p.park_window_s if parked else p.drive_window_s
        self._samples.append(sample)
        self._samples = [s for s in self._samples if s.t >= sample.t - window]
        if len(self._samples) < (p.park_min_samples if parked else p.drive_min_samples):
            return None

        lat = sum(s.lat for s in self._samples) / len(self._samples)
        lon = sum(s.lon for s in self._samples) / len(self._samples)
        last = self.last if self._last_over == self._over else None
        since_last = sample.t - self._last_at
        moved = last is None or distance_m(last.lat, last.lon, lat, lon) >= p.drive_min_distance_m
        if parked:
            if sample.t - self._mode_since < p.park_window_s:
                return None
            if (
                last is not None
                and last.mode == PARKED
                and not moved
                and since_last < p.park_interval_s
            ):
                return None
        else:
            if last is not None and (since_last < p.drive_min_interval_s or not moved):
                return None

        emission = self._emit(lat, lon)
        self.last = emission
        self._last_at = sample.t
        self._last_over = self._over
        self._samples.clear()  # the next bearing is built from new readings only
        return emission

    def _emit(self, lat: float, lon: float) -> Emission:
        samples = self._inliers()
        azimuths = [s.azimuth_true_deg for s in samples]
        spread = circular_std_deg(azimuths)
        sigma_heading = max(s.sigma_heading_deg for s in samples)
        n = len(samples)
        return Emission(
            t=sum(s.t for s in samples) / n,
            azimuth_true_deg=circular_mean_deg(azimuths),
            sigma_deg=combined_sigma(spread, sigma_heading, self.p),
            lat=lat,
            lon=lon,
            mode=samples[-1].mode,
            samples=n,
            confidence=sum(s.confidence for s in samples) / n,
            power_db=sum(s.power_db for s in samples) / n,
            spread_deg=spread,
            rejected=len(self._samples) - n,
            window_start=self._samples[0].t,
            window_end=self._samples[-1].t,
        )

    def _inliers(self) -> list[Sample]:
        """Drop single multipath jumps far from the window mean (keep all if too few remain)."""
        samples = self._samples
        mean = circular_mean_deg([s.azimuth_true_deg for s in samples])
        kept = [
            s for s in samples if abs(angle_diff_deg(s.azimuth_true_deg, mean)) <= self.p.reject_deg
        ]
        if len(kept) < max(2, len(samples) // 2):
            return samples
        if len(kept) < len(samples):  # the outliers pulled the first mean; centre again on the rest
            mean = circular_mean_deg([s.azimuth_true_deg for s in kept])
            kept = [
                s
                for s in samples
                if abs(angle_diff_deg(s.azimuth_true_deg, mean)) <= self.p.reject_deg
            ]
        return kept if len(kept) >= max(2, len(samples) // 2) else samples
