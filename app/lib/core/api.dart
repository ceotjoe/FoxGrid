import 'package:dio/dio.dart';

import 'models.dart';
import 'session.dart';

class ApiException implements Exception {
  ApiException(this.statusCode, this.message);

  final int? statusCode;
  final String message;

  @override
  String toString() => message;
}

/// Server calls used by the UI; kept as an interface so tests can fake it.
abstract class FoxGridApi {
  Future<Session> createMission({
    required String baseUrl,
    required String name,
    required double frequencyMhz,
    required String callsign,
  });

  Future<Session> join({
    required String baseUrl,
    required String inviteToken,
    required String callsign,
    required String role,
  });

  Future<Map<String, dynamic>> snapshot();

  /// Returns normally for 200 and 201 (idempotent retry).
  Future<void> postBearing(Map<String, dynamic> payload);

  Future<void> startTransmission();

  Future<void> stopTransmission();

  Future<void> setBearingOutlier(String id, {required bool outlier});

  Future<void> postPositions(List<Map<String, dynamic>> positions);
}

class DioFoxGridApi implements FoxGridApi {
  DioFoxGridApi({this._session, Dio? dio}) : _dio = dio ?? Dio();

  final Session? _session;
  final Dio _dio;

  String get _mission => '/api/v1/missions/${_session!.missionId}';

  Future<Response<dynamic>> _call(
    String method,
    String url, {
    Object? data,
    String? baseUrl,
    bool auth = true,
  }) async {
    try {
      return await _dio.request<dynamic>(
        '${baseUrl ?? _session!.baseUrl}$url',
        data: data,
        options: Options(
          method: method,
          headers: auth && _session != null
              ? {'Authorization': 'Bearer ${_session.token}'}
              : null,
          sendTimeout: const Duration(seconds: 10),
          receiveTimeout: const Duration(seconds: 10),
        ),
      );
    } on DioException catch (e) {
      final body = e.response?.data;
      final detail = body is Map && body['detail'] != null
          ? body['detail'].toString()
          : (e.message ?? 'Netzwerkfehler');
      throw ApiException(e.response?.statusCode, detail);
    }
  }

  Session _sessionFrom(
    Map<String, dynamic> j,
    String baseUrl, {
    String? inviteToken,
  }) {
    final p = j['participant'] as Map<String, dynamic>;
    return Session(
      baseUrl: baseUrl,
      token: j['token'] as String,
      missionId: (j['mission'] as Map)['id'] as String,
      participantId: p['id'] as String,
      callsign: p['callsign'] as String,
      role: p['role'] as String,
      inviteToken: inviteToken,
    );
  }

  @override
  Future<Session> createMission({
    required String baseUrl,
    required String name,
    required double frequencyMhz,
    required String callsign,
  }) async {
    final r = await _call(
      'POST',
      '/api/v1/missions',
      baseUrl: baseUrl,
      auth: false,
      data: {'name': name, 'frequency_mhz': frequencyMhz, 'callsign': callsign},
    );
    final j = r.data as Map<String, dynamic>;
    return _sessionFrom(j, baseUrl, inviteToken: j['invite_token'] as String);
  }

  @override
  Future<Session> join({
    required String baseUrl,
    required String inviteToken,
    required String callsign,
    required String role,
  }) async {
    final r = await _call(
      'POST',
      '/api/v1/join',
      baseUrl: baseUrl,
      auth: false,
      data: {'invite_token': inviteToken, 'callsign': callsign, 'role': role},
    );
    return _sessionFrom(r.data as Map<String, dynamic>, baseUrl);
  }

  @override
  Future<Map<String, dynamic>> snapshot() async {
    final r = await _call('GET', '$_mission/snapshot');
    return r.data as Map<String, dynamic>;
  }

  @override
  Future<void> postBearing(Map<String, dynamic> payload) =>
      _call('POST', '$_mission/bearings', data: payload);

  @override
  Future<void> startTransmission() =>
      _call('POST', '$_mission/transmissions/start', data: <String, dynamic>{});

  @override
  Future<void> stopTransmission() =>
      _call('POST', '$_mission/transmissions/stop', data: <String, dynamic>{});

  @override
  Future<void> setBearingOutlier(String id, {required bool outlier}) =>
      _call('PATCH', '$_mission/bearings/$id', data: {'is_outlier': outlier});

  @override
  Future<void> postPositions(List<Map<String, dynamic>> positions) =>
      _call('POST', '$_mission/positions', data: positions);
}

Mission missionFromSnapshot(Map<String, dynamic> s) =>
    Mission.fromJson(s['mission'] as Map<String, dynamic>);
