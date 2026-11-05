"""Authorities (what a participant may manage) and the permissions each one carries.

Two independent axes describe a participant:

* ``role`` (`mobile` / `fixed` / `lead`) is the data *source*: it decides whether omnidirectional
  readings are accepted. ``lead`` is a legacy value, kept so old clients keep working.
* ``authority`` (this module) is the *standing* in the mission: what the participant may do.

The matrix below is the single place that says who may do what. Endpoints ask
``has_permission(participant, Permission.X)`` (or use the ``require`` dependency) instead of
comparing roles. See ``docs/adr/0007-roles-and-permissions.md``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol


class Authority(StrEnum):
    LEAD = "lead"  # mission lead: everything
    DEPUTY = "deputy"  # stands in for the lead, minus role assignment and ending the mission
    ANALYST = "analyst"  # judges the data: flags outliers, sets trust, enters external bearings
    COORDINATOR = "coordinator"  # organises the team: chat moderation, tasks, teams, invites
    MEMBER = "member"  # standard bearer
    STATION = "station"  # automatic station / sensor: delivers readings only
    OBSERVER = "observer"  # read-only guest: map and result, no chat, no positions


AUTHORITIES: tuple[str, ...] = tuple(a.value for a in Authority)

# Assigned by the lead to people. `station` belongs to sensors and is never assigned by hand.
ASSIGNABLE: tuple[Authority, ...] = (
    Authority.LEAD,
    Authority.DEPUTY,
    Authority.ANALYST,
    Authority.COORDINATOR,
    Authority.MEMBER,
    Authority.OBSERVER,
)


class Permission(StrEnum):
    # --- seeing
    VIEW_RESULT = "view.result"  # map, estimate, bearings, points
    VIEW_POSITIONS = "view.positions"  # other participants' positions and tracks
    CHAT_READ = "chat.read"
    # --- contributing data
    BEARING_CREATE = "bearing.create"  # own bearings
    BEARING_EXTERNAL = "bearing.external"  # bearings of external points (e.g. BNetzA)
    RSSI_SUBMIT = "rssi.submit"  # own directional readings
    POSITION_SHARE = "position.share"  # own position goes to the others
    # --- judging data
    BEARING_FLAG = "bearing.flag"  # mark anybody's bearing as outlier / deactivate
    BEARING_EDIT_ANY = "bearing.edit_any"  # append a revision to somebody else's bearing
    TRANSMISSION_MANAGE = "transmission.manage"  # edit any transmission, not just one's own
    TRUST_SET = "trust.set"
    QUARANTINE = "quarantine"
    ESTIMATE_CONFIGURE = "estimate.configure"  # engine parameters, search area, repeater
    POINT_MANAGE = "point.manage"  # external bearing points
    # --- team work
    CHAT_WRITE = "chat.write"
    CHAT_MODERATE = "chat.moderate"
    TASK_MANAGE = "task.manage"  # create and assign tasks, edit any task
    TASK_WORK = "task.work"  # take on and complete tasks assigned to oneself
    TEAM_MANAGE = "team.manage"
    # --- administration
    INVITE_CREATE = "invite.create"  # create member links (limited, see invites API)
    INVITE_MANAGE = "invite.manage"  # list, revoke, any default role / auto-approve
    PARTICIPANT_MANAGE = "participant.manage"  # approve, reject, remove, release device
    SENSOR_MANAGE = "sensor.manage"
    AUDIT_VIEW = "audit.view"
    ROLE_ASSIGN = "role.assign"
    MISSION_END = "mission.end"  # end, archive, change mission-level settings
    EXPORT = "export"
    EXPORT_TRACKS = "export.tracks"  # position tracks inside an export


P = Permission

_MEMBER = frozenset(
    {
        P.VIEW_RESULT,
        P.VIEW_POSITIONS,
        P.CHAT_READ,
        P.CHAT_WRITE,
        P.BEARING_CREATE,
        P.RSSI_SUBMIT,
        P.POSITION_SHARE,
        P.TASK_WORK,
        P.EXPORT,
        P.EXPORT_TRACKS,
    }
)

_ANALYST = _MEMBER | {
    P.BEARING_EXTERNAL,
    P.BEARING_FLAG,
    P.TRANSMISSION_MANAGE,
    P.TRUST_SET,
    P.ESTIMATE_CONFIGURE,
    P.POINT_MANAGE,
}

_COORDINATOR = _MEMBER | {
    P.CHAT_MODERATE,
    P.TASK_MANAGE,
    P.TEAM_MANAGE,
    P.INVITE_CREATE,
}

_DEPUTY = (
    _ANALYST
    | _COORDINATOR
    | {
        P.BEARING_EDIT_ANY,
        P.QUARANTINE,
        P.INVITE_MANAGE,
        P.PARTICIPANT_MANAGE,
        P.SENSOR_MANAGE,
        P.AUDIT_VIEW,
    }
)

_LEAD = frozenset(Permission)

MATRIX: dict[Authority, frozenset[Permission]] = {
    Authority.LEAD: _LEAD,
    Authority.DEPUTY: frozenset(_DEPUTY),
    Authority.ANALYST: frozenset(_ANALYST),
    Authority.COORDINATOR: frozenset(_COORDINATOR),
    Authority.MEMBER: _MEMBER,
    # Stations deliver readings only; they see nothing and say nothing.
    Authority.STATION: frozenset({P.RSSI_SUBMIT, P.POSITION_SHARE}),
    # Observers read the map and the result. No chat, no positions of the others, no tracks.
    Authority.OBSERVER: frozenset({P.VIEW_RESULT, P.EXPORT}),
}


class _HasAuthority(Protocol):
    authority: str


def permissions_of(authority: str) -> frozenset[Permission]:
    """Permissions of an authority; an unknown value carries none (fail closed)."""
    try:
        return MATRIX[Authority(authority)]
    except ValueError:
        return frozenset()


def has_permission(participant: _HasAuthority, permission: Permission) -> bool:
    return permission in permissions_of(participant.authority)


def authority_for_role(role: str) -> Authority:
    """Authority implied by a legacy `role`: only the old `lead` carried standing."""
    return Authority.LEAD if role == "lead" else Authority.MEMBER


def feeds_estimate(authority: str) -> bool:
    """Whether data from this authority may move the estimate (observers never do)."""
    return Permission.BEARING_CREATE in permissions_of(authority) or authority == Authority.STATION
