import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import 'permissions.dart';

/// Everything needed to talk to one mission as one participant.
class Session {
  const Session({
    required this.baseUrl,
    required this.token,
    required this.missionId,
    required this.participantId,
    required this.callsign,
    required this.role,
    this.authority,
    this.permissions,
    this.inviteToken,
    this.status = 'active',
    this.missionName,
  });

  final String baseUrl;
  final String token;
  final String missionId;
  final String participantId;
  final String callsign;
  final String role;

  /// Standing in the mission (`lead`, `deputy`, `analyst`, ...); absent in sessions stored by
  /// older versions, which then count as lead or member by [role].
  final String? authority;

  /// What the server lets this participant do; absent in sessions stored by older versions.
  final Set<String>? permissions;

  /// Only known on the device that created the mission.
  final String? inviteToken;

  /// `pending` until the lead lets the joiner in; `rejected` if the lead said no.
  final String status;

  /// For the list of recent missions; absent in sessions stored by older versions.
  final String? missionName;

  String get effectiveAuthority =>
      authority ?? (role == 'lead' ? 'lead' : 'member');
  bool get isLead => effectiveAuthority == 'lead';
  bool get isObserver => effectiveAuthority == 'observer';

  /// Whether the server allows [permission]; the server enforces it, this only steers the UI.
  bool can(String permission) =>
      (permissions ?? legacyPermissions(role)).contains(permission);
  bool get isPending => status == 'pending';

  /// Whether any of the "run the mission" tools applies (the manage sheet is worth opening).
  bool get canManage => [
    Perm.participantManage,
    Perm.trustSet,
    Perm.inviteCreate,
    Perm.pointManage,
    Perm.sensorManage,
    Perm.auditView,
    Perm.missionEnd,
  ].any(can);

  Session copyWith({
    String? role,
    String? authority,
    Set<String>? permissions,
    String? status,
    String? inviteToken,
  }) => Session(
    baseUrl: baseUrl,
    token: token,
    missionId: missionId,
    participantId: participantId,
    callsign: callsign,
    role: role ?? this.role,
    authority: authority ?? this.authority,
    permissions: permissions ?? this.permissions,
    inviteToken: inviteToken ?? this.inviteToken,
    status: status ?? this.status,
    missionName: missionName,
  );

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
    'authority': authority,
    'permissions': permissions?.toList(),
    'inviteToken': inviteToken,
    'status': status,
    'missionName': missionName,
  };

  factory Session.fromJson(Map<String, dynamic> j) => Session(
    baseUrl: j['baseUrl'] as String,
    token: j['token'] as String,
    missionId: j['missionId'] as String,
    participantId: j['participantId'] as String,
    callsign: j['callsign'] as String,
    role: j['role'] as String,
    authority: j['authority'] as String?,
    permissions: (j['permissions'] as List?)?.cast<String>().toSet(),
    inviteToken: j['inviteToken'] as String?,
    status: j['status'] as String? ?? 'active',
    missionName: j['missionName'] as String?,
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

/// Whether the JWT expires within [margin] (or is unreadable/expired already).
bool tokenExpiresWithin(String jwt, Duration margin, {DateTime? now}) {
  try {
    final payload = utf8.decode(
      base64Url.decode(base64Url.normalize(jwt.split('.')[1])),
    );
    final exp = (jsonDecode(payload) as Map<String, dynamic>)['exp'] as num;
    final expires = DateTime.fromMillisecondsSinceEpoch(
      exp.toInt() * 1000,
      isUtc: true,
    );
    return expires.isBefore((now ?? DateTime.now().toUtc()).add(margin));
  } on Object {
    return false; // not a JWT we can read: let the server decide
  }
}
