# KrakenSDR in a vehicle

A KrakenSDR with a circular antenna array (UCA) on a car roof takes a bearing several times per second, while driving and while
parked. With FoxGrid it becomes a **mobile bearing station**: the car shows on the map, its bearings flow into the estimate, and
a person decides which of them belong to the interferer. Background and design: [ADR 0010](../adr/0010-vehicle-mounted-kraken-sdr.md);
technical details of the bridge: [MQTT interface](../reference/mqtt.md#krakensdr-in-a-vehicle).

## What you need

- A KrakenSDR with a **UCA** (a linear array cannot tell front from back) and the current DSP software
  ([krakensdr_doa](https://github.com/krakenrf/krakensdr_doa)) on its Raspberry Pi.
- A GNSS receiver on the Pi with **gpsd**, and the Pi's clock synchronised to GNSS (chrony with gpsd as source). The Kraken stamps
  its results with the system clock; the bridge warns when Kraken time and GNSS time drift apart.
- Mobile internet in the car, and a FoxGrid server whose MQTT broker is reachable **with TLS**.

## Set up

1. **Kraken:** set the frequency of the mission, the array to UCA, the data format to **"Kraken App"** and the heading to
   **fixed 0°**. The bridge applies the heading from the GNSS course itself.
2. **Sensor in the app:** *Menü → Einsatz verwalten → Sensoren → Sensor*, kind "Peilstation", **without** "Feste Station an meinem
   Standort". Note the API key; it is shown once. A station without a fixed position is a *mobile station*: by default it counts
   only while the interferer transmits (see below).
3. **Bridge on the Pi:** copy `tools/kraken_bridge` and run it (as a systemd service in practice):

   ```bash
   uv run tools/kraken_bridge/bridge.py --broker foxgrid.example.org --port 8883 --tls \
       --user foxgrid --password … --mission <mission id> --sensor <sensor id> --key fgs_… \
       --freq-mhz 145.500 --mount-offset 0 --environment mixed
   ```

   `--environment` describes the multipath where you drive: `open` country, `mixed` (default) or `urban`. It widens the
   uncertainty of every bearing. The bridge keeps unsent bearings in `--outbox`, so a dead spot or a reboot loses nothing.
4. **Calibrate the mount** once per installation (next section) and put the result into `--mount-offset`.

Without hardware, `--simulate --dry-run` (add `--sim-users 2` for repeater users) prints what the bridge would send.

## Calibrate the mount

The array's 0° mark is rarely exactly in the driving direction. Find the offset with a transmitter at a **known position**
(a beacon, a friend with a handheld on a known spot, a repeater) on the Kraken's frequency:

```bash
uv run tools/kraken_bridge/calibrate.py --tx-lat 48.1234 --tx-lon 11.5678 --freq-mhz 145.500 \
    --duration 900 --save calibration.jsonl
```

While it records, drive **straight legs in at least three, better four directions**, each for a minute or more, at least
300 m from the transmitter; open country is best. The tool only uses readings with a steady driving heading and averages per
heading sector, so the direction you drove longest does not dominate. It prints a table per sector and the line to use, for
example `--mount-offset 7.0`.

- *"only N heading sectors"*: drive more directions.
- *"sectors differ by up to …"*: the car body or something nearby distorts the pattern in some directions. One offset cannot
  fix that; check the mount (centre of the roof, away from roof bars and other antennas) and calibrate elsewhere.
- `--load calibration.jsonl` evaluates a recording again; `--simulate` shows the procedure without hardware.

## During the hunt

- **Press *Aussendung Start* when the interferer transmits, and *Aussendung Ende* when it stops.** A mobile station's bearings
  count only while a transmission runs, because the Kraken also bears every legitimate repeater user. Everything else is stored
  and can be counted later.
- **Pressed late?** The clock button next to *Aussendung Start* starts it 5, 10 or 30 s back. Bearings that arrived meanwhile
  are re-evaluated automatically.
- **On the map** the car shows with its course, speed and the last hour of its track. Its rays are thinner than hand bearings;
  rays that do not count are hidden unless *Filter → Nicht gezählte Stationspeilungen zeigen* is on.
- **Parking:** drive the last metres straight into the parking spot. The heading is frozen when the car stops; after turning or
  manoeuvring it counts as uncertain and the bearings get a much larger uncertainty. While manoeuvring and turning no bearings
  are sent.
- **Driving:** the bridge sends at most one bearing every 100 m and every 5 s. A long stop counts like a single bearing, so a
  parked car does not outvote the hand-held bearers.

## Sorting out bearings afterwards

*Menü → Peilungen verwalten* (lead, deputy, analyst) shows the station's bearings on a **timeline** of azimuth over time, with
transmissions as bands. The interferer forms one trace, every repeater user another.

- Drag over a time range or tap a transmission to select; filter by station, interferer and state ("Zählt", "Nur gespeichert",
  "Manuell gezählt", "Manuell ausgeschlossen").
- **Zählen** / **Nicht zählen** decides by hand and wins over the automatic rule; **Automatisch** drops the decision.
  **Störer …** assigns the selection to another interferer. A map shows the selected rays before anything is applied.
- Typical cases: the button was forgotten (select the interferer's trace, *Zählen*), a user transmitted during a
  transmission (select that trace, *Nicht zählen*), a second interferer (assign its trace to a new interferer).

Nothing is ever deleted; every change is a revision.

## Station settings

Tap the station in *Sensoren*:

- **Gewicht** (0–2): how much its bearings count. Lower it in town with many reflections, 0 takes them out completely.
- **Standard-Störer:** the interferer its bearings belong to, instead of the running transmission's.
- **Nur bei „Störer sendet“ zählen:** the gate described above. Switch it off only when nobody else uses the frequency.

## Try it without a car

With the server running and MQTT enabled (`docker compose --profile mqtt up -d`):

```bash
uv run tools/simulator/run.py --kraken --kraken-users 2
```

A simulated car drives towards a hidden emitter while two repeater users share the frequency. The simulator starts
transmissions only for the interferer's overs, a little late, and prints the estimate error with the gate on and off. Join the
printed invite in the app to watch, and open *Peilungen verwalten* to see the traces.
