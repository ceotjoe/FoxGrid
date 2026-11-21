# 0008 – Several interferers per mission

**Status:** accepted (unreleased)

**Context.** A mission had exactly one estimate, so bearings of two interferers on the same band were fused into one wrong
position. Teams need to tell the sources apart, filter the map by source and see each one's result.

**Decision.**

- New entity `interferers` (client UUID, name, `color_slot` 0–5, `status`, `is_active`; never deleted). Every bearing and every
  RSSI reading carries a NOT NULL `interferer_id`; transmissions carry an optional one as the default for their bearings.
- Estimates are computed per interferer and scope (`estimates.interferer_id`). The engine stays untouched: it gets one
  interferer's bearings. `current` is the newest transmission with data for that interferer. Calibration readings serve all.
- Mandatory assignment instead of an "unassigned" bucket: a bearing without one would feed no estimate. Clients preselect the
  active interferer; a request without one falls back to the transmission's, then the mission's default interferer, so older
  clients and MQTT sensors keep working. The migration creates "Störer 1" for every existing mission.
- Reassigning is an append-only revision. The owner may reassign; others need the new permission `interferer.manage`
  (lead, deputy, analyst).
- At most 6 active interferers: the clients have six colour families, each with a letter badge for the red night mode.

**Consequences.** One transmission still has at most one open slot per mission, so truly simultaneous interferers are told apart
per bearing, not per transmission. Stations (MQTT) report for the default interferer until a sensor-level setting exists.
Two interferers that turn out to be one are merged (`POST …/merge`): all data moves as revisions and the source is deactivated. Exports (JSON, GPX, KML, PDF) carry every active interferer's estimate, named; the transmission push names the interferer when there are several.
