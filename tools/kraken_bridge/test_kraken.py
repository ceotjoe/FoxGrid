from __future__ import annotations

from geo import (
    angle_diff_deg,
    circular_mean_deg,
    circular_std_deg,
    destination,
    distance_m,
    initial_bearing_deg,
)
from kraken import parse_line, parse_output, select_vfo
from simulate import kraken_line

# Shape of a real "Kraken App" line (krakensdr_doa, December 2025), spectrum shortened.
REAL_LINE = (
    "1764553200123, 312.0, 4.37, -52.3, 145500000, UCA, 205, NOCALL, 0.0, 0.0, 0.0, 0.0, "
    "GPS, R, R, R, R, 0.00, 1.25, 3.50 \n"
)


def test_parses_a_kraken_app_line() -> None:
    r = parse_line(REAL_LINE)
    assert r is not None
    assert r.timestamp_ms == 1764553200123
    assert r.t == 1764553200.123
    assert r.doa_rel_deg == 312.0
    assert r.confidence == 4.37
    assert r.power_db == -52.3
    assert r.freq_hz == 145_500_000
    assert r.array == "UCA"
    assert r.station_id == "NOCALL"


def test_malformed_lines_are_skipped() -> None:
    assert parse_line("") is None
    assert parse_line("1, 2, 3") is None
    assert parse_line("abc, 1, 2, 3, 4, UCA, 5, X") is None
    assert parse_line("1764553200123, nan, 4, -50, 145500000, UCA, 5, X") is None
    assert parse_line("0, 10, 4, -50, 145500000, UCA, 5, X") is None
    assert parse_output("garbage\n\n" + REAL_LINE) == [parse_line(REAL_LINE)]


def test_doa_is_normalised() -> None:
    r = parse_line(REAL_LINE.replace("312.0", "360.0"))
    assert r is not None and r.doa_rel_deg == 0.0


def test_vfo_selection_by_frequency() -> None:
    lines = kraken_line(1000.0, 10, 5, -50, 145_500_000) + kraken_line(
        1000.0, 200, 5, -50, 433_500_000
    )
    readings = parse_output(lines)
    assert len(readings) == 2
    assert select_vfo(readings, None) == readings[0]
    assert select_vfo(readings, 433.5) == readings[1]
    assert select_vfo(readings, 433.52) == readings[1]
    assert select_vfo(readings, 438.0) is None
    assert select_vfo([], 145.5) is None


def test_simulated_line_roundtrip() -> None:
    r = parse_line(kraken_line(1234.5, -30.0, 4.0, -45.0, 145_500_000))
    assert r is not None
    assert r.timestamp_ms == 1234500
    assert r.doa_rel_deg == 330.0
    assert r.array == "UCA"


def test_geo_helpers() -> None:
    lat, lon = destination(48.1, 11.5, 45.0, 1000.0)
    assert abs(distance_m(48.1, 11.5, lat, lon) - 1000.0) < 0.5
    assert abs(initial_bearing_deg(48.1, 11.5, lat, lon) - 45.0) < 0.1
    assert angle_diff_deg(1, 359) == 2
    assert angle_diff_deg(359, 1) == -2
    assert abs(angle_diff_deg(circular_mean_deg([350, 10]), 0)) < 1e-9
    assert circular_std_deg([42.0]) == 0.0
    assert circular_std_deg([0.0, 180.0]) == 180.0
    assert 3.4 < circular_std_deg([355, 0, 5, 0]) < 3.7  # population std of -5, 0, 5, 0
