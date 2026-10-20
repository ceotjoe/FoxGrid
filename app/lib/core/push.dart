import 'dart:async';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';

/// The device side of push: asks for permission and hands out the FCM token.
/// An interface so tests (and builds without Firebase config) do not touch the plugin.
abstract class PushMessaging {
  /// Asks for notification permission and returns the device token, or `null` when the user
  /// said no or the platform cannot deliver pushes (e.g. iOS simulator).
  Future<String?> requestToken();

  /// New tokens after the first one (FCM rotates them now and then).
  Stream<String> get tokenRefreshes;

  /// Drops the token so a device that left a mission stops receiving its pushes.
  Future<void> deleteToken();
}

/// Used on web, in tests and when the Firebase config files are missing.
class NoopPushMessaging implements PushMessaging {
  const NoopPushMessaging();

  @override
  Future<String?> requestToken() async => null;

  @override
  Stream<String> get tokenRefreshes => const Stream.empty();

  @override
  Future<void> deleteToken() async {}
}

class FirebasePushMessaging implements PushMessaging {
  FirebasePushMessaging._(this._fcm);

  final FirebaseMessaging _fcm;

  /// `null` if push is unavailable: web (needs a VAPID key, not set up) or no
  /// `google-services.json` / `GoogleService-Info.plist` in this build.
  static Future<FirebasePushMessaging?> tryInit() async {
    if (kIsWeb) return null;
    try {
      await Firebase.initializeApp();
      return FirebasePushMessaging._(FirebaseMessaging.instance);
    } on Object catch (e) {
      debugPrint('Push disabled, Firebase is not configured: $e');
      return null;
    }
  }

  @override
  Future<String?> requestToken() async {
    try {
      final settings = await _fcm.requestPermission();
      if (settings.authorizationStatus == AuthorizationStatus.denied) {
        return null;
      }
      if (defaultTargetPlatform == TargetPlatform.iOS) {
        // The FCM token only exists once Apple handed out an APNs token (never on the simulator).
        for (var i = 0; i < 10 && await _fcm.getAPNSToken() == null; i++) {
          await Future<void>.delayed(const Duration(seconds: 1));
        }
        if (await _fcm.getAPNSToken() == null) return null;
      }
      return await _fcm.getToken();
    } on Object catch (e) {
      debugPrint('Could not get a push token: $e');
      return null;
    }
  }

  @override
  Stream<String> get tokenRefreshes => _fcm.onTokenRefresh;

  @override
  Future<void> deleteToken() async {
    try {
      await _fcm.deleteToken();
    } on Object catch (e) {
      debugPrint('Could not delete the push token: $e');
    }
  }
}
