# /// script
# requires-python = ">=3.12"
# dependencies = ["aiomqtt>=2.0"]
# ///
"""KrakenSDR bridge: a vehicle-mounted KrakenSDR as a mobile FoxGrid bearing station (ADR 0010).

Runs on the Kraken's Raspberry Pi next to the DSP software and reads

* the DoA result in the "Kraken App" format (``http://127.0.0.1:8081/DOA_value.html``), with the
  heading in the Kraken set to fixed 0°, so the value is relative to the array,
* position, speed and course from gpsd (``127.0.0.1:2947``).

It turns the relative DoA into a true bearing (GNSS course + DoA + mount offset), drops readings
without a signal or a usable heading, averages and thins them, and sends them to the FoxGrid MQTT
ingest (docs/reference/mqtt.md) through a persistent outbox. A heartbeat carries the vehicle
position.

    uv run tools/kraken_bridge/bridge.py --broker foxgrid.example.org --port 8883 --tls \\
        --user foxgrid --password ... --mission <id> --sensor <id> --key fgs_... \\
        --freq-mhz 145.500 --mount-offset 0 --environment mixed

``--simulate`` drives a simulated car past a hidden emitter instead of reading hardware;
``--dry-run`` prints the messages instead of sending them.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import ssl
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from aggregate import ENVIRONMENTS, AggregationParams, Aggregator, Emission, Sample
from heading import DRIVING, Fix, HeadingParams, HeadingTracker
from kraken import Reading, parse_output, select_vfo
from outbox import Outbox

log = logging.getLogger("kraken_bridge")

MODE_LABEL = {DRIVING: "fahrend", "parked": "stehend"}


@dataclass
class BridgeConfig:
    mission: str
    sensor: str
    key: str
    freq_mhz: float | None = None  # pick this VFO; without it the first line is used
    mount_offset_deg: float = 0.0  # added to the Kraken DoA (calibrated on a known transmitter)
    environment: str = "mixed"
    min_confidence: float = 2.0  # dB, peak-to-average of the DoA spectrum
    min_power_db: float | None = None  # uncalibrated; off by default
    max_fix_age_s: float = 2.0  # reading and GNSS fix must be this close in time
    max_reading_age_s: float = 5.0  # older readings (e.g. the file after a restart) are ignored
    polarization: str = "unknown"
    interferer: str | None = None  # interferer id; else the sensor default applies
    gap_s: float = 1.5  # a pause in the readings longer than this starts a new window
    heading: HeadingParams = field(default_factory=HeadingParams)
    aggregation: AggregationParams | None = None

    @property
    def prefix(self) -> str:
        return f"foxgrid/{self.mission}/{self.sensor}"


@dataclass
class Counters:
    readings: int = 0
    duplicate: int = 0
    no_vfo: int = 0
    not_uca: int = 0
    stale: int = 0
    weak: int = 0
    no_fix: int = 0
    no_heading: int = 0
    used: int = 0
    bearings: int = 0


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat()


def parse_tpv(line: str | bytes) -> Fix | None:
    """A gpsd TPV report with a 2D/3D fix, or ``None``."""
    try:
        doc = json.loads(line)
    except ValueError:
        return None
    if not isinstance(doc, dict) or doc.get("class") != "TPV" or int(doc.get("mode", 0)) < 2:
        return None
    try:
        t = datetime.fromisoformat(str(doc["time"])).timestamp()
        lat, lon = float(doc["lat"]), float(doc["lon"])
        speed = float(doc["speed"])
    except (KeyError, TypeError, ValueError):
        return None
    track = doc.get("track")
    return Fix(t, lat, lon, speed, float(track) if isinstance(track, (int, float)) else None)


class Bridge:
    """Pure processing: fixes and Kraken output in, bearing messages into the outbox."""

    def __init__(
        self,
        config: BridgeConfig,
        outbox: Outbox,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.config = config
        self.outbox = outbox
        self.clock = clock
        self.tracker = HeadingTracker(config.heading)
        params = config.aggregation or AggregationParams(
            sigma_env=ENVIRONMENTS[config.environment], gap_s=config.gap_s
        )
        self.aggregator = Aggregator(params)
        self.counters = Counters()
        self._last_timestamp_ms: int | None = None
        self._warned: set[str] = set()

    def _warn_once(self, code: str, message: str, *args: object) -> None:
        if code not in self._warned:
            self._warned.add(code)
            log.warning(message, *args)

    def on_fix(self, fix: Fix) -> None:
        self.tracker.update(fix)

    def on_kraken_output(self, text: str) -> Emission | None:
        readings = parse_output(text)
        reading = select_vfo(readings, self.config.freq_mhz)
        if reading is None:
            if readings:
                self.counters.no_vfo += 1
                self._warn_once(
                    "vfo",
                    "no Kraken VFO near %.4f MHz (have %s): "
                    "check the Kraken frequency against the mission",
                    self.config.freq_mhz or 0.0,
                    ", ".join(f"{r.freq_hz / 1e6:.4f}" for r in readings),
                )
            return None
        if reading.timestamp_ms == self._last_timestamp_ms:
            self.counters.duplicate += 1  # the file keeps its content while the squelch is closed
            return None
        self._last_timestamp_ms = reading.timestamp_ms
        self.counters.readings += 1
        return self.on_reading(reading)

    def on_reading(self, reading: Reading) -> Emission | None:
        c, cfg = self.counters, self.config
        if reading.array.upper() != "UCA":
            c.not_uca += 1
            self._warn_once(
                "uca", "Kraken reports array %r: only UCA gives unambiguous bearings", reading.array
            )
            return None
        if abs(self.clock() - reading.t) > cfg.max_reading_age_s:
            c.stale += 1
            return None
        if reading.confidence < cfg.min_confidence or (
            cfg.min_power_db is not None and reading.power_db < cfg.min_power_db
        ):
            c.weak += 1
            return None
        fix = self.tracker.last_fix
        if fix is None or abs(reading.t - fix.t) > cfg.max_fix_age_s:
            c.no_fix += 1
            if fix is not None:
                self._warn_once(
                    "clock",
                    "Kraken time and GNSS time differ by %.1f s: "
                    "sync the Pi clock to GNSS (chrony + gpsd)",
                    reading.t - fix.t,
                )
            return None
        heading = self.tracker.current
        if heading is None:
            c.no_heading += 1
            self.aggregator.reset()
            return None
        c.used += 1
        azimuth = (heading.heading_deg + reading.doa_rel_deg + cfg.mount_offset_deg) % 360.0
        emission = self.aggregator.add(
            Sample(
                t=reading.t,
                azimuth_true_deg=azimuth,
                lat=fix.lat,
                lon=fix.lon,
                mode=heading.mode,
                sigma_heading_deg=heading.sigma_deg,
                confidence=reading.confidence,
                power_db=reading.power_db,
            )
        )
        if emission is not None:
            c.bearings += 1
            message = self.bearing_message(emission, certain=heading.certain)
            self.outbox.enqueue(str(message["id"]), f"{cfg.prefix}/bearing", message)
            log.info(
                "bearing %.1f° ±%.1f° (%s, %d readings)",
                emission.azimuth_true_deg,
                emission.sigma_deg,
                emission.mode,
                emission.samples,
            )
        return emission

    def bearing_message(self, e: Emission, *, certain: bool = True) -> dict[str, Any]:
        note = (
            f"KrakenSDR {MODE_LABEL.get(e.mode, e.mode)}"
            f"{'' if certain else ', Fahrtrichtung unsicher'}: {e.samples} Werte"
            f"{f' ({e.rejected} verworfen)' if e.rejected else ''}, "
            f"Streuung {e.spread_deg:.1f}°, Konfidenz {e.confidence:.1f} dB, "
            f"Pegel {e.power_db:.1f} dB"
        )
        message: dict[str, Any] = {
            "key": self.config.key,
            "id": str(uuid.uuid4()),  # stored with the message, so retries keep it
            "azimuth_true_deg": round(e.azimuth_true_deg, 2),
            "sigma_deg": round(e.sigma_deg, 1),
            "measured_at": iso(e.t),
            "window_start": iso(e.window_start),
            "window_end": iso(e.window_end),
            "lat": round(e.lat, 7),
            "lon": round(e.lon, 7),
            "polarization": self.config.polarization,
            "note": note,
        }
        if self.config.interferer:
            message["interferer"] = self.config.interferer
        return message

    def status_message(self) -> dict[str, Any]:
        """Heartbeat; with a fresh fix also the vehicle position, which becomes its track."""
        message: dict[str, Any] = {"key": self.config.key}
        fix = self.tracker.last_fix
        if fix is not None and self.clock() - fix.t <= 10.0:
            message.update(
                lat=round(fix.lat, 7),
                lon=round(fix.lon, 7),
                speed=round(min(fix.speed_mps, 100.0), 1),
                at=iso(fix.t),
            )
            heading = self.tracker.current
            if heading is not None:
                message["heading"] = round(heading.heading_deg, 1)
        return message


# ---------------------------------------------------------------------------------------------- I/O


class MqttLike(Protocol):
    async def publish(self, topic: str, payload: str, qos: int = ...) -> Any: ...


async def flush(outbox: Outbox, client: MqttLike) -> int:
    """Send everything pending, oldest first; an item is removed once the broker acknowledged it."""
    sent = 0
    while items := outbox.pending():
        for item in items:
            await client.publish(item.topic, item.payload, qos=1)
            outbox.done(item.id)
            sent += 1
    return sent


async def read_gpsd(bridge: Bridge, host: str, port: int) -> None:
    backoff = 1.0
    while True:
        try:
            reader, writer = await asyncio.open_connection(host, port)
            writer.write(b'?WATCH={"enable":true,"json":true}\n')
            await writer.drain()
            log.info("connected to gpsd at %s:%d", host, port)
            backoff = 1.0
            while line := await reader.readline():
                fix = parse_tpv(line)
                if fix is not None:
                    bridge.on_fix(fix)
            writer.close()
        except OSError as exc:
            log.warning("gpsd: %s; retrying in %.0f s", exc, backoff)
        await asyncio.sleep(backoff)
        backoff = min(30.0, backoff * 2)


def _fetch(url: str) -> str:
    import urllib.request

    with urllib.request.urlopen(url, timeout=2.0) as response:  # only the local Kraken
        return str(response.read().decode("utf-8", errors="replace"))


async def poll_kraken(bridge: Bridge, url: str, interval_s: float) -> None:
    failing = False
    while True:
        try:
            text = await asyncio.to_thread(_fetch, url)
            if failing:
                log.info("Kraken output reachable again")
            failing = False
            bridge.on_kraken_output(text)
        except OSError as exc:
            if not failing:
                log.warning("Kraken output %s not reachable: %s", url, exc)
            failing = True
        await asyncio.sleep(interval_s)


async def send_loop(bridge: Bridge, outbox: Outbox, args: argparse.Namespace) -> None:
    import aiomqtt

    tls = ssl.create_default_context() if args.tls else None
    backoff = 1.0
    while True:
        try:
            async with aiomqtt.Client(
                hostname=args.broker,
                port=args.port,
                username=args.user,
                password=args.password,
                tls_context=tls,
                identifier=f"foxgrid-kraken-{args.sensor}",
            ) as client:
                log.info(
                    "connected to %s:%d, %d messages pending", args.broker, args.port, len(outbox)
                )
                backoff = 1.0
                last_heartbeat = 0.0
                while True:
                    if time.monotonic() - last_heartbeat >= args.heartbeat:
                        await client.publish(
                            f"{bridge.config.prefix}/status",
                            json.dumps(bridge.status_message()),
                            qos=1,
                        )
                        last_heartbeat = time.monotonic()
                    await flush(outbox, client)
                    await asyncio.sleep(0.5)
        except aiomqtt.MqttError as exc:
            log.warning(
                "MQTT: %s; %d messages pending, retrying in %.0f s", exc, len(outbox), backoff
            )
        await asyncio.sleep(backoff)
        backoff = min(60.0, backoff * 2)


async def report_counters(bridge: Bridge, every_s: float = 60.0) -> None:
    while True:
        await asyncio.sleep(every_s)
        log.info("counters: %s", bridge.counters)


def make_config(args: argparse.Namespace) -> BridgeConfig:
    return BridgeConfig(
        mission=args.mission,
        sensor=args.sensor,
        key=args.key,
        freq_mhz=args.freq_mhz,
        mount_offset_deg=args.mount_offset,
        environment=args.environment,
        min_confidence=args.min_confidence,
        min_power_db=args.min_power,
        polarization=args.polarization,
        interferer=args.interferer,
        gap_s=args.gap,
    )


class PrintClient:
    async def publish(self, topic: str, payload: str, qos: int = 1) -> None:
        print(topic, payload, flush=True)


async def print_loop(outbox: Outbox) -> None:
    while True:
        await flush(outbox, PrintClient())
        await asyncio.sleep(0.5)


async def run_live(args: argparse.Namespace) -> None:
    outbox = Outbox(":memory:" if args.dry_run else args.outbox)
    bridge = Bridge(make_config(args), outbox)
    await asyncio.gather(
        read_gpsd(bridge, args.gpsd_host, args.gpsd_port),
        poll_kraken(bridge, args.kraken_url, args.poll),
        report_counters(bridge),
        print_loop(outbox) if args.dry_run else send_loop(bridge, outbox, args),
    )


async def run_simulation(args: argparse.Namespace) -> None:
    from simulate import drive, route_duration

    start = (args.sim_lat, args.sim_lon)
    emitter = (args.sim_lat + 0.015, args.sim_lon + 0.012)  # about 2 km north-east
    t0 = time.time() - route_duration() - 5.0  # the whole drive lies in the recent past
    now = [t0]
    outbox = Outbox(":memory:")
    bridge = Bridge(make_config(args), outbox, clock=lambda: now[0])
    for step in drive(t0, start, emitter, freq_hz=(args.freq_mhz or 145.5) * 1e6):
        now[0] = step.t
        if step.fix is not None:
            bridge.on_fix(step.fix)
        if step.kraken_text is not None:
            bridge.on_kraken_output(step.kraken_text)
    log.info("simulated emitter at %.5f, %.5f; %s", *emitter, bridge.counters)
    if args.dry_run:
        await flush(outbox, PrintClient())
        return
    import aiomqtt

    async with aiomqtt.Client(
        hostname=args.broker,
        port=args.port,
        username=args.user,
        password=args.password,
        tls_context=ssl.create_default_context() if args.tls else None,
    ) as client:
        await client.publish(f"{bridge.config.prefix}/status", json.dumps({"key": args.key}), qos=1)
        log.info("sent %d bearings", await flush(outbox, client))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    mqtt = ap.add_argument_group("FoxGrid MQTT")
    mqtt.add_argument("--broker", default="localhost")
    mqtt.add_argument("--port", type=int, default=1883)
    mqtt.add_argument(
        "--tls", action="store_true", help="TLS to the broker (required over the internet)"
    )
    mqtt.add_argument("--user")
    mqtt.add_argument("--password")
    mqtt.add_argument("--mission", required=True)
    mqtt.add_argument(
        "--sensor", required=True, help="id of the sensor registered with kind=station"
    )
    mqtt.add_argument("--key", required=True, help="the sensor's API key (fgs_...)")
    mqtt.add_argument(
        "--heartbeat", type=float, default=10.0, help="seconds between heartbeats with position"
    )
    mqtt.add_argument("--interferer", help="interferer id for every bearing (else sensor default)")
    mqtt.add_argument("--outbox", default="kraken_outbox.sqlite", help="persistent message queue")
    src = ap.add_argument_group("Inputs")
    src.add_argument("--kraken-url", default="http://127.0.0.1:8081/DOA_value.html")
    src.add_argument("--poll", type=float, default=0.2, help="Kraken poll interval (s)")
    src.add_argument("--gpsd-host", default="127.0.0.1")
    src.add_argument("--gpsd-port", type=int, default=2947)
    df = ap.add_argument_group("Bearings")
    df.add_argument("--freq-mhz", type=float, help="use the Kraken VFO on this frequency")
    df.add_argument(
        "--mount-offset", type=float, default=0.0, help="degrees added to the Kraken DoA"
    )
    df.add_argument(
        "--environment",
        choices=sorted(ENVIRONMENTS),
        default="mixed",
        help="multipath preset for sigma",
    )
    df.add_argument(
        "--min-confidence", type=float, default=2.0, help="minimum Kraken confidence (dB)"
    )
    df.add_argument("--min-power", type=float, help="minimum Kraken power (dB, uncalibrated)")
    df.add_argument(
        "--gap",
        type=float,
        default=1.5,
        help="pause in the readings (s) that ends a window, e.g. the squelch between two overs",
    )
    df.add_argument("--polarization", choices=["h", "v", "unknown"], default="unknown")
    sim = ap.add_argument_group("Simulation")
    sim.add_argument(
        "--simulate", action="store_true", help="drive a simulated car past a hidden emitter"
    )
    sim.add_argument("--sim-lat", type=float, default=48.10)
    sim.add_argument("--sim-lon", type=float, default=11.50)
    ap.add_argument("--dry-run", action="store_true", help="print messages instead of sending them")
    return ap


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_parser().parse_args()
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run_simulation(args) if args.simulate else run_live(args))


if __name__ == "__main__":
    main()
