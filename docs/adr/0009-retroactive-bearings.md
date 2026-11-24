# 0009 – Retroactive bearings

**Status:** accepted

**Context.** Bearers sometimes cannot enter a bearing in the field (no time while driving, no GPS). They need to add it later
with the time and place it was taken.

**Decision.** `bearings.entry_mode` (`live` | `retroactive`) is stored separately from `source` (`manual`/`sensor`/`external`),
because the origin of the data and the way it was entered are independent. The existing `POST /bearings` accepts it; no new
endpoint. Retroactive bearings are limited to 7 days back, nothing may lie in the future, and they skip the own-track plausibility
checks. All other bearing rules (append-only, trust, sigma) stay.

**Consequences.** The estimate is recomputed on arrival and places the bearing by `measured_at`. The audit trail shows both
`measured_at` and `received_at` plus the entry mode. The app marks such bearings with a badge.
