# Access control and security for mission leads

FoxGrid has no passwords. Access to a mission hangs on an **invite link**. Anyone who knows the link could, without further
measures, read along or feed in false bearings. This document describes what FoxGrid does about that, what the mission lead
should do, and what is deliberately not covered.

## What can happen

| Case | Example | Countermeasure in FoxGrid |
|---|---|---|
| Link becomes known | It is posted in a group the interferer also reads | Expiry after 24 h, use limit, "Replace link", approval by the lead |
| Callsign is taken over | Someone joins as a colleague who has not joined yet | Callsigns are bound to a device; join code over the radio |
| False data | Someone sends bearings in the wrong direction | Trust level, quarantine, plausibility hints |
| Flooding | Chat messages or bearings are sent in bulk | Rate limits (HTTP 429) |
| Foreign device | Phone lost or stolen | Remove participant, release device |

## What FoxGrid does

1. **Approval queue.** Whoever joins through a link only sees a waiting screen. Map, bearings, chat, live channel and push
   notifications stay locked until the mission lead approves in the "Participants" menu. Rejected joiners cannot get back in
   with the link.
2. **Join code.** The waiting screen shows four digits. The same digits appear next to the entry on the lead's screen. The lead
   asks for the code over the radio: only someone who really sits in front of the device can say it. Someone impersonating a
   colleague who has not joined cannot.
3. **Device binding.** Every installation generates a random secret; the server stores only a hash. An existing callsign can
   only be re-entered with the same secret. When someone changes phones, the lead releases the device. The same secret also
   allows returning without an invite (`POST /missions/{id}/rejoin`): this is how the lead gets back into their own mission once
   the session (72 h) and the invite (24 h) have expired. This never creates a participant; removed, rejected, approved (without
   binding) and sensor participants always get the same refusal.
4. **Roles only from the lead.** A link always joins as "Mobile". "Fixed" and "Lead" are assigned by the lead.
5. **Trust.** Only trusted participants move the estimate. Approval and promotion by the lead count as trust. Links with
   `auto_approve` (for exercises) yield participants who are initially untrusted: their bearings are visible and in the log, but
   do not change the result until the lead trusts them.
6. **Quarantine.** Takes all bearings and readings of a participant out of the estimate at once, withdraws trust and can remove
   the participant in the same step. Nothing is deleted: the log stays complete and each bearing carries a revision.
7. **Plausibility hints.** The lead can have the data checked for inconsistencies (bearings against the result of the others,
   position jumps, bearing location against the participant's own track). These are hints, not verdicts.
8. **Rate limits.** Joins per client address; bearings, readings and chat per participant. The app resends later on 429.
9. **Security log.** The lead sees who joined, was approved, removed or quarantined, and who created or replaced invites. Failed
   attempts from foreign devices are listed as well.

## Checklist for the mission lead

**Before**

- Do not post the link in open or mixed groups. Better: hand it over in person, as a QR code, or in a group that contains only the team.
- Decide which radio net is used to ask for the join code.
- For exercises with a known group an `auto_approve` link may be used; not for a real mission.

**During the mission**

- Approve new entries under "Participants" only if the code matches over the radio and the callsign belongs to a known person.
- Once the team is assembled, **replace** the link (invite dialog → "Replace link"). People already in stay in.
- Check the plausibility hints now and then (magnifier in the Participants menu), especially when the result suddenly jumps.
- If in doubt: first **withdraw trust** (their data stops counting, nothing is lost); if the suspicion is confirmed, **quarantine**
  and remove.

**Afterwards**

- Review the security log before archiving the mission. It belongs to the mission's record.
- End the mission: afterwards no new participants can join.

## Invite links in detail

- Invites expire after 24 h by default and are valid for at most 20 new participants (`FOXGRID_INVITE_TTL_HOURS`,
  `FOXGRID_INVITE_MAX_USES`). If a link has fallen into the wrong hands,
  `POST /api/v1/missions/{id}/invites/{invite_id}/rotate` replaces it; participants who already joined stay in.
- "Replace link" in the invite dialog (`POST …/invites/replace`) revokes all open links and issues one new one.
- If someone changes phones, the lead releases the device (`PATCH …/participants/{id}` with `{"reset_device": true}`); after that
  a new join is enough.
- Whoever joins via a link is always "Mobile". "Fixed" (omnidirectional station) and "Lead" are only assigned by the lead
  (`PATCH …/participants/{id}` with `{"role": "fixed"}`) or by an invite with `default_role: "fixed"`.
- The lead can remove participants (`{"is_active": false}`): access ends immediately and open connections are closed. The
  participant's bearings are kept. Undo with `{"is_active": true}`.
- Rejected joiners cannot join again with the link. Invites with `auto_approve: true` skip the approval queue.
- Quarantine is undone only bearing by bearing (reactivate through `PATCH`).
- Plausibility hints (`GET …/plausibility`) cover: bearings that clearly miss the result of the others (needs 3 bearings in the
  result), position jumps above about 250 km/h, bearing locations far from the participant's own track, and bearings without any
  position report. Nothing is changed automatically.
- The security log is `GET …/audit?scope=security|all&limit=`; with `scope=all` it also includes bearing changes and more.

## What is not covered

- **Eavesdropping on radio traffic** and anything that happens outside FoxGrid.
- **A taken-over device that is unlocked.** Device binding protects against the link, not against an attacker holding the phone.
  The lead has to remove the account.
- **A compromised server.** Device secrets are stored there only as a hash, but whoever controls the server sees the mission data.
- **A trusted participant who deliberately supplies bad data.** The estimate tolerates single outliers, but not a targeted attack
  with several trusted accounts. That is a matter of choosing the people.
- The secret is kept in the app settings (SharedPreferences), not in the keychain. A rooted device can read it.
- Undoing a quarantine is only possible bearing by bearing.

## Operations

- Behind a reverse proxy: set `FORWARDED_ALLOW_IPS` for uvicorn to the proxy address, otherwise all users share one join counter
  and rate limits trigger too early. See [Deployment](../operations/deployment.md).
- Limits are adjustable: `FOXGRID_INVITE_TTL_HOURS`, `FOXGRID_INVITE_MAX_USES`, `FOXGRID_RATE_*_PER_MIN`
  (see [Configuration](../reference/configuration.md)).
- HTTPS is mandatory in release builds; without TLS bystanders can read tokens and data.
