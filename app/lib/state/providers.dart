import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter_compass/flutter_compass.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geolocator/geolocator.dart';
import 'package:latlong2/latlong.dart';
import 'package:uuid/uuid.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../core/api.dart';
import '../core/database.dart';
import '../core/homing.dart';
import '../core/live.dart';
import '../core/models.dart';
import '../core/outbox.dart';
import '../core/session.dart';
import '../core/sync.dart';
import 'settings.dart';

export 'settings.dart' show sharedPrefsProvider, settingsProvider;

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

/// Persistent offline queue. The web build keeps it in memory (no sqlite wasm bundled yet).
final outboxStoreProvider = Provider<OutboxStore>((ref) {
  if (kIsWeb) return MemoryOutboxStore();
  final db = AppDatabase();
  ref.onDispose(db.close);
  return DriftOutboxStore(db);
});

/// Creates the WebSocket connection; replaced in tests.
final channelFactoryProvider = Provider<ChannelFactory>(
  (ref) => WebSocketChannel.connect,
);

// --- sync queue -----------------------------------------------------------------------

class SyncStatus {
  const SyncStatus({
    this.pending = 0,
    this.failed = 0,
    this.syncing = false,
    this.lastSuccess,
    this.lastError,
  });

  final int pending;
  final int failed;
  final bool syncing;
  final DateTime? lastSuccess;
  final String? lastError;

  bool get allSynced => pending == 0 && failed == 0;

  SyncStatus copyWith({
    int? pending,
    int? failed,
    bool? syncing,
    DateTime? lastSuccess,
    String? lastError,
    bool clearError = false,
  }) => SyncStatus(
    pending: pending ?? this.pending,
    failed: failed ?? this.failed,
    syncing: syncing ?? this.syncing,
    lastSuccess: lastSuccess ?? this.lastSuccess,
    lastError: clearError ? null : (lastError ?? this.lastError),
  );
}

class SyncNotifier extends Notifier<SyncStatus> {
  SyncService? _service;
  StreamSubscription<List<OutboxEntry>>? _sub;
  Timer? _timer;
  bool _disposed = false;

  @override
  SyncStatus build() {
    _disposed = false;
    final store = ref.watch(outboxStoreProvider);
    final api = ref.watch(apiProvider);
    _service = SyncService(store: store, send: api.sendQueued);
    _sub = store.watch().listen(_onEntries);
    _timer = Timer.periodic(const Duration(seconds: 5), (_) => kick());
    ref.onDispose(() {
      _disposed = true;
      _sub?.cancel();
      _timer?.cancel();
    });
    return const SyncStatus();
  }

  void _onEntries(List<OutboxEntry> entries) {
    if (_disposed) return;
    final failed = entries.where((e) => e.isFailed).toList();
    final pending = entries.where((e) => !e.isFailed).toList();
    final err = pending.map((e) => e.lastError).whereType<String>().firstOrNull;
    state = SyncStatus(
      pending: pending.length,
      failed: failed.length,
      syncing: state.syncing,
      lastSuccess: state.lastSuccess,
      lastError:
          err ?? failed.map((e) => e.lastError).whereType<String>().firstOrNull,
    );
  }

  /// Try to deliver the queue now (called after every write and when back online).
  Future<void> kick() async {
    final session = ref.read(sessionProvider);
    if (_disposed || session == null || state.syncing) return;
    state = state.copyWith(syncing: true);
    try {
      final delivered = await _service!.run(missionId: session.missionId);
      if (_disposed) return;
      state = state.copyWith(
        syncing: false,
        lastSuccess: delivered > 0 ? DateTime.now() : null,
      );
    } on Object catch (e) {
      if (!_disposed) state = state.copyWith(syncing: false, lastError: '$e');
    }
  }

  Future<void> retry(OutboxEntry e) async {
    await _service!.retry(e);
    unawaited(kick());
  }

  Future<void> discard(OutboxEntry e) => _service!.discard(e);
}

final syncProvider = NotifierProvider<SyncNotifier, SyncStatus>(
  SyncNotifier.new,
);

/// All queue entries for the sync sheet.
final outboxEntriesProvider = StreamProvider.autoDispose<List<OutboxEntry>>(
  (ref) => ref.watch(outboxStoreProvider).watch(),
);

// --- mission state ----------------------------------------------------------------------

class MissionState {
  const MissionState({
    this.mission,
    this.participants = const {},
    this.positions = const {},
    this.trails = const {},
    this.bearings = const {},
    this.transmissions = const [],
    this.estimates = const {},
    this.messages = const [],
    this.tasks = const {},
    this.teams = const [],
    this.rssi = const [],
    this.connection = LiveStatus.connecting,
    this.error,
    this.loaded = false,
    this.stale = false,
  });

  final Mission? mission;
  final Map<String, Participant> participants;
  final Map<String, PositionFix> positions;
  final Map<String, List<LatLng>> trails;
  final Map<String, Bearing> bearings;
  final List<Transmission> transmissions;
  final Map<String, Estimate> estimates;
  final List<ChatMessage> messages;
  final Map<String, TaskItem> tasks;
  final List<Team> teams;

  /// Signal strength readings of all participants, oldest first.
  final List<RssiSample> rssi;
  final LiveStatus connection;
  final String? error;
  final bool loaded;

  /// Showing the cached snapshot because the server could not be reached yet.
  final bool stale;

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
    List<ChatMessage>? messages,
    Map<String, TaskItem>? tasks,
    List<Team>? teams,
    List<RssiSample>? rssi,
    LiveStatus? connection,
    String? error,
    bool clearError = false,
    bool? loaded,
    bool? stale,
  }) => MissionState(
    mission: mission ?? this.mission,
    participants: participants ?? this.participants,
    positions: positions ?? this.positions,
    trails: trails ?? this.trails,
    bearings: bearings ?? this.bearings,
    transmissions: transmissions ?? this.transmissions,
    estimates: estimates ?? this.estimates,
    messages: messages ?? this.messages,
    tasks: tasks ?? this.tasks,
    teams: teams ?? this.teams,
    rssi: rssi ?? this.rssi,
    connection: connection ?? this.connection,
    error: clearError ? null : (error ?? this.error),
    loaded: loaded ?? this.loaded,
    stale: stale ?? this.stale,
  );
}

const _maxTrail = 60;

/// Holds the live state of the joined mission: snapshot + WebSocket events.
///
/// Every write goes to the outbox first and is applied to the state optimistically, so the
/// app keeps working offline; [SyncNotifier] delivers the queue.
class MissionNotifier extends Notifier<MissionState> {
  LiveClient? _live;
  bool _disposed = false;

  Session get _session => ref.read(sessionProvider)!;

  String get _base => '/api/v1/missions/${_session.missionId}';

  OutboxStore get _store => ref.read(outboxStoreProvider);

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
      connect: ref.read(channelFactoryProvider),
    );
    _live = live;
    // Start after build() returned: these calls update `state`.
    Future.microtask(() async {
      if (_disposed) return;
      live.start();
      await _loadCached(session.missionId);
      await _loadSnapshot(api);
    });
    return const MissionState();
  }

  String _cacheKey(String missionId) => 'snapshot:$missionId';

  Future<void> _loadCached(String missionId) async {
    final raw = await _store.getCached(_cacheKey(missionId));
    if (raw == null || _disposed) return;
    try {
      await _apply(jsonDecode(raw) as Map<String, dynamic>, stale: true);
    } on Object {
      // a broken cache must never block the app
    }
  }

  Future<void> _loadSnapshot(FoxGridApi api) async {
    try {
      final s = await api.snapshot();
      if (_disposed) return;
      unawaited(_store.putCached(_cacheKey(_session.missionId), jsonEncode(s)));
      await _apply(s, stale: false);
    } on ApiException catch (e) {
      if (e.statusCode == 401 || e.statusCode == 403) {
        await ref.read(sessionProvider.notifier).leave();
        return;
      }
      // Offline: keep the cached state and stay usable.
      if (!state.loaded) state = state.copyWith(error: e.message);
    }
  }

  Future<void> _apply(Map<String, dynamic> s, {required bool stale}) async {
    final participants = {
      for (final p in s['participants'] as List)
        (p as Map<String, dynamic>)['id'] as String: Participant.fromJson(p),
    };
    final positions = {
      for (final p in s['positions'] as List)
        (p as Map<String, dynamic>)['participant_id'] as String:
            PositionFix.fromJson(p),
    };
    var next = state.copyWith(
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
      estimates: {
        for (final e in s['estimates'] as List)
          (e as Map<String, dynamic>)['scope'] as String: Estimate.fromJson(e),
      },
      messages: [
        for (final m in (s['messages'] as List?) ?? const [])
          ChatMessage.fromJson(m as Map<String, dynamic>),
      ],
      tasks: {
        for (final t in (s['tasks'] as List?) ?? const [])
          (t as Map<String, dynamic>)['id'] as String: TaskItem.fromJson(t),
      },
      teams: [
        for (final t in (s['teams'] as List?) ?? const [])
          Team.fromJson(t as Map<String, dynamic>),
      ],
      rssi: [
        for (final r in (s['rssi'] as List?) ?? const [])
          RssiSample.fromJson(r as Map<String, dynamic>),
      ],
      loaded: true,
      stale: stale,
      clearError: true,
    );
    next = await _overlayPending(next);
    if (!_disposed) state = next;
  }

  /// Re-applies writes that are still queued, so they stay visible after a reload.
  Future<MissionState> _overlayPending(MissionState base) async {
    var s = base;
    final session = ref.read(sessionProvider);
    if (session == null) return s;
    for (final e in await _store.all()) {
      if (e.missionId != session.missionId) continue;
      try {
        final decoded = e.bodyJson == null ? null : jsonDecode(e.bodyJson!);
        if (e.kind == 'rssi') {
          final known = {for (final r in s.rssi) r.id};
          s = s.copyWith(
            rssi: [
              ...s.rssi,
              for (final item in decoded as List)
                if (!known.contains((item as Map<String, dynamic>)['id']))
                  _rssiFromPayload(item, session),
            ],
          );
          continue;
        }
        final body = decoded == null
            ? <String, dynamic>{}
            : decoded as Map<String, dynamic>;
        switch (e.kind) {
          case 'bearing':
            s = _withBearing(s, _bearingFromPayload(body, session));
          case 'message':
            if (!s.messages.any((m) => m.id == body['id'])) {
              s = s.copyWith(
                messages: [...s.messages, _messageFromPayload(body, session)],
              );
            }
          case 'task_create':
            s = s.copyWith(
              tasks: {
                ...s.tasks,
                body['id'] as String:
                    s.tasks[body['id']] ?? _taskFromPayload(body, session),
              },
            );
          case 'task_patch':
            final id = e.path.split('/').last;
            final t = s.tasks[id];
            if (t != null) {
              s = s.copyWith(tasks: {...s.tasks, id: _patchTask(t, body)});
            }
          case 'outlier':
            final id = e.path.split('/').last;
            final b = s.bearings[id];
            if (b != null) {
              s = s.copyWith(
                bearings: {
                  ...s.bearings,
                  id: _withOutlier(b, body['is_outlier'] as bool),
                },
              );
            }
          case 'tx_start':
            if (s.running == null) {
              s = s.copyWith(
                transmissions: [
                  ...s.transmissions,
                  _localTransmission(s, body),
                ],
              );
            }
          case 'tx_stop':
            s = _endRunning(s, DateTime.parse(body['at'] as String).toUtc());
        }
      } on Object {
        continue; // a malformed queue entry must never break the app
      }
    }
    return s;
  }

  void _onStatus(LiveStatus status) {
    if (_disposed) return;
    final previous = state.connection;
    state = state.copyWith(connection: status);
    if (status == LiveStatus.connected) {
      // Back online: deliver queued writes and resync what may have been missed.
      unawaited(ref.read(syncProvider.notifier).kick());
      if (previous == LiveStatus.reconnecting) {
        unawaited(_loadSnapshot(ref.read(apiProvider)));
      }
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
        state = _withBearing(state, Bearing.fromJson(data));
      case 'transmission_started':
        // The server copy replaces our optimistic local one.
        state = state.copyWith(
          transmissions: [
            for (final t in state.transmissions)
              if (!(t.local && t.isRunning)) t,
          ],
        );
        _upsertTransmission(Transmission.fromJson(data));
        // Not every platform can vibrate; an alert must never throw.
        unawaited(HapticFeedback.heavyImpact().catchError((Object _) {}));
      case 'transmission_ended':
        _upsertTransmission(Transmission.fromJson(data));
      case 'estimate_updated':
        final e = Estimate.fromJson(data);
        state = state.copyWith(estimates: {...state.estimates, e.scope: e});
      case 'message':
        final m = ChatMessage.fromJson(data);
        final list = [
          for (final x in state.messages)
            if (x.id != m.id) x,
          m,
        ]..sort((a, b) => a.sentAt.compareTo(b.sentAt));
        state = state.copyWith(messages: list);
      case 'task_updated':
        final t = TaskItem.fromJson(data);
        state = state.copyWith(tasks: {...state.tasks, t.id: t});
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

  // --- optimistic helpers -------------------------------------------------------------

  static MissionState _withBearing(MissionState s, Bearing b) =>
      s.copyWith(bearings: {...s.bearings, b.id: b});

  static Bearing _withOutlier(Bearing b, bool outlier) => Bearing(
    id: b.id,
    participantId: b.participantId,
    station: b.station,
    azimuthTrueDeg: b.azimuthTrueDeg,
    sigmaDeg: b.sigmaDeg,
    measuredAt: b.measuredAt,
    isOutlier: outlier,
    isActive: b.isActive,
    transmissionId: b.transmissionId,
    rssiDbm: b.rssiDbm,
    note: b.note,
  );

  static Bearing _bearingFromPayload(Map<String, dynamic> p, Session s) =>
      Bearing(
        id: p['id'] as String,
        participantId: s.participantId,
        station: LatLng(
          (p['lat'] as num).toDouble(),
          (p['lon'] as num).toDouble(),
        ),
        azimuthTrueDeg: (p['azimuth_true_deg'] as num).toDouble(),
        sigmaDeg: (p['sigma_deg'] as num).toDouble(),
        measuredAt: DateTime.parse(p['measured_at'] as String).toUtc(),
        isOutlier: false,
        isActive: true,
        rssiDbm: (p['rssi_dbm'] as num?)?.toDouble(),
        note: p['note'] as String?,
      );

  static RssiSample _rssiFromPayload(Map<String, dynamic> p, Session s) =>
      RssiSample(
        id: p['id'] as String,
        participantId: s.participantId,
        point: LatLng(
          (p['lat'] as num).toDouble(),
          (p['lon'] as num).toDouble(),
        ),
        rssiDbm: (p['rssi_dbm'] as num).toDouble(),
        attenuationDb: (p['attenuation_db'] as num?)?.toDouble() ?? 0,
        measuredAt: DateTime.parse(p['measured_at'] as String).toUtc(),
        pending: true,
        receiver: (p['receiver'] as String?) ?? 'mobile',
        isCalibration: (p['is_calibration'] as bool?) ?? false,
      );

  static ChatMessage _messageFromPayload(Map<String, dynamic> p, Session s) =>
      ChatMessage(
        id: p['id'] as String,
        authorId: s.participantId,
        authorCallsign: s.callsign,
        teamId: p['team_id'] as String?,
        body: p['body'] as String,
        sentAt: DateTime.parse(p['sent_at'] as String).toUtc(),
        pending: true,
      );

  static TaskItem _taskFromPayload(Map<String, dynamic> p, Session s) =>
      TaskItem(
        id: p['id'] as String,
        title: p['title'] as String,
        description: p['description'] as String?,
        status: 'open',
        createdBy: s.participantId,
        assigneeParticipantId: p['assignee_participant_id'] as String?,
        assigneeTeamId: p['assignee_team_id'] as String?,
        pending: true,
      );

  static TaskItem _patchTask(TaskItem t, Map<String, dynamic> changes) {
    var out = t.copyWith(
      title: changes['title'] as String?,
      status: changes['status'] as String?,
      pending: true,
    );
    if (changes.containsKey('assignee_participant_id') ||
        changes.containsKey('assignee_team_id')) {
      out = out.copyWith(
        clearAssignee: true,
        assigneeParticipantId: changes['assignee_participant_id'] as String?,
        assigneeTeamId: changes['assignee_team_id'] as String?,
      );
    }
    return out;
  }

  static Transmission _localTransmission(
    MissionState s,
    Map<String, dynamic> body,
  ) => Transmission(
    id: 'local-${body['at']}',
    seq: s.transmissions.fold(0, (m, t) => t.seq > m ? t.seq : m) + 1,
    startedAt: DateTime.parse(body['at'] as String).toUtc(),
    local: true,
  );

  static MissionState _endRunning(MissionState s, DateTime at) => s.copyWith(
    transmissions: [
      for (final t in s.transmissions)
        t.isRunning ? t.copyWith(endedAt: at) : t,
    ],
  );

  Future<void> _enqueue({
    required String kind,
    required String method,
    required String path,
    Object? body,
  }) async {
    await _store.add(
      missionId: _session.missionId,
      kind: kind,
      method: method,
      path: path,
      bodyJson: body == null ? null : jsonEncode(body),
    );
    unawaited(ref.read(syncProvider.notifier).kick());
  }

  // --- user actions (all offline-first) ---------------------------------------------------

  /// Logs one signal strength reading of the homing track (offline-first like everything else).
  Future<void> logRssi({
    required double rssiDbm,
    required PositionFix at,
    double attenuationDb = 0,
    String source = 'manual',
    DateTime? when,
    String receiver = 'mobile',
    bool isCalibration = false,
  }) async {
    final payload = {
      'id': const Uuid().v4(),
      'lat': at.point.latitude,
      'lon': at.point.longitude,
      'accuracy_m': at.accuracyM,
      'rssi_dbm': rssiDbm,
      'attenuation_db': attenuationDb,
      'measured_at': (when ?? DateTime.now()).toUtc().toIso8601String(),
      'source': source,
      if (receiver != 'mobile') 'receiver': receiver,
      if (isCalibration) 'is_calibration': true,
    };
    state = state.copyWith(
      rssi: [...state.rssi, _rssiFromPayload(payload, _session)],
    );
    await _enqueue(
      kind: 'rssi',
      method: 'POST',
      path: '$_base/rssi',
      body: [payload],
    );
  }

  /// Lead only: sets where the repeater is and on which frequencies it works.
  Future<void> setRepeater(Repeater repeater) async {
    final mission = state.mission;
    if (mission != null) {
      state = state.copyWith(mission: mission.withRepeater(repeater));
    }
    await _enqueue(
      kind: 'mission',
      method: 'PATCH',
      path: _base,
      body: {'repeater': repeater.toJson()},
    );
  }

  Future<void> saveBearing(Map<String, dynamic> payload) async {
    state = _withBearing(state, _bearingFromPayload(payload, _session));
    await _enqueue(
      kind: 'bearing',
      method: 'POST',
      path: '$_base/bearings',
      body: payload,
    );
  }

  Future<void> sendMessage(
    String body, {
    String? teamId,
    String? id,
    DateTime? at,
  }) async {
    final payload = {
      'id': id ?? _newId(),
      'body': body,
      'sent_at': (at ?? DateTime.now()).toUtc().toIso8601String(),
      'team_id': teamId,
    };
    state = state.copyWith(
      messages: [...state.messages, _messageFromPayload(payload, _session)],
    );
    await _enqueue(
      kind: 'message',
      method: 'POST',
      path: '$_base/messages',
      body: payload,
    );
  }

  Future<void> createTask({
    required String title,
    String? description,
    String? participantId,
    String? teamId,
    String? id,
  }) async {
    final payload = {
      'id': id ?? _newId(),
      'title': title,
      'description': description,
      'assignee_participant_id': participantId,
      'assignee_team_id': teamId,
    };
    state = state.copyWith(
      tasks: {
        ...state.tasks,
        payload['id']!: _taskFromPayload(payload, _session),
      },
    );
    await _enqueue(
      kind: 'task_create',
      method: 'POST',
      path: '$_base/tasks',
      body: payload,
    );
  }

  Future<void> patchTask(String id, Map<String, dynamic> changes) async {
    final t = state.tasks[id];
    if (t != null) {
      state = state.copyWith(
        tasks: {...state.tasks, id: _patchTask(t, changes)},
      );
    }
    await _enqueue(
      kind: 'task_patch',
      method: 'PATCH',
      path: '$_base/tasks/$id',
      body: changes,
    );
  }

  Future<void> setOutlier(String bearingId, {required bool outlier}) async {
    final b = state.bearings[bearingId];
    if (b != null) {
      state = _withBearing(state, _withOutlier(b, outlier));
    }
    await _enqueue(
      kind: 'outlier',
      method: 'PATCH',
      path: '$_base/bearings/$bearingId',
      body: {'is_outlier': outlier},
    );
  }

  Future<void> toggleTransmission() async {
    final at = DateTime.now().toUtc();
    final body = {'at': at.toIso8601String()};
    if (state.running == null) {
      state = state.copyWith(
        transmissions: [
          ...state.transmissions,
          _localTransmission(state, body),
        ],
      );
      await _enqueue(
        kind: 'tx_start',
        method: 'POST',
        path: '$_base/transmissions/start',
        body: body,
      );
    } else {
      state = _endRunning(state, at);
      await _enqueue(
        kind: 'tx_stop',
        method: 'POST',
        path: '$_base/transmissions/stop',
        body: body,
      );
    }
  }

  static String _newId() => const Uuid().v4();

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

/// Sends the own position to the server every few seconds (the server throttles to >= 5 s).
final positionReporterProvider = Provider<void>((ref) {
  final timer = Timer.periodic(const Duration(seconds: 7), (_) {
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

/// Latest known magnetic declination, cached so it works offline.
class DeclinationNotifier extends Notifier<double?> {
  static const _key = 'foxgrid.declination';

  @override
  double? build() => ref.watch(sharedPrefsProvider).getDouble(_key);

  /// Fetch for a position; silently keeps the cached value when offline.
  Future<void> refresh(LatLng at) async {
    try {
      final d = await ref
          .read(apiProvider)
          .declination(at.latitude, at.longitude);
      state = d;
      await ref.read(sharedPrefsProvider).setDouble(_key, d);
    } on ApiException {
      // offline: keep the cached value
    }
  }
}

final declinationProvider = NotifierProvider<DeclinationNotifier, double?>(
  DeclinationNotifier.new,
);

/// Fixed location of this station for the current mission (typed in, e.g. a home QTH without GPS
/// or with a poor fix indoors); persisted per mission. `null` = use the GPS position.
class StationPositionNotifier extends Notifier<LatLng?> {
  String? get _key {
    final id = ref.watch(sessionProvider)?.missionId;
    return id == null ? null : 'foxgrid.station.$id';
  }

  @override
  LatLng? build() {
    final key = _key;
    if (key == null) return null;
    final parts = ref.watch(sharedPrefsProvider).getString(key)?.split(',');
    if (parts == null || parts.length != 2) return null;
    final lat = double.tryParse(parts[0]);
    final lon = double.tryParse(parts[1]);
    return lat == null || lon == null ? null : LatLng(lat, lon);
  }

  Future<void> set(LatLng? point) async {
    state = point;
    final key = _key;
    if (key == null) return;
    final prefs = ref.read(sharedPrefsProvider);
    if (point == null) {
      await prefs.remove(key);
    } else {
      await prefs.setString(key, '${point.latitude},${point.longitude}');
    }
  }
}

final stationPositionProvider =
    NotifierProvider<StationPositionNotifier, LatLng?>(
      StationPositionNotifier.new,
    );

/// Attenuator currently in front of the receiver (dB); persisted so it survives restarts.
class AttenuationNotifier extends Notifier<int> {
  static const _key = 'foxgrid.attenuation';

  @override
  int build() => ref.watch(sharedPrefsProvider).getInt(_key) ?? 0;

  Future<void> set(int db) async {
    state = db;
    await ref.read(sharedPrefsProvider).setInt(_key, db);
  }
}

final attenuationProvider = NotifierProvider<AttenuationNotifier, int>(
  AttenuationNotifier.new,
);

/// Magnetic compass heading in degrees; `null` where there is no compass (web, desktop).
final compassProvider = StreamProvider<double?>((ref) {
  if (kIsWeb) return Stream.value(null);
  return FlutterCompass.events?.map((e) => e.heading) ?? Stream.value(null);
});

/// True heading: GPS course while moving, compass plus declination while standing still.
final headingProvider = Provider<double?>((ref) {
  final own = ref.watch(ownPositionProvider);
  return chooseHeading(
    gpsCourse: own?.headingDeg,
    speedMps: own?.speedMps,
    compassMagnetic: ref.watch(compassProvider).value,
    declinationDeg: ref.watch(declinationProvider) ?? 0,
  );
});

/// Whether the map shows the suggested bearing positions (fetched only while on).
class ShowSuggestionsNotifier extends Notifier<bool> {
  @override
  bool build() => false;

  // ignore: use_setters_to_change_properties
  void set(bool on) => state = on;
}

final showSuggestionsProvider = NotifierProvider<ShowSuggestionsNotifier, bool>(
  ShowSuggestionsNotifier.new,
);

/// The best places for the next bearing. Refreshes whenever the estimate changes.
final suggestionsProvider = FutureProvider.autoDispose<List<Suggestion>>((
  ref,
) async {
  if (!ref.watch(showSuggestionsProvider)) return const [];
  final scope = ref.watch(estimateScopeProvider);
  ref.watch(
    missionProvider.select(
      (s) =>
          s.estimates[scope.name]?.computedAt ?? s.estimates['all']?.computedAt,
    ),
  );
  return ref.read(apiProvider).suggestions(scope: scope.name);
});

/// Registered sensors of the mission (lead screen).
final sensorsProvider = FutureProvider.autoDispose<List<SensorInfo>>(
  (ref) => ref.watch(apiProvider).listSensors(),
);
