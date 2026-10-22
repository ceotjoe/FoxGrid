# Coordination, offline use and export

## Chat and tasks

- **Chat** has a mission channel and team channels. Team messages stay private to the team.
- **Tasks** can be assigned to a team or a participant and track their status.
- Push notifications announce the start of a transmission to participants whose app is in the background.

## Offline use

- All writes go to the local database first and are sent through a sync queue with retry and backoff. The sync status is always
  visible in the bar at the top; failed entries stay visible.
- The last state is cached for an offline start. Bearings, readings, chat, tasks, outlier flags and transmissions are queued;
  position updates are not resent when the connection is missing.
- The automatic magnetic declination needs network once; then the cached value applies.
- On the web the queue exists only in memory.

## Maps

Tiles come from OpenStreetMap or OpenTopoMap and the viewed tiles are cached. Their usage policies forbid bulk downloads; a
targeted area download works only with your own tile server. See [limitations](../reference/limitations.md).

## Export

The map menu exports a mission as **GPX, KML, JSON or a PDF report** (map, bearings, result). The exports include the homing track
and readings.

## Appearance

Light, dark and system appearance, and a red night mode that preserves night vision.

## Sensors (lead)

Automatic bearing stations and a repeater hook report over MQTT; the lead creates them in the app under *Sensors*. See
[MQTT interface](../reference/mqtt.md).
