import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:foxgrid/core/api.dart';
import 'package:foxgrid/core/session.dart';
import 'package:foxgrid/state/deep_link.dart';
import 'package:foxgrid/state/providers.dart';
import 'package:foxgrid/ui/join_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'helpers.dart';

class _JoinApi extends FakeApi {
  String? joinedServer;

  @override
  Future<Session> join({
    required String baseUrl,
    required String inviteToken,
    required String callsign,
    required String deviceSecret,
  }) async {
    joinedServer = baseUrl;
    return testSession;
  }
}

Future<ProviderContainer> _pump(
  WidgetTester tester,
  Map<String, Object> prefsValues, {
  FoxGridApi? api,
}) async {
  SharedPreferences.setMockInitialValues(prefsValues);
  final prefs = await SharedPreferences.getInstance();
  final container = ProviderContainer(
    overrides: [
      sharedPrefsProvider.overrideWithValue(prefs),
      if (api != null) apiProvider.overrideWithValue(api),
    ],
  );
  addTearDown(container.dispose);
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: const MaterialApp(home: JoinScreen()),
    ),
  );
  return container;
}

String _text(WidgetTester tester, String key) =>
    tester.widget<TextField>(find.byKey(Key(key))).controller!.text;

void main() {
  testWidgets('prefills the last server and callsign', (tester) async {
    await _pump(tester, {
      lastServerKey: 'https://fox.example.org',
      lastCallsignKey: 'DL1ABC',
    });
    expect(_text(tester, 'server'), 'https://fox.example.org');
    expect(_text(tester, 'callsign'), 'DL1ABC');
  });

  testWidgets('remembers server and callsign after a successful join', (
    tester,
  ) async {
    final container = await _pump(tester, {}, api: _JoinApi());
    await tester.enterText(find.byKey(const Key('server')), 'http://x.test');
    await tester.enterText(find.byKey(const Key('callsign')), 'DL9ZZ');
    await tester.enterText(find.byKey(const Key('invite')), 'tok');
    await tester.tap(find.byKey(const Key('join')));
    await tester.pumpAndSettle();
    final prefs = container.read(sharedPrefsProvider);
    expect(prefs.getString(lastServerKey), testSession.baseUrl);
    expect(prefs.getString(lastCallsignKey), testSession.callsign);
  });

  testWidgets('a scanned invite link fills server and invite', (tester) async {
    final container = await _pump(tester, {});
    final link = inviteLink('https://fox.example.org', 'abc123');
    container.read(pendingInviteProvider.notifier).offer(Uri.parse(link));
    await tester.pump();
    expect(_text(tester, 'server'), 'https://fox.example.org');
    expect(_text(tester, 'invite'), link);
    expect(container.read(pendingInviteProvider), isNull);
  });

  test('foreign or empty links are not offered', () {
    final c = ProviderContainer();
    addTearDown(c.dispose);
    final n = c.read(pendingInviteProvider.notifier);
    n.offer(Uri.parse('https://evil.example/join?token=x'));
    n.offer(Uri.parse('foxgrid://join?server=https://a.b'));
    expect(c.read(pendingInviteProvider), isNull);
  });
}
