# /// script
# requires-python = ">=3.12"
# dependencies = ["foxgrid-engine", "numpy>=1.26"]
#
# [tool.uv.sources]
# foxgrid-engine = { path = "../../engine" }
# ///
"""Offline accuracy study for fixed omnidirectional stations (S-meter readings only).

Usage:
    uv run tools/simulator/omni_eval.py [--trials 40] [--stations 4 6 8 12]

Simulates an interferer heard on the repeater input by N fixed stations with different receiver
offsets, S-meter steps of 6 dB and fading, and prints how far the engine's estimate is from the
truth (median / 90th percentile) and the 2 sigma ellipse size. No API or database needed.
"""

from __future__ import annotations

import argparse
import math

import numpy as np
from foxgrid_engine import EngineParams, RssiSample, estimate
from pyproj import Geod

GEOD = Geod(ellps="WGS84")
ORIGIN = (48.137, 11.575)
P0, EXPONENT = -20.0, 3.0  # dBm at 1 m, path loss exponent


def offset(lat: float, lon: float, east_m: float, north_m: float) -> tuple[float, float]:
    az = math.degrees(math.atan2(east_m, north_m))
    lon2, lat2, _ = GEOD.fwd(lon, lat, az, math.hypot(east_m, north_m))
    return lat2, lon2


def dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return float(GEOD.inv(a[1], a[0], b[1], b[0])[2])


def trial(
    rng: np.random.Generator, n: int, offset_sigma: float, fading: float
) -> tuple[float, float]:
    emitter = offset(*ORIGIN, rng.uniform(-2000, 2000), rng.uniform(-2000, 2000))
    samples = []
    for k in range(n):
        ang, r = rng.uniform(0, 2 * math.pi), rng.uniform(2000.0, 15000.0)
        pos = offset(*emitter, r * math.sin(ang), r * math.cos(ang))
        level = (
            P0
            + rng.normal(0, offset_sigma)  # antenna / cable / receiver
            - 10 * EXPONENT * math.log10(dist(pos, emitter))
            + rng.normal(0, fading)
        )
        s_units = round((level + 93.0) / 6.0)  # IARU VHF: S9 = -93 dBm, 6 dB per S unit
        samples.append(RssiSample(*pos, rssi_dbm=-93.0 + 6.0 * s_units, group=f"st{k}", event="tx"))
    est = estimate([], EngineParams(max_cells=250), rssi=samples)
    return dist((est.lat, est.lon), emitter), est.ellipse_2s.semi_major_m


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--trials", type=int, default=40)
    ap.add_argument("--stations", type=int, nargs="+", default=[4, 6, 8, 12])
    ap.add_argument(
        "--offset-sigma", type=float, default=4.0, help="true station offset spread, dB"
    )
    ap.add_argument("--fading", type=float, default=4.0, help="fading scatter, dB")
    args = ap.parse_args()
    rng = np.random.default_rng(1)
    print(
        f"offsets {args.offset_sigma} dB, fading {args.fading} dB, S steps of 6 dB, {args.trials} trials"
    )
    print("stations  median err   p90 err   median 2s-ellipse")
    for n in args.stations:
        res = np.array([trial(rng, n, args.offset_sigma, args.fading) for _ in range(args.trials)])
        print(
            f"{n:8d}  {np.median(res[:, 0]):8.0f} m  {np.percentile(res[:, 0], 90):7.0f} m"
            f"  {np.median(res[:, 1]):9.0f} m"
        )


if __name__ == "__main__":
    main()
