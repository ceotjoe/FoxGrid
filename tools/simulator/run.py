# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.27", "pyproj>=3.6"]
# ///
"""Replay a FoxGrid mission with simulated bearers against a running API.

Usage:
    uv run tools/simulator/run.py --base-url http://localhost:8000

The script creates a mission, lets N simulated bearers join, starts a transmission and has
every bearer post a (noisy) bearing towards a hidden emitter. After each bearing it prints how
far the live estimate is from the true position. It exits non-zero if the final error exceeds
``--max-error-m``. Real participants can join the printed invite while it runs.
"""

from __future__ import annotations

import argparse
import math
import random
import sys
import time
import uuid
from datetime import UTC, datetime

import httpx
from pyproj import Geod

GEOD = Geod(ellps="WGS84")


def offset(lat: float, lon: float, az_deg: float, dist_m: float) -> tuple[float, float]:
    lon2, lat2, _ = GEOD.fwd(lon, lat, az_deg, dist_m)
    return lat2, lon2


def error_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    return float(GEOD.inv(a[1], a[0], b[1], b[0])[2])


def homing_walk(
    http: httpx.Client,
    base: str,
    headers: dict[str, str],
    truth: tuple[float, float],
    args: argparse.Namespace,
    rng: random.Random,
) -> dict | None:
    """Spiral in on the emitter and log RSSI like a mobile with a handheld would.

    A 20 dB attenuator is switched in when the signal gets strong, and the reading is reduced
    accordingly: the server has to add it back (attenuation_db) for the path loss fit to hold.
    """
    print("\nhoming: mobile closes in, logging signal strength")
    n_total = args.rssi_samples
    batch: list[dict] = []
    last_est: dict | None = None
    sent = 0
    for i in range(n_total):
        frac = i / max(n_total - 1, 1)
        radius = 5000.0 * (1 - frac) + 400.0 * frac
        angle = 270.0 * frac + rng.uniform(-10, 10)
        lat, lon = offset(*truth, angle, radius)
        dist = max(error_m((lat, lon), truth), 1.0)
        level = args.rssi_p0_dbm - 10.0 * args.path_loss_n * math.log10(dist)
        level += rng.gauss(0.0, args.rssi_noise_db)
        attenuation = 20.0 if level > -75.0 else 0.0
        batch.append(
            {
                "id": str(uuid.uuid4()),
                "lat": lat,
                "lon": lon,
                "rssi_dbm": round(level - attenuation, 1),
                "attenuation_db": attenuation,
                "measured_at": datetime.now(UTC).isoformat(),
            }
        )
        if len(batch) == 5 or i == n_total - 1:
            http.post(f"{base}/rssi", json=batch, headers=headers).raise_for_status()
            sent += len(batch)
            batch = []
            est = wait_for_rssi_estimate(http, base, headers, sent)
            if est:
                last_est = est
                fit = est["rssi"]
                print(
                    f"homing {sent:3d}/{n_total} samples: error "
                    f"{error_m((est['lat'], est['lon']), truth):6.0f} m, n={fit['exponent']:.2f}, "
                    f"1s ellipse {est['ellipse_1s']['semi_major_m']:.0f}x"
                    f"{est['ellipse_1s']['semi_minor_m']:.0f} m"
                )
            time.sleep(args.interval_s)
    return last_est


def wait_for_rssi_estimate(
    http: httpx.Client, base: str, headers: dict[str, str], n: int
) -> dict | None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        r = http.get(f"{base}/estimate?scope=all", headers=headers)
        if r.status_code == 200:
            est = r.json()
            if est.get("rssi") and est["rssi"]["n_samples"] == n:
                return est
        time.sleep(0.1)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--bearers", type=int, default=5)
    ap.add_argument("--lat", type=float, default=48.137, help="true emitter latitude")
    ap.add_argument("--lon", type=float, default=11.575, help="true emitter longitude")
    ap.add_argument("--noise-deg", type=float, default=4.0, help="real azimuth noise (1 sigma)")
    ap.add_argument("--sigma-deg", type=float, default=8.0, help="declared sigma per bearing")
    ap.add_argument("--outliers", type=int, default=1, help="number of grossly wrong bearings")
    ap.add_argument("--interval-s", type=float, default=1.0, help="pause between bearings")
    ap.add_argument("--max-error-m", type=float, default=600.0)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--mission-name", default="Simulated hunt")
    ap.add_argument(
        "--homing",
        action="store_true",
        help="after the bearings, a mobile walks a spiral towards the emitter logging RSSI",
    )
    ap.add_argument("--rssi-samples", type=int, default=40)
    ap.add_argument("--rssi-noise-db", type=float, default=3.0, help="fading scatter (1 sigma)")
    ap.add_argument("--path-loss-n", type=float, default=3.0, help="true path loss exponent")
    ap.add_argument("--rssi-p0-dbm", type=float, default=-20.0, help="true level at 1 m")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    truth = (args.lat, args.lon)
    api = f"{args.base_url.rstrip('/')}/api/v1"

    with httpx.Client(timeout=15) as http:
        r = http.post(
            f"{api}/missions",
            json={
                "name": args.mission_name,
                "frequency_mhz": 433.5,
                "callsign": "SIM1",
                "device_secret": "simulator-SIM1-0123456789",
            },
        )
        r.raise_for_status()
        created = r.json()
        mission_id = created["mission"]["id"]
        invite = created["invite_token"]
        tokens = [created["token"]]
        print(f"mission {mission_id}\ninvite  {invite}  (join in the app to watch live)")
        for i in range(2, args.bearers + 1):
            j = http.post(
                f"{api}/join",
                json={
                    "invite_token": invite,
                    "callsign": f"SIM{i}",
                    "device_secret": f"simulator-SIM{i}-0123456789",
                },
            )
            j.raise_for_status()
            tokens.append(j.json()["token"])
            approve = http.patch(  # new joiners wait for the lead's approval
                f"{api}/missions/{mission_id}/participants/{j.json()['participant']['id']}",
                json={"status": "active"},
                headers={"Authorization": f"Bearer {tokens[0]}"},
            )
            approve.raise_for_status()

        def hdr(i: int) -> dict[str, str]:
            return {"Authorization": f"Bearer {tokens[i]}"}

        base = f"{api}/missions/{mission_id}"
        http.post(f"{base}/transmissions/start", headers=hdr(0)).raise_for_status()
        print("transmission started - emitter is on air")

        outlier_idx = set(rng.sample(range(args.bearers), min(args.outliers, args.bearers)))
        last = None
        for i in range(args.bearers):
            # spread bearers around the emitter so the geometry is good
            az = (360.0 / args.bearers) * i + rng.uniform(-20, 20)
            lat, lon = offset(*truth, az, rng.uniform(2000, 8000))
            now = datetime.now(UTC).isoformat()
            http.post(
                f"{base}/positions",
                json=[{"lat": lat, "lon": lon, "recorded_at": now}],
                headers=hdr(i),
            ).raise_for_status()

            true_az, _, _ = GEOD.inv(lon, lat, truth[1], truth[0])
            measured = true_az + rng.gauss(0, args.noise_deg)
            tag = ""
            if i in outlier_idx:
                measured += rng.choice([-1, 1]) * rng.uniform(60, 120)
                tag = "  (gross outlier)"
            payload = {
                "id": str(uuid.uuid4()),
                "lat": lat,
                "lon": lon,
                "azimuth_true_deg": round(measured % 360.0, 2),
                "sigma_deg": args.sigma_deg,
                "measured_at": datetime.now(UTC).isoformat(),
                "note": f"simulated{tag}",
            }
            t0 = time.monotonic()
            http.post(f"{base}/bearings", json=payload, headers=hdr(i)).raise_for_status()

            est = None
            if i >= 1:  # an estimate needs two bearings
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    e = http.get(f"{base}/estimate?scope=all", headers=hdr(0))
                    if e.status_code == 200 and e.json()["n_bearings"] == i + 1:
                        est = e.json()
                        break
                    time.sleep(0.1)
            if est:
                last = est
                err = error_m((est["lat"], est["lon"]), truth)
                print(
                    f"bearing {i + 1}/{args.bearers} SIM{i + 1}{tag}: estimate error "
                    f"{err:7.0f} m, 1s ellipse {est['ellipse_1s']['semi_major_m']:.0f}x"
                    f"{est['ellipse_1s']['semi_minor_m']:.0f} m "
                    f"(update after {time.monotonic() - t0:.2f}s)"
                )
            else:
                print(f"bearing {i + 1}/{args.bearers} SIM{i + 1}{tag}: no estimate yet")
            time.sleep(args.interval_s)

        if args.homing:
            last = homing_walk(http, base, hdr(0), truth, args, rng) or last

        http.post(f"{base}/transmissions/stop", headers=hdr(0)).raise_for_status()
        if last is None:
            print("no estimate produced", file=sys.stderr)
            return 2
        final = error_m((last["lat"], last["lon"]), truth)
        verdict = "OK" if final <= args.max_error_m else "TOO FAR"
        print(f"\nfinal error {final:.0f} m (limit {args.max_error_m:.0f} m): {verdict}")
        if not math.isfinite(final) or final > args.max_error_m:
            return 1
        return 0


if __name__ == "__main__":
    sys.exit(main())
