import 'dart:convert';

import 'package:dio/dio.dart';

import 'models.dart';
import 'outbox.dart';
import 'session.dart';
import 'sync.dart';

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
    required String deviceSecret,
  });

  Future<Session> join({
    required String baseUrl,
    required String inviteToken,
    required String callsign,
    required String deviceSecret,
  });

  Future<Map<String, dynamic>> snapshot();

  /// Lead only: revokes every open invite and returns the token of a fresh one.
  Future<String> replaceInvite();

  /// Own state; works while the join is still waiting for the lead's approval.
  Future<Participant> me();

  /// Lead only: approve/reject, change the role, remove or release the device.
  Future<Participant> patchParticipant(
    String id, {
    String? role,
    String? status,
    bool? isActive,
    bool? trusted,
    bool resetDevice = false,
  });

  /// Lead only: security log, newest first.
  Future<List<AuditEntry>> audit({int limit});

  /// Lead only: join codes of pending participants, by participant id.
  Future<Map<String, String>> joinCodes();

  /// Lead only: hints per participant id (German texts); an empty list means nothing stands out.
  Future<Map<String, List<String>>> plausibility();

  /// Lead only: takes all of a participant's bearings and readings out of the estimate.
  Future<QuarantineResult> quarantine(String id, {bool remove = false});

  /// Delivers one queued write and classifies the result for the sync service.
  Future<SendResult> sendQueued(OutboxEntry entry);

  /// Magnetic declination (positive = magnetic north east of true north).
  Future<double> declination(double lat, double lon);

  /// Ad-hoc estimate for a filter; `null` if fewer than two bearings match.
  Future<Estimate?> queryEstimate({
    List<String> transmissions = const [],
    DateTime? since,
    double? halfLifeS,
  });

  Future<List<int>> exportBytes(String format);

  /// Where one more bearing helps most; empty while there are no bearings.
  Future<List<Suggestion>> suggestions({
    required String scope,
    double sigmaDeg = 10,
  });

  Future<List<SensorInfo>> listSensors();

  /// Registers a station or repeater hook; the result carries the API key once.
  Future<SensorInfo> createSensor({
    required String name,
    required String kind,
    double? lat,
    double? lon,
  });

  Future<SensorInfo> setSensorActive(String id, {required bool active});
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
        // Dio only JSON-encodes maps; a list body (batch uploads) would go out as Dart's toString.
        data: data == null ? null : jsonEncode(data),
        options: Options(
          method: method,
          contentType: data == null ? null : Headers.jsonContentType,
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
      status: p['status'] as String? ?? 'active',
    );
  }

  @override
  Future<Session> createMission({
    required String baseUrl,
    required String name,
    required double frequencyMhz,
    required String callsign,
    required String deviceSecret,
  }) async {
    final r = await _call(
      'POST',
      '/api/v1/missions',
      baseUrl: baseUrl,
      auth: false,
      data: {
        'name': name,
        'frequency_mhz': frequencyMhz,
        'callsign': callsign,
        'device_secret': deviceSecret,
      },
    );
    final j = r.data as Map<String, dynamic>;
    return _sessionFrom(j, baseUrl, inviteToken: j['invite_token'] as String);
  }

  @override
  Future<Session> join({
    required String baseUrl,
    required String inviteToken,
    required String callsign,
    required String deviceSecret,
  }) async {
    final r = await _call(
      'POST',
      '/api/v1/join',
      baseUrl: baseUrl,
      auth: false,
      data: {
        'invite_token': inviteToken,
        'callsign': callsign,
        'device_secret': deviceSecret,
      },
    );
    return _sessionFrom(r.data as Map<String, dynamic>, baseUrl);
  }

  @override
  Future<String> replaceInvite() async {
    final r = await _call('POST', '$_mission/invites/replace');
    return (r.data as Map<String, dynamic>)['token'] as String;
  }

  @override
  Future<Participant> me() async {
    final r = await _call('GET', '$_mission/me');
    return Participant.fromJson(r.data as Map<String, dynamic>);
  }

  @override
  Future<Participant> patchParticipant(
    String id, {
    String? role,
    String? status,
    bool? isActive,
    bool? trusted,
    bool resetDevice = false,
  }) async {
    final r = await _call(
      'PATCH',
      '$_mission/participants/$id',
      data: {
        'role': ?role,
        'status': ?status,
        'is_active': ?isActive,
        'trusted': ?trusted,
        if (resetDevice) 'reset_device': true,
      },
    );
    return Participant.fromJson(r.data as Map<String, dynamic>);
  }

  @override
  Future<List<AuditEntry>> audit({int limit = 200}) async {
    final r = await _call('GET', '$_mission/audit?limit=$limit');
    return [
      for (final e in r.data as List)
        AuditEntry.fromJson(e as Map<String, dynamic>),
    ];
  }

  @override
  Future<Map<String, String>> joinCodes() async {
    final r = await _call('GET', '$_mission/participants');
    return {
      for (final p in r.data as List)
        if ((p as Map<String, dynamic>)['join_code'] != null)
          p['id'] as String: p['join_code'] as String,
    };
  }

  @override
  Future<Map<String, List<String>>> plausibility() async {
    final r = await _call('GET', '$_mission/plausibility');
    return {
      for (final e in r.data as List)
        (e as Map<String, dynamic>)['participant_id'] as String: [
          for (final f in e['flags'] as List)
            (f as Map<String, dynamic>)['detail'] as String,
        ],
    };
  }

  @override
  Future<QuarantineResult> quarantine(String id, {bool remove = false}) async {
    final r = await _call(
      'POST',
      '$_mission/participants/$id/quarantine',
      data: {'remove': remove},
    );
    final j = r.data as Map<String, dynamic>;
    return QuarantineResult(
      participant: Participant.fromJson(
        j['participant'] as Map<String, dynamic>,
      ),
      bearings: j['bearings_deactivated'] as int,
      rssi: j['rssi_deactivated'] as int,
    );
  }

  @override
  Future<Map<String, dynamic>> snapshot() async {
    final r = await _call('GET', '$_mission/snapshot');
    return r.data as Map<String, dynamic>;
  }

  @override
  Future<SendResult> sendQueued(OutboxEntry e) async {
    try {
      await _call(
        e.method,
        e.path,
        data: e.bodyJson == null ? null : jsonDecode(e.bodyJson!),
      );
      return const SendResult(SendOutcome.ok);
    } on ApiException catch (ex) {
      final code = ex.statusCode;
      // Starting/stopping a transmission twice is not an error: the state is already right.
      if (code == 409 && (e.kind == 'tx_start' || e.kind == 'tx_stop')) {
        return const SendResult(SendOutcome.ok);
      }
      if (code == null || code >= 500 || code == 408 || code == 429) {
        return SendResult(SendOutcome.retry, ex.message);
      }
      if (code == 401 || code == 403) {
        return SendResult(
          SendOutcome.retry,
          'Anmeldung abgelaufen: ${ex.message}',
        );
      }
      return SendResult(SendOutcome.rejected, ex.message);
    }
  }

  @override
  Future<double> declination(double lat, double lon) async {
    final r = await _call('GET', '/api/v1/declination?lat=$lat&lon=$lon');
    return ((r.data as Map<String, dynamic>)['declination_deg'] as num)
        .toDouble();
  }

  @override
  Future<Estimate?> queryEstimate({
    List<String> transmissions = const [],
    DateTime? since,
    double? halfLifeS,
  }) async {
    final query = <String>[
      for (final t in transmissions) 'transmission=$t',
      if (since != null)
        'since=${Uri.encodeQueryComponent(since.toUtc().toIso8601String())}',
      if (halfLifeS != null) 'half_life_s=$halfLifeS',
    ].join('&');
    try {
      final r = await _call('GET', '$_mission/estimate/query?$query');
      return Estimate.fromJson(r.data as Map<String, dynamic>);
    } on ApiException catch (e) {
      if (e.statusCode == 404) return null;
      rethrow;
    }
  }

  @override
  Future<List<Suggestion>> suggestions({
    required String scope,
    double sigmaDeg = 10,
  }) async {
    try {
      final r = await _call(
        'GET',
        '$_mission/suggestions?scope=$scope&sigma_deg=$sigmaDeg',
      );
      return [
        for (final s in (r.data as Map<String, dynamic>)['suggestions'] as List)
          Suggestion.fromJson(s as Map<String, dynamic>),
      ];
    } on ApiException catch (e) {
      if (e.statusCode == 404) return const [];
      rethrow;
    }
  }

  @override
  Future<List<SensorInfo>> listSensors() async {
    final r = await _call('GET', '$_mission/sensors');
    return [
      for (final s in r.data as List)
        SensorInfo.fromJson(s as Map<String, dynamic>),
    ];
  }

  @override
  Future<SensorInfo> createSensor({
    required String name,
    required String kind,
    double? lat,
    double? lon,
  }) async {
    final r = await _call(
      'POST',
      '$_mission/sensors',
      data: {'name': name, 'kind': kind, 'lat': lat, 'lon': lon},
    );
    return SensorInfo.fromJson(r.data as Map<String, dynamic>);
  }

  @override
  Future<SensorInfo> setSensorActive(String id, {required bool active}) async {
    final r = await _call(
      'PATCH',
      '$_mission/sensors/$id',
      data: {'is_active': active},
    );
    return SensorInfo.fromJson(r.data as Map<String, dynamic>);
  }

  @override
  Future<List<int>> exportBytes(String format) async {
    try {
      final r = await _dio.get<List<int>>(
        '${_session!.baseUrl}$_mission/export.$format',
        options: Options(
          responseType: ResponseType.bytes,
          headers: {'Authorization': 'Bearer ${_session.token}'},
        ),
      );
      return r.data!;
    } on DioException catch (e) {
      throw ApiException(e.response?.statusCode, e.message ?? 'Netzwerkfehler');
    }
  }
}

Mission missionFromSnapshot(Map<String, dynamic> s) =>
    Mission.fromJson(s['mission'] as Map<String, dynamic>);
