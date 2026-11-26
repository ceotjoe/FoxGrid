from __future__ import annotations

from pathlib import Path

import pytest
from calibrate import Calibrator, CalSample, calibrate, load, save, simulate
from geo import destination, initial_bearing_deg
from heading import Fix
from simulate import kraken_line

TX = (48.12, 11.55)


@pytest.mark.parametrize("offset", [7.0, -12.0, 0.0])
def test_simulated_loop_finds_the_offset(offset: float) -> None:
    result = calibrate(simulate(TX, offset), TX)
    assert result.ok, result.warnings
    assert result.offset_deg == pytest.approx(offset, abs=1.0)
    assert len(result.sectors) >= 4
    assert result.spread_deg < 6.0


def synthetic(
    headings: list[float], offset_for: dict[float, float] | None = None, dist: float = 2000.0
) -> list[CalSample]:
    """Readings from 30 positions per heading around the transmitter."""
    out = []
    for h in headings:
        for i in range(30):
            lat, lon = destination(*TX, (h + 90 + i) % 360, dist)
            truth = initial_bearing_deg(lat, lon, *TX)
            off = (offset_for or {}).get(h, 5.0)
            out.append(CalSample(float(i), lat, lon, h, (truth - h - off) % 360))
    return out


def test_one_direction_is_not_enough() -> None:
    result = calibrate(synthetic([10.0]), TX)
    assert result.offset_deg == pytest.approx(5.0, abs=0.01)
    assert not result.ok
    assert "heading sectors" in result.warnings[0]


def test_heading_dependent_errors_are_reported() -> None:
    result = calibrate(synthetic([10.0, 100.0, 190.0, 280.0], {100.0: 15.0}), TX)
    assert result.sector_spread_deg > 5.0
    assert any("car body" in w for w in result.warnings)


def test_readings_near_the_transmitter_are_ignored() -> None:
    samples = synthetic([10.0, 100.0, 190.0]) + synthetic([280.0], {280.0: 40.0}, dist=100.0)
    result = calibrate(samples, TX)
    assert result.offset_deg == pytest.approx(5.0, abs=0.01)
    assert any("closer than" in w for w in result.warnings)
    assert calibrate([], TX).warnings == ["no usable readings"]


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    samples = synthetic([10.0, 100.0, 190.0])
    path = tmp_path / "cal.jsonl"
    save(samples, path)
    assert load(path) == samples


def test_calibrator_uses_only_driving_headings_and_new_readings() -> None:
    cal = Calibrator(freq_mhz=145.5)
    t = 1_800_000_000.0
    for i in range(8):  # 8 s straight east at 10 m/s: the heading becomes valid after 5 s
        cal.on_fix(Fix(t + i, 48.1, 11.5 + i * 1e-4, 10.0, 90.0))
    line = kraken_line(t + 7, 30.0, 5.0, -50.0, 145.5e6)
    cal.on_kraken_output(line)
    cal.on_kraken_output(line)  # the file keeps its content: used once
    assert len(cal.samples) == 1
    assert cal.samples[0].heading_deg == pytest.approx(90.0)
    assert cal.samples[0].doa_rel_deg == pytest.approx(30.0)
    cal.on_kraken_output(kraken_line(t + 7.5, 30.0, 0.5, -50.0, 145.5e6))  # too weak
    for i in range(8, 12):  # stopping: parked headings are not used
        cal.on_fix(Fix(t + i, 48.1, 11.5008, 0.0, None))
    cal.on_kraken_output(kraken_line(t + 11, 30.0, 5.0, -50.0, 145.5e6))
    assert len(cal.samples) == 1
