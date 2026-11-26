"""A simulated drive for ``--simulate`` and the tests: GNSS fixes and Kraken output for a hidden
emitter.

The car accelerates east, drives straight, turns north, drives on, brakes and parks. The Kraken
output is generated in its own format (``kraken.parse_output`` reads it back), with DoA noise and
occasional multipath outliers; GNSS course and speed carry a little noise, and while parked the
course is random, as real receivers report it.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterator
from dataclasses import dataclass

from geo import angle_diff_deg, destination, initial_bearing_deg
from heading import Fix

# (duration s, speed at start m/s, speed at end m/s, turn rate deg/s)
DEFAULT_ROUTE = [
    (6.0, 0.0, 12.0, 0.0),  # accelerate eastwards
    (90.0, 12.0, 12.0, 0.0),  # straight east, about 1 km
    (10.0, 8.0, 8.0, -9.0),  # turn left to north
    (40.0, 12.0, 12.0, 0.0),  # straight north
    (6.0, 12.0, 0.0, 0.0),  # brake
    (120.0, 0.0, 0.0, 0.0),  # parked
]


@dataclass(frozen=True)
class SimStep:
    t: float
    fix: Fix | None  # one per second
    kraken_text: str | None  # several per second
    true_azimuth_deg: float


def kraken_line(
    t: float, doa_rel_deg: float, confidence: float, power_db: float, freq_hz: float
) -> str:
    """One VFO line in the Kraken App format, including the 360-value spectrum."""
    head = (
        f"{int(t * 1000)}, {doa_rel_deg % 360.0:.2f}, {confidence:.2f}, {power_db:.1f}, "
        f"{int(freq_hz)}, UCA, 200, "
        "SIM, 0.0, 0.0, 0.0, 0.0, GPS, R, R, R, R"
    )
    spectrum = ", ".join(
        f"{max(0.0, 30.0 - abs(angle_diff_deg(i, doa_rel_deg)) / 3):.2f}" for i in range(360)
    )
    return f"{head}, {spectrum} \n"


def drive(
    start_t: float,
    start: tuple[float, float],
    emitter: tuple[float, float],
    *,
    route: list[tuple[float, float, float, float]] | None = None,
    start_course_deg: float = 90.0,
    freq_hz: float = 145_500_000.0,
    readings_per_s: int = 4,
    doa_noise_deg: float = 3.0,
    outlier_rate: float = 0.03,
    mount_offset_deg: float = 0.0,
    seed: int = 1,
) -> Iterator[SimStep]:
    rng = random.Random(seed)
    lat, lon = start
    course = start_course_deg
    t = start_t
    dt = 1.0 / readings_per_s
    tick = 0
    for duration, v0, v1, turn_rate in route or DEFAULT_ROUTE:
        steps = max(1, round(duration / dt))
        for i in range(steps):
            speed = v0 + (v1 - v0) * (i + 1) / steps
            course = (course + turn_rate * dt) % 360.0
            lat, lon = destination(lat, lon, course, speed * dt)
            t += dt
            tick += 1
            true_az = initial_bearing_deg(lat, lon, *emitter)
            fix = None
            if tick % readings_per_s == 0:
                reported_track = (
                    course + rng.gauss(0, 1.0) if speed >= 0.5 else rng.uniform(0, 360)
                )  # receivers report a random course at standstill
                fix = Fix(t, lat, lon, max(0.0, speed + rng.gauss(0, 0.1)), reported_track % 360.0)
            rel = true_az - course - mount_offset_deg
            rel += (
                rng.uniform(-180, 180)
                if rng.random() < outlier_rate
                else rng.gauss(0, doa_noise_deg)
            )
            text = kraken_line(
                t,
                rel,
                confidence=rng.uniform(3.0, 8.0),
                power_db=rng.uniform(-60, -40),
                freq_hz=freq_hz,
            )
            yield SimStep(t, fix, text, true_az)


def route_duration(route: list[tuple[float, float, float, float]] | None = None) -> float:
    return math.fsum(step[0] for step in route or DEFAULT_ROUTE)
