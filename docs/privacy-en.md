---
title: Privacy policy – FoxGrid
permalink: /privacy-en
---

# FoxGrid privacy policy

*Deutsche Fassung: [Datenschutzerklärung](privacy)*

Last updated: 17 October 2026

> **DRAFT – review before publishing.** Fill in "Controller" below and have the text legally reviewed,
> then remove this note.

## 1. What this is

FoxGrid is an app for radio amateurs who locate an interferer on VHF/UHF (for example a repeater) as a group. The app is a
**client for a FoxGrid server that your group runs itself**. There is no central FoxGrid service operated by
the app's publisher.

## 2. Controller

For the app (publisher in the App Store and Google Play): [name, address, e-mail of the publisher]

The publisher **does not collect, store or receive** any personal data from your use of the app.

For all data created while using a FoxGrid server, **the operator of that server** is responsible (usually the
person or club that gave you the invite link). Contact them for access, correction and deletion requests.

## 3. What the app processes

When you join an operation and while you use it, the app sends the following to the server you entered:

| Data | Purpose | When |
|---|---|---|
| Callsign and role (mobile/fixed) | Attribute bearings, chat and tasks to participants | Joining |
| Location (latitude, longitude, accuracy) | Position for bearings; showing participants on the map | Only while the app is open and after you allowed location access |
| Bearings (time, position, azimuth, uncertainty, field strength, note) | Compute the most likely interferer location | When you save a bearing |
| Signal levels (S-meter/dBm) | Homing and estimate | When you record them |
| Chat messages and tasks | Teamwork | When you send them |
| Access token (JWT) | Password-less sign-in to the server | Joining |
| Device secret (random, per installation; the server stores only a hash) | A callsign can only be re-joined from the same device | Joining |
| Last used server and callsign (stored only on the device, never transmitted) | Prefill the fields on the next start | Creating / joining a mission |
| 4-digit join code (only until approval) | Compare by radio with the mission lead | Joining through a link that needs approval |
| Push token (identifier of this device at Google Firebase Cloud Messaging, via Apple APNs on iOS) | Background notification when the interferer starts transmitting | After approval, only if you allowed notifications; removed when you leave the mission |
| Security log (who joined, was approved, removed or quarantined, and when) | Accountability for the mission lead | Ongoing, visible to the mission lead only |

The app does **not** request background location access. There are no ads and no analytics or tracking tools.
Data is only passed on for push notifications: the server hands the title, text and push token of a notification to
Google (Firebase Cloud Messaging) and, on iPhones, to Apple (APNs), which deliver it. If you decline notifications,
this does not happen.

## 4. Storage on your device

Credentials, settings, not yet synced entries (offline queue) and cached map tiles are stored locally on your
device. They are removed when you uninstall the app.

## 5. Retention on the server

The server operator decides. Default of the FoxGrid software: position tracks are deleted 30 days after an
operation ends. Bearings are kept for traceability (they are never deleted, only flagged as outliers or
deactivated). To have your data deleted, contact the server operator.

## 6. Map tiles

The map loads tiles directly from OpenStreetMap (tile.openstreetmap.org) or OpenTopoMap (opentopomap.org).
Technically this transmits your IP address and the viewed map area to those services. See their privacy
notices: <https://wiki.osmfoundation.org/wiki/Privacy_Policy> and <https://opentopomap.org/about>.

## 7. Connection

Store builds of the app connect to the server over HTTPS/WSS only.

## 8. Your rights

Under the GDPR you may request access, correction, deletion, restriction, portability and object to processing,
and you may lodge a complaint with a supervisory authority. Exercise these rights against the server operator;
the app can export an operation for this purpose.

## 9. Contact

[e-mail of the publisher]

Source code and issues: <https://github.com/ceotjoe/FoxGrid>
