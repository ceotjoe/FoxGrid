# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.27", "pyproj>=3.6", "aiomqtt>=2.0"]
# ///
"""Replay a FoxGrid mission with simulated bearers against a running API.

Usage:
    uv run tools/simulator/run.py --base-url http://localhost:8000

The script creates a mission, lets N simulated bearers join, starts a transmission and has
every bearer post a (noisy) bearing towards a hidden emitter. After each bearing it prints how
far the live estimate is from the true position. It exits non-zero if the final error exceeds
``--max-error-m``. Real participants can join the printed invite while it runs.

``--kraken`` instead drives a car with a KrakenSDR past the emitter (ADR 0010). Repeater users
(``--kraken-users``) take turns with the interferer; transmissions are started only for the
interferer's overs, a little late, as a person would. The bearings go through the real bridge code
and MQTT (needs ``docker compose --profile mqtt up -d``), and the script compares the estimate with
the gate on and off.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import random
import sys
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


def second_interferer(
    http: httpx.Client,
    base: str,
    hdr: Callable[[int], dict[str, str]],
    first_truth: tuple[float, float],
    args: argparse.Namespace,
    rng: random.Random,
) -> tuple[float, dict[str, Any] | None]:
    """A second emitter 4 km east of the first: the same bearers take bearings for it.

    Returns the true position and the final estimate of that interferer (None if it got none).
    """
    truth = offset(*first_truth, 90.0, 4000.0)
    created = http.post(
        f"{base}/interferers", json={"id": str(uuid.uuid4()), "name": "Störer B"}, headers=hdr(0)
    )
    created.raise_for_status()
    interferer_id = created.json()["id"]
    print(f"second interferer {interferer_id} at {truth[0]:.5f}, {truth[1]:.5f}")
    for i in range(args.bearers):
        az = (360.0 / args.bearers) * i + rng.uniform(-20, 20)
        lat, lon = offset(*truth, az, rng.uniform(2000, 8000))
        true_az, _, _ = GEOD.inv(lon, lat, truth[1], truth[0])
        payload = {
            "id": str(uuid.uuid4()),
            "lat": lat,
            "lon": lon,
            "azimuth_true_deg": round((true_az + rng.gauss(0, args.noise_deg)) % 360.0, 2),
            "sigma_deg": args.sigma_deg,
            "measured_at": datetime.now(UTC).isoformat(),
            "interferer_id": interferer_id,
            "note": "simulated, interferer B",
        }
        http.post(f"{base}/bearings", json=payload, headers=hdr(i)).raise_for_status()
        time.sleep(args.interval_s)
    deadline = time.monotonic() + 5
    est = None
    while time.monotonic() < deadline:
        e = http.get(f"{base}/estimate?scope=all&interferer={interferer_id}", headers=hdr(0))
        if e.status_code == 200 and e.json()["n_bearings"] == args.bearers:
            est = e.json()
            break
        time.sleep(0.1)
    return truth, est


def _poll(fn: Callable[[], Any], timeout_s: float = 20.0) -> Any:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if (value := fn()) is not None:
            return value
        time.sleep(0.2)
    return None


def kraken_vehicle(
    http: httpx.Client,
    base: str,
    lead: dict[str, str],
    args: argparse.Namespace,
    rng: random.Random,
) -> int:
    """A Kraken car drives towards the emitter while repeater users share the frequency."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "kraken_bridge"))
    from bridge import Bridge, BridgeConfig, flush  # type: ignore[import-not-found]
    from outbox import Outbox  # type: ignore[import-not-found]
    from simulate import (  # type: ignore[import-not-found]
        FOX,
        default_overs,
        drive,
        place_users,
        route_duration,
    )

    truth = (args.lat, args.lon)
    created = http.post(f"{base}/sensors", json={"name": "Kraken Auto"}, headers=lead)
    created.raise_for_status()
    sensor = created.json()
    print(f"sensor {sensor['id']} (gated: {sensor['gated']})")

    start = offset(*truth, 225.0, 2500.0)  # the drive starts 2.5 km south-west
    users = place_users(start, args.kraken_users)
    overs = default_overs(route_duration(), args.kraken_users)
    t0 = time.time() - route_duration() - 30.0  # the whole drive lies in the recent past

    def iso(t: float) -> str:
        return datetime.fromtimestamp(t, UTC).isoformat()

    for over in overs:
        if over.source != FOX:
            continue
        late = rng.uniform(0.0, 3.0)  # the button is pressed a little late
        http.post(
            f"{base}/transmissions/start", json={"at": iso(t0 + over.start_s + late)}, headers=lead
        ).raise_for_status()
        http.post(
            f"{base}/transmissions/stop", json={"at": iso(t0 + over.end_s + 1.0)}, headers=lead
        ).raise_for_status()
    fox = sum(o.source == FOX for o in overs)
    print(f"{fox} interferer overs as transmissions, {len(overs) - fox} overs of repeater users")

    now = [t0]
    config = BridgeConfig(
        mission=str(sensor["topic_prefix"]).split("/")[1],
        sensor=sensor["id"],
        key=sensor["api_key"],
        freq_mhz=433.5,
    )
    outbox = Outbox(":memory:")
    bridge = Bridge(config, outbox, clock=lambda: now[0])
    for step in drive(t0, start, truth, freq_hz=433.5e6, users=users, overs=overs, seed=args.seed):
        now[0] = step.t
        if step.fix is not None:
            bridge.on_fix(step.fix)
        if step.kraken_text is not None:
            bridge.on_kraken_output(step.kraken_text)
    total = bridge.counters.bearings

    async def publish() -> None:
        import aiomqtt

        async with aiomqtt.Client(
            hostname=args.mqtt_host,
            port=args.mqtt_port,
            username=args.mqtt_user,
            password=args.mqtt_password,
        ) as client:
            await flush(outbox, client)

    asyncio.run(publish())
    print(f"bridge sent {total} bearings over MQTT ({args.mqtt_host}:{args.mqtt_port})")

    def count(**params: Any) -> int | None:
        r = http.get(
            f"{base}/bearings", params={"sensors_only": True, "limit": 1, **params}, headers=lead
        )
        return int(r.headers["X-Total-Count"]) if r.status_code == 200 else None

    if _poll(lambda: True if count() == total else None) is None:
        print(
            f"only {count()} of {total} bearings arrived: is the ingest running?", file=sys.stderr
        )
        return 2
    counted, stored = count(state="counted") or 0, count(state="stored") or 0
    print(f"stored {total}: {counted} count (interferer on air), {stored} only stored")

    def estimate(n: int) -> dict[str, Any] | None:
        def get() -> dict[str, Any] | None:
            e = http.get(f"{base}/estimate?scope=all", headers=lead)
            return e.json() if e.status_code == 200 and e.json()["n_bearings"] == n else None

        return _poll(get)  # type: ignore[no-any-return]

    gated = estimate(counted)
    http.patch(f"{base}/sensors/{sensor['id']}", json={"gated": False}, headers=lead)
    ungated = estimate(total)
    http.patch(f"{base}/sensors/{sensor['id']}", json={"gated": True}, headers=lead)
    if gated is None:
        print("no estimate from the counted bearings", file=sys.stderr)
        return 2
    err = error_m((gated["lat"], gated["lon"]), truth)
    print(f"\ngate on  ({counted} bearings): error {err:6.0f} m")
    if ungated is not None:
        err_all = error_m((ungated["lat"], ungated["lon"]), truth)
        print(f"gate off ({total} bearings): error {err_all:6.0f} m (repeater users mixed in)")
    verdict = "OK" if err <= args.max_error_m else "TOO FAR"
    print(f"limit {args.max_error_m:.0f} m: {verdict}")
    return 0 if err <= args.max_error_m else 1


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
    ap.add_argument(
        "--two-interferers",
        action="store_true",
        help="a second emitter 4 km east of the first, tracked as its own interferer",
    )
    ap.add_argument(
        "--kraken",
        action="store_true",
        help="instead of hand bearers: a KrakenSDR car with repeater users (needs MQTT)",
    )
    ap.add_argument("--kraken-users", type=int, default=2, help="repeater users on the frequency")
    ap.add_argument("--mqtt-host", default="localhost")
    ap.add_argument("--mqtt-port", type=int, default=int(os.environ.get("FOXGRID_MQTT_PORT", 1883)))
    ap.add_argument("--mqtt-user", default=os.environ.get("FOXGRID_MQTT_USERNAME", "foxgrid"))
    ap.add_argument(
        "--mqtt-password",
        default=os.environ.get("FOXGRID_MQTT_PASSWORD"),
        help="broker password (default: $FOXGRID_MQTT_PASSWORD)",
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
        if args.kraken:
            return kraken_vehicle(
                http,
                f"{api}/missions/{mission_id}",
                {"Authorization": f"Bearer {tokens[0]}"},
                args,
                rng,
            )
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

        second_ok = True
        if args.two_interferers:
            truth_b, est_b = second_interferer(http, base, hdr, truth, args, rng)
            if est_b is None:
                print("no estimate for the second interferer", file=sys.stderr)
                second_ok = False
            else:
                err_b = error_m((est_b["lat"], est_b["lon"]), truth_b)
                second_ok = err_b <= args.max_error_m
                verdict_b = "OK" if second_ok else "TOO FAR"
                print(f"second interferer: error {err_b:.0f} m ({verdict_b})")

        if args.homing:
            last = homing_walk(http, base, hdr(0), truth, args, rng) or last

        http.post(f"{base}/transmissions/stop", headers=hdr(0)).raise_for_status()
        if last is None:
            print("no estimate produced", file=sys.stderr)
            return 2
        final = error_m((last["lat"], last["lon"]), truth)
        verdict = "OK" if final <= args.max_error_m else "TOO FAR"
        print(f"\nfinal error {final:.0f} m (limit {args.max_error_m:.0f} m): {verdict}")
        if not math.isfinite(final) or final > args.max_error_m or not second_ok:
            return 1
        return 0


if __name__ == "__main__":
    sys.exit(main())
