# /// script
# requires-python = ">=3.12"
# dependencies = ["aiomqtt>=2.0", "pyproj>=3.6"]
# ///
"""Example client for an automatic bearing station (and a template for your own hardware).

It publishes a heartbeat and bearings to the FoxGrid MQTT ingest (docs/reference/mqtt.md). A real station
would read its azimuth from a Doppler unit or a rotating antenna; here it either points at a
hidden emitter with some noise (``--truth``) or sends a fixed ``--azimuth``.

    uv run tools/sensor_client/station.py --mission <id> --sensor <id> --key fgs_... \\
        --lat 48.10 --lon 11.50 --truth 48.137 11.575 --count 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import uuid
from datetime import UTC, datetime

from pyproj import Geod

GEOD = Geod(ellps="WGS84")


def true_azimuth(lat: float, lon: float, target: tuple[float, float]) -> float:
    az, _, _ = GEOD.inv(lon, lat, target[1], target[0])
    return float(az % 360.0)


def build_bearing(
    key: str,
    azimuth_deg: float,
    sigma_deg: float,
    *,
    lat: float | None = None,
    lon: float | None = None,
    rssi_dbm: float | None = None,
    at: datetime | None = None,
    message_id: uuid.UUID | None = None,
) -> dict[str, object]:
    """One bearing message. Without lat/lon the registered fixed position is used."""
    msg: dict[str, object] = {
        "key": key,
        "id": str(message_id or uuid.uuid4()),  # keep it stable when you retry a send
        "azimuth_true_deg": round(azimuth_deg % 360.0, 2),
        "sigma_deg": sigma_deg,
        "measured_at": (at or datetime.now(UTC)).isoformat(),
    }
    if lat is not None and lon is not None:
        msg.update(lat=lat, lon=lon)
    if rssi_dbm is not None:
        msg["rssi_dbm"] = rssi_dbm
    return msg


async def main_async(args: argparse.Namespace) -> None:
    import aiomqtt

    prefix = f"foxgrid/{args.mission}/{args.sensor}"
    rng = random.Random(args.seed)
    async with aiomqtt.Client(
        hostname=args.broker, port=args.port, username=args.user, password=args.password
    ) as client:
        await client.publish(f"{prefix}/status", json.dumps({"key": args.key}), qos=1)
        for i in range(args.count):
            if args.truth:
                azimuth = true_azimuth(args.lat, args.lon, tuple(args.truth)) + rng.gauss(0, args.noise)
            else:
                azimuth = args.azimuth
            msg = build_bearing(args.key, azimuth, args.sigma, lat=args.lat, lon=args.lon)
            await client.publish(f"{prefix}/bearing", json.dumps(msg), qos=1)
            print(f"bearing {i + 1}/{args.count}: {msg['azimuth_true_deg']} deg (sigma {args.sigma})")
            await asyncio.sleep(args.interval)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--user")
    ap.add_argument("--password")
    ap.add_argument("--mission", required=True)
    ap.add_argument("--sensor", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--lat", type=float, help="omit to use the position registered for the sensor")
    ap.add_argument("--lon", type=float)
    ap.add_argument("--truth", type=float, nargs=2, metavar=("LAT", "LON"), help="point at this emitter")
    ap.add_argument("--azimuth", type=float, default=0.0, help="fixed true azimuth without --truth")
    ap.add_argument("--noise", type=float, default=3.0, help="azimuth noise with --truth (deg)")
    ap.add_argument("--sigma", type=float, default=8.0, help="declared sigma (deg)")
    ap.add_argument("--count", type=int, default=5)
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--seed", type=int, default=1)
    return ap


def main() -> None:
    args = build_parser().parse_args()
    if args.truth and (args.lat is None or args.lon is None):
        raise SystemExit("--truth needs --lat and --lon")
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
