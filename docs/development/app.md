# App internals

Flutter app for Android, iOS and the web control room. Stack: `flutter_map` (OSM / OpenTopoMap), Riverpod, `geolocator`,
`flutter_compass`, `drift`, `dio`, a WebSocket client.

```
app/lib/
  core/    api (Dio), models, session, live (WebSocket), outbox + sync (offline queue), database (Drift), geo, homing,
           signal (S-meter), tile_cache, push, device_secret, recent_missions, radio/ (CAT protocols)
  state/   Riverpod providers: providers, filter, settings, tiles, push, deep_link, app_info
  ui/      screens and sheets: join, pending, map, capture, bearings, homing, station, chat, tasks, participants,
           sensors, audit, suggestions, filter, sync, settings
```

## Offline-first

All writes go through `MissionNotifier` to the local Drift database first (`OutboxStore`: Drift on native, memory on web), then
`SyncService` sends them: head-of-line, exponential backoff, 4xx marks an entry failed and visible, 409 on transmission start/stop
counts as success, 429 is retried. `app/lib/core/database.g.dart` is generated (`dart run build_runner build`) and committed.

## Maps and tiles

`flutter_map_tile_caching` is incompatible with flutter_map 8 / latlong2 0.10, so `core/tile_cache.dart` is a small file cache of
our own. Bulk download is blocked for public OSM servers (tile usage policy). The last map view is remembered per mission.

## Join and session

- `JoinScreen` remembers the last server and callsign (SharedPreferences `foxgrid.last_server` / `foxgrid.last_callsign`, written
  after a successful join/create). Release builds accept HTTPS servers only (`serverUrlError` in `join_screen.dart`); cleartext is
  allowed in the debug manifest only.
- The invite dialog shows the link as QR (`QrPainter` in a `CustomPaint`; `QrImageView` crashes inside `AlertDialog` because of its
  `LayoutBuilder`).
- Deep link `foxgrid://join?server=&token=` is registered in `Info.plist` and `AndroidManifest.xml`; `state/deep_link.dart`
  (`app_links`) offers it through `pendingInviteProvider`. The join screen only fills in server and invite and switches to the join
  tab; it never joins automatically. Not yet tried on a real device.
- Returning without an invite: `POST /missions/{id}/rejoin` (callsign + device secret). `SessionNotifier.refresh()` runs when the
  JWT has less than 12 h left (checked every 5 s tick, at most every 5 min) and on a 401 snapshot; only `denied` logs out, being
  offline keeps the session. `RecentMissionsStore` (SharedPreferences, no secrets) feeds the "Zuletzt benutzt" list.
- **Permissions.** Participant records carry `authority` and `permissions`; the session stores them (`Session.can(Perm.x)`,
  `core/permissions.dart` has the names and German labels). Older stored sessions fall back to the role until the server's list
  arrives. The UI only shows or hides functions; the server enforces. A role change closes the live socket (4409), the app
  reconnects and `MissionNotifier._syncOwnSession` updates the session from the snapshot. Never test `role == 'lead'` in the UI.
- `Session.status`, `ui/pending_screen.dart` (gate in `main.dart`) and `ui/participants_screen.dart` (lead menu with badge) implement
  the approval flow; `MissionNotifier.applyParticipant` also updates the own role live.
- The device secret (`core/device_secret.dart`) is a random per-install value in SharedPreferences.

## Signals and homing

- The S-meter convention (IARU VHF/UHF, S9 = −93 dBm, 6 dB per S-unit) lives in `core/signal.dart`: one place to change. `parseSLevel` reads typed S values; `DbmField` (`ui/dbm_field.dart`) has a dBm/S unit button whose state is `AppSettings.levelInS` (persisted), and `parseLevel` is the single entry point for all level fields.
- The homing screen has scrolling content plus a pinned `_EntryPanel`, so S-meter taps never scroll away.
- `core/radio/` has protocol codecs (Icom CI-V, ASCII `SM0`), `RawScale` calibration and `RadioSignalSource`. There is no
  `RadioTransport` implementation yet (needs USB/Bluetooth plugins).

## Fixed stations

`ui/station_screen.dart` (role `fixed` or lead) with S-value buttons, a calibration switch and a lead dialog for the repeater.
Readings go through `MissionNotifier.logRssi(receiver: 'omni', isCalibration: ...)`, the repeater through `setRepeater` (outbox kind
`mission`, PATCH). A station can type in a fixed location (`stationPositionProvider`, persisted per mission) which wins over GPS.
The map draws, per station, the distance ring from `ringDistanceM` (`core/signal.dart`) using the estimate's `rssi` fit (p0, n,
offsets) with ± residual bands; the filter toggle is `showRings`. The calibration offset is not known to the app, so rings use only
the estimated offset. Homing dots show `mobile` readings only.

## Interferers

`Interferer` (`core/models.dart`) and `MissionState.interferers` (snapshot `interferers`, live `interferer_created` /
`interferer_updated`). Bearings, readings and transmissions carry `interfererId`. `MissionState.estimates` is keyed by
`estimateKey(interfererId, scope)` (`interferer:scope`; the plain scope for a server that predates interferers, which then answers
for everybody); read it with `estimateFor` / `bestEstimateFor`, never by scope alone.

The **active interferer** is what new bearings, readings and transmissions are for: `activeInterfererProvider` (chosen, persisted per
mission) resolved by `effectiveInterfererId` (chosen while it exists and is active, else the oldest active one; `null` for an older
server, then no `interferer_id` is sent). `MissionNotifier` computes it itself instead of reading `activeInterfererIdProvider`
(that provider watches the mission state: a cycle). `saveBearing` and `logRssi` add it centrally; calibration readings carry none.

`createInterferer` (lowest free colour slot, at most 6 active), `patchInterferer` and `reassignBearing` go through the outbox (kinds
`interferer_create`, `interferer_patch`, `bearing_interferer`, `interferer_merge`) and are re-applied by `_overlayPending`. UI: the chip in the capture sheet
switches the active interferer; *Menü → Störer* (`ui/interferers_screen.dart`) adds, renames, marks as found and deactivates; a long
press on a bearing in the list reassigns it (owner, or `interferer.manage`). 

**Peilungen verwalten** (`ui/manage_bearings_screen.dart`, ADR 0010; menu entry for `bearing.flag` or `interferer.manage`) works on
the bearings the app already holds (snapshot plus live events), so it needs no extra loading and works offline. Filters: stations
only, sensor, interferer, gate state (`GateFilter`, the same definitions as the server's `state`). The timeline (`_Timeline`,
a `CustomPaint`) draws azimuth over time with transmissions as bands; dragging selects a time range, a transmission chip selects
its bearings (with the server's 5 s slack). Bulk actions open a map preview of the selected rays and then call
`MissionNotifier.bulkUpdateBearings`: optimistic, outbox kind `bearing_bulk` in chunks of 500 (`POST …/bearings/bulk`), re-applied
by `_overlayPending`. The gate actions only send sensor bearings. `bearings_updated` events update many bearings at once.

**Mobile stations** (ADR 0010). *Sensoren* (`ui/sensors_screen.dart`) opens `SensorSettingsSheet` on a tap: weight (slider
0–2), default interferer and the gate ("Nur bei „Störer sendet“ zählen"), saved with one `PATCH …/sensors/{id}` (online, like the
rest of the sensor administration; only changed fields are sent). On the map a participant with authority `station` and a
position is drawn as a vehicle (`_vehicleMarker`: car, course arrow and km/h while moving, faded after 2 minutes without a fix).
Station trails keep 360 points instead of 60, and after each snapshot `_loadStationTracks` fetches the last hour of their
track (`positionsSince`). Sensor rays are thinner and their fans fainter; sensor bearings that do not count (`gateCounts`) are
hidden unless *Filter → Nicht gezählte Stationspeilungen zeigen* (`BearingFilter.showStoredSensor`) is on, then dimmed and
dashed.

**Map.** With a single interferer the map looks as before (participant colours, red estimate). With several (`state.interferers.length > 1`)
it draws one estimate per shown interferer (ellipses, contours, MLE marker with letter badge, station rings from that interferer's
readings) and colours each bearing with its interferer's family from `MapPalette.interferer(slot)`, shaded by field strength
(`interfererSignal`: weak = pale by day, dim by night). Each ray ends in a letter badge. The red night mode has only red hues, so the
slots also differ in brightness and dash pattern (`interfererDash`: solid, dashed, dotted) and the badge. `BearingFilter.interfererIds`
(empty = all) hides the other interferers' bearings, estimates and readings, or with `dimOthers` fades their bearings to 25 %. The
legend (chips under the scope buttons) is the quick filter: tap = only this one (again = all), long press = add to / remove from the
selection; the filter sheet has the same choice. Ad-hoc estimates (`filteredEstimatesProvider`) are queried per shown interferer.

## External bearing points

`BearingPoint` (`core/models.dart`) and `MissionState.points` (snapshot `points`, live `point_created` / `point_updated`). The lead's
`MissionNotifier.createPoint`, `patchPoint` and `saveExternalBearing` write through the outbox like everything else (kinds
`point_create`, `point_patch`, `bearing` with `point_id`); queued points are re-applied by `_overlayPending`. A point's position is
immutable and an external bearing always uses the point's position and `azimuth_input_ref: true`. The lead finds the list (`ui/points_screen.dart`: estimate
switch, deactivate, bearing count) under *verwalten → Externe Peilpunkte*. `ui/point_editor_screen.dart` creates a point: tap on the
map, typed coordinates or the device location keep one marker and two fields in sync; the name must be unique (the server enforces
it too). `core/coords.dart` parses decimal degrees, degrees + decimal minutes and degrees/minutes/seconds with N/S/E/W/O. `ui/external_bearing_sheet.dart` enters
a bearing for a point (true azimuth, sigma preset, measurement time, note; "save and more"); it is opened from the list and right
after a point is created. The map draws each point as a labelled marker in its own colour (`point:<id>` through `MapPalette`), its
rays dashed when the point is off or inactive; `BearingFilter.showExternal` hides points and rays (display only).

## Retroactive bearings

`CaptureSheet(retroactive: true)` (menu *Peilung nachträglich*, needs `bearing.create`) replaces the GPS fix and `now` with a chosen time
(date/time picker, 7 days back) and position: map (`ui/position_picker_screen.dart`), typed coordinates (`core/coords.dart`), the own
track at that time (`FoxGridApi.positionsSince`, nearest sample within ±15 min) or the current fix. The payload carries
`entry_mode: retroactive` and no `station_accuracy_m` unless the position came from a fix or the track. The declination is fetched for the
chosen position. Everything else (outbox, `_overlayPending`, sigma, interferer) is the normal bearing path. `Bearing.retroactive`
drives the "nachträglich" mark in the list.

## Dialogs, sheets and buttons

Component styling (button height and shape, input borders, dialog and sheet shape) lives once in `ui/app_theme.dart`
(`withAppStyle`, applied to all three themes); do not hard-code font sizes, button heights or `OutlineInputBorder` in screens.
Building blocks are in `ui/app_dialogs.dart`:

- `AppDialog` instead of `AlertDialog`/`SimpleDialog`, `confirmDialog(...)` for cancel/confirm questions (`destructive: true` for
  irreversible ones), `AppSheet` + `showAppSheet` for bottom sheets (pinned action bar above the keyboard).
- `ActionBar` with `AppAction`s: all buttons equal width and height, labels never wrap. When the labels do not fit side by side the
  buttons stack (main action on top). Keep labels short; at most one main action, "Abbrechen" first.
- `FieldRow` / `CoordinateFields` for paired inputs (equal width, stacked on narrow widths).

## Version and about

The single source of version and build is `version:` in `app/pubspec.yaml` (`x.y.z+build`). `appVersionProvider`
(`state/app_info.dart`, via `package_info_plus`) reads it at runtime. *Einstellungen* ends with "Über FoxGrid" showing
"Version x.y.z (Build n)"; a tap opens Flutter's `AboutDialog` (the one exception to `AppDialog`, because it links the
open-source licence page).

## Push

`PushRegistrar` (`state/push.dart`, `core/push.dart`) registers the FCM token. See [Push notifications](../operations/push-notifications.md).
Firebase config files are gitignored and come from CI secrets.

## Tests

`flutter analyze` with zero warnings; widget tests for the capture flow. See [Setup and testing](setup-and-testing.md) for
conventions.
