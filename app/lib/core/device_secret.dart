import 'dart:convert';
import 'dart:math';

import 'package:shared_preferences/shared_preferences.dart';

const _key = 'foxgrid.device_secret';

/// Random secret of this installation. The server stores only its hash and binds a callsign to it,
/// so someone who knows an invite link cannot re-join under another participant's callsign.
/// A lead can release the binding when a participant changes phones.
String deviceSecret(SharedPreferences prefs, {Random? random}) {
  final existing = prefs.getString(_key);
  if (existing != null && existing.length >= 16) return existing;
  final rng = random ?? Random.secure();
  final secret = base64UrlEncode(
    List<int>.generate(32, (_) => rng.nextInt(256)),
  );
  prefs.setString(_key, secret);
  return secret;
}
