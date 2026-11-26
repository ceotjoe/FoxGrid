import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:foxgrid/core/models.dart';
import 'package:foxgrid/core/sync.dart';
import 'package:foxgrid/ui/manage_bearings_screen.dart';
import 'package:material_ui/material_ui.dart';

import 'helpers.dart';

/// A Kraken bearing at minute [minute] after 10:00, with a gate state.
Map<String, dynamic> krakenJson(
  String id,
  int minute, {
  String? gate = 'outside',
  bool? override,
  double az = 90,
  String interferer = 'i1',
}) => {
  ...bearingJson(id, az: az, interferer: interferer),
  'participant_id': 'p2',
  'source': 'sensor',
  'sensor_id': 's1',
  'measured_at': '2026-01-01T10:${minute.toString().padLeft(2, '0')}:00Z',
  'gate_state': gate,
  'gate_override': override,
};

FakeApi _api() => FakeApi()
  ..sendResult = const SendResult(SendOutcome.retry, 'offline')
  ..snapshotData = snapshotJson(
    interferers: [
      interfererJson('i1'),
      interfererJson('i2', name: 'Störer B', slot: 1),
    ],
    transmissions: [
      {
        'id': 'tx1',
        'seq': 1,
        'started_at': '2026-01-01T10:01:30Z',
        'ended_at': '2026-01-01T10:03:30Z',
      },
    ],
    bearings: [
      krakenJson('k0', 0),
      krakenJson('k1', 1),
      krakenJson('k2', 2, gate: 'inside'),
      krakenJson('k3', 3, gate: 'inside', az: 200),
      krakenJson('k4', 4, override: true),
      bearingJson('hand', interferer: 'i1'),
    ],
  );

Future<void> _tap(WidgetTester tester, String key) async {
  final f = find.byKey(Key(key));
  await tester.ensureVisible(f);
  await tester.pumpAndSettle();
  await tester.tap(f);
  await tester.pumpAndSettle();
}

Future<WidgetEnv> _open(WidgetTester tester) async {
  tester.view.physicalSize = const Size(900, 1600);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final env = await pumpWith(tester, const ManageBearingsScreen(), api: _api());
  await tester.pumpAndSettle();
  return env;
}

String _summary(WidgetTester tester) =>
    tester.widget<Text>(find.byKey(const Key('bulk-summary'))).data!;

void main() {
  test('gate filters follow the server definitions', () {
    Map<String, dynamic> j(String? gate, bool? override) =>
        krakenJson('x', 0, gate: gate, override: override);
    bool m(GateFilter f, String? gate, bool? override) =>
        f.matches(Bearing.fromJson(j(gate, override)));
    expect(m(GateFilter.counted, null, null), isTrue);
    expect(m(GateFilter.counted, 'outside', null), isFalse);
    expect(m(GateFilter.counted, 'outside', true), isTrue);
    expect(m(GateFilter.stored, 'outside', null), isTrue);
    expect(m(GateFilter.stored, 'outside', false), isFalse);
    expect(m(GateFilter.included, 'outside', true), isTrue);
    expect(m(GateFilter.excluded, 'inside', false), isTrue);
  });

  testWidgets('filters narrow the list; hand bearings only on request', (
    tester,
  ) async {
    await _open(tester);
    expect(_summary(tester), startsWith('5 Peilungen'));
    await _tap(tester, 'filter-stored');
    await tester.pumpAndSettle();
    expect(_summary(tester), startsWith('2 Peilungen'));
    await _tap(tester, 'filter-stored');
    await _tap(tester, 'filter-sensors-only');
    await tester.pumpAndSettle();
    expect(_summary(tester), startsWith('6 Peilungen'));
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('a transmission selects its bearings; count them in bulk', (
    tester,
  ) async {
    final env = await _open(tester);
    await _tap(tester, 'select-tx-1');
    await tester.pumpAndSettle();
    expect(_summary(tester), contains('2 ausgewählt'));

    await tester.tap(find.byKey(const Key('bulk-exclude')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('bulk-preview')), findsOneWidget);
    await tester.tap(find.byKey(const Key('bulk-apply')));
    await tester.pump(const Duration(milliseconds: 300));

    final entry = (await env.store.all()).singleWhere(
      (e) => e.kind == 'bearing_bulk',
    );
    expect(entry.path, endsWith('/bearings/bulk'));
    expect(jsonDecode(entry.bodyJson!), {
      'ids': ['k2', 'k3'],
      'gate_override': false,
    });
    // applied optimistically: both are now manually excluded
    await _tap(tester, 'filter-excluded');
    await tester.pumpAndSettle();
    expect(_summary(tester), startsWith('2 Peilungen'));
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('dragging the timeline selects a time range', (tester) async {
    await _open(tester);
    final box = tester.getRect(find.byKey(const Key('bulk-timeline')));
    // the span is 10:00–10:04 plus 3 % padding: the first half holds 10:00 and 10:01
    await tester.dragFrom(
      box.centerLeft + const Offset(2, 0),
      Offset(box.width / 2 - 4, 0),
    );
    await tester.pumpAndSettle();
    expect(_summary(tester), contains('2 ausgewählt'));
    await tester.tap(find.byKey(const Key('select-none')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('bulk-count')), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('assign an interferer to the selection', (tester) async {
    final env = await _open(tester);
    await tester.tap(find.byKey(const Key('bulk-row-k0')));
    await tester.tap(find.byKey(const Key('bulk-row-k1')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('bulk-assign')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('bulk-interferer-i2')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('bulk-apply')));
    await tester.pump(const Duration(milliseconds: 300));
    final entry = (await env.store.all()).singleWhere(
      (e) => e.kind == 'bearing_bulk',
    );
    expect(jsonDecode(entry.bodyJson!), {
      'ids': ['k0', 'k1'],
      'interferer_id': 'i2',
    });
    await tester.pumpWidget(const SizedBox());
  });
}
