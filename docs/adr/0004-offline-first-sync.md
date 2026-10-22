# 0004 – Offline-first app with an outbox

**Status:** accepted

**Context.** Hunts happen in the field with poor coverage.

**Decision.** All writes go to the local Drift database first and into an outbox, synced with head-of-line ordering and
exponential backoff. Bearings, readings, messages and tasks carry client-generated UUIDs so that retries are idempotent (duplicate
POST = 200, no-op). Timestamps come from the client in UTC; the server adds `received_at`.

**Consequences.** The app works without network and shows its sync status. On the web the queue is in memory only (no sqlite-WASM
shipped). Position updates are not queued. After a reconnect clients reload a snapshot instead of replaying events.
