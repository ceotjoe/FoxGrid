"""The authority/permission matrix (pure, no database)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.services.permissions import (
    ASSIGNABLE,
    AUTHORITIES,
    MATRIX,
    Authority,
    Permission,
    authority_for_role,
    feeds_estimate,
    has_permission,
    permissions_of,
)

A = Authority
P = Permission


@dataclass
class Who:
    authority: str


def test_every_authority_has_a_row_and_every_permission_a_holder() -> None:
    assert set(MATRIX) == set(Authority)
    assert set(AUTHORITIES) == {a.value for a in Authority}
    assert set().union(*MATRIX.values()) == set(Permission)


def test_lead_has_everything() -> None:
    assert permissions_of("lead") == frozenset(Permission)


@pytest.mark.parametrize("authority", [A.LEAD, A.DEPUTY, A.ANALYST])
def test_external_points_and_bearings_for_lead_deputy_analyst(authority: A) -> None:
    assert has_permission(Who(authority), P.POINT_MANAGE)
    assert has_permission(Who(authority), P.BEARING_EXTERNAL)


@pytest.mark.parametrize("authority", [A.COORDINATOR, A.MEMBER, A.STATION, A.OBSERVER])
def test_no_external_points_for_the_rest(authority: A) -> None:
    assert not has_permission(Who(authority), P.POINT_MANAGE)
    assert not has_permission(Who(authority), P.BEARING_EXTERNAL)


def test_only_the_lead_assigns_roles_and_ends_the_mission() -> None:
    for a in Authority:
        assert has_permission(Who(a), P.ROLE_ASSIGN) == (a is A.LEAD)
        assert has_permission(Who(a), P.MISSION_END) == (a is A.LEAD)


def test_deputy_administers_but_does_not_assign_roles() -> None:
    d = Who(A.DEPUTY)
    for p in (P.PARTICIPANT_MANAGE, P.INVITE_MANAGE, P.QUARANTINE, P.TRUST_SET, P.AUDIT_VIEW):
        assert has_permission(d, p)
    assert not has_permission(d, P.ROLE_ASSIGN)


def test_analyst_judges_data_but_does_not_administer() -> None:
    a = Who(A.ANALYST)
    for p in (P.BEARING_FLAG, P.TRUST_SET, P.ESTIMATE_CONFIGURE, P.TRANSMISSION_MANAGE):
        assert has_permission(a, p)
    for p in (P.PARTICIPANT_MANAGE, P.INVITE_CREATE, P.QUARANTINE, P.ROLE_ASSIGN, P.TASK_MANAGE):
        assert not has_permission(a, p)


def test_coordinator_organises_but_does_not_touch_data() -> None:
    c = Who(A.COORDINATOR)
    for p in (P.CHAT_MODERATE, P.TASK_MANAGE, P.TEAM_MANAGE, P.INVITE_CREATE):
        assert has_permission(c, p)
    for p in (P.BEARING_FLAG, P.TRUST_SET, P.POINT_MANAGE, P.INVITE_MANAGE, P.PARTICIPANT_MANAGE):
        assert not has_permission(c, p)


def test_member_is_a_plain_bearer() -> None:
    m = permissions_of("member")
    assert {P.BEARING_CREATE, P.CHAT_WRITE, P.VIEW_POSITIONS, P.POSITION_SHARE} <= m
    assert not m & {P.BEARING_FLAG, P.TRUST_SET, P.PARTICIPANT_MANAGE, P.TASK_MANAGE}


def test_station_delivers_readings_only() -> None:
    assert permissions_of("station") == frozenset({P.RSSI_SUBMIT, P.POSITION_SHARE})


def test_observer_sees_neither_chat_nor_positions() -> None:
    o = permissions_of("observer")
    assert o == frozenset({P.VIEW_RESULT, P.EXPORT})
    assert not o & {P.CHAT_READ, P.CHAT_WRITE, P.VIEW_POSITIONS, P.EXPORT_TRACKS, P.POSITION_SHARE}
    assert not o & {P.BEARING_CREATE, P.RSSI_SUBMIT}


def test_unknown_authority_fails_closed() -> None:
    assert permissions_of("root") == frozenset()
    assert not has_permission(Who("root"), P.VIEW_RESULT)


def test_station_is_never_assigned_by_hand() -> None:
    assert A.STATION not in ASSIGNABLE
    assert set(ASSIGNABLE) | {A.STATION} == set(Authority)


def test_legacy_role_mapping() -> None:
    assert authority_for_role("lead") is A.LEAD
    assert authority_for_role("fixed") is A.MEMBER
    assert authority_for_role("mobile") is A.MEMBER


def test_observer_never_feeds_the_estimate() -> None:
    assert not feeds_estimate("observer")
    assert feeds_estimate("member") and feeds_estimate("station")
