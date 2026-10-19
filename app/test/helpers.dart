import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:foxgrid/core/api.dart';
import 'package:foxgrid/core/models.dart';
import 'package:foxgrid/core/outbox.dart';
import 'package:foxgrid/core/session.dart';
import 'package:latlong2/latlong.dart';
import 'package:foxgrid/core/sync.dart';
import 'package:foxgrid/state/providers.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:stream_channel/stream_channel.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

const testSession = Session(
  baseUrl: 'http://localhost:8000',
  token: 't',
  missionId: 'm1',
  participantId: 'p1',
  callsign: 'DL1ABC',
  role: 'lead',
);

Map<String, dynamic> snapshotJson({
  List<Map<String, dynamic>> bearings = const [],
  List<Map<String, dynamic>> transmissions = const [],
  List<Map<String, dynamic>> estimates = const [],
  List<Map<String, dynamic>> messages = const [],
  List<Map<String, dynamic>> tasks = const [],
  Map<String, dynamic>? repeater,
  List<Map<String, dynamic>> rssi = const [],
}) => {
  'mission': {
    'id': 'm1',
    'name': 'Test hunt',
    'frequency_mhz': 433.5,
    'status': 'active',
    'repeater': ?repeater,
  },
  'rssi': rssi,
  'participants': [
    {'id': 'p1', 'callsign': 'DL1ABC', 'role': 'lead', 'team': 'Alpha'},
    {'id': 'p2', 'callsign': 'DL2XYZ', 'role': 'mobile', 'team': null},
  ],
  'positions': <dynamic>[],
  'bearings': bearings,
  'transmissions': transmissions,
  'estimates': estimates,
  'messages': messages,
  'tasks': tasks,
  'teams': [
    {'id': 't1', 'name': 'Alpha'},
  ],
};

Map<String, dynamic> bearingJson(
  String id, {
  double az = 90,
  bool outlier = false,
  String? tx,
}) => {
  'id': id,
  'participant_id': 'p2',
  'transmission_id': tx,
  'lat': 48.1,
  'lon': 11.5,
  'azimuth_true_deg': az,
  'sigma_deg': 10.0,
  'measured_at': '2026-01-01T10:00:00Z',
  'is_outlier': outlier,
  'is_active': true,
  'rssi_dbm': null,
  'note': null,
};

Map<String, dynamic> estimateJson({String scope = 'all', int n = 3}) {
  Map<String, dynamic> ellipse() => {
    'semi_major_m': 100.0,
    'semi_minor_m': 50.0,
    'orientation_deg': 10.0,
    'polygon': {
      'type': 'Polygon',
      'coordinates': [
        [
          [11.0, 48.0],
          [11.1, 48.0],
          [11.0, 48.0],
        ],
      ],
    },
  };
  return {
    'id': 'e1',
    'scope': scope,
    'n_bearings': n,
    'lat': 48.1,
    'lon': 11.5,
    'computed_at': '2026-01-01T10:00:00Z',
    'ellipse_1s': ellipse(),
    'ellipse_2s': ellipse(),
    'contours': {
      '50': [ellipse()['polygon']],
      '95': [ellipse()['polygon']],
    },
  };
}

class FakeApi implements FoxGridApi {
  Map<String, dynamic>? snapshotData;
  Object? snapshotError;
  SendResult sendResult = const SendResult(SendOutcome.ok);
  final sent = <OutboxEntry>[];
  Estimate? queried;
  final queries = <Map<String, dynamic>>[];
  double declinationValue = 4.5;
  Object? declinationError;

  @override
  Future<Map<String, dynamic>> snapshot() async {
    if (snapshotError != null) throw snapshotError!;
    return snapshotData ?? snapshotJson();
  }

  @override
  Future<SendResult> sendQueued(OutboxEntry entry) async {
    sent.add(entry);
    return sendResult;
  }

  @override
  Future<double> declination(double lat, double lon) async {
    if (declinationError != null) throw declinationError!;
    return declinationValue;
  }

  @override
  Future<Estimate?> queryEstimate({
    List<String> transmissions = const [],
    DateTime? since,
    double? halfLifeS,
  }) async {
    queries.add({
      'transmissions': transmissions,
      'since': since,
      'halfLifeS': halfLifeS,
    });
    return queried;
  }

  @override
  Future<List<int>> exportBytes(String format) async => [1, 2, 3];

  List<Suggestion> suggestionList = const [];
  Object? suggestionsError;
  final suggestionCalls = <String>[];

  @override
  Future<List<Suggestion>> suggestions({
    required String scope,
    double sigmaDeg = 10,
  }) async {
    suggestionCalls.add(scope);
    if (suggestionsError != null) throw suggestionsError!;
    return suggestionList;
  }

  Participant meValue = const Participant(
    id: 'p1',
    callsign: 'DL1ABC',
    role: 'lead',
  );
  Object? meError;
  final patched = <Map<String, Object?>>[];
  String? replacedInvite;

  @override
  Future<Participant> me() async {
    if (meError != null) throw meError!;
    return meValue;
  }

  @override
  Future<String> replaceInvite() async => replacedInvite = 'new-invite-token';

  @override
  Future<Participant> patchParticipant(
    String id, {
    String? role,
    String? status,
    bool? isActive,
    bool resetDevice = false,
  }) async {
    patched.add({
      'id': id,
      'role': role,
      'status': status,
      'isActive': isActive,
      'resetDevice': resetDevice,
    });
    final known = [
      for (final p in (snapshotData ?? snapshotJson())['participants'] as List)
        Participant.fromJson(p as Map<String, dynamic>),
    ].firstWhere((p) => p.id == id);
    return Participant(
      id: id,
      callsign: known.callsign,
      role: role ?? known.role,
      status: status ?? known.status,
      isActive: isActive ?? known.isActive,
      deviceBound: resetDevice ? false : known.deviceBound,
    );
  }

  List<SensorInfo> sensorList = [];
  Object? createSensorError;
  final createdSensors = <Map<String, Object?>>[];
  final toggled = <(String, bool)>[];

  @override
  Future<List<SensorInfo>> listSensors() async => List.of(sensorList);

  @override
  Future<SensorInfo> createSensor({
    required String name,
    required String kind,
    double? lat,
    double? lon,
  }) async {
    if (createSensorError != null) throw createSensorError!;
    createdSensors.add({'name': name, 'kind': kind, 'lat': lat, 'lon': lon});
    final s = sensorInfo(name: name, kind: kind, apiKey: 'fgs_secret_key');
    sensorList = [...sensorList, s];
    return s;
  }

  @override
  Future<SensorInfo> setSensorActive(String id, {required bool active}) async {
    toggled.add((id, active));
    return sensorList.firstWhere((s) => s.id == id);
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class FakeSink implements WebSocketSink {
  FakeSink(this.sent);

  final List<String> sent;

  @override
  void add(dynamic data) => sent.add(data as String);

  @override
  void addError(Object error, [StackTrace? stackTrace]) {}

  @override
  Future<void> addStream(Stream<dynamic> stream) async {}

  @override
  Future<void> close([int? closeCode, String? closeReason]) async {}

  @override
  Future<void> get done => Completer<void>().future;
}

class FakeChannel extends StreamChannelMixin<dynamic>
    implements WebSocketChannel {
  final _in = StreamController<dynamic>.broadcast();
  final sent = <String>[];

  void push(String type, Map<String, dynamic> data) => _in.add(
    jsonEncode({
      'type': type,
      'mission_id': 'm1',
      'seq': 1,
      'ts': '2026-01-01T10:00:00Z',
      'data': data,
    }),
  );

  void drop() => _in.close();

  @override
  Stream<dynamic> get stream => _in.stream;

  @override
  WebSocketSink get sink => FakeSink(sent);

  @override
  Future<void> get ready => Future.value();

  @override
  int? get closeCode => null;

  @override
  String? get closeReason => null;

  @override
  String? get protocol => null;
}

class TestEnv {
  TestEnv({
    required this.container,
    required this.api,
    required this.store,
    required this.channel,
  });

  final ProviderContainer container;
  final FakeApi api;
  final MemoryOutboxStore store;
  final FakeChannel channel;

  MissionNotifier get mission => container.read(missionProvider.notifier);

  MissionState get state => container.read(missionProvider);

  /// Let the microtask-started load and event handlers run.
  Future<void> settle() async {
    for (var i = 0; i < 6; i++) {
      await Future<void>.delayed(Duration.zero);
    }
  }
}

Future<TestEnv> makeEnv({
  FakeApi? api,
  MemoryOutboxStore? store,
  Session? session = testSession,
  List<Override> extra = const [],
}) async {
  SharedPreferences.setMockInitialValues({});
  final prefs = await SharedPreferences.getInstance();
  if (session != null) await SessionStore(prefs).save(session);
  final fakeApi = api ?? FakeApi();
  final fakeStore = store ?? MemoryOutboxStore();
  final channel = FakeChannel();
  final container = ProviderContainer(
    overrides: [
      sharedPrefsProvider.overrideWithValue(prefs),
      apiProvider.overrideWithValue(fakeApi),
      outboxStoreProvider.overrideWithValue(fakeStore),
      channelFactoryProvider.overrideWithValue((_) => channel),
      ...extra,
    ],
  );
  return TestEnv(
    container: container,
    api: fakeApi,
    store: fakeStore,
    channel: channel,
  );
}

class LatLngForTest {
  const LatLngForTest(this.lat, this.lon);

  final double lat;
  final double lon;

  LatLng toLatLng() => LatLng(lat, lon);
}

class PositionFixForTest {
  static PositionFix at(double lat, double lon) => PositionFix(
    participantId: 'p1',
    point: LatLng(lat, lon),
    recordedAt: DateTime.utc(2026, 1, 1),
  );
}

/// Own position stub for widget tests.
class FakePosition extends OwnPositionNotifier {
  FakePosition(this.fix);

  final PositionFix? fix;

  @override
  PositionFix? build() => fix;
}

class WidgetEnv {
  WidgetEnv(this.api, this.store, this.channel);

  final FakeApi api;
  final MemoryOutboxStore store;
  final FakeChannel channel;
}

/// Pumps [child] with a real [MissionNotifier] on top of fake API, socket and queue.
Future<WidgetEnv> pumpWith(
  WidgetTester tester,
  Widget child, {
  PositionFix? fix,
  FakeApi? api,
  bool noFix = false,
  List<Override> extra = const [],
}) async {
  SharedPreferences.setMockInitialValues({});
  final prefs = await SharedPreferences.getInstance();
  await SessionStore(prefs).save(testSession);
  final fakeApi = api ?? FakeApi();
  final store = MemoryOutboxStore();
  final channel = FakeChannel();
  final position =
      fix ??
      PositionFix(
        participantId: 'p1',
        point: const LatLng(48.137, 11.575),
        recordedAt: DateTime.utc(2026, 1, 1),
        accuracyM: 5,
      );
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        sharedPrefsProvider.overrideWithValue(prefs),
        apiProvider.overrideWithValue(fakeApi),
        outboxStoreProvider.overrideWithValue(store),
        channelFactoryProvider.overrideWithValue((_) => channel),
        ownPositionProvider.overrideWith(
          () => FakePosition(noFix ? null : position),
        ),
        ...extra,
      ],
      child: MaterialApp(home: child),
    ),
  );
  return WidgetEnv(fakeApi, store, channel);
}

SensorInfo sensorInfo({
  String name = 'Station Nord',
  String kind = 'station',
  bool online = false,
  bool active = true,
  String? apiKey,
}) => SensorInfo(
  id: 'sensor-$name',
  name: name,
  kind: kind,
  callsign: name.toUpperCase().replaceAll(' ', ''),
  isActive: active,
  online: online,
  topicPrefix: 'foxgrid/m1/sensor-$name',
  lastSeenAt: online ? DateTime.utc(2026, 1, 1, 10, 0, 5) : null,
  apiKey: apiKey,
);

Suggestion suggestion(
  double reduction, {
  double az = 180,
  double dist = 1500,
}) => Suggestion(
  point: const LatLng(48.12, 11.57),
  expectedReduction: reduction,
  expectedSemiMajorM: 210,
  expectedSemiMinorM: 120,
  azimuthToTargetDeg: az,
  distanceToTargetM: dist,
);
