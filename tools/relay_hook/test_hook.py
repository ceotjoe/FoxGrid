from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from hook import (  # noqa: E402
    Event,
    HookConfig,
    InterfererDetector,
    RelayHook,
    build_parser,
    iso,
    parse_state,
)


def feed(det: InterfererDetector, steps: list[tuple[float, bool, bool]]) -> list[Event]:
    """steps: (time, squelch, ctcss); ticks once per 0.1 s between steps."""
    events: list[Event] = []
    t_prev = steps[0][0]
    for t, squelch, ctcss in steps:
        while t_prev + 0.1 < t:
            t_prev += 0.1
            events += det.tick(t_prev)
        events += det.update(squelch, ctcss, t)
        t_prev = t
    return events


def test_a_legitimate_user_with_ctcss_is_ignored() -> None:
    det = InterfererDetector()
    assert feed(det, [(0, False, False), (1, True, True), (6, True, True), (7, False, False), (20, False, False)]) == []


def test_interferer_start_carries_the_time_it_began() -> None:
    det = InterfererDetector(min_on_s=1.0, hang_s=4.0)
    events = feed(det, [(0, False, False), (10, True, False), (14, True, False)])
    assert events == [Event("start", 10.0)]
    assert det.active


def test_short_glitches_are_not_reported() -> None:
    det = InterfererDetector(min_on_s=1.0)
    assert feed(det, [(0, False, False), (5, True, False), (5.4, False, False), (30, False, False)]) == []
    assert not det.active


def test_stop_after_hang_time_with_the_last_seen_time() -> None:
    det = InterfererDetector(min_on_s=1.0, hang_s=4.0)
    events = feed(
        det,
        [(0, True, False), (3, True, False), (8, False, False), (13, False, False)],
    )
    assert events == [Event("start", 0.0), Event("stop", 3.0)]
    assert not det.active


def test_brief_dropouts_do_not_split_a_transmission() -> None:
    det = InterfererDetector(min_on_s=1.0, hang_s=4.0)
    events = feed(
        det,
        [(0, True, False), (3, True, False), (3.5, False, False), (5, True, False), (9, True, False), (10, False, False), (20, False, False)],
    )
    assert [e.kind for e in events] == ["start", "stop"]
    assert events[1].at == 9.0


def test_ctcss_appearing_ends_the_interference() -> None:
    # a legitimate user keys up with the tone while the interferer is gone: not interferer any more
    det = InterfererDetector(min_on_s=1.0, hang_s=2.0)
    events = feed(det, [(0, True, False), (2, True, False), (3, True, True), (6, True, True)])
    assert [e.kind for e in events] == ["start", "stop"]


def test_repeated_cycles() -> None:
    det = InterfererDetector(min_on_s=0.5, hang_s=1.0)
    steps = [(0, True, False), (2, True, False), (3, False, False), (5, False, False),
             (10, True, False), (12, True, False), (13, False, False), (15, False, False)]
    kinds = [e.kind for e in feed(det, steps)]
    assert kinds == ["start", "stop", "start", "stop"]


def test_parse_state() -> None:
    assert parse_state('{"squelch": true, "ctcss": false}') == (True, False)
    assert parse_state(b'{"squelch": false, "ctcss": false}') == (False, False)
    for bad in ("nope", "[]", "{}", '{"squelch": 1, "ctcss": 0}', '{"squelch": true}', b"\xff"):
        assert parse_state(bad) is None


class FakeClient:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict, int]] = []

    async def publish(self, topic: str, payload: str, qos: int = 0) -> None:
        self.sent.append((topic, json.loads(payload), qos))


def test_hook_publishes_events_with_key_and_timestamps() -> None:
    now = [100.0]
    client = FakeClient()
    cfg = HookConfig("mission-1", "sensor-1", "fgs_secret", relay="DB0XYZ", min_on_s=1.0, hang_s=2.0)
    hook = RelayHook(cfg, client, clock=lambda: now[0])

    async def scenario() -> None:
        await hook.on_state('{"squelch": true, "ctcss": false}')
        now[0] = 102.0
        await hook.on_tick()
        await hook.on_state("garbage")  # ignored
        now[0] = 110.0
        await hook.on_state('{"squelch": false, "ctcss": false}')
        now[0] = 113.0
        await hook.on_tick()
        await hook.heartbeat()

    asyncio.run(scenario())
    assert cfg.prefix == "foxgrid/mission-1/sensor-1"
    assert cfg.state_topic == "relay/DB0XYZ/state"
    (t1, start, q1), (t2, stop, q2), (t3, hb, _) = client.sent
    assert t1 == t2 == "foxgrid/mission-1/sensor-1/transmission" and q1 == q2 == 1
    assert start["event"] == "start" and start["key"] == "fgs_secret"
    assert start["at"] == iso(100.0) and start["note"] == "Squelch offen ohne CTCSS"
    assert stop["event"] == "stop" and stop["at"] == iso(100.0)
    assert t3.endswith("/status") and hb == {"key": "fgs_secret"}


def test_cli_requires_the_identifiers() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([])
    args = build_parser().parse_args(["--mission", "m", "--sensor", "s", "--key", "k", "--simulate"])
    assert args.simulate and args.hang == 4.0 and args.broker == "localhost"
