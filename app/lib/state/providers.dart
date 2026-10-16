import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geolocator/geolocator.dart';
import 'package:latlong2/latlong.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../core/api.dart';
import '../core/live.dart';
import '../core/models.dart';
import '../core/session.dart';

final sharedPrefsProvider = Provider<SharedPreferences>(
  (ref) => throw UnimplementedError('override in main()'),
);

/// Current login; `null` means show the join screen.
class SessionNotifier extends Notifier<Session?> {
  @override
  Session? build() => SessionStore(ref.watch(sharedPrefsProvider)).load();

  Future<void> set(Session s) async {
    await SessionStore(ref.read(sharedPrefsProvider)).save(s);
    state = s;
  }

  Future<void> leave() async {
    await SessionStore(ref.read(sharedPrefsProvider)).clear();
    state = null;
  }
}

final sessionProvider = NotifierProvider<SessionNotifier, Session?>(
  SessionNotifier.new,
);

/// API bound to the current session (join calls work without one).
final apiProvider = Provider<FoxGridApi>(
  (ref) => DioFoxGridApi(session: ref.watch(sessionProvider)),
);

class MissionState {
  const MissionState({
    this.mission,
    this.participants = const {},
    this.positions = const {},
    this.trails = const {},
    this.bearings = const {},
    this.transmissions = const [],
    this.estimates = const {},
    this.connection = LiveStatus.connecting,
    this.error,
    this.loaded = false,
  });

  final Mission? mission;
  final Map<String, Participant> participants;
  final Map<String, PositionFix> positions;
  final Map<String, List<LatLng>> trails;
  final Map<String, Bearing> bearings;
  final List<Transmission> transmissions;
  final Map<String, Estimate> estimates;
  final LiveStatus connection;
  final String? error;
  final bool loaded;

  Transmission? get running {
    for (final t in transmissions.reversed) {
      if (t.isRunning) return t;
    }
    return null;
  }

  MissionState copyWith({
    Mission? mission,
    Map<String, Participant>? participants,
    Map<String, PositionFix>? positions,
    Map<String, List<LatLng>>? trails,
    Map<String, Bearing>? bearings,
    List<Transmission>? transmissions,
    Map<String, Estimate>? estimates,
    LiveStatus? connection,
    String? error,
    bool clearError = false,
    bool? loaded,
  }) => MissionState(
    mission: mission ?? this.mission,
    participants: participants ?? this.participants,
    positions: positions ?? this.positions,
    trails: trails ?? this.trails,
    bearings: bearings ?? this.bearings,
    transmissions: transmissions ?? this.transmissions,
    estimates: estimates ?? this.estimates,
    connection: connection ?? this.connection,
    error: clearError ? null : (error ?? this.error),
    loaded: loaded ?? this.loaded,
  );
}

const _maxTrail = 60;

/// Holds the live state of the joined mission: snapshot + WebSocket events.
class MissionNotifier extends Notifier<MissionState> {
  LiveClient? _live;
  bool _disposed = false;

  @override
  MissionState build() {
    final session = ref.watch(sessionProvider);
    _disposed = false;
    ref.onDispose(() {
      _disposed = true;
      _live?.close();
    });
    if (session == null) return const MissionState();
    final api = ref.watch(apiProvider);
    final live = LiveClient(
      uri: session.wsUri,
      onEvent: _onEvent,
      onStatus: _onStatus,
    );
    _live = live;
    // Start after build() returned: both calls update `state`.
    Future.microtask(() {
      if (_disposed) return;
      live.start();
      unawaited(_loadSnapshot(api));
    });
    return const MissionState();
  }

  Future<void> _loadSnapshot(FoxGridApi api) async {
    try {
      final s = await api.snapshot();
      if (_disposed) return;
      final participants = {
        for (final p in s['participants'] as List)
          (p as Map<String, dynamic>)['id'] as String: Participant.fromJson(p),
      };
      final positions = {
        for (final p in s['positions'] as List)
          (p as Map<String, dynamic>)['participant_id'] as String:
              PositionFix.fromJson(p),
      };
      final estimates = {
        for (final e in s['estimates'] as List)
          (e as Map<String, dynamic>)['scope'] as String: Estimate.fromJson(e),
      };
      state = state.copyWith(
        mission: missionFromSnapshot(s),
        participants: participants,
        positions: positions,
        trails: {
          for (final e in positions.entries) e.key: [e.value.point],
        },
        bearings: {
          for (final b in s['bearings'] as List)
            (b as Map<String, dynamic>)['id'] as String: Bearing.fromJson(b),
        },
        transmissions: [
          for (final t in s['transmissions'] as List)
            Transmission.fromJson(t as Map<String, dynamic>),
        ],
        estimates: estimates,
        loaded: true,
        clearError: true,
      );
    } on ApiException catch (e) {
      if (e.statusCode == 401 || e.statusCode == 403) {
        await ref.read(sessionProvider.notifier).leave();
        return;
      }
      state = state.copyWith(error: e.message);
    }
  }

  void _onStatus(LiveStatus status) {
    if (_disposed) return;
    final previous = state.connection;
    state = state.copyWith(connection: status);
    // Events may have been missed while disconnected: resync from the snapshot.
    if (status == LiveStatus.connected &&
        previous == LiveStatus.reconnecting &&
        ref.exists(sessionProvider)) {
      unawaited(_loadSnapshot(ref.read(apiProvider)));
    }
  }

  void _onEvent(Map<String, dynamic> event) {
    if (_disposed) return;
    final data = event['data'];
    if (data is! Map<String, dynamic>) return;
    switch (event['type']) {
      case 'participant_position':
        final fix = PositionFix.fromJson(data);
        final trails = {...state.trails};
        final trail = [
          ...(trails[fix.participantId] ?? const <LatLng>[]),
          fix.point,
        ];
        trails[fix.participantId] = trail.length > _maxTrail
            ? trail.sublist(trail.length - _maxTrail)
            : trail;
        state = state.copyWith(
          positions: {...state.positions, fix.participantId: fix},
          trails: trails,
        );
        if (!state.participants.containsKey(fix.participantId)) {
          unawaited(_loadSnapshot(ref.read(apiProvider)));
        }
      case 'bearing_created' || 'bearing_updated':
        final b = Bearing.fromJson(data);
        state = state.copyWith(bearings: {...state.bearings, b.id: b});
      case 'transmission_started':
        _upsertTransmission(Transmission.fromJson(data));
        unawaited(HapticFeedback.heavyImpact());
      case 'transmission_ended':
        _upsertTransmission(Transmission.fromJson(data));
      case 'estimate_updated':
        final e = Estimate.fromJson(data);
        state = state.copyWith(estimates: {...state.estimates, e.scope: e});
    }
  }

  void _upsertTransmission(Transmission t) {
    final list = [...state.transmissions];
    final i = list.indexWhere((x) => x.id == t.id);
    if (i >= 0) {
      list[i] = t;
    } else {
      list.add(t);
    }
    list.sort((a, b) => a.seq.compareTo(b.seq));
    state = state.copyWith(transmissions: list);
  }

  Future<void> toggleTransmission() async {
    final api = ref.read(apiProvider);
    try {
      if (state.running == null) {
        await api.startTransmission();
      } else {
        await api.stopTransmission();
      }
    } on ApiException catch (e) {
      state = state.copyWith(error: e.message);
    }
  }

  Future<void> setOutlier(String bearingId, {required bool outlier}) async {
    try {
      await ref
          .read(apiProvider)
          .setBearingOutlier(bearingId, outlier: outlier);
    } on ApiException catch (e) {
      state = state.copyWith(error: e.message);
    }
  }

  void sendPosition(PositionFix fix) {
    _live?.send({
      'type': 'position',
      'data': {
        'lat': fix.point.latitude,
        'lon': fix.point.longitude,
        'accuracy_m': fix.accuracyM,
        'heading_deg': fix.headingDeg,
        'recorded_at': fix.recordedAt.toUtc().toIso8601String(),
      },
    });
  }

  /// Add a bearing that this device just saved so it shows up at once.
  void addLocalBearing(Bearing b) {
    state = state.copyWith(bearings: {...state.bearings, b.id: b});
  }

  void clearError() => state = state.copyWith(clearError: true);
}

final missionProvider = NotifierProvider<MissionNotifier, MissionState>(
  MissionNotifier.new,
);

/// Own GPS fix; `null` until the first reading or when unavailable.
class OwnPositionNotifier extends Notifier<PositionFix?> {
  StreamSubscription<Position>? _sub;
  String? lastError;

  @override
  PositionFix? build() {
    ref.onDispose(() => _sub?.cancel());
    final session = ref.watch(sessionProvider);
    if (session != null) Future.microtask(() => _start(session.participantId));
    return null;
  }

  Future<void> _start(String participantId) async {
    try {
      if (!await Geolocator.isLocationServiceEnabled()) {
        lastError = 'Ortungsdienste sind ausgeschaltet';
        return;
      }
      var perm = await Geolocator.checkPermission();
      if (perm == LocationPermission.denied) {
        perm = await Geolocator.requestPermission();
      }
      if (perm == LocationPermission.denied ||
          perm == LocationPermission.deniedForever) {
        lastError = 'Standortberechtigung fehlt';
        return;
      }
      _sub =
          Geolocator.getPositionStream(
            locationSettings: const LocationSettings(
              accuracy: LocationAccuracy.high,
              distanceFilter: 3,
            ),
          ).listen(
            (p) => state = PositionFix(
              participantId: participantId,
              point: LatLng(p.latitude, p.longitude),
              recordedAt: DateTime.now().toUtc(),
              accuracyM: p.accuracy,
              headingDeg: p.heading >= 0 ? p.heading : null,
            ),
            onError: (Object e) => lastError = e.toString(),
          );
    } on Object catch (e) {
      lastError = e.toString();
      if (kDebugMode) debugPrint('location error: $e');
    }
  }
}

final ownPositionProvider = NotifierProvider<OwnPositionNotifier, PositionFix?>(
  OwnPositionNotifier.new,
);

/// Sends the own position to the server every [interval] while it is moving or stale.
final positionReporterProvider = Provider<void>((ref) {
  const interval = Duration(seconds: 7);
  final timer = Timer.periodic(interval, (_) {
    final fix = ref.read(ownPositionProvider);
    if (fix != null) {
      ref
          .read(missionProvider.notifier)
          .sendPosition(
            PositionFix(
              participantId: fix.participantId,
              point: fix.point,
              recordedAt: DateTime.now().toUtc(),
              accuracyM: fix.accuracyM,
              headingDeg: fix.headingDeg,
            ),
          );
    }
  });
  ref.onDispose(timer.cancel);
});

/// Which estimate the map shows: the latest transmission or everything.
enum EstimateScope { current, all }

class ScopeNotifier extends Notifier<EstimateScope> {
  @override
  EstimateScope build() => EstimateScope.current;

  // ignore: use_setters_to_change_properties
  void select(EstimateScope s) => state = s;
}

final estimateScopeProvider = NotifierProvider<ScopeNotifier, EstimateScope>(
  ScopeNotifier.new,
);
