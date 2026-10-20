import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:foxgrid/core/api.dart';
import 'package:foxgrid/core/recent_missions.dart';
import 'package:foxgrid/core/session.dart';
import 'package:foxgrid/state/providers.dart';
import 'package:foxgrid/ui/join_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'helpers.dart';

String _jwt(DateTime exp) {
  String part(Object o) =>
      base64Url.encode(utf8.encode(jsonEncode(o))).replaceAll('=', '');
  return '${part({'alg': 'HS256'})}.${part({'exp': exp.millisecondsSinceEpoch ~/ 1000})}.sig';
}

Session _session(String id, {String? name = 'Hunt'}) => Session(
  baseUrl: 'https://fox.example.org',
  token: 't',
  missionId: id,
  participantId: 'p',
  callsign: 'DL1ABC',
  role: 'lead',
  missionName: name,
);

void main() {
  group('RecentMissionsStore', () {
    late SharedPreferences prefs;
    setUp(() async {
      SharedPreferences.setMockInitialValues({});
      prefs = await SharedPreferences.getInstance();
    });

    test(
      'keeps one entry per mission, newest first, and caps the list',
      () async {
        final store = RecentMissionsStore(prefs, limit: 2);
        await store.remember(_session('a'), now: DateTime.utc(2026, 1, 1));
        await store.remember(_session('b'), now: DateTime.utc(2026, 1, 2));
        await store.remember(_session('a'), now: DateTime.utc(2026, 1, 3));
        expect(store.load().map((m) => m.missionId), ['a', 'b']);
        await store.remember(_session('c'));
        expect(store.load().map((m) => m.missionId), ['c', 'a']);
      },
    );

    test(
      'forget removes only that mission; broken data reads as empty',
      () async {
        final store = RecentMissionsStore(prefs);
        await store.remember(_session('a'));
        await store.remember(_session('b'));
        await store.forget('a');
        expect(store.load().map((m) => m.missionId), ['b']);
        await prefs.setString('foxgrid.recent_missions', 'nonsense');
        expect(store.load(), isEmpty);
      },
    );

    test('stores no secrets', () async {
      final store = RecentMissionsStore(prefs);
      await store.remember(_session('a').copyWith(inviteToken: 'INV'));
      final raw = prefs.getString('foxgrid.recent_missions')!;
      expect(raw, isNot(contains('INV')));
      expect(raw, isNot(contains('"token"')));
    });
  });

  group('tokenExpiresWithin', () {
    final now = DateTime.utc(2026, 1, 1, 12);
    test('detects near, far and past expiry', () {
      const margin = Duration(hours: 12);
      expect(
        tokenExpiresWithin(
          _jwt(now.add(const Duration(hours: 2))),
          margin,
          now: now,
        ),
        isTrue,
      );
      expect(
        tokenExpiresWithin(
          _jwt(now.subtract(const Duration(hours: 1))),
          margin,
          now: now,
        ),
        isTrue,
      );
      expect(
        tokenExpiresWithin(
          _jwt(now.add(const Duration(hours: 40))),
          margin,
          now: now,
        ),
        isFalse,
      );
      expect(tokenExpiresWithin('not-a-jwt', margin, now: now), isFalse);
    });
  });

  group('SessionNotifier.refresh', () {
    test('renews, keeps the invite and the recent list', () async {
      final api = FakeApi()
        ..rejoinResult = const Session(
          baseUrl: 'http://localhost:8000',
          token: 'fresh',
          missionId: 'm1',
          participantId: 'p1',
          callsign: 'DL1ABC',
          role: 'lead',
          missionName: 'Hunt',
        );
      final env = await makeEnv(
        api: api,
        session: testSession.copyWith(inviteToken: 'INV'),
      );
      addTearDown(env.container.dispose);
      final r = await env.container.read(sessionProvider.notifier).refresh();
      expect(r, RefreshResult.renewed);
      final s = env.container.read(sessionProvider)!;
      expect(s.token, 'fresh');
      expect(s.inviteToken, 'INV');
      expect(env.container.read(recentMissionsProvider).single.missionId, 'm1');
    });

    test('a refusal is denied; an ended mission leaves the list', () async {
      final api = FakeApi()
        ..rejoinError = ApiException(409, 'mission has ended');
      final env = await makeEnv(api: api);
      addTearDown(env.container.dispose);
      await env.container
          .read(recentMissionsProvider.notifier)
          .remember(testSession);
      final r = await env.container.read(sessionProvider.notifier).refresh();
      expect(r, RefreshResult.denied);
      expect(env.container.read(recentMissionsProvider), isEmpty);
    });

    test('network trouble is not a refusal', () async {
      final api = FakeApi()..rejoinError = ApiException(null, 'offline');
      final env = await makeEnv(api: api);
      addTearDown(env.container.dispose);
      expect(
        await env.container.read(sessionProvider.notifier).refresh(),
        RefreshResult.unreachable,
      );
    });
  });

  group('join screen', () {
    Future<(ProviderContainer, FakeApi)> pump(
      WidgetTester tester,
      FakeApi api,
    ) async {
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      await RecentMissionsStore(prefs).remember(testSession);
      final container = ProviderContainer(
        overrides: [
          sharedPrefsProvider.overrideWithValue(prefs),
          apiProvider.overrideWithValue(api),
        ],
      );
      addTearDown(container.dispose);
      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: const MaterialApp(home: JoinScreen()),
        ),
      );
      return (container, api);
    }

    testWidgets('tapping a recent mission returns without an invite', (
      tester,
    ) async {
      final api = FakeApi()..rejoinResult = testSession;
      final (container, _) = await pump(tester, api);
      await tester.tap(find.byKey(const Key('recent-m1')));
      await tester.pumpAndSettle();
      expect(api.rejoinCalls, 1);
      expect(container.read(sessionProvider)?.missionId, 'm1');
    });

    testWidgets('an ended mission is explained and dropped', (tester) async {
      final api = FakeApi()
        ..rejoinError = ApiException(409, 'mission has ended');
      final (container, _) = await pump(tester, api);
      await tester.tap(find.byKey(const Key('recent-m1')));
      await tester.pumpAndSettle();
      expect(find.text('Dieser Einsatz ist beendet.'), findsOneWidget);
      expect(container.read(recentMissionsProvider), isEmpty);
      expect(container.read(sessionProvider), isNull);
    });

    testWidgets('a refusal points to a new invite', (tester) async {
      final api = FakeApi();
      await pump(tester, api);
      await tester.tap(find.byKey(const Key('recent-m1')));
      await tester.pumpAndSettle();
      expect(find.textContaining('Einladungslink'), findsOneWidget);
      expect(find.byKey(const Key('recent-m1')), findsOneWidget);
    });
  });
}
