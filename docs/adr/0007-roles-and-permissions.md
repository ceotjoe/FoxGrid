# 0007 – Roles and permissions

**Status:** accepted (v0.5.0)

**Context.** There was one privileged role, the lead. Everyone else was equal. Real missions need more: someone who judges the
data without administering the group, someone who runs chat and tasks, a guest who may only look. The old check
(`role == "lead"`) was spread over about 25 places in the backend and several in the app.

**Decision.**

- Two independent axes. `participants.role` (`mobile` / `fixed` / legacy `lead`) stays the data *source*: it decides whether
  omnidirectional readings are accepted. The new `participants.authority` is the *standing* in the mission:
  `lead`, `deputy`, `analyst`, `coordinator`, `member`, `station`, `observer`. A person at a fixed location can be an analyst; a
  mobile bearer can be the lead.
- One table, `backend/app/services/permissions.py`, maps each authority to a set of permissions (`bearing.flag`, `point.manage`,
  `chat.read`, …). Endpoints declare what they need with `require(Permission.X)`; nothing compares roles any more. Unknown
  authorities carry no permissions (fail closed).
- Permissions are read from the database on every request, so a role change takes effect at once. The JWT only identifies.
- Only the lead assigns roles (`role.assign`), only to active participants, and a mission always keeps at least one lead. A
  non-lead can never change or quarantine a lead. Invites yield `member` (or `observer`, which needs `invite.manage`).
- `trusted` stays a separate flag: a promotion does not make anybody trusted. The exception is the legacy `role` field, which keeps
  its old behaviour. Observers never feed the estimate, whatever their trust flag says (`domain.trusted_only`).
- Observers get no chat and no positions of others: not through REST, not in the snapshot, not on the live channel (events are
  filtered per permission), and exports leave out the tracks. A role change closes the participant's WebSocket (code `4409`); the
  app reconnects and reads its new permissions from the snapshot.
- The app mirrors the permission names only to show or hide functions. The server enforces everything.
- `station` belongs to the virtual participant of a sensor and is never assigned by hand.

**Consequences.** Rights are easy to read (one table), to test (one test per endpoint and authority) and to extend. Plain members
can no longer create tasks (that is the coordinator's job). Observers still see the *locations of bearings* because the result
cannot be shown without them; only live positions and tracks are withheld. `team.manage` exists in the table but no endpoint uses
it yet. Not covered: a lead who misuses the role (that is a matter of choosing the people). See
[Roles and permissions](../user-guide/roles.md) and [Access control](../user-guide/mission-lead-security.md).
