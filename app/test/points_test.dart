import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:foxgrid/core/outbox.dart';
import 'package:foxgrid/core/sync.dart';
import 'package:foxgrid/state/providers.dart';
import 'package:latlong2/latlong.dart';

import 'helpers.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late TestEnv env;

  Future<TestEnv> start({FakeApi? api, MemoryOutboxStore? store}) async {
    env = await makeEnv(api: api, store: store);
    addTearDown(env.container.dispose);
    env.container.read(missionProvider);
    env.container.read(syncProvider);
    await env.settle();
    return env;
  }

  FakeApi offline() =>
      FakeApi()..sendResult = const SendResult(SendOutcome.retry, 'offline');

  test('the snapshot carries points and external bearings', () async {
    final api = FakeApi()
      ..snapshotData = snapshotJson(
        points: [pointJson('pt1', useInEstimate: false)],
        bearings: [
          {...bearingJson('b1'), 'point_id': 'pt1'},
          bearingJson('b2'),
        ],
      );
    await start(api: api);
    final pt = env.state.points['pt1']!;
    expect(pt.name, 'BNetzA Köln');
    expect(pt.useInEstimate, isFalse);
    expect(pt.position, const LatLng(50.9, 6.9));
    expect(env.state.bearings['b1']!.isExternal, isTrue);
    expect(env.state.bearings['b2']!.isExternal, isFalse);
  });

  test(
    'a point and its bearing are shown at once and queued in order',
    () async {
      await start(api: offline());
      final id = await env.mission.createPoint(
        name: '  BNetzA Köln ',
        position: const LatLng(50.9, 6.9),
      );
      final point = env.state.points[id]!;
      expect(point.name, 'BNetzA Köln');

      await env.mission.saveExternalBearing(
        point,
        azimuthTrueDeg: 123.5,
        sigmaDeg: 15,
        measuredAt: DateTime.utc(2026, 1, 1, 10),
        sMeter: 6,
        note: 'per Telefon',
      );
      await env.settle();

      final queue = await env.store.all();
      expect(queue.map((e) => e.kind), ['point_create', 'bearing']);
      expect(queue[0].path, '/api/v1/missions/m1/points');
      final bearing = jsonDecode(queue[1].bodyJson!) as Map<String, dynamic>;
      expect(bearing['point_id'], id);
      expect(bearing['lat'], 50.9);
      expect(bearing['lon'], 6.9);
      expect(bearing['azimuth_true_deg'], 123.5);
      expect(bearing['azimuth_input_ref'], 'true');
      expect(bearing['sigma_deg'], 15);
      final shown = env.state.bearings[bearing['id']]!;
      expect(shown.pointId, id);
      expect(shown.isExternal, isTrue);
    },
  );

  test('patching a point updates it locally and queues a PATCH', () async {
    final api = offline()
      ..snapshotData = snapshotJson(points: [pointJson('pt1')]);
    await start(api: api);
    await env.mission.patchPoint('pt1', {'use_in_estimate': false});
    expect(env.state.points['pt1']!.useInEstimate, isFalse);
    await env.mission.patchPoint('pt1', {'name': 'BNetzA'});
    final queue = await env.store.all();
    expect(queue.map((e) => e.kind), ['point_patch', 'point_patch']);
    expect(queue.first.method, 'PATCH');
    expect(queue.first.path, '/api/v1/missions/m1/points/pt1');
    expect(env.state.points['pt1']!.name, 'BNetzA');
    expect(env.state.points['pt1']!.useInEstimate, isFalse);
  });

  test('queued points survive a restart and stay visible', () async {
    final store = MemoryOutboxStore();
    await start(api: offline(), store: store);
    final id = await env.mission.createPoint(
      name: 'BNetzA',
      position: const LatLng(50.9, 6.9),
    );
    await env.mission.patchPoint(id, {'use_in_estimate': false});
    await env.settle();
    env.container.dispose();

    await start(api: offline(), store: store);
    await env.settle();
    final pt = env.state.points[id]!;
    expect(pt.name, 'BNetzA');
    expect(pt.useInEstimate, isFalse);
  });

  test('live events add and change points', () async {
    await start();
    env.channel.push('point_created', pointJson('pt9'));
    await env.settle();
    expect(env.state.points['pt9']!.isActive, isTrue);
    env.channel.push('point_updated', pointJson('pt9', useInEstimate: false));
    await env.settle();
    expect(env.state.points['pt9']!.useInEstimate, isFalse);
  });
}
