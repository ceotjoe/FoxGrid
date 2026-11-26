# MQTT interface for bearing stations and the relay hook

Automatic bearing stations and the relay hook report their data over MQTT. A single service
(`python -m app.mqtt_ingest`, Compose service `ingest`) reads the topics, checks the sender and stores
bearings, signal levels and transmissions in the database. The app shows them like all other data
(rays, estimate, banner, push); every station appears as its own participant.

## Setup

```bash
docker compose --profile mqtt up -d      # start Mosquitto (127.0.0.1:1883) and the ingest service
```

1. As lead, create a station in the app under *Sensors* (or via the API): name, kind
   (`station` or `relay`) and, for fixed stations, the position. **The API key (`fgs_…`) is shown only
   once.**
2. The device connects to the broker (user and password from `.env`, `FOXGRID_MQTT_*`) and
   publishes under the topic prefix shown, `foxgrid/<mission-id>/<sensor-id>`.

```bash
# Example client: a station bearing a hidden transmitter
uv run tools/sensor_client/station.py --user foxgrid --password … \
  --mission <mission-id> --sensor <sensor-id> --key fgs_… \
  --lat 48.10 --lon 11.50 --truth 48.137 11.575 --count 5
```

## Security

* The broker login only decides who may talk to the broker. In addition, every message carries the station's
  API key in the field `key`; it is checked against the stored hash, and mission and sensor must match the topic.
  A wrong or deactivated station is dropped silently (log entry only), without revealing what was wrong.
* The key is part of the message. Anyone reaching the broker over an insecure network needs TLS
  (a listener with a certificate in `deploy/mosquitto/mosquitto.conf`). Compromised stations can be
  deactivated in the app; their earlier data stays in the log.
* At most 30 messages per second are accepted per station (`FOXGRID_MQTT_MAX_MSGS_PER_S`);
  messages larger than 64 KB are dropped.
* The ingest service must run **only once**, otherwise messages would be processed twice.

## Topics and messages

All messages are JSON, QoS 1, times with time zone (UTC recommended). `key` is always required.
The device generates the IDs (`id`) itself and keeps them on retries: a message that is delivered again
is recognised and ignored.

### `foxgrid/<mission>/<sensor>/bearing`

```json
{
  "key": "fgs_…",
  "id": "5d9c0f3e-…",
  "azimuth_true_deg": 123.4,
  "sigma_deg": 8.0,
  "measured_at": "2026-10-16T21:15:00Z",
  "lat": 48.10, "lon": 11.50,
  "rssi_dbm": -82.0, "attenuation_db": 0, "polarization": "v", "note": "…"
}
```

`azimuth_true_deg` is true north (0 ≤ az < 360), `sigma_deg` is mandatory (0 < σ ≤ 90). `lat`/`lon`
are omitted for fixed stations: the registered position applies then. Without either, the message is
rejected. `rssi_dbm`, `attenuation_db`, `polarization` (`h`, `v`, `unknown`) and `note` are optional.

`interferer` (optional) names the interferer the bearing belongs to. Without it the sensor's default interferer applies
(set by the lead), then the running transmission's, then the mission's default. An unknown or deactivated interferer in the
message rejects it; a sensor default that was deactivated meanwhile is skipped.

### `foxgrid/<mission>/<sensor>/rssi`

A single reading, or up to 100 collected. An optional `interferer` applies to all samples of the message:

```json
{"key": "fgs_…", "id": "…", "rssi_dbm": -90.5, "attenuation_db": 10, "measured_at": "…"}
{"key": "fgs_…", "samples": [{"id": "…", "rssi_dbm": -70, "measured_at": "…", "lat": 48.1, "lon": 11.5}]}
```

### `foxgrid/<mission>/<sensor>/status`

Heartbeat, for example every 30 s: `{"key": "fgs_…"}`. A station counts as *online* if it has sent
anything in the last two minutes (every valid message counts).

Mobile stations add their position; it is stored as the station's track (shown on the map, purged with all tracks):

```json
{"key": "fgs_…", "lat": 48.10, "lon": 11.50, "speed": 12.5, "heading": 91.0, "at": "2026-10-16T21:15:00Z"}
```

`lat` and `lon` come together; `speed` (m/s, 0–100), `heading` (true north, 0 ≤ h < 360) and `at` (time of the fix, default
time of receipt) are optional.

### `foxgrid/<mission>/<sensor>/transmission` (sensors of kind `relay` only)

```json
{"key": "fgs_…", "event": "start", "at": "2026-10-16T21:15:00Z", "note": "squelch open without CTCSS"}
{"key": "fgs_…", "event": "stop",  "at": "2026-10-16T21:15:42Z"}
```

`start` creates a transmission with source `relay` (banner, push, assignment of bearings),
`stop` ends it. A repeated `start` while a transmission is running and a `stop` without a running
transmission are harmless and ignored. `at` is optional (default: time of receipt).

### Replies from the ingest service

There is no reply to the device. The service logs `ok`, `duplicate` or `rejected:<reason>` per message
(`auth`, `topic`, `payload`, `invalid`, `too_large`, `rate_limited`, `no_position`,
`id_conflict`, `not_relay`, `mission`, `kind`, `interferer`).

## KrakenSDR in a vehicle

`tools/kraken_bridge/bridge.py` makes a KrakenSDR with a circular array (UCA) on a car roof a mobile station
([ADR 0010](../adr/0010-vehicle-mounted-kraken-sdr.md)). It runs on the Kraken's Raspberry Pi and needs:

* the KrakenSDR DSP software with the data format **"Kraken App"** and the heading set to **fixed 0°**. The bridge reads
  `http://127.0.0.1:8081/DOA_value.html` and applies the heading itself,
* gpsd with a GNSS receiver (`127.0.0.1:2947`), and the Pi's clock synchronised to GNSS (for example chrony with gpsd as
  source), because the Kraken stamps its results with the system clock,
* a sensor of kind `station` **without** a fixed position, and TLS to the broker when it is reached over the mobile network.

```bash
uv run tools/kraken_bridge/bridge.py --broker foxgrid.example.org --port 8883 --tls --user foxgrid --password … \
  --mission <mission-id> --sensor <sensor-id> --key fgs_… --freq-mhz 145.500 --mount-offset 0 --environment mixed
```

What it does with the Kraken results:

* **True bearing:** GNSS course + Kraken DoA + `--mount-offset`. The course counts once the car has driven straight
  (< 10° change) at ≥ 2 m/s for 5 s. When the car stops, the last course is frozen. If the car turned or manoeuvred for more
  than 10 s before the stop, the frozen course is "uncertain" (much larger sigma). No bearings while manoeuvring
  (0.5–2 m/s) or turning, so for bearings at a stop drive the last metres straight into the parking spot.
* **Signal gate:** readings below `--min-confidence` (dB, default 2) or `--min-power` (off by default) are dropped. Set
  both from a recording with and without the signal. Each Kraken result is used once, because the output file keeps its last
  value while the squelch is closed.
* **Thinning:**
  * driving: circular mean over 3 s, at most one bearing every 5 s and every 100 m,
  * parked: the first bearing after 10 s, then one per minute.

  Readings more than 25° off the window's mean are dropped as multipath.
* **Sigma:** root-sum-square of the spread in the window (≥ 2°), the heading part (2–4° driving, 3° parked, 12° uncertain),
  2° mount residual and the `--environment` preset (`open` 3°, `mixed` 5°, `urban` 8°), clamped to 5°–30°.
* **Note:** each bearing says "KrakenSDR fahrend/stehend" with the number of readings, spread, confidence and the
  uncalibrated power. The power is not sent as `rssi_dbm`.
* **Outbox:** messages are stored in `--outbox` (SQLite) and removed only after the broker acknowledged them, so they
  survive a lost connection or a reboot.
* **Heartbeat:** every 10 s (`--heartbeat`) with position, speed, heading and fix time, so the car moves on the map.
* **Interferer:** the sensor's default interferer applies (set by the lead); `--interferer <id>` names one in every
  bearing instead.

Without hardware: `--simulate` drives a simulated car past a hidden emitter, and `--dry-run` prints the messages instead of
sending them. Tests: `uv run --with pytest --with aiomqtt pytest tools/kraken_bridge`.

## Relay hook

`tools/relay_hook/hook.py` reports "squelch open without CTCSS" as a transmission. A repeater only opens for
users with the right CTCSS tone; if the squelch opens without a tone, someone else is transmitting on the
input frequency.

* **Input:** The repeater controller publishes its state on `relay/<name>/state` as
  `{"squelch": true, "ctcss": false}` (assumption: the controller can speak MQTT).
* **Debouncing:** Start only after `--min-on` seconds (default 1 s, short interference pulses do not count),
  stop only after `--hang` seconds of silence (default 4 s, short dropouts of a weak signal do not split a
  transmission). The start time is the beginning of the interference, the stop time its last moment.
* **Demo without hardware:** `--simulate` plays back a legitimate user, an interference pulse and the interferer.

```bash
uv run tools/relay_hook/hook.py --broker localhost --user foxgrid --password … \
  --mission <mission-id> --sensor <relay-sensor-id> --key fgs_… --relay DB0XYZ [--simulate]
```

Both tools have their own tests: `uv run --with pytest --with aiomqtt pytest tools/relay_hook`.
