from __future__ import annotations

import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from station import build_bearing, build_parser, true_azimuth  # noqa: E402


def test_true_azimuth_points_at_the_target() -> None:
    assert true_azimuth(48.0, 11.0, (48.1, 11.0)) == pytest.approx(0.0, abs=0.01)
    assert true_azimuth(48.0, 11.0, (48.0, 11.1)) == pytest.approx(90.0, abs=0.2)
    assert true_azimuth(48.1, 11.0, (48.0, 11.0)) == pytest.approx(180.0, abs=0.01)
    assert true_azimuth(48.0, 11.1, (48.0, 11.0)) == pytest.approx(270.0, abs=0.2)


def test_bearing_message_matches_the_ingest_schema() -> None:
    mid = uuid.uuid4()
    at = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    msg = build_bearing("fgs_k", 365.123, 8.0, lat=48.1, lon=11.5, rssi_dbm=-80, at=at, message_id=mid)
    assert msg == {
        "key": "fgs_k",
        "id": str(mid),
        "azimuth_true_deg": 5.12,
        "sigma_deg": 8.0,
        "measured_at": "2026-01-01T10:00:00+00:00",
        "lat": 48.1,
        "lon": 11.5,
        "rssi_dbm": -80,
    }
    minimal = build_bearing("fgs_k", 10.0, 5.0)
    assert "lat" not in minimal and "rssi_dbm" not in minimal  # fixed position is used
    assert minimal["id"] != build_bearing("fgs_k", 10.0, 5.0)["id"]


def test_cli() -> None:
    args = build_parser().parse_args(["--mission", "m", "--sensor", "s", "--key", "k", "--truth", "48.1", "11.5"])
    assert args.truth == [48.1, 11.5] and args.count == 5
