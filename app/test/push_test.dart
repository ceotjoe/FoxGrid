import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:foxgrid/core/push.dart';
import 'package:foxgrid/core/session.dart';
import 'package:foxgrid/state/providers.dart';
import 'package:foxgrid/state/push.dart';

import 'helpers.dart';

class FakePush implements PushMessaging {
  FakePush(this.token);

  String? token;
  final refreshes = StreamController<String>.broadcast();
  var deleted = 0;

  @override
  Future<String?> requestToken() async => token;

  @override
  Stream<String> get tokenRefreshes => refreshes.stream;

  @override
  Future<void> deleteToken() async => deleted++;
}

Future<void> _settle() async {
  for (var i = 0; i < 6; i++) {
    await Future<void>.delayed(Duration.zero);
  }
}

void main() {
  late FakeApi api;
  late FakePush push;

  Future<TestEnv> env({Session? session = testSession}) async {
    final e = await makeEnv(
      api: api,
      session: session,
      extra: [pushMessagingProvider.overrideWithValue(push)],
    );
    addTearDown(e.container.dispose);
    // The app root keeps the registrar alive.
    e.container.listen(pushRegistrarProvider, (_, _) {});
    await _settle();
    return e;
  }

  setUp(() {
    api = FakeApi();
    push = FakePush('fcm-token-1234567890');
  });

  test('registers the device token for an active participant', () async {
    final e = await env();
    expect(api.pushRegistered, ['fcm-token-1234567890']);
    expect(e.container.read(pushRegistrarProvider), 'fcm-token-1234567890');
  });

  test('does nothing without a session or while the join is pending', () async {
    await env(session: null);
    await env(session: testSession.copyWith(status: 'pending'));
    expect(api.pushRegistered, isEmpty);
  });

  test('does nothing when permission is denied', () async {
    push.token = null;
    await env();
    expect(api.pushRegistered, isEmpty);
  });

  test('sends a refreshed token', () async {
    await env();
    push.refreshes.add('fcm-token-rotated-0987');
    await _settle();
    expect(api.pushRegistered, [
      'fcm-token-1234567890',
      'fcm-token-rotated-0987',
    ]);
  });

  test('a failing server call is swallowed', () async {
    api.pushError = Exception('offline');
    final e = await env();
    expect(api.pushRegistered, isEmpty);
    expect(e.container.read(pushRegistrarProvider), isNull);
  });

  test('leaving the mission unregisters and drops the token', () async {
    final e = await env();
    await e.container.read(sessionProvider.notifier).leave();
    await _settle();
    expect(api.pushUnregistered, ['fcm-token-1234567890']);
    expect(push.deleted, 1);
    expect(e.container.read(pushRegistrarProvider), isNull);
  });

  test('the role change of a lead promotion does not re-register', () async {
    final e = await env();
    await e.container
        .read(sessionProvider.notifier)
        .set(testSession.copyWith(role: 'mobile'));
    await _settle();
    expect(api.pushRegistered, hasLength(1));
  });
}
