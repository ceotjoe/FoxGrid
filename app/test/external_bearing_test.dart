import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:foxgrid/core/models.dart';
import 'package:foxgrid/state/filter.dart';
import 'package:foxgrid/ui/bearings_sheet.dart';
import 'package:foxgrid/ui/external_bearing_sheet.dart';
import 'package:foxgrid/ui/map_screen.dart';
import 'package:foxgrid/ui/points_screen.dart';

import 'helpers.dart';

void _tall(WidgetTester tester) {
  tester.view.physicalSize = const Size(800, 1800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
}

Future<void> _unmount(WidgetTester tester) =>
    tester.pumpWidget(const SizedBox());

Future<WidgetEnv> _openSheet(
  WidgetTester tester, {
  List<Map<String, dynamic>>? points,
  String pointId = 'pt1',
}) async {
  _tall(tester);
  final env = await pumpWith(
    tester,
    Scaffold(body: ExternalBearingSheet(pointId: pointId)),
    api: FakeApi()
      ..snapshotData = snapshotJson(points: points ?? [pointJson('pt1')]),
  );
  await tester.pumpAndSettle();
  return env;
}

List<Map<String, dynamic>> _bearings(WidgetEnv env) => [
  for (final e in env.api.sent.where((x) => x.kind == 'bearing'))
    jsonDecode(e.bodyJson!) as Map<String, dynamic>,
];

void main() {
  testWidgets('saves a bearing at the point, not at the device', (
    tester,
  ) async {
    final env = await _openSheet(tester);
    expect(find.text('Peilung von BNetzA Köln'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('ext-azimuth')), '123,5');
    await tester.tap(find.byKey(const Key('ext-sigma-5')));
    await tester.enterText(find.byKey(const Key('ext-note')), 'per Telefon');
    await tester.tap(find.byKey(const Key('ext-save')));
    await tester.pumpAndSettle();

    final b = _bearings(env).single;
    expect(b['point_id'], 'pt1');
    expect(b['lat'], 50.9); // the point, not the fake device position at 48.137
    expect(b['lon'], 6.9);
    expect(b['azimuth_true_deg'], 123.5);
    expect(b['azimuth_input_ref'], 'true');
    expect(b['sigma_deg'], 5);
    expect(b['note'], 'per Telefon');
    final at = DateTime.parse(b['measured_at'] as String);
    expect(DateTime.now().toUtc().difference(at).inMinutes.abs(), lessThan(2));
    await _unmount(tester);
  });

  testWidgets('"save and more" keeps the sheet for the next value', (
    tester,
  ) async {
    final env = await _openSheet(tester);
    await tester.enterText(find.byKey(const Key('ext-azimuth')), '100');
    await tester.tap(find.byKey(const Key('ext-save-more')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('ext-saved')), findsOneWidget);
    expect(find.text('1 gespeichert'), findsOneWidget);
    expect(
      tester
          .widget<TextField>(find.byKey(const Key('ext-azimuth')))
          .controller!
          .text,
      isEmpty,
    );

    await tester.enterText(find.byKey(const Key('ext-azimuth')), '105');
    await tester.tap(find.byKey(const Key('ext-save-more')));
    await tester.pumpAndSettle();
    expect(find.text('2 gespeichert'), findsOneWidget);
    expect(_bearings(env).map((b) => b['azimuth_true_deg']), [100, 105]);
    await _unmount(tester);
  });

  testWidgets('a missing or out-of-range azimuth is not saved', (tester) async {
    final env = await _openSheet(tester);
    await tester.tap(find.byKey(const Key('ext-save')));
    await tester.pumpAndSettle();
    expect(find.text('Azimut 0–360° eingeben'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('ext-azimuth')), '400');
    await tester.tap(find.byKey(const Key('ext-save')));
    await tester.pumpAndSettle();
    expect(find.text('Azimut 0–360° eingeben'), findsOneWidget);
    expect(_bearings(env), isEmpty);
    await _unmount(tester);
  });

  testWidgets('a deactivated point takes no more bearings', (tester) async {
    final env = await _openSheet(
      tester,
      points: [pointJson('pt1', active: false)],
    );
    await tester.enterText(find.byKey(const Key('ext-azimuth')), '90');
    await tester.tap(find.byKey(const Key('ext-save')));
    await tester.pumpAndSettle();
    expect(find.text('Peilpunkt ist nicht mehr aktiv'), findsOneWidget);
    expect(_bearings(env), isEmpty);
    await _unmount(tester);
  });

  testWidgets('the points list opens the sheet for a point', (tester) async {
    _tall(tester);
    await pumpWith(
      tester,
      const PointsScreen(),
      api: FakeApi()..snapshotData = snapshotJson(points: [pointJson('pt1')]),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('point-bearing-pt1')));
    await tester.pumpAndSettle();
    expect(find.byType(ExternalBearingSheet), findsOneWidget);
    expect(find.text('Peilung von BNetzA Köln'), findsOneWidget);
    await _unmount(tester);
  });

  testWidgets('the map shows point markers; the filter hides them', (
    tester,
  ) async {
    _tall(tester);
    await pumpWith(
      tester,
      const MapScreen(),
      api: FakeApi()
        ..snapshotData = snapshotJson(
          points: [
            pointJson('pt1'),
            pointJson('pt2', name: 'Alt', active: false),
          ],
          bearings: [
            {...bearingJson('b1'), 'point_id': 'pt1'},
          ],
        ),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('point-marker-pt1')), findsOneWidget);
    expect(find.byKey(const Key('point-marker-pt2')), findsNothing);
    expect(find.text('BNetzA Köln'), findsOneWidget);

    final container = ProviderScope.containerOf(
      tester.element(find.byType(MapScreen)),
    );
    container
        .read(filterProvider.notifier)
        .set(container.read(filterProvider).copyWith(showExternal: false));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('point-marker-pt1')), findsNothing);
    await _unmount(tester);
  });

  test('the filter hides only external bearings when switched off', () {
    const f = BearingFilter(showExternal: false);
    final now = DateTime.utc(2026, 1, 1, 11);
    final plain = Bearing.fromJson(bearingJson('a'));
    final external = Bearing.fromJson({...bearingJson('b'), 'point_id': 'pt1'});
    expect(f.allows(plain, now), isTrue);
    expect(f.allows(external, now), isFalse);
    expect(const BearingFilter().allows(external, now), isTrue);
  });

  testWidgets('the bearings list labels external bearings', (tester) async {
    _tall(tester);
    await pumpWith(
      tester,
      const Scaffold(body: BearingsSheet()),
      api: FakeApi()
        ..snapshotData = snapshotJson(
          points: [pointJson('pt1', useInEstimate: false)],
          bearings: [
            {...bearingJson('b1'), 'point_id': 'pt1'},
            bearingJson('b2'),
          ],
        ),
    );
    await tester.pumpAndSettle();
    expect(find.textContaining('extern: BNetzA Köln'), findsOneWidget);
    expect(find.textContaining('nicht in Schätzung'), findsOneWidget);
    expect(find.textContaining('DL2XYZ'), findsOneWidget);
    await _unmount(tester);
  });
}
