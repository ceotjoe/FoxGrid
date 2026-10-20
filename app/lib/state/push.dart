import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api.dart';
import '../core/push.dart';
import 'providers.dart';

/// Replaced in `main` when Firebase is configured; the default does nothing.
final pushMessagingProvider = Provider<PushMessaging>(
  (ref) => const NoopPushMessaging(),
);

/// Keeps the device token registered on the server while the participant is active in a mission,
/// and unregisters it when the session ends. State is the token the server currently knows.
class PushRegistrar extends Notifier<String?> {
  // The api of the last registration: its session is still valid when the participant leaves.
  FoxGridApi? _api;
  String? _token;
  String? _pending;

  @override
  String? build() {
    final key = ref.watch(
      sessionProvider.select(
        (s) => s != null && !s.isPending && s.status == 'active'
            ? '${s.missionId}/${s.participantId}'
            : null,
      ),
    );
    final messaging = ref.read(pushMessagingProvider);
    if (key == null) {
      _unregister(messaging);
      return null;
    }
    final api = ref.read(apiProvider);
    // New session (possibly another participant): the token must be registered for it again.
    _token = null;
    _pending = null;
    final refreshes = messaging.tokenRefreshes.listen(
      (token) => _register(api, token),
    );
    ref.onDispose(refreshes.cancel);
    unawaited(
      messaging.requestToken().then((token) {
        if (token != null) return _register(api, token);
      }),
    );
    return null;
  }

  Future<void> _register(FoxGridApi api, String token) async {
    // requestToken() and the first token refresh often deliver the same token.
    if (token == _token || token == _pending) return;
    _pending = token;
    try {
      await api.registerPushToken(token);
      _api = api;
      _token = token;
      if (ref.mounted) state = token;
    } on Object {
      // Offline or server down: the token is sent again on the next start or token refresh.
    } finally {
      if (_pending == token) _pending = null;
    }
  }

  Future<void> _unregister(PushMessaging messaging) async {
    final api = _api;
    final token = _token;
    _api = null;
    _token = null;
    if (api == null || token == null) return;
    try {
      await api.unregisterPushToken(token);
    } on Object {
      // Removed participants cannot call the API any more; the server drops the token on the
      // first failed delivery after deleteToken().
    }
    await messaging.deleteToken();
  }
}

final pushRegistrarProvider = NotifierProvider<PushRegistrar, String?>(
  PushRegistrar.new,
);
