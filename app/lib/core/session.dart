import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

/// Everything needed to talk to one mission as one participant.
class Session {
  const Session({
    required this.baseUrl,
    required this.token,
    required this.missionId,
    required this.participantId,
    required this.callsign,
    required this.role,
    this.inviteToken,
  });

  final String baseUrl;
  final String token;
  final String missionId;
  final String participantId;
  final String callsign;
  final String role;

  /// Only known on the device that created the mission.
  final String? inviteToken;

  bool get isLead => role == 'lead';

  Uri get wsUri {
    final base = Uri.parse(baseUrl);
    return base.replace(
      scheme: base.scheme == 'https' ? 'wss' : 'ws',
      path: '/ws/missions/$missionId',
      queryParameters: {'token': token},
    );
  }

  Map<String, dynamic> toJson() => {
    'baseUrl': baseUrl,
    'token': token,
    'missionId': missionId,
    'participantId': participantId,
    'callsign': callsign,
    'role': role,
    'inviteToken': inviteToken,
  };

  factory Session.fromJson(Map<String, dynamic> j) => Session(
    baseUrl: j['baseUrl'] as String,
    token: j['token'] as String,
    missionId: j['missionId'] as String,
    participantId: j['participantId'] as String,
    callsign: j['callsign'] as String,
    role: j['role'] as String,
    inviteToken: j['inviteToken'] as String?,
  );
}

class SessionStore {
  SessionStore(this._prefs);

  static const _key = 'foxgrid.session';
  final SharedPreferences _prefs;

  Session? load() {
    final raw = _prefs.getString(_key);
    if (raw == null) return null;
    try {
      return Session.fromJson(jsonDecode(raw) as Map<String, dynamic>);
    } on Object {
      return null;
    }
  }

  Future<void> save(Session s) =>
      _prefs.setString(_key, jsonEncode(s.toJson()));

  Future<void> clear() => _prefs.remove(_key);
}

/// Parses an invite given as a bare token or as `foxgrid://join?server=...&token=...`.
({String? server, String token}) parseInvite(String input) {
  final text = input.trim();
  final uri = Uri.tryParse(text);
  if (uri != null && uri.scheme == 'foxgrid' && uri.host == 'join') {
    return (
      server: uri.queryParameters['server'],
      token: uri.queryParameters['token'] ?? '',
    );
  }
  return (server: null, token: text);
}

String inviteLink(String server, String token) => Uri(
  scheme: 'foxgrid',
  host: 'join',
  queryParameters: {'server': server, 'token': token},
).toString();
