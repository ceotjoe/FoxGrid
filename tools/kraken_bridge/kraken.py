"""Parser for the KrakenSDR DSP software's "Kraken App" output.

The DSP software (https://github.com/krakenrf/krakensdr_doa) rewrites ``_share/DOA_value.html``
after every processed frame with a valid result and serves it on
``http://<pi>:8081/DOA_value.html``. With the data format "Kraken App" it holds one CSV line per
VFO::

    timestamp_ms, doa_deg, confidence, power_db, freq_hz, array, latency_ms, station_id,
    lat, lon, heading, heading, GPS, R, R, R, R, spectrum_0, ..., spectrum_359

``doa_deg`` is already ``360 - theta``: clockwise relative to the array, **without** the heading.
``confidence`` is the peak-to-average ratio of the DoA spectrum in dB; ``power_db`` is uncalibrated.
Format checked against krakensdr_doa commit 2e1c4e6 (December 2025).

While the squelch is closed the file keeps its last content, so a reading must be used only once
(see ``Reading.timestamp_ms``).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

log = logging.getLogger("kraken_bridge.kraken")

MIN_FIELDS = 8  # up to station_id; GPS fields and spectrum are not needed


@dataclass(frozen=True)
class Reading:
    timestamp_ms: int
    doa_rel_deg: float  # clockwise relative to the array's reference direction
    confidence: float
    power_db: float
    freq_hz: float
    array: str  # "UCA" or "ULA"
    station_id: str

    @property
    def t(self) -> float:
        """POSIX seconds."""
        return self.timestamp_ms / 1000.0


def parse_line(line: str) -> Reading | None:
    """One VFO line, or ``None`` if it is not a valid one."""
    fields = [f.strip() for f in line.split(",")]
    if len(fields) < MIN_FIELDS:
        return None
    try:
        reading = Reading(
            timestamp_ms=int(float(fields[0])),
            doa_rel_deg=float(fields[1]) % 360.0,
            confidence=float(fields[2]),
            power_db=float(fields[3]),
            freq_hz=float(fields[4]),
            array=fields[5],
            station_id=fields[7],
        )
    except ValueError:
        return None
    if not all(
        math.isfinite(v)
        for v in (reading.doa_rel_deg, reading.confidence, reading.power_db, reading.freq_hz)
    ):
        return None
    if reading.timestamp_ms <= 0:
        return None
    return reading


def parse_output(text: str) -> list[Reading]:
    """All VFO lines of one ``DOA_value.html``; malformed lines are skipped."""
    readings = []
    for line in text.splitlines():
        if not line.strip():
            continue
        reading = parse_line(line)
        if reading is None:
            log.debug("skipping malformed Kraken line: %.80r", line)
        else:
            readings.append(reading)
    return readings


def select_vfo(
    readings: list[Reading], freq_mhz: float | None, tolerance_mhz: float = 0.05
) -> Reading | None:
    """The line for ``freq_mhz`` (closest within tolerance), or the first one without frequency."""
    if not readings:
        return None
    if freq_mhz is None:
        return readings[0]
    best = min(readings, key=lambda r: abs(r.freq_hz / 1e6 - freq_mhz))
    if abs(best.freq_hz / 1e6 - freq_mhz) > tolerance_mhz:
        return None
    return best
