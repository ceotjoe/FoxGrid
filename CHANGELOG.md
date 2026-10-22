# Changelog

All notable changes. Versions follow the app's `pubspec.yaml`; dates are from the Git tags. The project uses
[Conventional Commits](https://www.conventionalcommits.org/).

## Unreleased

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
