# Fixed omnidirectional stations

Stations with omnidirectional antennas (role *fixed*) can contribute even though they cannot take a bearing. They report the S-value
of the interferer; the engine fuses the levels of several stations into a **coarse area**.

## Reporting

- Open the tower icon in the map bar (role *fixed* or lead) and tap the S-value.
- **Measure on the repeater input frequency** (use the reverse key of the radio): on the output you only hear the repeater.
- The location comes from GPS or from a typed fixed location (for example your home QTH); the fixed location is stored per mission
  and wins over GPS.
- Reports go through the same offline queue as all other readings.

## Calibration (optional)

The lead sets the repeater location (Station → "Relais festlegen", or `PATCH /missions/{id}`). Each station then measures the level of
the repeater **output** once with the calibration switch on; the server derives the relative offsets of the stations from that.
Calibration readings never enter the fit directly.

## What you see

- Per station a marker with the latest S-value (blue weak, red strong) and a **distance ring** where the level model places the
  interferer, plus two pale rings for the scatter of the fit (switch off in the filter). Where the rings meet lies the estimate.
- The repeater is drawn as a tower.

## What to expect

At least 4 distinct stations are needed. Accuracy is a coarse area: median error of 1–4 km for stations 2–15 km away
(`uv run tools/simulator/omni_eval.py`). As soon as bearings exist they dominate.
