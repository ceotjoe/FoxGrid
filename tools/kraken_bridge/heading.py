"""Vehicle heading from GNSS course over ground, frozen while parked (ADR 0010).

GNSS course is true north and only meaningful while the vehicle moves. The tracker therefore

* accepts the course as heading once the vehicle has driven straight (course change below
  ``straight_max_change_deg``) at ``driving_speed`` or more for ``straight_window_s``,
* freezes the last valid heading when the vehicle stops. Ordinary braking keeps it valid, but
  turning or more than ``manoeuvre_grace_s`` at manoeuvring speed since the last valid heading makes
  it "uncertain" (a much larger sigma),
* yields no heading while manoeuvring or turning.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from geo import angle_diff_deg, circular_mean_deg

DRIVING = "driving"
PARKED = "parked"


@dataclass(frozen=True)
class Fix:
    t: float  # POSIX seconds (GNSS time)
    lat: float
    lon: float
    speed_mps: float
    track_deg: float | None  # course over ground, true north


@dataclass(frozen=True)
class Heading:
    heading_deg: float  # true north
    sigma_deg: float  # heading part of the bearing's sigma
    mode: str  # DRIVING or PARKED
    certain: bool = True


@dataclass(frozen=True)
class HeadingParams:
    stop_speed: float = 0.5  # m/s, below: parked
    driving_speed: float = 2.0  # m/s, at or above: driving (the Kraken software uses 2 m/s as well)
    fast_speed: float = 5.0  # m/s, at or above: the course is very steady
    straight_window_s: float = 5.0
    straight_max_change_deg: float = 10.0
    manoeuvre_grace_s: float = (
        10.0  # slow time after the last valid heading that still counts as braking
    )
    max_fix_gap_s: float = 3.0  # a longer gap breaks the "driven straight for ..." history
    sigma_fast: float = 2.0
    sigma_slow: float = 4.0
    sigma_parked: float = 3.0
    sigma_parked_uncertain: float = 12.0


class HeadingTracker:
    def __init__(self, params: HeadingParams | None = None) -> None:
        self.p = params or HeadingParams()
        self.current: Heading | None = None
        self.last_fix: Fix | None = None
        self._history: deque[tuple[float, float]] = deque()
        self._drive_since: float | None = None
        self._frozen: float | None = None
        self._frozen_valid = False
        self._slow_time = 0.0

    def update(self, fix: Fix) -> Heading | None:
        p = self.p
        dt = 0.0
        if self.last_fix is not None:
            dt = fix.t - self.last_fix.t
            if dt < 0:
                return self.current  # out of order, ignore
            if dt > p.max_fix_gap_s:
                self._history.clear()
                self._drive_since = None
                dt = 0.0
        self.last_fix = fix

        if fix.speed_mps >= p.driving_speed and fix.track_deg is not None:
            if self._drive_since is None:
                self._drive_since = fix.t
            self._history.append((fix.t, fix.track_deg % 360.0))
            while self._history and self._history[0][0] < fix.t - p.straight_window_s:
                self._history.popleft()
            if fix.t - self._drive_since >= p.straight_window_s and self._is_straight():
                self._frozen = fix.track_deg % 360.0
                self._frozen_valid = True
                self._slow_time = 0.0
                sigma = p.sigma_fast if fix.speed_mps >= p.fast_speed else p.sigma_slow
                self.current = Heading(self._frozen, sigma, DRIVING)
            else:
                # Starting off or turning: the course does not describe a steady heading.
                self._frozen_valid = False
                self.current = None
            return self.current

        self._history.clear()
        self._drive_since = None
        if fix.speed_mps < p.stop_speed:
            if self._frozen is None:
                self.current = None
            elif self._frozen_valid and self._slow_time <= p.manoeuvre_grace_s:
                self.current = Heading(self._frozen, p.sigma_parked, PARKED)
            else:
                self.current = Heading(
                    self._frozen, p.sigma_parked_uncertain, PARKED, certain=False
                )
        else:
            self._slow_time += dt  # manoeuvring
            self.current = None
        return self.current

    def _is_straight(self) -> bool:
        tracks = [track for _, track in self._history]
        mean = circular_mean_deg(tracks)
        return (
            max(abs(angle_diff_deg(t, mean)) for t in tracks) * 2 < self.p.straight_max_change_deg
        )
