# Homing (close-range search)

Open the homing screen with the compass icon in the map bar. It combines the estimate with signal strength for the last metres.

- **Arrow:** a large arrow points to the most likely location with the distance, and a note when you are inside the 1σ region. The
  arrow uses the GPS course above 1.5 m/s and otherwise the compass plus declination; without a compass (web) it points relative to
  north.
- **Level history and track:** the signal history is charted, and your track is coloured by field strength (blue weak, red strong),
  with the map next to it.
- **Quick entry** (pinned at the bottom): S-meter buttons from S1 to S9+60 (S9 = −93 dBm, 6 dB per S-unit, IARU VHF/UHF), a dBm
  field, an attenuator selector (off/10/20/30/40 dB) and a switch "log the last value every 2 s".
- The readings go through the same offline queue as everything else. They are never deleted, only deactivated.

## How the signal is used

The engine fits a log-distance path-loss model with unknown exponent and reference level at every candidate point, after
correcting the readings for the attenuator, and adds this as a likelihood to the bearings. Fewer than 5 readings are ignored. See
[Engine](../concepts/engine.md#rssi-fusion-homing). Reflections and shadowing create outliers; bearings remain more reliable.

## Radio (CAT) input

The app has protocol codecs and calibration for reading the S-meter from radios (Icom CI-V, Kenwood/Yaesu ASCII) but no transport
yet, so values are typed in for now ([limitations](../reference/limitations.md)).
