# 0010 – Vehicle-mounted KrakenSDR as a mobile bearing station

**Status:** proposed; steps 1 (bridge), 2 (backend: track, weight, default interferer), 3 (engine), 4 (manual gate), 5
(bulk management) and 6 (app: sensor settings, vehicle, ray display) implemented

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
4. The Kraken bears everything on the frequency, including legitimate repeater users who transmit during the drive. Their
   bearings point elsewhere and are consistent, so the outlier mixture does not catch them. Telling the interferer apart
   automatically (CTCSS, signal features) is not reliable enough, so a person has to decide.
5. A drive yields hundreds of bearings. Assigning them to interferers and deciding which count must be practical in the app,
   which so far edits bearings one at a time.

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
  well below that. Between 0.5 and 2 m/s (manoeuvring) and while turning no bearing is sent. GNSS course is true north, so
  no declination is applied (`azimuth_input_ref` true, declination 0). The Pi's clock follows GNSS time (chrony + gpsd),
  because the Kraken timestamp comes from the system clock.
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
- **Correlated series in the engine.** Each bearing of a sensor gets weight 1/n, where n is the number of the same sensor's
  bearings within 75 m (`cluster_radius_m`), itself included. This is multiplied into the existing per-bearing weight (age
  decay). A long stop thus counts as one bearing, while a drive past many positions keeps its value. Hand-held bearings are not
  affected.
  - Neighbourhoods are counted per bearing instead of forming fixed clusters. Clusters would chain a drive with bearings every
    100 m into one cluster.
  - The radius (first planned as 150 m) is below the bridge's 100 m spacing while driving, so a drive keeps full weight.
  - The engine stays generic: it knows `group`, `weight` and a per-bearing `outlier_fraction`, not sensors.
- **Outlier fraction per source.** Sensor bearings use ε = 0.2 (`sensor_outlier_fraction`, tunable per mission) instead of
  the mission's `outlier_fraction` (default 0.1), because reflections are more frequent for mobile DF.
- **Sensor weight.** A per-sensor factor (default 1.0, range 0–2, `sensor.manage`) scales the log-likelihood of that sensor's
  bearings, so the lead can lower a Kraken in town without deactivating it.
- **MQTT extensions.**
  - `status` may carry `lat`/`lon`/`heading`/`speed`. This feeds the virtual participant's position track, which shows the
    car on the map and is purged with all tracks.
  - Each sensor gets a default interferer, and a bearing may name one (`interferer`).
- **Counting only while the interferer transmits (manual gate).** A person switches *Störer sendet* on and off in the app.
  This uses the existing manual transmissions; an optional relay hook may still start them.
  - Every sensor gets the setting "nur bei Störer sendet zählen". It is on by default for stations without a fixed position.
  - A sensor bearing counts only if its whole averaging window lies inside a transmission. All other bearings are stored but
    get the automatic state "außerhalb Aussendung" and do not feed the estimate. They are never deleted.
  - The bridge sends the window as `window_start`/`window_end` next to `measured_at`. It also closes a window at a gap in the
    readings (default > 1.5 s, the squelch closing between two overs), so one window does not mix a user and the interferer.
    After such a gap the interval and distance limits start afresh, so the interferer's over right after a user's gets its
    own bearing; the density weighting in the engine still keeps a stop from counting twice.
  - People press the button late. Therefore the start can be backdated in the app ("seit 5/10/30 s"; the API already takes
    `at`), and the existing assignment slack (5 s) applies at both ends. A backdated start never reaches back before the
    previous transmission's end.
  - The state is re-evaluated whenever a transmission starts, stops or its times change, because bearings may arrive before
    the start (outbox, mobile network) or the start may be entered late. Changed bearings go out as one
    `bearings_updated` event. The gate applies to bearings only, not to RSSI readings (the Kraken sends none).
  - A manual decision ("zählen" / "nicht zählen") overrides the automatic state and is kept on re-evaluation. Like every edit
    it is an append-only revision. The estimate query (`domain.trusted_only`) excludes bearings that are automatically out and
    not manually included.
- **Managing sensor bearings in the app (*Peilungen verwalten*).** This is a screen for leads, deputies and analysts, built for
  hundreds of bearings.
  - **Timeline:** azimuth over time, one point per bearing, coloured by interferer. Counted bearings are filled; stored-only and
    excluded ones are hollow. Transmissions show as bands. A second direction, such as a repeater user, stands out as its own
    trace.
  - **Selection:**
    - Drag a time range on the timeline.
    - Select everything in a transmission.
    - Filter by sensor, interferer, state (counts / stored only / manually excluded) and time window.
    - The list below is virtualised. The app works on the bearings it already holds (snapshot plus live events), so the
      screen also works offline; the server's paging serves other clients such as the web control room.
  - **Bulk actions** on the selection:
    - assign an interferer,
    - "zählen", "nicht zählen", "automatisch" (drop the manual decision).
    - A preview on the map shows the selected rays before applying.
  - **Backend:** `GET /bearings` gains filters (`sensor`, `interferer`, `state`, `from`/`to`, `transmission`) and paging.
    A new bulk endpoint applies one change to up to 500 bearings in one transaction, with the same permissions as the
    single-bearing PATCH and one revision per bearing. It publishes one `bearings_updated` event and triggers one recompute.
  - **Map:** for sensors, only counted rays are shown by default; stored-only ones can be shown dimmed. Sensor rays are
    thinner and their fans fainter than hand bearings, because they come in dozens.
- **Mount calibration.** A tool compares measured and geodesic azimuth to a known transmitter from several vehicle headings
  and stores the median offset in the bridge configuration.

**Consequences.**

- The engine changes slightly: it gains cluster weights, per-bearing ε and a sensor weight. The grid model stays the same.
- Initial values (75 m, ε 0.2, σ presets, signal gate) are guesses. The simulator gets a Kraken vehicle, and the values are
  checked against real drives.
- Parked bearings need a straight approach to the parking spot. This goes into the user guide.
- One more device to run (Pi + bridge), with its own outbox. Bearing IDs come from the bridge and stay stable across retries,
  so redelivery is harmless.
- The key travels in every message over the mobile network, so TLS at the broker is required.
- The Kraken's power is uncalibrated (not dBm), so it goes into the bearing's `note` together with the confidence, not into
  `rssi_dbm` and not into homing readings.
- With the gate on, a Kraken contributes nothing until someone switches *Störer sendet* on. That is intended: a forgotten
  button loses no data, because stored bearings can be counted afterwards by backdating the transmission or by selecting them
  in *Peilungen verwalten*.
- If a user and the interferer transmit at the same time (doubling), the bearings mix. The gap split and the outlier rejection
  in the bridge only partly help; such stretches are excluded by hand.

**Steps.**

1. Bridge (`tools/kraken_bridge`). *Done.*
2. Backend: heartbeat position as track, sensor weight, default interferer, `interferer` in messages. *Done.*
3. Engine: cluster weighting per sensor, ε per source, sensor weight. *Done.*
4. Manual gate. *Done.*
   - Bridge: `window_start`/`window_end`, window split at reading gaps.
   - Backend: gate setting per sensor, automatic state with re-evaluation on transmission changes, manual override,
     `trusted_only` extension.
   - App: backdated start of *Störer sendet*.
5. Bulk management. *Done.*
   - Backend: filters, paging and the bulk endpoint for bearings.
   - App: *Peilungen verwalten* with timeline, selection, bulk actions and map preview.
6. App, sensors: weight, default interferer and gate in the sensor settings; vehicle marker with track; reduced ray display.
   *Done.*
7. Simulator vehicle with repeater users, calibration tool, user guide.

**Alternatives considered.**

- *App reads the Kraken over Wi-Fi:* couples the bearings to a phone and needs native networking in the app.
- *Kraken applies the heading itself:* it freezes after 3 s below 2 m/s, but sets position and heading to 0 without a fix and
  does not report speed, so the bridge cannot judge heading quality.
- *JSON output ("Kraken Pro"):* needs the Node middleware and carries the raw counter-clockwise θ.
- *Hard cap of bearings per sensor:* simpler, but throws away the real geometric gain of a drive.
- *Magnetometer:* unusable in a car without extensive compensation.
- *Automatic interferer detection* (relay hook only, CTCSS decoder in the car, signal features): not reliable enough and not
  always available (no repeater access, interferer sending the right tone). The relay hook stays an optional source of
  transmissions; the decision stays with a person.
- *Deactivating bearings outside transmissions* (`is_active = false`): mixes an automatic rule with the manual flag that
  quarantine also uses, and could not be undone by re-evaluation. Hence a separate automatic state plus a manual override.
