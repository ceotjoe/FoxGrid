import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:foxgrid/core/models.dart';
import 'package:foxgrid/core/permissions.dart';
import 'package:foxgrid/core/session.dart';
import 'package:foxgrid/state/providers.dart';
import 'package:foxgrid/ui/map_screen.dart';
import 'package:foxgrid/ui/participants_screen.dart';

import 'helpers.dart';

/// What the server sends per authority (a trimmed copy of its matrix, enough to steer the UI).
const _perms = <String, List<String>>{
  'lead': [
    Perm.viewResult,
    Perm.viewPositions,
    Perm.chatRead,
    Perm.chatWrite,
    Perm.bearingCreate,
    Perm.positionShare,
    Perm.taskWork,
    Perm.export,
    Perm.participantManage,
    Perm.trustSet,
    Perm.roleAssign,
    Perm.quarantine,
    Perm.inviteCreate,
    Perm.inviteManage,
    Perm.pointManage,
    Perm.sensorManage,
    Perm.auditView,
    Perm.missionEnd,
    Perm.transmissionManage,
  ],
  'analyst': [
    Perm.viewResult,
    Perm.viewPositions,
    Perm.chatRead,
    Perm.chatWrite,
    Perm.bearingCreate,
    Perm.positionShare,
    Perm.taskWork,
    Perm.export,
    Perm.trustSet,
    Perm.pointManage,
    Perm.transmissionManage,
  ],
  'coordinator': [
    Perm.viewResult,
    Perm.viewPositions,
    Perm.chatRead,
    Perm.chatWrite,
    Perm.bearingCreate,
    Perm.positionShare,
    Perm.taskWork,
    Perm.export,
    Perm.inviteCreate,
    Perm.taskManage,
  ],
  'member': [
    Perm.viewResult,
    Perm.viewPositions,
    Perm.chatRead,
    Perm.chatWrite,
    Perm.bearingCreate,
    Perm.positionShare,
    Perm.taskWork,
    Perm.export,
  ],
  'observer': [Perm.viewResult, Perm.export],
};

Session _session(String authority) => Session(
  baseUrl: 'http://localhost:8000',
  token: 't',
  missionId: 'm1',
  participantId: 'p1',
  callsign: 'DL1ABC',
  role: authority == 'lead' ? 'lead' : 'mobile',
  authority: authority,
  permissions: _perms[authority]!.toSet(),
);

/// A snapshot in which p1 (us) has [authority], as the server would send it.
FakeApi _apiFor(String authority) {
  final s = snapshotJson();
  final list = <Map<String, dynamic>>[
    for (final p in s['participants'] as List) {...(p as Map<String, dynamic>)},
  ];
  list[0] = {
    ...list[0],
    'role': authority == 'lead' ? 'lead' : 'mobile',
    'authority': authority,
    'permissions': _perms[authority],
  };
  s['participants'] = list;
  return FakeApi()..snapshotData = s;
}

Future<WidgetEnv> _open(WidgetTester tester, String authority) async {
  tester.view.physicalSize = const Size(800, 1600);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final env = await pumpWith(
    tester,
    const MapScreen(),
    api: _apiFor(authority),
  );
  ProviderScope.containerOf(tester.element(find.byType(MapScreen)))
      .read(sessionProvider.notifier)
      .set(_session(authority));
  await tester.pumpAndSettle();
  return env;
}

Future<void> _openMenu(WidgetTester tester) async {
  await tester.tap(find.byType(PopupMenuButton<String>));
  await tester.pumpAndSettle();
}

void main() {
  group('session', () {
    test('sessions from older versions fall back to the role', () {
      const lead = Session(
        baseUrl: 'x',
        token: 't',
        missionId: 'm',
        participantId: 'p',
        callsign: 'A',
        role: 'lead',
      );
      const mobile = Session(
        baseUrl: 'x',
        token: 't',
        missionId: 'm',
        participantId: 'p',
        callsign: 'A',
        role: 'mobile',
      );
      expect(lead.isLead, isTrue);
      expect(lead.can(Perm.missionEnd), isTrue);
      expect(mobile.isLead, isFalse);
      expect(mobile.can(Perm.bearingCreate), isTrue);
      expect(mobile.can(Perm.missionEnd), isFalse);
      expect(mobile.canManage, isFalse);
    });

    test('permissions survive storing the session', () {
      final back = Session.fromJson(_session('observer').toJson());
      expect(back.authority, 'observer');
      expect(back.isObserver, isTrue);
      expect(back.can(Perm.viewResult), isTrue);
      expect(back.can(Perm.chatRead), isFalse);
      expect(back.can(Perm.bearingCreate), isFalse);
    });

    test('the server list wins over the fallback', () {
      // an observer is a "mobile" role, but must not get the member fallback
      expect(_session('observer').can(Perm.chatRead), isFalse);
      expect(_session('analyst').canManage, isTrue); // trust + points
      expect(_session('member').canManage, isFalse);
    });

    test('participants carry authority and permissions', () {
      final p = Participant.fromJson({
        'id': 'p9',
        'callsign': 'DL9OBS',
        'role': 'mobile',
        'authority': 'observer',
        'permissions': ['view.result', 'export'],
      });
      expect(p.authority, 'observer');
      expect(p.permissions, {'view.result', 'export'});
      final old = Participant.fromJson({
        'id': 'p8',
        'callsign': 'DL8OLD',
        'role': 'lead',
      });
      expect(old.authority, 'lead');
      expect(old.permissions, isEmpty);
    });

    test('every assignable authority has a German label', () {
      for (final a in [...assignableAuthorities, 'station']) {
        expect(authorityLabel(a), isNot(a));
      }
      expect(authorityLabel('observer'), 'Beobachter');
    });
  });

  group('map', () {
    testWidgets('an observer sees the map but cannot chat, task or bear', (
      tester,
    ) async {
      await _open(tester, 'observer');
      expect(find.byKey(const Key('open-chat')), findsNothing);
      expect(find.byKey(const Key('open-tasks')), findsNothing);
      expect(find.byKey(const Key('open-capture')), findsNothing);
      expect(find.byKey(const Key('toggle-transmission')), findsNothing);
      await _openMenu(tester);
      expect(find.byKey(const Key('open-manage')), findsNothing);
      expect(find.byKey(const Key('open-export')), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
    });

    testWidgets('a member bears and chats but does not manage', (tester) async {
      await _open(tester, 'member');
      expect(find.byKey(const Key('open-chat')), findsOneWidget);
      expect(find.byKey(const Key('open-capture')), findsOneWidget);
      await _openMenu(tester);
      expect(find.byKey(const Key('open-manage')), findsNothing);
      await tester.pumpWidget(const SizedBox());
    });

    testWidgets('an analyst manages points but not invites or the end', (
      tester,
    ) async {
      await _open(tester, 'analyst');
      await _openMenu(tester);
      await tester.tap(find.byKey(const Key('open-manage')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('open-points')), findsOneWidget);
      expect(find.byKey(const Key('open-participants')), findsOneWidget);
      expect(find.byKey(const Key('open-invite')), findsNothing);
      expect(find.byKey(const Key('open-audit')), findsNothing);
      expect(find.byKey(const Key('open-sensors')), findsNothing);
      expect(find.byKey(const Key('end-mission')), findsNothing);
      await tester.pumpWidget(const SizedBox());
    });

    testWidgets('a coordinator invites but cannot hand out observer links', (
      tester,
    ) async {
      await _open(tester, 'coordinator');
      await _openMenu(tester);
      await tester.tap(find.byKey(const Key('open-manage')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('open-invite')), findsOneWidget);
      expect(find.byKey(const Key('open-invite-observer')), findsNothing);
      expect(find.byKey(const Key('open-points')), findsNothing);
      expect(find.byKey(const Key('open-participants')), findsNothing);
      await tester.pumpWidget(const SizedBox());
    });

    testWidgets('the lead can issue an observer link and end the mission', (
      tester,
    ) async {
      final env = await _open(tester, 'lead');
      await _openMenu(tester);
      await tester.tap(find.byKey(const Key('open-manage')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('end-mission')), findsOneWidget);
      await tester.tap(find.byKey(const Key('open-invite-observer')));
      await tester.pumpAndSettle();
      expect(env.api.inviteAuthorities, ['observer']);
      expect(find.byKey(const Key('invite-qr')), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
    });

    testWidgets('a role change of ours reaches the menus at once', (
      tester,
    ) async {
      final env = await _open(tester, 'member');
      expect(find.byKey(const Key('open-chat')), findsOneWidget);
      // the server has the new role too, so the snapshot after the rebuild agrees
      env.api.snapshotData = _apiFor('observer').snapshotData;
      final container = ProviderScope.containerOf(
        tester.element(find.byType(MapScreen)),
      );
      container
          .read(missionProvider.notifier)
          .applyParticipant(
            Participant(
              id: 'p1',
              callsign: 'DL1ABC',
              role: 'mobile',
              authority: 'observer',
              permissions: _perms['observer']!.toSet(),
            ),
          );
      await tester.pumpAndSettle();
      expect(container.read(sessionProvider)!.isObserver, isTrue);
      expect(find.byKey(const Key('open-chat')), findsNothing);
      expect(find.byKey(const Key('open-capture')), findsNothing);
      await tester.pumpWidget(const SizedBox());
    });
  });

  group('participants', () {
    Future<FakeApi> openParticipants(WidgetTester tester, String who) async {
      final api = _apiFor(who);
      await pumpWith(tester, const ParticipantsScreen(), api: api);
      ProviderScope.containerOf(tester.element(find.byType(ParticipantsScreen)))
          .read(sessionProvider.notifier)
          .set(_session(who));
      await tester.pumpAndSettle();
      return api;
    }

    testWidgets('the lead picks a role by its German name', (tester) async {
      final api = await openParticipants(tester, 'lead');
      await tester.tap(find.byKey(const Key('menu-DL2XYZ')));
      await tester.pumpAndSettle();
      expect(find.text('Rolle: Auswerter'), findsOneWidget);
      expect(find.text('Rolle: Beobachter'), findsOneWidget);
      expect(find.text('Rolle: Co-Leiter'), findsOneWidget);
      expect(find.text('Rolle: Peiler'), findsNothing); // already one
      await tester.tap(find.text('Rolle: Auswerter'));
      await tester.pumpAndSettle();
      expect(api.patched.last['authority'], 'analyst');
      expect(find.textContaining('Auswerter'), findsWidgets);
      await tester.pumpWidget(const SizedBox());
    });

    testWidgets('an analyst can set trust but not roles or removal', (
      tester,
    ) async {
      await openParticipants(tester, 'analyst');
      await tester.tap(find.byKey(const Key('menu-DL2XYZ')));
      await tester.pumpAndSettle();
      expect(find.text('Vertrauen entziehen'), findsOneWidget);
      expect(find.textContaining('Rolle:'), findsNothing);
      expect(find.text('Entfernen'), findsNothing);
      expect(find.byKey(const Key('quarantine')), findsNothing);
      await tester.pumpWidget(const SizedBox());
    });

    testWidgets('a plain member gets no actions at all', (tester) async {
      await openParticipants(tester, 'member');
      expect(find.byKey(const Key('menu-DL2XYZ')), findsNothing);
      expect(find.byKey(const Key('refresh-hints')), findsNothing);
      await tester.pumpWidget(const SizedBox());
    });
  });
}
