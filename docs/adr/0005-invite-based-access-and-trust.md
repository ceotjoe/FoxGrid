# 0005 – Invite-based access, device binding, approval and trust

**Status:** accepted (access control steps A–E, October 2026)

**Context.** There are no passwords, so a leaked invite link is the main threat (saboteurs, impersonation, false data).

**Decision.** Layered measures: invites expire (24 h) and are limited (20 uses); a per-install device secret binds a callsign to a
device; new joiners wait in an approval queue with a spoken four-digit code; roles come only from the lead; only trusted
participants feed estimates (`domain.trusted_only`); the lead can quarantine; rate limits and plausibility hints; a security log.

**Consequences.** Strong protection against link leaks without passwords, at the cost of a manual approval step (skippable with
`auto_approve` for exercises). Not covered: unlocked stolen devices, compromised servers, deliberate bad data from several trusted
accounts. See [Access control](../user-guide/mission-lead-security.md).
