# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Mount calibration for a vehicle-mounted KrakenSDR (ADR 0010).

The bridge computes ``true bearing = GNSS course + Kraken DoA + mount offset``. The offset covers
how the array sits on the roof (its 0° mark against the driving direction). This tool finds it:
put a transmitter at a known position (a beacon, a friend with a handheld on a known spot, a
repeater), then drive several straight legs in different directions, at least a few hundred
metres from it. For every reading with a valid driving heading it compares the measured direction
with the geodesic azimuth to the transmitter.

    uv run tools/kraken_bridge/calibrate.py --tx-lat 48.1234 --tx-lon 11.5678 \\
        --freq-mhz 145.500 --duration 900 --save calibration.jsonl

The result is averaged per heading sector (45°), so the direction you drove longest does not
dominate, and the spread between sectors shows whether the car body distorts the pattern (then a
single offset cannot fix everything). Put the printed ``--mount-offset`` into the bridge's
configuration. ``--load`` evaluates a saved recording again; ``--simulate`` drives a simulated
loop with a known offset.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import math
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from geo import angle_diff_deg, circular_mean_deg, circular_std_deg, distance_m, initial_bearing_deg
from heading import DRIVING, Fix, HeadingTracker
from kraken import parse_output, select_vfo

log = logging.getLogger("kraken_calibrate")

SECTOR_DEG = 45.0
MIN_SECTOR_SAMPLES = 20
MIN_SECTORS = 3
REJECT_DEG = 25.0  # readings this far from the result are multipath, not mount offset
MIN_DISTANCE_M = 300.0  # closer, a few metres of GNSS error already shift the azimuth


@dataclass(frozen=True)
class CalSample:
    t: float
    lat: float
    lon: float
    heading_deg: float
    doa_rel_deg: float

    def offset_deg(self, tx: tuple[float, float]) -> float:
        """The mount offset this one reading implies (−180..180)."""
        truth = initial_bearing_deg(self.lat, self.lon, *tx)
        return angle_diff_deg(truth, self.heading_deg + self.doa_rel_deg)


@dataclass(frozen=True)
class SectorResult:
    sector_deg: float  # start of the heading sector
    samples: int
    offset_deg: float


@dataclass(frozen=True)
class CalResult:
    offset_deg: float
    spread_deg: float  # circular std of the kept readings
    sector_spread_deg: float  # largest deviation of a sector from the result
    samples: int
    rejected: int
    sectors: list[SectorResult]
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return not self.warnings


def calibrate(samples: list[CalSample], tx: tuple[float, float]) -> CalResult:
    """Mount offset from readings with a known transmitter position.

    Each heading sector with enough readings gets one vote (its circular mean), then readings far
    from that first result are dropped as multipath and the sectors are averaged again.
    """
    warnings: list[str] = []
    far = [s for s in samples if distance_m(s.lat, s.lon, *tx) >= MIN_DISTANCE_M]
    if len(far) < len(samples):
        warnings.append(
            f"{len(samples) - len(far)} readings closer than {MIN_DISTANCE_M:.0f} m ignored"
        )
    samples = far

    def by_sector(items: list[CalSample]) -> dict[float, list[float]]:
        out: dict[float, list[float]] = {}
        for s in items:
            key = math.floor((s.heading_deg % 360.0) / SECTOR_DEG) * SECTOR_DEG
            out.setdefault(key, []).append(s.offset_deg(tx))
        return out

    def vote(groups: dict[float, list[float]]) -> tuple[float, dict[float, list[float]]]:
        used = {k: v for k, v in groups.items() if len(v) >= MIN_SECTOR_SAMPLES}
        if not used:
            used = groups
        return circular_mean_deg([circular_mean_deg(v) for v in used.values()]), used

    if not samples:
        return CalResult(0.0, 0.0, 0.0, 0, 0, [], [*warnings, "no usable readings"])
    first, _ = vote(by_sector(samples))
    kept = [s for s in samples if abs(angle_diff_deg(s.offset_deg(tx), first)) <= REJECT_DEG]
    if len(kept) < len(samples) // 2:
        kept = samples  # mostly scattered: keep everything rather than pick a cluster
    offset, used = vote(by_sector(kept))
    offset = angle_diff_deg(offset, 0.0)
    sectors = [
        SectorResult(k, len(v), angle_diff_deg(circular_mean_deg(v), 0.0))
        for k, v in sorted(by_sector(kept).items())
    ]
    sector_spread = max(
        (abs(angle_diff_deg(circular_mean_deg(v), offset)) for v in used.values()), default=0.0
    )
    if len(used) < MIN_SECTORS or any(len(v) < MIN_SECTOR_SAMPLES for v in used.values()):
        warnings.append(
            f"only {sum(len(v) >= MIN_SECTOR_SAMPLES for v in used.values())} heading sectors with "
            f"{MIN_SECTOR_SAMPLES}+ readings: drive straight legs in at least {MIN_SECTORS} "
            "directions"
        )
    if sector_spread > 5.0:
        warnings.append(
            f"sectors differ by up to {sector_spread:.1f}°: the car body or a nearby reflector "
            "distorts the pattern; one offset cannot correct that"
        )
    return CalResult(
        offset_deg=offset,
        spread_deg=circular_std_deg([s.offset_deg(tx) for s in kept]),
        sector_spread_deg=sector_spread,
        samples=len(kept),
        rejected=len(samples) - len(kept),
        sectors=sectors,
        warnings=warnings,
    )


class Calibrator:
    """Collects readings with a valid driving heading; fed like the bridge (fixes, Kraken text)."""

    def __init__(
        self, freq_mhz: float | None = None, min_confidence: float = 2.0, max_fix_age_s: float = 2.0
    ) -> None:
        self.tracker = HeadingTracker()
        self.freq_mhz = freq_mhz
        self.min_confidence = min_confidence
        self.max_fix_age_s = max_fix_age_s
        self.samples: list[CalSample] = []
        self._last_ms: int | None = None

    def on_fix(self, fix: Fix) -> None:
        self.tracker.update(fix)

    def on_kraken_output(self, text: str) -> None:
        reading = select_vfo(parse_output(text), self.freq_mhz)
        if reading is None or reading.timestamp_ms == self._last_ms:
            return
        self._last_ms = reading.timestamp_ms
        fix, heading = self.tracker.last_fix, self.tracker.current
        if (
            reading.confidence < self.min_confidence
            or fix is None
            or abs(reading.t - fix.t) > self.max_fix_age_s
            or heading is None
            or heading.mode != DRIVING  # parked headings are frozen guesses
        ):
            return
        self.samples.append(
            CalSample(reading.t, fix.lat, fix.lon, heading.heading_deg, reading.doa_rel_deg)
        )


def report(result: CalResult, tx: tuple[float, float]) -> str:
    lines = [f"transmitter {tx[0]:.5f}, {tx[1]:.5f}", "heading sector   readings   offset"]
    for s in result.sectors:
        lines.append(
            f"{s.sector_deg:5.0f}–{s.sector_deg + SECTOR_DEG:3.0f}°   {s.samples:8d}   "
            f"{s.offset_deg:+6.1f}°"
        )
    lines.append(
        f"\nmount offset {result.offset_deg:+.1f}° (spread {result.spread_deg:.1f}°, "
        f"{result.samples} readings, {result.rejected} dropped as multipath)"
    )
    lines.extend(f"warning: {w}" for w in result.warnings)
    lines.append(f"\nbridge option:  --mount-offset {result.offset_deg:.1f}")
    return "\n".join(lines)


def save(samples: list[CalSample], path: Path) -> None:
    with path.open("w") as f:
        for s in samples:
            f.write(json.dumps(asdict(s)) + "\n")


def load(path: Path) -> list[CalSample]:
    return [CalSample(**json.loads(line)) for line in path.read_text().splitlines() if line.strip()]


def simulate(tx: tuple[float, float], offset_deg: float, seed: int = 3) -> list[CalSample]:
    from geo import destination
    from simulate import CALIBRATION_ROUTE, drive

    start = destination(*tx, 200.0, 1500.0)  # a loop 1.5 km south-west of the transmitter
    cal = Calibrator()
    for step in drive(
        1_800_000_000.0,
        start,
        tx,
        route=CALIBRATION_ROUTE * 2,
        freq_hz=145.5e6,
        mount_offset_deg=offset_deg,
        seed=seed,
    ):
        if step.fix is not None:
            cal.on_fix(step.fix)
        if step.kraken_text is not None:
            cal.on_kraken_output(step.kraken_text)
    return cal.samples


async def record(args: argparse.Namespace, cal: Calibrator) -> None:
    from bridge import poll_kraken, read_gpsd

    tasks = [
        asyncio.create_task(read_gpsd(cal, args.gpsd_host, args.gpsd_port)),  # type: ignore[arg-type]
        asyncio.create_task(poll_kraken(cal, args.kraken_url, args.poll)),  # type: ignore[arg-type]
    ]
    end = time.monotonic() + args.duration
    try:
        while time.monotonic() < end:
            await asyncio.sleep(min(60.0, max(0.0, end - time.monotonic())))
            sectors = {math.floor(s.heading_deg / SECTOR_DEG) for s in cal.samples}
            log.info("%d readings in %d heading sectors", len(cal.samples), len(sectors))
    finally:
        for task in tasks:
            task.cancel()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--tx-lat", type=float, required=True, help="known transmitter latitude")
    ap.add_argument("--tx-lon", type=float, required=True, help="known transmitter longitude")
    ap.add_argument("--freq-mhz", type=float, help="use the Kraken VFO on this frequency")
    ap.add_argument("--duration", type=float, default=900.0, help="recording time (s)")
    ap.add_argument("--min-confidence", type=float, default=2.0)
    ap.add_argument("--kraken-url", default="http://127.0.0.1:8081/DOA_value.html")
    ap.add_argument("--poll", type=float, default=0.2)
    ap.add_argument("--gpsd-host", default="127.0.0.1")
    ap.add_argument("--gpsd-port", type=int, default=2947)
    ap.add_argument("--save", type=Path, help="write the readings as JSON lines")
    ap.add_argument("--load", type=Path, help="evaluate saved readings instead of recording")
    ap.add_argument("--simulate", action="store_true", help="drive a simulated loop")
    ap.add_argument("--sim-offset", type=float, default=7.0, help="true offset in the simulation")
    args = ap.parse_args()
    tx = (args.tx_lat, args.tx_lon)

    if args.load:
        samples = load(args.load)
    elif args.simulate:
        samples = simulate(tx, args.sim_offset)
    else:
        cal = Calibrator(args.freq_mhz, args.min_confidence)
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(record(args, cal))
        samples = cal.samples
    if args.save:
        save(samples, args.save)
    result = calibrate(samples, tx)
    print(report(result, tx))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
