# App internals

Flutter app for Android, iOS and the web control room. Stack: `flutter_map` (OSM / OpenTopoMap), Riverpod, `geolocator`,
`flutter_compass`, `drift`, `dio`, a WebSocket client.

```
app/lib/
  core/    api (Dio), models, session, live (WebSocket), outbox + sync (offline queue), database (Drift), geo, homing,
           signal (S-meter), tile_cache, push, device_secret, recent_missions, radio/ (CAT protocols)
  state/   Riverpod providers: providers, filter, settings, tiles, push, deep_link
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
- `Session.status`, `ui/pending_screen.dart` (gate in `main.dart`) and `ui/participants_screen.dart` (lead menu with badge) implement
  the approval flow; `MissionNotifier.applyParticipant` also updates the own role live.
- The device secret (`core/device_secret.dart`) is a random per-install value in SharedPreferences.

## Signals and homing

- The S-meter convention (IARU VHF/UHF, S9 = −93 dBm, 6 dB per S-unit) lives in `core/signal.dart`: one place to change.
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

## Push

`PushRegistrar` (`state/push.dart`, `core/push.dart`) registers the FCM token. See [Push notifications](../operations/push-notifications.md).
Firebase config files are gitignored and come from CI secrets.

## Tests

`flutter analyze` with zero warnings; widget tests for the capture flow. See [Setup and testing](setup-and-testing.md) for
conventions.
