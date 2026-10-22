# The engine (`foxgrid_engine`)

`engine/foxgrid_engine` is a self-contained Python package (numpy and pyproj only; **no web or database dependencies**). It
takes plain data structures and returns result dataclasses. The backend calls it in a thread pool.

```python
estimate(bearings, params, rssi=[...])  # -> Estimate
```

## Bearing fusion

- The grid lives in a local metric projection (UTM via pyproj). It covers the stations plus robust ray intersections plus a margin
  (default ≥ 5 km), capped at `max_cells` per axis (default 250; the resolution is coarsened to respect that). Default cell size 50 m.
- Per bearing and cell: a **von Mises** density over (measured azimuth − direction station→cell), with concentration κ derived from
  `sigma_deg` (κ ≈ 1/σ², σ in radians).
- **Outlier mixture:** each bearing is a mixture of the von Mises term and a uniform term with weight ε (default 0.1,
  `outlier_fraction`). Cells behind the station (more than 90° off) get only ε.
- **Fusion** = sum of the log-likelihoods of the active, trusted bearings. Optional **age decay** (half-life, `half_life_s`) and
  **per-transmission scoping** (estimate scopes `current` and `all`).
- The maximum is refined (`refine_steps`, default 2).

Output (`Estimate`): MLE point, covariance, 1σ and 2σ error ellipses, probability-mass **contours** (50/80/95 %, GeoJSON polygons
via marching squares in `contours.py`; the API stores them keyed `"50"`/`"80"`/`"95"`), optionally a PNG raster (not implemented yet).

Performance budget: 200×200 cells with 50 bearings in under 200 ms (vectorised numpy).

## RSSI fusion (homing)

`rssi.py` adds a second likelihood from signal levels. For each candidate point a weighted least-squares fit of the log-distance
path-loss model

```
level = p0 - 10 n log10(d)
```

(with the exponent `n` clipped to [1.5, 6]) gives a Gaussian log-likelihood from the residuals. Levels are `rssi_dbm + attenuation_db`
(the attenuator is corrected first).

- Fewer than `rssi_min_samples` (5) readings are ignored. An RSSI-only estimate is allowed.
- Only the newest `rssi_max_samples` (300) are used, since the cost grows with the number of samples.
- Both estimate scopes use the readings of the same transmission scope.
- The fit is exposed as `EstimateOut.rssi` (`params.rssi_fit`: p0, n, residual scatter and, for fixed stations, offsets).

## Fixed omnidirectional stations

Readings marked with `RssiSample(group=<station>, event=<transmission>)` come from fixed stations. The model becomes

```
level = p0 + b_k - 10 n log10(d)
```

with a per-station offset `b_k ~ N(0, rssi_station_sigma_db)` (antenna, cable, receiver; default 6 dB). It is solved as a
generalised least-squares problem via the Woodbury identity (`_fit_arrays` in `rssi.py`).

- One reading per (station, transmission) is used (the median, `usable_samples`).
- At least `rssi_omni_min_stations` (4) distinct stations are needed; the homing track still needs `rssi_min_samples`.
- `RssiSample.offset_db` is a known calibration offset; `RssiFit.station_offsets_db` returns the estimated ones.
- **Expected accuracy** (`uv run tools/simulator/omni_eval.py`): a coarse area only, median error 1–4 km for stations 2–15 km away.
  Bearings dominate as soon as they exist.

## Position suggestions

`suggest.py` proposes the best places for the next bearing, with the expected gain in area. It uses the analytic **Fisher
information** of the bearings, deliberately not the grid posterior: the posterior's outlier-mixture tails make a good extra bearing
look like it grows the ellipse. Suggestions are computed per request (milliseconds); nothing is stored.

## Tunable parameters

User-tunable per mission (`engine_params`, validated by `EngineParamsIn`):

| Parameter | Default | Meaning |
|---|---|---|
| `resolution_m` | 50 (5–1000) | grid cell size |
| `outlier_fraction` | 0.1 | ε of the uniform outlier mixture |
| `half_life_s` | off | age weighting |
| `margin_m` | 5000 (1000–100000) | margin around stations and intersections |
| `use_rssi` | on | include the homing RSSI track |
| `rssi_sigma_db` | 6 | fading and measurement scatter around the model |
| `rssi_weight` | 1 | scales the RSSI log-likelihood against the bearings |
| `rssi_station_sigma_db` | 6 | spread of the unknown receiver offsets (fixed stations) |
| `rssi_omni_min_stations` | 4 | minimum number of distinct fixed stations |

## Tests

`cd engine && uv run pytest`. Coverage must stay above 90 %. The suite checks, among others: an exact 3-bearer hit within 20 m, noisy
bearings within the 2σ ellipse, a gross outlier barely shifting the result, parallel bearings giving an elongated ellipse, and the
359°/1° wraparound. `mypy --strict` is required for the package.
