import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import 'session.dart';

/// A mission this device took part in, kept so the user can return after the session is gone.
class RecentMission {
  const RecentMission({
    required this.baseUrl,
    required this.missionId,
    required this.callsign,
    required this.name,
    required this.usedAt,
  });

  final String baseUrl;
  final String missionId;
  final String callsign;
  final String name;
  final DateTime usedAt;

  Map<String, dynamic> toJson() => {
    'baseUrl': baseUrl,
    'missionId': missionId,
    'callsign': callsign,
    'name': name,
    'usedAt': usedAt.toUtc().toIso8601String(),
  };

  factory RecentMission.fromJson(Map<String, dynamic> j) => RecentMission(
    baseUrl: j['baseUrl'] as String,
    missionId: j['missionId'] as String,
    callsign: j['callsign'] as String,
    name: j['name'] as String,
    usedAt: DateTime.parse(j['usedAt'] as String),
  );
}

/// Newest first, one entry per mission, at most [limit]. Holds no secrets: the device secret
/// and the invite stay out of it, so it cannot be used to enter a mission by itself.
class RecentMissionsStore {
  RecentMissionsStore(this._prefs, {this.limit = 10});

  static const _key = 'foxgrid.recent_missions';
  final SharedPreferences _prefs;
  final int limit;

  List<RecentMission> load() {
    final raw = _prefs.getString(_key);
    if (raw == null) return const [];
    try {
      return [
        for (final e in jsonDecode(raw) as List)
          RecentMission.fromJson(e as Map<String, dynamic>),
      ];
    } on Object {
      return const [];
    }
  }

  Future<List<RecentMission>> remember(Session s, {DateTime? now}) async {
    final entry = RecentMission(
      baseUrl: s.baseUrl,
      missionId: s.missionId,
      callsign: s.callsign,
      name: s.missionName ?? 'Einsatz',
      usedAt: now ?? DateTime.now(),
    );
    final list = [
      entry,
      ...load().where((m) => m.missionId != s.missionId),
    ].take(limit).toList();
    await _save(list);
    return list;
  }

  Future<List<RecentMission>> forget(String missionId) async {
    final list = load().where((m) => m.missionId != missionId).toList();
    await _save(list);
    return list;
  }

  Future<void> _save(List<RecentMission> list) =>
      _prefs.setString(_key, jsonEncode([for (final m in list) m.toJson()]));
}
