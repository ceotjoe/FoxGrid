from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from bridge import Bridge, BridgeConfig, build_parser, flush, parse_tpv
from geo import angle_diff_deg, initial_bearing_deg
from heading import Fix
from outbox import Outbox
from simulate import drive, kraken_line

START = (48.10, 11.50)
EMITTER = (48.115, 11.512)


def make_bridge(now: list[float], **kwargs: Any) -> Bridge:
    config = BridgeConfig(mission="m1", sensor="s1", key="fgs_test", freq_mhz=145.5, **kwargs)
    return Bridge(config, Outbox(), clock=lambda: now[0])


def run_drive(bridge: Bridge, now: list[float], **kwargs: Any) -> list[dict[str, Any]]:
    for step in drive(now[0], START, EMITTER, **kwargs):
        now[0] = step.t
        if step.fix is not None:
            bridge.on_fix(step.fix)
        if step.kraken_text is not None:
            bridge.on_kraken_output(step.kraken_text)
    return [json.loads(item.payload) for item in bridge.outbox.pending(limit=1000)]


def test_simulated_drive_points_at_the_emitter() -> None:
    now = [1_800_000_000.0]
    bridge = make_bridge(now)
    messages = run_drive(bridge, now)
    assert 10 <= len(messages) <= 30  # thinned: hundreds of readings, a few dozen bearings
    for m in messages:
        truth = initial_bearing_deg(m["lat"], m["lon"], *EMITTER)
        assert abs(angle_diff_deg(m["azimuth_true_deg"], truth)) < 2.5 * m["sigma_deg"]
        assert 5.0 <= m["sigma_deg"] <= 30.0
        assert m["key"] == "fgs_test"
        assert str(m["measured_at"]).endswith("+00:00")
    notes = [str(m["note"]) for m in messages]
    assert any("fahrend" in n for n in notes) and any("stehend" in n for n in notes)
    assert bridge.counters.no_heading > 0  # turning and braking produced no bearings


def test_mount_offset_is_applied() -> None:
    now = [1_800_000_000.0]
    bridge = make_bridge(now, mount_offset_deg=40.0)
    messages = run_drive(bridge, now, mount_offset_deg=40.0, outlier_rate=0.0)
    errors = [
        abs(
            angle_diff_deg(m["azimuth_true_deg"], initial_bearing_deg(m["lat"], m["lon"], *EMITTER))
        )
        for m in messages
    ]
    assert max(errors) < 10.0


def test_wrong_mount_offset_is_visible() -> None:
    now = [1_800_000_000.0]
    bridge = make_bridge(now)
    messages = run_drive(bridge, now, mount_offset_deg=40.0, outlier_rate=0.0)
    errors = [
        angle_diff_deg(initial_bearing_deg(m["lat"], m["lon"], *EMITTER), m["azimuth_true_deg"])
        for m in messages
    ]
    assert all(abs(e - 40.0) < 10.0 for e in errors)


def fix_at(t: float, speed: float = 10.0, track: float = 90.0) -> Fix:
    return Fix(t, 48.1, 11.5, speed, track)


def warm_up(bridge: Bridge, now: list[float]) -> None:
    for i in range(10):
        now[0] = 1000.0 + i
        bridge.on_fix(fix_at(now[0]))


def test_repeated_file_content_is_used_once() -> None:
    now = [0.0]
    bridge = make_bridge(now)
    warm_up(bridge, now)
    text = kraken_line(now[0], 0.0, 5.0, -50.0, 145_500_000)
    bridge.on_kraken_output(text)
    bridge.on_kraken_output(text)
    assert bridge.counters.readings == 1
    assert bridge.counters.duplicate == 1


def test_gates() -> None:
    now = [0.0]
    bridge = make_bridge(now, min_power_db=-70.0)
    warm_up(bridge, now)
    t = now[0]
    bridge.on_kraken_output(kraken_line(t - 0.1, 0.0, 1.0, -50.0, 145_500_000))  # low confidence
    bridge.on_kraken_output(kraken_line(t - 0.2, 0.0, 5.0, -80.0, 145_500_000))  # weak
    bridge.on_kraken_output(kraken_line(t - 60, 0.0, 5.0, -50.0, 145_500_000))  # stale file
    bridge.on_kraken_output(kraken_line(t - 0.3, 0.0, 5.0, -50.0, 433_500_000))  # other frequency
    bridge.on_kraken_output(
        kraken_line(t - 0.4, 0.0, 5.0, -50.0, 145_500_000).replace("UCA", "ULA")
    )
    c = bridge.counters
    assert (c.weak, c.stale, c.no_vfo, c.not_uca, c.used) == (2, 1, 1, 1, 0)


def test_clock_skew_between_kraken_and_gnss_is_rejected() -> None:
    now = [0.0]
    bridge = make_bridge(now, max_reading_age_s=30.0)
    warm_up(bridge, now)
    bridge.on_kraken_output(kraken_line(now[0] - 10, 0.0, 5.0, -50.0, 145_500_000))
    assert bridge.counters.no_fix == 1


def test_no_heading_resets_the_window() -> None:
    now = [0.0]
    bridge = make_bridge(now)
    now[0] = 1000.0
    bridge.on_fix(fix_at(now[0], speed=1.0))  # manoeuvring
    bridge.on_kraken_output(kraken_line(now[0], 0.0, 5.0, -50.0, 145_500_000))
    assert bridge.counters.no_heading == 1


def test_status_message_carries_the_position_while_fresh() -> None:
    now = [0.0]
    bridge = make_bridge(now)
    assert bridge.status_message() == {"key": "fgs_test"}
    warm_up(bridge, now)
    status = bridge.status_message()
    assert status["lat"] == 48.1 and status["speed"] == 10.0 and status["heading"] == 90.0
    now[0] += 60
    assert bridge.status_message() == {"key": "fgs_test"}


def test_parse_tpv() -> None:
    line = (
        '{"class":"TPV","mode":3,"time":"2026-10-16T21:15:00.000Z",'
        '"lat":48.1,"lon":11.5,"speed":12.3,"track":91.5}'
    )
    fix = parse_tpv(line)
    assert fix is not None
    assert fix.t == 1792185300.0
    assert (fix.lat, fix.lon, fix.speed_mps, fix.track_deg) == (48.1, 11.5, 12.3, 91.5)
    assert parse_tpv(line.replace('"mode":3', '"mode":1')) is None
    assert parse_tpv('{"class":"SKY"}') is None
    assert parse_tpv("not json") is None
    assert parse_tpv('{"class":"TPV","mode":2,"time":"2026-10-16T21:15:00Z","lat":48.1}') is None
    no_track = parse_tpv(line.replace(',"track":91.5', ""))
    assert no_track is not None and no_track.track_deg is None


class FakeClient:
    def __init__(self, fail_after: int | None = None) -> None:
        self.sent: list[tuple[str, str, int]] = []
        self.fail_after = fail_after

    async def publish(self, topic: str, payload: str, qos: int = 0) -> None:
        if self.fail_after is not None and len(self.sent) >= self.fail_after:
            raise ConnectionError("link down")
        self.sent.append((topic, payload, qos))


def test_outbox_survives_a_lost_connection(tmp_path: Path) -> None:
    path = str(tmp_path / "outbox.sqlite")
    box = Outbox(path)
    for i in range(3):
        box.enqueue(f"id{i}", "foxgrid/m/s/bearing", {"n": i})
    box.enqueue("id0", "foxgrid/m/s/bearing", {"n": 99})  # same id: kept once
    assert len(box) == 3
    client = FakeClient(fail_after=1)
    with pytest.raises(ConnectionError):
        asyncio.run(flush(box, client))
    assert len(box) == 2
    box.close()

    reopened = Outbox(path)  # after a reboot
    client = FakeClient()
    assert asyncio.run(flush(reopened, client)) == 2
    assert [json.loads(p)["n"] for _, p, _ in client.sent] == [1, 2]
    assert all(qos == 1 for _, _, qos in client.sent)
    assert len(reopened) == 0


def test_parser_defaults() -> None:
    args = build_parser().parse_args(["--mission", "m", "--sensor", "s", "--key", "k"])
    assert args.kraken_url == "http://127.0.0.1:8081/DOA_value.html"
    assert args.gpsd_port == 2947
    assert args.environment == "mixed"
    assert not args.tls
