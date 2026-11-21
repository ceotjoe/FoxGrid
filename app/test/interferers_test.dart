import 'dart:convert';

import 'package:material_ui/material_ui.dart';

import 'package:flutter_test/flutter_test.dart';
import 'package:foxgrid/core/outbox.dart';
import 'package:foxgrid/core/sync.dart';
import 'package:foxgrid/state/providers.dart';
import 'package:foxgrid/ui/bearings_sheet.dart';
import 'package:foxgrid/ui/capture_sheet.dart';
import 'package:foxgrid/ui/interferers_screen.dart';

import 'helpers.dart';

Map<String, dynamic> _snapshot({
  List<Map<String, dynamic>> bearings = const [],
  List<Map<String, dynamic>> estimates = const [],
  bool interferers = true,
}) => snapshotJson(
  bearings: bearings,
  estimates: estimates,
  interferers: [
    if (interferers) ...[
      interfererJson('ia'),
      interfererJson('ib', name: 'Brummer', slot: 1),
    ],
  ],
);

Map<String, dynamic> _body(OutboxEntry e) =>
    jsonDecode(e.bodyJson!) as Map<String, dynamic>;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late TestEnv env;

  Future<TestEnv> start({FakeApi? api}) async {
    env = await makeEnv(api: api);
    addTearDown(env.container.dispose);
    env.container.read(missionProvider);
    env.container.read(syncProvider);
    await env.settle();
    return env;
  }

  FakeApi offline({Map<String, dynamic>? snapshot}) => FakeApi()
    ..snapshotData = snapshot ?? _snapshot()
    ..sendResult = const SendResult(SendOutcome.retry, 'offline');

  Future<List<OutboxEntry>> queue() => env.store.all();

  group('state', () {
    test(
      'the snapshot carries interferers and one estimate per interferer',
      () async {
        await start(
          api: FakeApi()
            ..snapshotData = _snapshot(
              bearings: [bearingJson('b1', interferer: 'ib')],
              estimates: [
                estimateJson(interferer: 'ia'),
                estimateJson(interferer: 'ib', n: 5),
              ],
            ),
        );
        expect(env.state.interferers.keys, ['ia', 'ib']);
        expect(env.state.interferers['ib']!.name, 'Brummer');
        expect(env.state.interferers['ib']!.letter, 'B');
        expect(env.state.bearings['b1']!.interfererId, 'ib');
        expect(env.state.estimateFor('ia', 'all')!.nBearings, 3);
        expect(env.state.estimateFor('ib', 'all')!.nBearings, 5);
      },
    );

    test(
      'estimates from an older server answer for every interferer',
      () async {
        await start(
          api: FakeApi()
            ..snapshotData = _snapshot(estimates: [estimateJson(n: 4)]),
        );
        expect(env.state.estimateFor('ia', 'all')!.nBearings, 4);
        expect(env.state.estimateFor(null, 'all')!.nBearings, 4);
      },
    );

    test('a live estimate replaces only its own interferer', () async {
      await start(
        api: FakeApi()
          ..snapshotData = _snapshot(
            estimates: [
              estimateJson(interferer: 'ia'),
              estimateJson(interferer: 'ib'),
            ],
          ),
      );
      env.channel.push(
        'estimate_updated',
        estimateJson(interferer: 'ib', n: 9),
      );
      await env.settle();
      expect(env.state.estimateFor('ib', 'all')!.nBearings, 9);
      expect(env.state.estimateFor('ia', 'all')!.nBearings, 3);
    });

    test(
      'bearings go to the active interferer, the default at first',
      () async {
        await start(api: offline());
        await env.mission.saveBearing({
          'id': 'x1',
          'lat': 48.1,
          'lon': 11.5,
          'azimuth_true_deg': 10.0,
          'sigma_deg': 5.0,
          'measured_at': '2026-01-01T10:00:00Z',
        });
        expect(_body((await queue()).single)['interferer_id'], 'ia');
        expect(env.state.bearings['x1']!.interfererId, 'ia');

        await env.container
            .read(activeInterfererProvider.notifier)
            .select('ib');
        await env.mission.saveBearing({
          'id': 'x2',
          'lat': 48.1,
          'lon': 11.5,
          'azimuth_true_deg': 10.0,
          'sigma_deg': 5.0,
          'measured_at': '2026-01-01T10:00:00Z',
        });
        expect(_body((await queue()).last)['interferer_id'], 'ib');
        expect(env.state.bearings['x2']!.interfererId, 'ib');
      },
    );

    test('a deactivated active interferer falls back to the default', () async {
      await start(api: offline());
      await env.container.read(activeInterfererProvider.notifier).select('ib');
      expect(env.container.read(activeInterfererIdProvider), 'ib');
      await env.mission.patchInterferer('ib', {'is_active': false});
      expect(env.container.read(activeInterfererIdProvider), 'ia');
    });

    test('a server without interferers gets no interferer id', () async {
      await start(api: offline(snapshot: _snapshot(interferers: false)));
      await env.mission.saveBearing({
        'id': 'x1',
        'lat': 48.1,
        'lon': 11.5,
        'azimuth_true_deg': 10.0,
        'sigma_deg': 5.0,
        'measured_at': '2026-01-01T10:00:00Z',
      });
      expect(
        _body((await queue()).single).containsKey('interferer_id'),
        isFalse,
      );
    });

    test(
      'a new interferer takes the lowest free colour slot and is queued first',
      () async {
        await start(api: offline());
        final id = await env.mission.createInterferer(name: ' Störer C ');
        final created = env.state.interferers[id]!;
        expect(created.name, 'Störer C');
        expect(created.colorSlot, 2);
        await env.container.read(activeInterfererProvider.notifier).select(id);
        await env.mission.saveBearing({
          'id': 'x1',
          'lat': 48.1,
          'lon': 11.5,
          'azimuth_true_deg': 10.0,
          'sigma_deg': 5.0,
          'measured_at': '2026-01-01T10:00:00Z',
        });
        final entries = await queue();
        expect(entries.map((e) => e.kind), ['interferer_create', 'bearing']);
        expect(entries.first.path, endsWith('/interferers'));
        expect(_body(entries.first)['color_slot'], 2);
        expect(_body(entries.last)['interferer_id'], id);
      },
    );

    test('at most six interferers can be active', () async {
      await start(api: offline());
      for (var n = 3; n <= 6; n++) {
        await env.mission.createInterferer(name: 'S$n');
      }
      expect(env.state.activeInterferers, hasLength(6));
      expect(
        () => env.mission.createInterferer(name: 'S7'),
        throwsA(isA<StateError>()),
      );
      // Deactivating one frees its slot again.
      await env.mission.patchInterferer('ib', {'is_active': false});
      final id = await env.mission.createInterferer(name: 'S7');
      expect(env.state.interferers[id]!.colorSlot, 1);
    });

    test('renaming and resolving are shown at once and queued', () async {
      await start(api: offline());
      await env.mission.patchInterferer('ib', {
        'name': 'Dauerträger',
        'status': 'resolved',
      });
      expect(env.state.interferers['ib']!.name, 'Dauerträger');
      expect(env.state.interferers['ib']!.isResolved, isTrue);
      final e = (await queue()).single;
      expect(
        (e.kind, e.method, e.path.split('/').last),
        ('interferer_patch', 'PATCH', 'ib'),
      );
    });

    test('reassigning a bearing is shown at once and queued', () async {
      await start(
        api: offline(
          snapshot: _snapshot(bearings: [bearingJson('b1', interferer: 'ia')]),
        ),
      );
      await env.mission.reassignBearing('b1', 'ib');
      expect(env.state.bearings['b1']!.interfererId, 'ib');
      final e = (await queue()).single;
      expect((e.kind, e.method), ('bearing_interferer', 'PATCH'));
      expect(e.path, endsWith('/bearings/b1'));
      expect(_body(e), {'interferer_id': 'ib'});
    });

    test(
      'merging moves bearings and readings and deactivates the source',
      () async {
        await start(
          api: offline(
            snapshot: _snapshot(
              bearings: [
                bearingJson('b1', interferer: 'ib'),
                bearingJson('b2', interferer: 'ia'),
              ],
            ),
          ),
        );
        await env.container
            .read(activeInterfererProvider.notifier)
            .select('ib');
        await env.mission.mergeInterferer('ib', 'ia');
        expect(env.state.bearings['b1']!.interfererId, 'ia');
        expect(env.state.bearings['b2']!.interfererId, 'ia');
        expect(env.state.interferers['ib']!.isActive, isFalse);
        expect(env.container.read(activeInterfererIdProvider), 'ia');
        final e = (await queue()).single;
        expect((e.kind, e.method), ('interferer_merge', 'POST'));
        expect(e.path, endsWith('/interferers/ib/merge'));
        expect(_body(e), {'into': 'ia'});
      },
    );

    test('queued interferer changes survive a reload', () async {
      final api = offline();
      await start(api: api);
      final id = await env.mission.createInterferer(name: 'Neu');
      await env.mission.patchInterferer('ib', {'name': 'Umbenannt'});
      env.channel.drop(); // reconnect: the snapshot is loaded again
      await env.settle();
      await env.mission.reassignBearing('nope', 'ia');
      expect(env.state.interferers[id]?.name, 'Neu');
      expect(env.state.interferers['ib']!.name, 'Umbenannt');
    });

    test('live interferer events add and change interferers', () async {
      await start(api: FakeApi()..snapshotData = _snapshot());
      env.channel.push(
        'interferer_created',
        interfererJson('ic', name: 'Neu', slot: 2),
      );
      env.channel.push(
        'interferer_updated',
        interfererJson('ib', name: 'B2', slot: 1),
      );
      await env.settle();
      expect(env.state.interferers['ic']!.name, 'Neu');
      expect(env.state.interferers['ib']!.name, 'B2');
    });

    test('a transmission and readings carry the active interferer', () async {
      await start(api: offline());
      await env.container.read(activeInterfererProvider.notifier).select('ib');
      await env.mission.toggleTransmission();
      expect(_body((await queue()).single)['interferer_id'], 'ib');
      expect(env.state.running!.interfererId, 'ib');
    });

    test('calibration readings belong to no interferer', () async {
      await start(api: offline());
      final fix = PositionFixForTest.at(48.1, 11.5);
      await env.mission.logRssi(rssiDbm: -80, at: fix);
      await env.mission.logRssi(
        rssiDbm: -80,
        at: fix,
        receiver: 'omni',
        isCalibration: true,
      );
      final entries = await queue();
      expect(
        (jsonDecode(entries[0].bodyJson!) as List).single['interferer_id'],
        'ia',
      );
      expect(
        (jsonDecode(entries[1].bodyJson!) as List).single.containsKey(
          'interferer_id',
        ),
        isFalse,
      );
    });
  });

  group('screens', () {
    testWidgets('the capture sheet chooses the interferer with one tap', (
      tester,
    ) async {
      final api = FakeApi()..snapshotData = _snapshot();
      final w = await pumpWith(
        tester,
        Builder(
          builder: (context) => TextButton(
            onPressed: () => showModalBottomSheet<bool>(
              context: context,
              isScrollControlled: true,
              builder: (_) => const CaptureSheet(),
            ),
            child: const Text('open'),
          ),
        ),
        api: api,
      );
      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();
      expect(
        find.descendant(
          of: find.byKey(const Key('interferer-chip')),
          matching: find.text('Störer 1'),
        ),
        findsOneWidget,
      );

      await tester.tap(find.byKey(const Key('interferer-chip')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('pick-interferer-ib')));
      await tester.pumpAndSettle();
      expect(
        find.descendant(
          of: find.byKey(const Key('interferer-chip')),
          matching: find.text('Brummer'),
        ),
        findsOneWidget,
      );

      await tester.enterText(find.byKey(const Key('azimuth')), '123');
      await tester.tap(find.byKey(const Key('save-bearing')));
      await tester.pumpAndSettle();
      final sent = w.api.sent.single;
      expect(jsonDecode(sent.bodyJson!)['interferer_id'], 'ib');
      await tester.pumpWidget(const SizedBox());
    });

    testWidgets('the interferers screen adds, renames and resolves', (
      tester,
    ) async {
      final api = FakeApi()
        ..snapshotData = _snapshot(
          bearings: [bearingJson('b1', interferer: 'ib')],
        )
        ..sendResult = const SendResult(SendOutcome.retry, 'offline');
      final w = await pumpWith(tester, const InterferersScreen(), api: api);
      await tester.pumpAndSettle();
      expect(find.text('Störer 1'), findsOneWidget);
      expect(find.text('Brummer'), findsOneWidget);
      expect(find.textContaining('1 Peilungen'), findsOneWidget);

      await tester.tap(find.byKey(const Key('interferer-add')));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('interferer-name')),
        'Fernseher',
      );
      await tester.tap(find.byKey(const Key('interferer-create')));
      await tester.pumpAndSettle();
      expect(find.text('Fernseher'), findsOneWidget);

      await tester.tap(find.byKey(const Key('interferer-menu-ib')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('interferer-resolve-ib')));
      await tester.pumpAndSettle();
      expect(find.textContaining('gefunden'), findsOneWidget);
      expect((await w.store.all()).map((e) => e.kind), [
        'interferer_create',
        'interferer_patch',
      ]);
      await tester.pumpWidget(const SizedBox());
    });

    testWidgets('merging asks for confirmation and queues the merge', (
      tester,
    ) async {
      final api = FakeApi()
        ..snapshotData = _snapshot(
          bearings: [bearingJson('b1', interferer: 'ib')],
        )
        ..sendResult = const SendResult(SendOutcome.retry, 'offline');
      final w = await pumpWith(tester, const InterferersScreen(), api: api);
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('interferer-menu-ib')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('interferer-merge-ib')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('merge-into-ia')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Abbrechen'));
      await tester.pumpAndSettle();
      expect(await w.store.all(), isEmpty);

      await tester.tap(find.byKey(const Key('interferer-menu-ib')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('interferer-merge-ib')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('merge-into-ia')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('merge-confirm')));
      await tester.pumpAndSettle();
      final e = (await w.store.all()).single;
      expect(e.kind, 'interferer_merge');
      expect(find.textContaining('deaktiviert'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
    });

    testWidgets('a long press reassigns a bearing', (tester) async {
      final api = FakeApi()
        ..snapshotData = _snapshot(
          bearings: [bearingJson('b1', interferer: 'ia')],
        )
        ..sendResult = const SendResult(SendOutcome.retry, 'offline');
      final w = await pumpWith(
        tester,
        const Scaffold(body: BearingsSheet()),
        api: api,
      );
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('reassign-hint')), findsOneWidget);
      await tester.longPress(find.byKey(const Key('bearing-b1')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('reassign-ib')));
      await tester.pumpAndSettle();
      final e = (await w.store.all()).single;
      expect(e.kind, 'bearing_interferer');
      expect(jsonDecode(e.bodyJson!), {'interferer_id': 'ib'});
      await tester.pumpWidget(const SizedBox());
    });
  });
}
