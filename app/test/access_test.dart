import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:foxgrid/core/api.dart';
import 'package:foxgrid/core/models.dart';
import 'package:foxgrid/core/session.dart';
import 'package:foxgrid/state/providers.dart';
import 'package:foxgrid/ui/participants_screen.dart';
import 'package:foxgrid/ui/pending_screen.dart';

import 'helpers.dart';

const _pendingSession = Session(
  baseUrl: 'http://localhost:8000',
  token: 't',
  missionId: 'm1',
  participantId: 'p9',
  callsign: 'DL9NEW',
  role: 'mobile',
  status: 'pending',
);

Future<TestEnv> _pendingEnv(WidgetTester tester, FakeApi api) async {
  final env = await makeEnv(api: api, session: _pendingSession);
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: env.container,
      child: const MaterialApp(
        home: PendingScreen(pollInterval: Duration(milliseconds: 100)),
      ),
    ),
  );
  return env;
}

Map<String, dynamic> _snapshotWithPending() {
  final s = snapshotJson();
  s['participants'] = <dynamic>[
    ...(s['participants'] as List),
    <String, dynamic>{
      'id': 'p3',
      'callsign': 'DL3NEW',
      'role': 'mobile',
      'team': null,
      'status': 'pending',
      'is_active': true,
      'device_bound': true,
    },
  ];
  return s;
}

void main() {
  test('session survives a round trip including its status', () {
    final back = Session.fromJson(_pendingSession.toJson());
    expect(back.isPending, isTrue);
    expect(back.copyWith(status: 'active', role: 'fixed').role, 'fixed');
    // sessions saved before approval existed count as active
    final old = _pendingSession.toJson()..remove('status');
    expect(Session.fromJson(old).isPending, isFalse);
  });

  group('waiting screen', () {
    testWidgets('lets the joiner in once the lead approved', (tester) async {
      final api = FakeApi()
        ..meValue = const Participant(
          id: 'p9',
          callsign: 'DL9NEW',
          role: 'fixed',
          status: 'active',
        );
      final env = await _pendingEnv(tester, api);
      await tester.pump(const Duration(milliseconds: 150));
      final session = env.container.read(sessionProvider)!;
      expect(session.isPending, isFalse);
      expect(session.role, 'fixed'); // the role the lead granted
    });

    testWidgets('keeps waiting while pending', (tester) async {
      final api = FakeApi()
        ..meValue = const Participant(
          id: 'p9',
          callsign: 'DL9NEW',
          role: 'mobile',
          status: 'pending',
        );
      final env = await _pendingEnv(tester, api);
      await tester.pump(const Duration(milliseconds: 250));
      expect(env.container.read(sessionProvider)!.isPending, isTrue);
      expect(find.byKey(const Key('pending-text')), findsOneWidget);
      await tester.pumpWidget(const SizedBox()); // stops the timer
    });

    testWidgets('tells a rejected joiner and offers to go back', (
      tester,
    ) async {
      final api = FakeApi()
        ..meValue = const Participant(
          id: 'p9',
          callsign: 'DL9NEW',
          role: 'mobile',
          status: 'rejected',
        );
      final env = await _pendingEnv(tester, api);
      await tester.pump(const Duration(milliseconds: 150));
      expect(find.textContaining('abgelehnt'), findsOneWidget);
      await tester.tap(find.byKey(const Key('pending-leave')));
      await tester.pump();
      expect(env.container.read(sessionProvider), isNull);
    });

    testWidgets('a removed login falls back to the join screen', (
      tester,
    ) async {
      final api = FakeApi()..meError = ApiException(401, 'unknown participant');
      final env = await _pendingEnv(tester, api);
      await tester.pump(const Duration(milliseconds: 150));
      expect(env.container.read(sessionProvider), isNull);
    });
  });

  group('participant list for the lead', () {
    testWidgets('approving moves the joiner to the active list', (
      tester,
    ) async {
      final api = FakeApi()..snapshotData = _snapshotWithPending();
      await pumpWith(tester, const ParticipantsScreen(), api: api);
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('pending-DL3NEW')), findsOneWidget);

      await tester.tap(find.byKey(const Key('approve-DL3NEW')));
      await tester.pumpAndSettle();
      expect(api.patched.single['status'], 'active');
      expect(find.byKey(const Key('pending-DL3NEW')), findsNothing);
      expect(find.byKey(const Key('participant-DL3NEW')), findsOneWidget);
    });

    testWidgets('rejecting sends the status', (tester) async {
      final api = FakeApi()..snapshotData = _snapshotWithPending();
      await pumpWith(tester, const ParticipantsScreen(), api: api);
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('reject-DL3NEW')));
      await tester.pumpAndSettle();
      expect(api.patched.single['status'], 'rejected');
      expect(find.textContaining('abgelehnt'), findsOneWidget);
    });

    testWidgets('a live join shows up without reloading', (tester) async {
      final env = await pumpWith(tester, const ParticipantsScreen());
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('pending-DL4LIVE')), findsNothing);
      env.channel.push('participant_updated', {
        'id': 'p4',
        'callsign': 'DL4LIVE',
        'role': 'mobile',
        'team': null,
        'status': 'pending',
        'is_active': true,
        'device_bound': true,
      });
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('pending-DL4LIVE')), findsOneWidget);
    });

    testWidgets('role, device release and removal go through the menu', (
      tester,
    ) async {
      final api = FakeApi();
      await pumpWith(tester, const ParticipantsScreen(), api: api);
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('menu-DL1ABC')),
        findsNothing,
      ); // not for yourself

      Future<void> choose(String text) async {
        await tester.tap(find.byKey(const Key('menu-DL2XYZ')));
        await tester.pumpAndSettle();
        await tester.tap(find.text(text));
        await tester.pumpAndSettle();
      }

      await choose('Rolle: Fest');
      expect(api.patched.last['role'], 'fixed');
      await choose('Entfernen');
      expect(api.patched.last['isActive'], false);
      expect(find.textContaining('entfernt'), findsOneWidget);
      await choose('Wieder zulassen');
      expect(api.patched.last['isActive'], true);
    });
  });

  group('trust and quarantine', () {
    Map<String, dynamic> snapshotWithUntrusted() {
      final s = snapshotJson();
      s['participants'] = <dynamic>[
        ...(s['participants'] as List),
        <String, dynamic>{
          'id': 'p5',
          'callsign': 'DL5OPEN',
          'role': 'mobile',
          'team': null,
          'status': 'active',
          'is_active': true,
          'device_bound': true,
          'trusted': false,
        },
      ];
      return s;
    }

    testWidgets('shows who is untrusted and lets the lead trust them', (
      tester,
    ) async {
      final api = FakeApi()..snapshotData = snapshotWithUntrusted();
      await pumpWith(tester, const ParticipantsScreen(), api: api);
      await tester.pumpAndSettle();
      expect(find.textContaining('nicht vertraut'), findsOneWidget);

      await tester.tap(find.byKey(const Key('menu-DL5OPEN')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Vertrauen'));
      await tester.pumpAndSettle();
      expect(api.patched.last['trusted'], true);
      expect(find.textContaining('nicht vertraut'), findsNothing);
    });

    testWidgets('quarantine asks first and reports what it took out', (
      tester,
    ) async {
      final api = FakeApi();
      await pumpWith(tester, const ParticipantsScreen(), api: api);
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('menu-DL2XYZ')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('quarantine')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Abbrechen'));
      await tester.pumpAndSettle();
      expect(api.quarantined, isEmpty);

      await tester.tap(find.byKey(const Key('menu-DL2XYZ')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('quarantine')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('quarantine-remove')));
      await tester.pumpAndSettle();
      expect(api.quarantined.single, ('p2', true));
      expect(
        find.textContaining('2 Peilungen und 5 Messwerte'),
        findsOneWidget,
      );
      expect(find.textContaining('entfernt'), findsOneWidget);
    });
  });
}
