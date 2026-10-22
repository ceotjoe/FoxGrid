# 0003 – Bearings are never deleted

**Status:** accepted

**Context.** A hunt may be reviewed afterwards, and a malicious or mistaken participant must not be able to erase evidence.

**Decision.** There is no delete endpoint; database triggers forbid `DELETE` on bearings, revisions and RSSI readings. Bearings
can be flagged as outliers or deactivated, each change creating an append-only revision. Azimuth is always stored as true north with
the input reference and applied declination recorded.

**Consequences.** The log is always complete and auditable; quarantine and trust act by deactivating, never deleting. Only
position tracks are purged after the retention period. See [Domain rules](../concepts/domain-rules.md).
