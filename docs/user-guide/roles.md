# Roles and permissions

A mission lead decides who may do what. Every participant has a **role** (in the app: *Rolle*) that carries a fixed set of
permissions. The role is independent of the data source: a person at a fixed location (*Fest*) can be an analyst, a mobile bearer
can be the lead.

## The roles

| Role (app label) | For | Can do |
|---|---|---|
| **Einsatzleiter** (`lead`) | the mission lead | everything: assign roles, end the mission, all of the below |
| **Co-Leiter** (`deputy`) | the lead's stand-in | everything except assigning roles and ending the mission; cannot change or quarantine a lead |
| **Auswerter** (`analyst`) | whoever judges the data | mark anybody's bearing as outlier, set trust, enter external bearings and manage external points, set the repeater and estimate parameters; may stop any transmission |
| **Koordinator** (`coordinator`) | whoever organises the team | create and assign tasks, moderate chat (sees all team channels), create ordinary invite links |
| **Peiler** (`member`) | everybody else; the default for a link | capture bearings and readings, chat, work on tasks assigned to them, share their position, export |
| **Feststation** (`station`) | a sensor's automatic account | only delivers readings; never assigned by hand |
| **Beobachter** (`observer`) | guests: authorities, press, colleagues who only follow | see map and result and export it (without tracks); **no chat, no tasks, no positions of others**; cannot bear; never moves the estimate |

## Who may do what

| | Leiter | Co-Leiter | Auswerter | Koordinator | Peiler | Beobachter |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| see map, result, bearings, points | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| see positions of others | ✓ | ✓ | ✓ | ✓ | ✓ | – |
| read and write chat | ✓ | ✓ | ✓ | ✓ | ✓ | – |
| capture own bearings and readings | ✓ | ✓ | ✓ | ✓ | ✓ | – |
| enter external bearings, manage points | ✓ | ✓ | ✓ | – | – | – |
| flag other people's bearings as outlier | ✓ | ✓ | ✓ | – | – | – |
| edit the note of other people's bearings | ✓ | ✓ | – | – | – | – |
| set trust, see plausibility hints | ✓ | ✓ | ✓ | – | – | – |
| set repeater / estimate parameters | ✓ | ✓ | ✓ | – | – | – |
| stop any transmission | ✓ | ✓ | ✓ | – | – | – |
| create and assign tasks | ✓ | ✓ | – | ✓ | – | – |
| moderate chat | ✓ | ✓ | – | ✓ | – | – |
| create ordinary invite links | ✓ | ✓ | – | ✓ | – | – |
| observer links, replace/revoke links, auto-approve | ✓ | ✓ | – | – | – | – |
| approve, reject, remove participants, release devices | ✓ | ✓ | – | – | – | – |
| quarantine, security log, sensors | ✓ | ✓ | – | – | – | – |
| assign roles | ✓ | – | – | – | – | – |
| end the mission | ✓ | – | – | – | – | – |
| export (tracks only with a "see positions" right) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ (no tracks) |

The exact list of permissions is `backend/app/services/permissions.py` and the
[API reference](../reference/api.md#permission-names). The server enforces it; the app only hides what you cannot do.

## Assigning roles

Only the lead assigns roles: *Einsatz verwalten → Teilnehmer*, menu of a participant → *Rolle: …*. (In the API:
`PATCH /missions/{id}/participants/{pid}` with `{"authority": "analyst"}`.)

- Roles can only be given to participants who are active, not to those still waiting for approval.
- A mission always keeps at least one lead. The only lead cannot step down; with a second lead they can.
- Nobody but a lead can change or quarantine a lead.
- A role change takes effect at once, also on a connected device: its live connection is renewed and the menus change.
- **Trust is separate.** A promotion does not make anybody trusted: an analyst whose data does not count yet still has to be
  trusted explicitly (*Vertrauen*). Observers never count, whatever the trust flag says; their bearings stay in the log.
- Every change is in the security log.

## Invite links

A link makes a **Peiler**. For guests the lead or a deputy creates an **observer link** (*Einsatz verwalten → Beobachter-Einladung*):
whoever joins through it waits for approval like everybody else and then sees the result, but no chat and no positions.
Coordinators may hand out ordinary links only (no `fixed` posts, no skipping the approval).

## What an observer still sees

The result cannot be shown without the **places where bearings were taken**, so observers see those. They do not see where
participants are right now, no tracks, no chat and no tasks. Keep that in mind before inviting somebody who should not know where
your bearers stood.

## Good practice

- Give out as few lead and deputy roles as you can.
- Use the *Auswerter* role for the person at the radio desk who takes the BNetzA's reports.
- Check the participant list before the mission starts and after the team has assembled; demote or remove what is no longer needed.
- See also [Access control and security](mission-lead-security.md).
