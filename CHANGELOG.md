# Changelog

All notable changes. Versions follow the app's `pubspec.yaml`; dates are from the Git tags. The project uses
[Conventional Commits](https://www.conventionalcommits.org/).

## Unreleased

- KrakenSDR in a vehicle (step 1 of 7, [ADR 0010](docs/adr/0010-vehicle-mounted-kraken-sdr.md)): `tools/kraken_bridge` runs on the Kraken's Raspberry Pi, reads the DSP software's "Kraken App" output and gpsd, and sends averaged, thinned true bearings with their own sigma to the MQTT ingest through a persistent outbox. The heading comes from the GNSS course and is frozen while parked. `--simulate` drives a simulated car past a hidden emitter. No backend changes in this step.
- Mobile stations (step 2 of 7): the MQTT heartbeat (`status`) may carry `lat`, `lon`, `speed`, `heading` and `at`, which become the station's track on the map. Sensors get a `weight` (0–2, used by the engine since step 3) and an optional default interferer; bearing and RSSI messages may name an `interferer`. Merging interferers moves sensor defaults. The Kraken bridge sends its heartbeat with position every 10 s and takes `--interferer`.
- Backend: one new migration (0015); run `alembic upgrade head` when deploying.
- Engine (step 3 of 7): bearings may carry a `weight`, their own `outlier_fraction` and a `group`. Same-group bearings share their weight within `cluster_radius_m` (default 75 m), so a long stop of a station counts like one bearing while a drive keeps its value. The backend passes the sensor id as group, the sensor's weight, and `sensor_outlier_fraction` (default 0.2) for sensor bearings. Both new parameters are tunable per mission. Changing a sensor's weight triggers a recompute.
- Manual gate (step 4 of 7): sensors get `gated` (on by default for stations without a fixed position). Their bearings count only if the whole averaging window (`window_start`/`window_end`, new in the MQTT bearing message) lies within a transmission; the others are stored with `gate_state = outside`. The state is re-evaluated when a transmission starts or stops (also backdated) and when the setting changes; `gate_override` on a bearing (PATCH, `bearing.flag`) counts or excludes it by hand and wins. A backdated start never reaches before the previous transmission's end. New event `bearings_updated`. Kraken bridge: windows end at a pause in the readings (`--gap`, default 1.5 s) and each bearing carries its window. App: next to *Aussendung Start* a button starts the transmission backdated ("Sendet seit 5/10/30 s"); rays of bearings outside a transmission are drawn dashed like other bearings that do not count.
- Backend: one new migration (0016); run `alembic upgrade head` when deploying.

## 0.7.0 – 2026-11-24

- App: unified layout of dialogs, sheets and buttons. One component theme (`ui/app_theme.dart`) and shared building blocks (`ui/app_dialogs.dart`: `AppDialog`, `confirmDialog`, `AppSheet`, `ActionBar`, `FieldRow`, `CoordinateFields`). Buttons in a row are equally sized and never wrap their label; when labels do not fit side by side they stack. The accuracy (sigma) presets are one row, the S-meter quick values a fixed 5×2 grid, and the quarantine dialog has two buttons plus an "also remove" checkbox. See [App internals](docs/development/app.md).
- App: the red night theme uses dark red borders and dividers instead of the near-white default; the map title has a left margin; the map source selector says "Eigener" instead of "Eigener Server".
- Retroactive bearings: *Menü → Peilung nachträglich* lets a bearer enter a bearing afterwards with a chosen time (up to 7 days back) and position (map, typed coordinates, own track at that time, or the current GPS fix). The bearing counts for the estimate like a live one and is marked "nachträglich" in the list. Backend: `entry_mode` on bearings (migration 0014), `measured_at` may not lie in the future, retroactive bearings skip the own-track plausibility checks. See [ADR 0009](docs/adr/0009-retroactive-bearings.md).
- Backend: one new migration (0014); run `alembic upgrade head` when deploying.

## 0.6.1 – 2026-11-24

- App: the bearing sheets (own bearing and external point) have a close button and an "Abbrechen" button. Closing with typed input (button, back gesture, tap outside, drag down) asks before discarding it.
- No backend changes and no migrations.

## 0.6.0 – 2026-11-24

- App: level fields (bearing capture, homing, station) take either dBm or an S value (`7`, `S9+20`); a unit button switches and remembers the choice, and the capture sheet gets the S buttons too.
- App: dBm fields (bearing capture, homing, station) have a ± button (cycles no sign, `-`, `+`) for keyboards without a minus key, and a level typed without sign is stored as negative (so `90` = −90 dBm; type `+5` for a positive level).
- Several interferers per mission (backend, step 1 of 4): new `interferers` table, `interferer_id` on bearings, RSSI readings and
  estimates (migration 0013; existing missions get "Störer 1" with all their data). Each interferer has its own estimate;
  `/estimate`, `/estimate/query` and `/suggestions` take `interferer=`; bearings can be reassigned (revision); new permission
  `interferer.manage`; JSON export lists interferers. Old clients keep working (default interferer). App (step 2 of 4): interferers in the model, state and outbox; the capture sheet has an interferer chip, *Menü → Störer* manages them, a long press reassigns a bearing; Map (step 3 of 4): one estimate per interferer, each in its own colour family (shaded by field strength; brightness, dash pattern and letter badge in the red night mode), a legend that is also the quick filter, and an interferer filter (hide or dim the others) in the filter sheet.
  Step 4: merge two interferers (`POST …/interferers/{id}/merge`, menu *Störer → Mit anderem zusammenführen*), exports (GPX, KML, PDF) with every interferer's estimate, the transmission push names the interferer, and `tools/simulator/run.py --two-interferers`.

## 0.5.1 – 2026-11-16

- Maintenance release: no functional changes and no migrations.
- App: migrated to `material_ui` for Flutter 3.50; updated drift, drift_dev and flutter_riverpod.
- Backend: updated fastapi, pydantic, geoalchemy2 and opentelemetry-api; engine and backend dev tools (ruff, pytest-asyncio).
- Dependabot ignores Firebase major bumps.

## 0.5.0 – 2026-11-05

- Roles and permissions: besides the data source (`role`) a participant now has an `authority`: lead, deputy (*Co-Leiter*), analyst
  (*Auswerter*), coordinator (*Koordinator*), member (*Peiler*, the default), station or observer (*Beobachter*). One table
  (`backend/app/services/permissions.py`) says what each may do; endpoints use `require(Permission.X)` instead of comparing roles
  (migrations 0011 and 0012, [ADR 0007](docs/adr/0007-roles-and-permissions.md), [Roles and permissions](docs/user-guide/roles.md)).
- The lead assigns roles (`PATCH …/participants/{id}` with `authority`); a mission keeps at least one lead and only a lead can
  change a lead. Invites can be created for observers (`default_authority`). Analysts can manage external points and enter external
  bearings, flag outliers and set trust; coordinators run chat, tasks and ordinary invites.
- Observers see the result but no chat, tasks or positions of others (REST, snapshot, live events, export tracks) and never move
  the estimate. Plain members can no longer create tasks. A role change renews the live connection (close code 4409).
- App: functions are shown by permission, role picker in the participant list, observer invite, own role changes take effect live.
- Older app versions do not know roles and show their menus by the old `role`; the server still enforces everything.

## 0.4.0 – 2026-11-05

- Backend: external bearing points (`/points`) so the lead can enter bearings received from outside the group (e.g. BNetzA); per-point switch for the estimate (migration 0010). App: model, state, outbox and live events for points; the lead can add points on the map, by coordinates or from the device location and enter bearings for them; the map shows points and their rays, with a filter switch. Exports (PDF, GPX, KML, JSON) name the points.
- App: remember the last map view per mission.
- Documentation consolidated, restructured and translated to English (see [docs/README.md](docs/README.md)).

## 0.3.1 – 2026-10-20

- Only the starter of a transmission or the lead can stop it.
- Fix: install the `requests` extra for `google-auth` so FCM push works; document that the FCM key file must be readable by the container user.

## 0.3.0 – 2026-10-20

- Rejoin a mission without an invite using the device secret; a returning lead can create a new invite link.
- App remembers the last server and callsign, shows the invite as QR code and opens `foxgrid://` links.

## 0.2.0 – 2026-10-20

- Push notifications: the app registers its FCM token (Android and iOS), server-side delivery via FCM HTTP v1.
- The lead can end a mission; connected members are notified.
- Server deployment guide; web app deployed to GitHub Pages; Liquid Glass app icon for iOS 26.

## 0.1.0 – 2026-10-19

First store release, covering the phases below.

**Phase 1 – MVP.** Missions, invite-token join, positions, manual bearings, live ray fan, MLE point and error ellipse, start/stop of
transmissions, outlier marking (bearings are never deleted). Mission simulator.

**Phase 2 – robustness and coordination.** Probability-mass contours (50/80/95 %), filters by transmission, time window and age
weighting; chat (mission and team channels) and tasks; offline-first sync queue; tile cache; WMM declination; GPX/KML/JSON/PDF
export; night mode; push on transmission start (server side).

**Phase 3 – homing.** Homing screen, S-meter entry, RSSI logging, RSSI fusion with a fitted log-distance path-loss model, CAT radio
abstraction (protocols and calibration).

**Phase 4 – automation.** MQTT ingest for automatic bearing stations, relay hook (squelch open without CTCSS), position
suggestions for the next bearing, sensor management.

**Phase 5 – omnidirectional stations.** Fixed stations report S-values on the repeater input; engine fusion with per-station
offsets, repeater calibration, distance rings on the map.

**Access control.** Expiring and limited invites, device binding, approval queue with join code, roles only from the lead, trust and
quarantine, rate limits, plausibility hints, security log.

**Branding and release.** Fadenkreuz-Fuchs app icon, store graphics and metadata (de-DE, en-US), tag-driven release workflow.
