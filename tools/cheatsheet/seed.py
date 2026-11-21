# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.27", "pyproj>=3.6"]
# ///
"""Seed a demo mission for the cheat-sheet screenshots and leave it live.

Usage:
    uv run tools/cheatsheet/seed.py [--pending]

Creates a mission with a lead (SIM1) and four simulated bearers who have already bearings and
homing readings in, a running transmission, a chat message and a task. Prints JSON with the invite
token and the lead's JWT. With ``--pending`` it only creates an empty mission, so a device that
joins stays on the waiting screen (the lead approves it later through the API).
The default location is a rural area chosen for screenshots, not a real incident.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import uuid
from datetime import UTC, datetime

import httpx
from pyproj import Geod

GEOD = Geod(ellps="WGS84")
TRUTH = (50.45, 9.95)


def offset(lat: float, lon: float, az: float, dist: float) -> tuple[float, float]:
    lon2, lat2, _ = GEOD.fwd(lon, lat, az, dist)
    return lat2, lon2


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--pending", action="store_true")
    ap.add_argument("--name", default="Übung Hochland")
    args = ap.parse_args()
    api = f"{args.base_url.rstrip('/')}/api/v1"
    rng = random.Random(11)

    with httpx.Client(timeout=15) as http:
        r = http.post(
            f"{api}/missions",
            json={
                "name": args.name,
                "frequency_mhz": 145.5,
                "callsign": "DL0LEI",
                "device_secret": f"seed-lead-{uuid.uuid4()}",
            },
        )
        r.raise_for_status()
        created = r.json()
        mid = created["mission"]["id"]
        invite = created["invite_token"]
        lead = {"Authorization": f"Bearer {created['token']}"}
        base = f"{api}/missions/{mid}"
        out = {"mission_id": mid, "invite": invite, "lead_token": created["token"], "api": api}
        if args.pending:
            print(json.dumps(out))
            return

        callsigns = ["DL1ABC", "DL2XYZ", "DL3PEI", "DL4FOX"]
        hdrs = []
        for cs in callsigns:
            j = http.post(
                f"{api}/join",
                json={"invite_token": invite, "callsign": cs, "device_secret": f"seed-{cs}-{uuid.uuid4()}"},
            )
            j.raise_for_status()
            pid = j.json()["participant"]["id"]
            http.patch(
                f"{base}/participants/{pid}", json={"status": "active"}, headers=lead
            ).raise_for_status()
            hdrs.append({"Authorization": f"Bearer {j.json()['token']}"})

        http.post(f"{base}/transmissions/start", headers=lead).raise_for_status()
        for i, h in enumerate(hdrs):
            az = 90.0 * i + rng.uniform(-15, 15) + 20
            lat, lon = offset(*TRUTH, az, rng.uniform(3000, 6500))
            now = datetime.now(UTC).isoformat()
            http.post(
                f"{base}/positions", json=[{"lat": lat, "lon": lon, "recorded_at": now}], headers=h
            ).raise_for_status()
            true_az, _, _ = GEOD.inv(lon, lat, TRUTH[1], TRUTH[0])
            http.post(
                f"{base}/bearings",
                json={
                    "id": str(uuid.uuid4()),
                    "lat": lat,
                    "lon": lon,
                    "azimuth_true_deg": round((true_az + rng.gauss(0, 4)) % 360, 2),
                    "sigma_deg": 10.0,
                    "measured_at": datetime.now(UTC).isoformat(),
                    "note": "",
                },
                headers=h,
            ).raise_for_status()

        batch = []
        for k in range(30):
            frac = k / 29
            lat, lon = offset(*TRUTH, 200 * frac, 4500 * (1 - frac) + 600 * frac)
            dist = max(GEOD.inv(lon, lat, TRUTH[1], TRUTH[0])[2], 1.0)
            level = -20.0 - 30.0 * math.log10(dist) + rng.gauss(0, 3)
            batch.append(
                {
                    "id": str(uuid.uuid4()),
                    "lat": lat,
                    "lon": lon,
                    "rssi_dbm": round(level, 1),
                    "attenuation_db": 0,
                    "measured_at": datetime.now(UTC).isoformat(),
                }
            )
        http.post(f"{base}/rssi", json=batch, headers=hdrs[0]).raise_for_status()
        print(json.dumps(out))


if __name__ == "__main__":
    main()
