# 0010 – Vehicle-mounted KrakenSDR as a mobile bearing station

**Status:** proposed (not implemented)

**Context.** A KrakenSDR with a circular antenna array (UCA) on a car roof yields an unambiguous 360° bearing several times per
second, both while driving and while parked. The MQTT interface ([0006](0006-mqtt-ingest-separate-process.md),
[MQTT interface](../reference/mqtt.md)) already accepts sensor bearings with a per-message position, but three gaps remain:

1. The Kraken reports a direction **relative to the array**. It needs a true-north heading, and GNSS course over ground has no
   heading at standstill.
2. The engine sums log-likelihoods as if bearings were independent. A car sending several bearings per second, or parking
   for ten minutes, would outvote every hand-held bearer, although its errors (multipath at the spot, heading error) are
   strongly correlated.
3. The vehicle is not visible on the map between bearings, and a station always reports for the mission's default interferer
   ([0008](0008-multiple-interferers.md)).

**Decision.**

- **Bridge on the vehicle.** A new tool `tools/kraken_bridge` runs on the Kraken's Raspberry Pi, next to the DSP software
  ([krakensdr_doa](https://github.com/krakenrf/krakensdr_doa)). It talks MQTT over TLS through the mobile network, using the
  existing station mechanism (sensor kind `station`, no fixed position, API key). The phone and the app play no part, so
  bearings do not depend on a handset.
- **Input format.** The bridge polls `http://<pi>:8081/DOA_value.html` in the Kraken DSP software's "Kraken App" format: one CSV
  line per VFO containing timestamp (ms), DoA as `360 − θ` (clockwise relative to the array, heading **not** applied),
  confidence (peak-to-average ratio of the DoA spectrum, dB), power (dB, uncalibrated), frequency (Hz), array type and the
  DoA spectrum. The file keeps its last value while the squelch is closed, so a timestamp is used only once. The Kraken is set
  to heading fixed at 0°. It may use GPS itself, but the bridge does not rely on it. A frequency that differs from the
  mission's `frequency_mhz` only triggers a warning. Format verified against commit `2e1c4e6` (December 2025).
- **Heading from GNSS course, frozen at standstill.** The bridge reads gpsd itself (speed, track, time):
  `az_true = (heading + doa + mount_offset) mod 360`. The heading is valid after ≥ 5 s at ≥ 2 m/s with < 10° course change
  (the same speed threshold the Kraken software uses). On stopping it is frozen. If the car was turning, or spent more than
  10 s manoeuvring at low speed since the last valid heading, the frozen heading counts as uncertain; ordinary braking stays
  well below that. Between 0.5 and 2 m/s (manoeuvring) and while turning no bearing is sent. GNSS course is true north, so no declination is applied
  (`azimuth_input_ref` true, declination 0). The Pi's clock follows GNSS time (chrony + gpsd), because the Kraken timestamp
  comes from the system clock.
- **Signal gate.** A bearing is sent only when confidence and power are above thresholds. Initial values are taken from a
  recording with and without signal.
- **Aggregation in the bridge.** The bridge takes the circular mean over a window.
  - While driving, it emits at most one bearing every 100 m and every 5 s at the earliest.
  - While parked, the first bearing comes after 10 s of averaging, then at most one every 60 s.
- **σ per bearing.** Root-sum-square of four parts, clamped to 5°–30°.
  - σ_DoA: circular spread in the window, at least 2°.
  - σ_heading:
    - 2° above 5 m/s straight
    - 4° at 2–5 m/s
    - 3° parked with a valid frozen heading
    - 12° parked with an uncertain heading
  - σ_mount: 2° calibration residual.
  - σ_env, an environment preset chosen by the operator: open 3°, mixed 5°, urban 8°.

  The best Kraken bearing therefore counts as much as a "sharp" (±5°) hand bearing.
- **Correlated series in the engine.** Per sensor, bearings within 150 m of each other form a cluster. Each bearing of a cluster
  with n members gets weight 1/n, multiplied into the existing per-bearing weight (age decay). A long stop thus counts as one
  bearing, while a drive past many positions keeps its value. Hand-held bearings are not clustered.
- **Outlier fraction per source.** Sensor bearings use ε = 0.2 instead of the mission's `outlier_fraction` (default 0.1),
  because reflections are more frequent for mobile DF.
- **Sensor weight.** A per-sensor factor (default 1.0, range 0–2, `sensor.manage`) scales the log-likelihood of that sensor's
  bearings, so the lead can lower a Kraken in town without deactivating it.
- **MQTT extensions.**
  - `status` may carry `lat`/`lon`/`heading`/`speed`. This feeds the virtual participant's position track, which shows the
    car on the map and is purged with all tracks.
  - Each sensor gets a default interferer, and a bearing may name one (`interferer`).
- **Mount calibration.** A tool compares measured and geodesic azimuth to a known transmitter from several vehicle headings
  and stores the median offset in the bridge configuration.

**Consequences.**

- The engine changes slightly: it gains cluster weights, per-bearing ε and a sensor weight. The grid model stays the same.
- Initial values (150 m, ε 0.2, σ presets, signal gate) are guesses. The simulator gets a Kraken vehicle, and the values are
  checked against real drives.
- Parked bearings need a straight approach to the parking spot. This goes into the user guide.
- One more device to run (Pi + bridge), with its own outbox. Bearing IDs come from the bridge and stay stable across retries,
  so redelivery is harmless.
- The key travels in every message over the mobile network, so TLS at the broker is required.
- The Kraken's power is uncalibrated (not dBm), so it goes into the bearing's `note` together with the confidence, not into
  `rssi_dbm` and not into homing readings.

**Alternatives considered.**

- *App reads the Kraken over Wi-Fi:* couples the bearings to a phone and needs native networking in the app.
- *Kraken applies the heading itself:* it freezes after 3 s below 2 m/s, but sets position and heading to 0 without a fix and
  does not report speed, so the bridge cannot judge heading quality.
- *JSON output ("Kraken Pro"):* needs the Node middleware and carries the raw counter-clockwise θ.
- *Hard cap of bearings per sensor:* simpler, but throws away the real geometric gain of a drive.
- *Magnetometer:* unusable in a car without extensive compensation.
