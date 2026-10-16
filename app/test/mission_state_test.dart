import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:foxgrid/core/api.dart';
import 'package:foxgrid/core/live.dart';
import 'package:foxgrid/core/outbox.dart';
import 'package:foxgrid/core/sync.dart';
import 'package:foxgrid/state/providers.dart';

import 'helpers.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late TestEnv env;

  Future<TestEnv> start({FakeApi? api, MemoryOutboxStore? store}) async {
    env = await makeEnv(api: api, store: store);
    addTearDown(env.container.dispose);
    env.container.read(missionProvider); // build + start
    env.container.read(syncProvider);
    await env.settle();
    return env;
  }

  test('loads the snapshot incl. chat, tasks and teams', () async {
    final api = FakeApi()
      ..snapshotData = snapshotJson(
        bearings: [bearingJson('b1')],
        estimates: [estimateJson()],
        messages: [
          {
            'id': 'm1',
            'author_id': 'p2',
            'author_callsign': 'DL2XYZ',
            'team_id': null,
            'body': 'hallo',
            'sent_at': '2026-01-01T10:00:00Z',
          },
        ],
        tasks: [
          {
            'id': 't1',
            'title': 'Wache',
            'description': null,
            'status': 'open',
            'created_by': 'p1',
            'assignee_participant_id': null,
            'assignee_team_id': 't1',
          },
        ],
      );
    await start(api: api);
    final s = env.state;
    expect(s.loaded, isTrue);
    expect(s.stale, isFalse);
    expect(s.bearings.keys, ['b1']);
    expect(s.messages.single.body, 'hallo');
    expect(s.tasks['t1']!.assigneeTeamId, 't1');
    expect(s.teams.single.name, 'Alpha');
    expect(s.estimates['all']!.contours['95'], isNotEmpty);
    expect(s.connection, LiveStatus.connected);
  });

  test('starts offline from the cached snapshot', () async {
    final store = MemoryOutboxStore();
    final first = FakeApi()
      ..snapshotData = snapshotJson(bearings: [bearingJson('b1')]);
    await start(api: first, store: store);
    env.container.dispose();

    final offline = FakeApi()..snapshotError = ApiException(null, 'offline');
    await start(api: offline, store: store);
    expect(env.state.loaded, isTrue);
    expect(env.state.bearings.keys, ['b1']);
    expect(env.state.error, isNull);
  });

  test('without any cache an offline start reports the error', () async {
    final api = FakeApi()..snapshotError = ApiException(null, 'kein Netz');
    await start(api: api);
    expect(env.state.loaded, isFalse);
    expect(env.state.error, 'kein Netz');
  });

  test(
    'a bearing is shown at once and queued while the server is unreachable',
    () async {
      final api = FakeApi()
        ..sendResult = const SendResult(SendOutcome.retry, 'offline');
      await start(api: api);
      await env.mission.saveBearing({
        'id': 'new-1',
        'lat': 48.0,
        'lon': 11.0,
        'azimuth_true_deg': 123.0,
        'sigma_deg': 15.0,
        'measured_at': '2026-01-01T10:00:00Z',
      });
      await env.settle();

      expect(env.state.bearings['new-1']!.azimuthTrueDeg, 123.0);
      final queued = (await env.store.all()).single;
      expect(queued.kind, 'bearing');
      expect(queued.path, '/api/v1/missions/m1/bearings');
      expect(jsonDecode(queued.bodyJson!)['id'], 'new-1');
      expect(env.container.read(syncProvider).pending, 1);
      expect(env.container.read(syncProvider).allSynced, isFalse);
    },
  );

  test('queued writes are delivered once the server answers', () async {
    final api = FakeApi()
      ..sendResult = const SendResult(SendOutcome.retry, 'offline');
    await start(api: api);
    await env.mission.sendMessage('Aussendung gehört');
    await env.settle();
    expect(env.container.read(syncProvider).pending, 1);

    api.sendResult = const SendResult(SendOutcome.ok);
    // the entry is backing off; a manual kick after the delay delivers it
    final entry = (await env.store.all()).single;
    await env.store.update(entry.copyWith(nextAttemptAt: DateTime.utc(2000)));
    await env.container.read(syncProvider.notifier).kick();
    await env.settle();
    expect(env.container.read(syncProvider).pending, 0);
    expect(env.container.read(syncProvider).allSynced, isTrue);
    expect(env.container.read(syncProvider).lastSuccess, isNotNull);
    expect(api.sent.last.kind, 'message');
  });

  test('a rejected write shows up as failed', () async {
    final api = FakeApi()
      ..sendResult = const SendResult(SendOutcome.rejected, 'ungültig');
    await start(api: api);
    await env.mission.saveBearing({
      'id': 'x',
      'lat': 1.0,
      'lon': 1.0,
      'azimuth_true_deg': 1.0,
      'sigma_deg': 5.0,
      'measured_at': '2026-01-01T10:00:00Z',
    });
    await env.settle();
    final s = env.container.read(syncProvider);
    expect(s.failed, 1);
    expect(s.lastError, 'ungültig');
  });

  test('queued writes survive a reload and stay visible', () async {
    final store = MemoryOutboxStore();
    final api = FakeApi()
      ..sendResult = const SendResult(SendOutcome.retry, 'offline');
    await start(api: api, store: store);
    await env.mission.saveBearing({
      'id': 'pending-b',
      'lat': 48.0,
      'lon': 11.0,
      'azimuth_true_deg': 10.0,
      'sigma_deg': 5.0,
      'measured_at': '2026-01-01T10:00:00Z',
    });
    await env.mission.sendMessage('queued hello', id: 'pending-m');
    await env.mission.createTask(title: 'queued task', id: 'pending-t');
    await env.mission.patchTask('pending-t', {'status': 'in_progress'});
    await env.mission.toggleTransmission();
    await env.settle();
    env.container.dispose();

    // app restart: fresh state, same persistent outbox, server still unreachable
    final offline = FakeApi()
      ..snapshotError = ApiException(null, 'offline')
      ..sendResult = const SendResult(SendOutcome.retry, 'offline');
    await start(api: offline, store: store);
    await env.store.putCached('snapshot:m1', jsonEncode(snapshotJson()));
    env.container.invalidate(missionProvider);
    env.container.read(missionProvider);
    await env.settle();

    expect(env.state.bearings.containsKey('pending-b'), isTrue);
    expect(env.state.messages.single.pending, isTrue);
    expect(env.state.tasks['pending-t']!.status, 'in_progress');
    expect(env.state.running, isNotNull);
    expect(env.state.running!.local, isTrue);
  });

  test('outlier flag is applied optimistically', () async {
    final api = FakeApi()
      ..snapshotData = snapshotJson(bearings: [bearingJson('b1')])
      ..sendResult = const SendResult(SendOutcome.retry, 'offline');
    await start(api: api);
    await env.mission.setOutlier('b1', outlier: true);
    expect(env.state.bearings['b1']!.isOutlier, isTrue);
    final entry = (await env.store.all()).single;
    expect(entry.kind, 'outlier');
    expect(jsonDecode(entry.bodyJson!), {'is_outlier': true});
  });

  test(
    'transmission toggle is local first, then replaced by the server copy',
    () async {
      final api = FakeApi()
        ..sendResult = const SendResult(SendOutcome.retry, 'offline');
      await start(api: api);
      await env.mission.toggleTransmission();
      expect(env.state.running!.local, isTrue);
      expect((await env.store.all()).single.kind, 'tx_start');

      env.channel.push('transmission_started', {
        'id': 'tx-real',
        'seq': 1,
        'started_at': '2026-01-01T10:00:00Z',
        'ended_at': null,
      });
      await env.settle();
      expect(env.state.transmissions.single.id, 'tx-real');
      expect(env.state.transmissions.single.local, isFalse);

      await env.mission.toggleTransmission();
      expect(env.state.running, isNull);
      expect((await env.store.all()).last.kind, 'tx_stop');
    },
  );

  test('live events update bearings, estimate, chat and tasks', () async {
    await start();
    env.channel
      ..push('bearing_created', bearingJson('live-1', az: 45))
      ..push('estimate_updated', estimateJson(n: 4))
      ..push('message', {
        'id': 'c1',
        'author_id': 'p2',
        'author_callsign': 'DL2XYZ',
        'team_id': null,
        'body': 'live',
        'sent_at': '2026-01-01T10:00:00Z',
      })
      ..push('task_updated', {
        'id': 'tk',
        'title': 'Live task',
        'description': null,
        'status': 'done',
        'created_by': 'p1',
        'assignee_participant_id': null,
        'assignee_team_id': null,
      })
      ..push('participant_position', {
        'participant_id': 'p2',
        'lat': 48.2,
        'lon': 11.6,
        'recorded_at': '2026-01-01T10:00:00Z',
      });
    await env.settle();
    final s = env.state;
    expect(s.bearings['live-1']!.azimuthTrueDeg, 45);
    expect(s.estimates['all']!.nBearings, 4);
    expect(s.messages.single.body, 'live');
    expect(s.tasks['tk']!.status, 'done');
    expect(s.positions['p2']!.point.latitude, 48.2);

    // the same message again must not duplicate (sent by us and echoed by the server)
    env.channel.push('message', {
      'id': 'c1',
      'author_id': 'p2',
      'author_callsign': 'DL2XYZ',
      'team_id': null,
      'body': 'live',
      'sent_at': '2026-01-01T10:00:00Z',
    });
    await env.settle();
    expect(env.state.messages, hasLength(1));
  });

  test('own pending message is confirmed by the server echo', () async {
    final api = FakeApi()
      ..sendResult = const SendResult(SendOutcome.retry, 'offline');
    await start(api: api);
    await env.mission.sendMessage('hi', id: 'mine');
    expect(env.state.messages.single.pending, isTrue);
    env.channel.push('message', {
      'id': 'mine',
      'author_id': 'p1',
      'author_callsign': 'DL1ABC',
      'team_id': null,
      'body': 'hi',
      'sent_at': '2026-01-01T10:00:00Z',
    });
    await env.settle();
    expect(env.state.messages.single.pending, isFalse);
  });

  test('an auth failure on the snapshot logs the user out', () async {
    final api = FakeApi()..snapshotError = ApiException(401, 'invalid token');
    await start(api: api);
    expect(env.container.read(sessionProvider), isNull);
  });

  test('declination is fetched, cached and survives offline', () async {
    final api = FakeApi();
    await start(api: api);
    expect(env.container.read(declinationProvider), isNull);
    await env.container
        .read(declinationProvider.notifier)
        .refresh(const LatLngForTest(48, 11).toLatLng());
    expect(env.container.read(declinationProvider), 4.5);

    api.declinationError = ApiException(null, 'offline');
    api.declinationValue = 9;
    await env.container
        .read(declinationProvider.notifier)
        .refresh(const LatLngForTest(48, 11).toLatLng());
    expect(env.container.read(declinationProvider), 4.5);
  });

  test('sending a position goes over the socket', () async {
    await start();
    env.mission.sendPosition(PositionFixForTest.at(48.1, 11.5));
    expect(
      env.channel.sent.map(jsonDecode).any((m) => m['type'] == 'position'),
      isTrue,
    );
  });
}
