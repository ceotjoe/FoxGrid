# /// script
# requires-python = ">=3.12"
# dependencies = ["aiomqtt>=2.0"]
# ///
"""Repeater hook: reports "squelch open without CTCSS" as a FoxGrid transmission.

A repeater only opens for users that send the right CTCSS tone. If its squelch opens *without*
the tone, somebody else is on the input frequency: the interferer. This service watches the
repeater controller's raw state and tells FoxGrid when the interferer keys up and drops out, so
the mission shows the "STÖRER SENDET" banner, pushes the team and files bearings under the
right transmission.

Input (from the repeater controller, MQTT, JSON, retained or not):

    topic  relay/<name>/state      payload  {"squelch": true, "ctcss": false}

Output (to FoxGrid, QoS 1, see docs/mqtt.md):

    foxgrid/<mission>/<sensor>/transmission   {"key": ..., "event": "start"|"stop", "at": ...}
    foxgrid/<mission>/<sensor>/status         {"key": ...}        (heartbeat)

Run it::

    uv run tools/relay_hook/hook.py --broker localhost --mission <id> --sensor <id> \\
        --key fgs_... --relay DB0XYZ

``--simulate`` replays a scripted sequence (a legitimate user, a glitch, the interferer)
without any hardware.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

log = logging.getLogger("relay_hook")


@dataclass(frozen=True)
class Event:
    kind: str  # "start" | "stop"
    at: float  # POSIX seconds of the first / last moment the interferer was on air


class InterfererDetector:
    """Debounced "squelch open and no CTCSS" detector.

    * a start is reported once the condition held for ``min_on_s`` (short glitches are ignored)
      and carries the time the condition began,
    * a stop is reported once it stayed away for ``hang_s`` (brief dropouts of a weak signal
      do not split one transmission in two) and carries the last time it was seen.
    """

    def __init__(self, min_on_s: float = 1.0, hang_s: float = 4.0) -> None:
        self.min_on_s = min_on_s
        self.hang_s = hang_s
        self.active = False  # a transmission has been reported and not yet stopped
        self._since: float | None = None  # condition currently true since
        self._last_seen: float | None = None  # last time the condition was true
        self._clear_since: float | None = None

    def update(self, squelch: bool, ctcss: bool, now: float) -> list[Event]:
        interferer = squelch and not ctcss
        if interferer:
            if self._since is None:
                self._since = now
            self._last_seen = now
            self._clear_since = None
        else:
            if self._clear_since is None:
                self._clear_since = now
            if not self.active:
                self._since = None  # the glitch never became a transmission
        return self.tick(now)

    def tick(self, now: float) -> list[Event]:
        """Advance time without new input (debounce timers)."""
        events: list[Event] = []
        if not self.active and self._since is not None and self._clear_since is None:
            if now - self._since >= self.min_on_s:
                self.active = True
                events.append(Event("start", self._since))
        if self.active and self._clear_since is not None:
            if now - self._clear_since >= self.hang_s:
                self.active = False
                events.append(Event("stop", self._last_seen if self._last_seen is not None else now))
                self._since = None
        return events


def parse_state(payload: bytes | str) -> tuple[bool, bool] | None:
    """``(squelch, ctcss)`` from a controller message, or ``None`` if it is not one."""
    try:
        doc = json.loads(payload)
        squelch, ctcss = doc["squelch"], doc["ctcss"]
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(squelch, bool) or not isinstance(ctcss, bool):
        return None
    return squelch, ctcss


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat()


class MqttLike(Protocol):
    async def publish(self, topic: str, payload: str, qos: int = ...) -> Any: ...


@dataclass
class HookConfig:
    mission: str
    sensor: str
    key: str
    relay: str = "relay"
    min_on_s: float = 1.0
    hang_s: float = 4.0
    heartbeat_s: float = 30.0

    @property
    def prefix(self) -> str:
        return f"foxgrid/{self.mission}/{self.sensor}"

    @property
    def state_topic(self) -> str:
        return f"relay/{self.relay}/state"


class RelayHook:
    def __init__(
        self,
        config: HookConfig,
        client: MqttLike,
        clock: Callable[[], float] | None = None,
    ) -> None:
        import time

        self.config = config
        self.client = client
        self.clock = clock or time.time
        self.detector = InterfererDetector(config.min_on_s, config.hang_s)

    async def _publish_event(self, event: Event) -> None:
        payload = {
            "key": self.config.key,
            "event": event.kind,
            "at": iso(event.at),
        }
        if event.kind == "start":
            payload["note"] = "Squelch offen ohne CTCSS"
        await self.client.publish(f"{self.config.prefix}/transmission", json.dumps(payload), qos=1)
        log.info("interferer %s at %s", event.kind, payload["at"])

    async def on_state(self, payload: bytes | str) -> None:
        state = parse_state(payload)
        if state is None:
            log.warning("ignoring malformed state message: %r", payload)
            return
        for event in self.detector.update(*state, self.clock()):
            await self._publish_event(event)

    async def on_tick(self) -> None:
        for event in self.detector.tick(self.clock()):
            await self._publish_event(event)

    async def heartbeat(self) -> None:
        await self.client.publish(
            f"{self.config.prefix}/status", json.dumps({"key": self.config.key}), qos=1
        )


async def _every(seconds: float, action: Callable[[], Awaitable[None]]) -> None:
    while True:
        await action()
        await asyncio.sleep(seconds)


async def run_live(args: argparse.Namespace) -> None:
    import aiomqtt

    config = HookConfig(
        args.mission, args.sensor, args.key, args.relay, args.min_on, args.hang, args.heartbeat
    )
    while True:
        try:
            async with aiomqtt.Client(
                hostname=args.broker,
                port=args.port,
                username=args.user,
                password=args.password,
                identifier=f"foxgrid-relay-hook-{args.relay}",
                clean_session=False,
            ) as client:
                hook = RelayHook(config, client)
                await client.subscribe(config.state_topic, qos=1)
                log.info("watching %s", config.state_topic)
                background = [
                    asyncio.create_task(_every(0.25, hook.on_tick)),
                    asyncio.create_task(_every(config.heartbeat_s, hook.heartbeat)),
                ]
                try:
                    async for message in client.messages:
                        await hook.on_state(bytes(message.payload or b""))  # type: ignore[arg-type]
                finally:
                    for task in background:
                        task.cancel()
        except aiomqtt.MqttError as exc:
            log.warning("MQTT connection lost (%s); retrying in 3 s", exc)
            await asyncio.sleep(3)


# Scripted demo: (seconds to wait, squelch, ctcss)
SIMULATION = [
    (0.0, False, False),
    (1.0, True, True),  # a legitimate user opens the repeater: must be ignored
    (3.0, False, False),
    (1.0, True, False),  # a 0.4 s glitch: ignored
    (0.4, False, False),
    (1.5, True, False),  # the interferer keys up
    (6.0, True, False),
    (0.5, False, False),  # a short dropout of a weak signal: still the same transmission
    (1.0, True, False),
    (3.0, True, False),
    (0.0, False, False),  # the interferer is gone
]


async def run_simulation(args: argparse.Namespace) -> None:
    import aiomqtt

    config = HookConfig(
        args.mission, args.sensor, args.key, args.relay, args.min_on, args.hang, args.heartbeat
    )
    async with aiomqtt.Client(
        hostname=args.broker, port=args.port, username=args.user, password=args.password
    ) as client:
        hook = RelayHook(config, client)
        await hook.heartbeat()
        for wait, squelch, ctcss in SIMULATION:
            end = asyncio.get_running_loop().time() + wait
            while asyncio.get_running_loop().time() < end:
                await hook.on_tick()
                await asyncio.sleep(0.1)
            log.info("squelch=%s ctcss=%s", squelch, ctcss)
            await hook.on_state(json.dumps({"squelch": squelch, "ctcss": ctcss}))
        for _ in range(int((config.hang_s + 1) / 0.1)):
            await hook.on_tick()
            await asyncio.sleep(0.1)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--user")
    ap.add_argument("--password")
    ap.add_argument("--mission", required=True)
    ap.add_argument("--sensor", required=True, help="id of the sensor registered with kind=relay")
    ap.add_argument("--key", required=True, help="the sensor's API key (fgs_...)")
    ap.add_argument("--relay", default="relay", help="name used in the controller topic")
    ap.add_argument("--min-on", type=float, default=1.0, help="seconds before a start is reported")
    ap.add_argument("--hang", type=float, default=4.0, help="seconds of silence before a stop")
    ap.add_argument("--heartbeat", type=float, default=30.0)
    ap.add_argument("--simulate", action="store_true", help="replay a scripted sequence and exit")
    return ap


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_parser().parse_args()
    try:
        asyncio.run(run_simulation(args) if args.simulate else run_live(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
