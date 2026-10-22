# Domain rules

These rules are binding. They protect the integrity of the data and the validity of the estimate. Code and tests must not
violate them.

## Bearings

- **Azimuth is always stored as true north** ("rechtweisend"). The app converts compass or magnetic input using the magnetic
  declination for the position (World Magnetic Model, `GET /declination`). For manual input the user picks *true* or *magnetic*.
  The server stores which reference was entered (`azimuth_input_ref`: `true`, `magnetic`, `compass`) and the declination
  applied (`declination_deg_applied`) for audit.
- **`sigma_deg` is mandatory** and strictly positive. Presets in the app: sharp ±5°, medium ±15°, poor ±30°.
- **Bearings are never deleted.** They can be flagged as outlier or deactivated. Edits are append-only revisions
  (`bearing_revisions`). A database trigger forbids `DELETE` on `bearings` (and on `rssi_samples`). The log stays complete.
- **Bearings carry a client-generated UUID.** This makes offline sync idempotent: a duplicate `POST` with identical content is
  a no-op (200), different content under the same ID is a 409.
- **Timestamps** come from the client in UTC (`measured_at`); the server additionally stores `received_at`.
- Every new or changed bearing triggers an **estimate recompute** in the background (debounce 500 ms, see
  [Architecture](architecture.md)).

## Data retention

- Position tracks are purged N days after the mission ended (default 30, `track_retention_days`, configurable per mission).
- Bearings and RSSI readings are kept.

## Authentication and trust

- No passwords. Each mission has **invite tokens** (QR code or link); the participant gives a callsign and receives a JWT.
- An invite decides the role of a new participant (`mobile` or `fixed`). Leads only arise by promotion.
- Whether a participant's data influences the estimate depends on **trust**. Every query feeding an estimate must go through
  `domain.trusted_only(stmt, Bearing | RssiSample)`: recompute (including calibration offsets), `/estimate/query` and
  `/suggestions`. A new such query must use it as well. Untrusted data is still stored, listed and exported.
- Details: [Access control and security](../user-guide/mission-lead-security.md).

## Radio conventions

- FoxGrid targets VHF/UHF at any frequency (for example 2 m, 70 cm, 23 cm). Below 30 MHz the app only warns.
- The S-meter scale is the IARU VHF/UHF convention: S9 = −93 dBm, 6 dB per S-unit (single place to change:
  `app/lib/core/signal.dart`).
- Fixed omnidirectional stations report the S-value of the interferer on the repeater **input** frequency (on the output you only
  hear the repeater). See [Fixed stations](../user-guide/omni-stations.md).

## Ask, do not guess

For questions of direction-finding technique or amateur radio, ask the maintainers instead of guessing.
