import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:foxgrid/state/filter.dart';
import 'package:foxgrid/ui/filter_sheet.dart';
import 'package:foxgrid/ui/map_screen.dart';
import 'package:material_ui/material_ui.dart';

import 'helpers.dart';

Future<ProviderContainer> _open(WidgetTester tester, {bool two = true}) async {
  tester.view.physicalSize = const Size(800, 1600);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final api = FakeApi()
    ..snapshotData = snapshotJson(
      interferers: [
        interfererJson('ia'),
        if (two) interfererJson('ib', name: 'Brummer', slot: 1),
      ],
      bearings: [
        bearingJson('a1', az: 10, interferer: 'ia'),
        bearingJson('a2', az: 20, interferer: 'ia'),
        if (two) bearingJson('b1', az: 100, interferer: 'ib'),
      ],
      estimates: [
        estimateJson(interferer: 'ia', n: 2),
        if (two) estimateJson(interferer: 'ib', n: 1),
      ],
    );
  await pumpWith(tester, const MapScreen(), api: api);
  await tester.pumpAndSettle();
  return ProviderScope.containerOf(tester.element(find.byType(MapScreen)));
}

/// Colours of the bearing rays (the 2.5 px lines), in drawing order.
List<Color> _rays(WidgetTester tester) => [
  for (final layer in tester.widgetList<PolylineLayer>(
    find.byType(PolylineLayer),
  ))
    for (final p in layer.polylines)
      if (p.strokeWidth == 2.5) p.color,
];

void main() {
  testWidgets(
    'every interferer gets its own estimate, summary and legend entry',
    (tester) async {
      await _open(tester);
      expect(find.byKey(const Key('interferer-legend')), findsOneWidget);
      expect(find.byKey(const Key('mle-marker-ia')), findsOneWidget);
      expect(find.byKey(const Key('mle-marker-ib')), findsOneWidget);
      expect(find.byKey(const Key('mle-marker')), findsNothing);
      expect(find.byKey(const Key('estimate-summary-ia')), findsOneWidget);
      expect(find.byKey(const Key('estimate-summary-ib')), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets('a single interferer looks like before: no legend, one marker', (
    tester,
  ) async {
    await _open(tester, two: false);
    expect(find.byKey(const Key('interferer-legend')), findsNothing);
    expect(find.byKey(const Key('mle-marker')), findsOneWidget);
    expect(find.byKey(const Key('estimate-summary')), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('rays take the colour family of their interferer', (
    tester,
  ) async {
    await _open(tester);
    final rays = _rays(tester);
    expect(rays, hasLength(3));
    // A is red (slot 0), B is blue (slot 1)
    expect(rays[0].r, greaterThan(rays[0].b));
    expect(rays[1].r, greaterThan(rays[1].b));
    expect(rays[2].b, greaterThan(rays[2].r));
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('tapping a legend entry shows only that interferer', (
    tester,
  ) async {
    final c = await _open(tester);
    await tester.tap(find.byKey(const Key('legend-ib')));
    await tester.pumpAndSettle();
    expect(c.read(filterProvider).interfererIds, {'ib'});
    expect(_rays(tester), hasLength(1));
    expect(find.byKey(const Key('mle-marker-ib')), findsOneWidget);
    expect(find.byKey(const Key('mle-marker-ia')), findsNothing);
    expect(find.byKey(const Key('estimate-summary-ia')), findsNothing);

    // tapping the only selected one again shows everything
    await tester.tap(find.byKey(const Key('legend-ib')));
    await tester.pumpAndSettle();
    expect(c.read(filterProvider).interfererIds, isEmpty);
    expect(_rays(tester), hasLength(3));
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('a long press adds an interferer to the selection', (
    tester,
  ) async {
    final c = await _open(tester);
    await tester.tap(find.byKey(const Key('legend-ia')));
    await tester.pumpAndSettle();
    await tester.longPress(find.byKey(const Key('legend-ib')));
    await tester.pumpAndSettle();
    expect(c.read(filterProvider).interfererIds, {'ia', 'ib'});
    expect(_rays(tester), hasLength(3));
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('dimming keeps the other interferers faintly visible', (
    tester,
  ) async {
    final c = await _open(tester);
    c
        .read(filterProvider.notifier)
        .set(const BearingFilter(interfererIds: {'ib'}, dimOthers: true));
    await tester.pumpAndSettle();
    final rays = _rays(tester);
    expect(rays, hasLength(3));
    expect(rays[0].a, lessThan(rays[2].a / 2)); // A is faded, B is not
    expect(find.byKey(const Key('mle-marker-ia')), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('the filter sheet lists interferers and filters', (tester) async {
    tester.view.physicalSize = const Size(800, 1600);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await pumpWith(
      tester,
      const Scaffold(body: FilterSheet()),
      api: FakeApi()
        ..snapshotData = snapshotJson(
          interferers: [
            interfererJson('ia'),
            interfererJson('ib', slot: 1, name: 'B'),
          ],
        ),
    );
    await tester.pumpAndSettle();
    final c = ProviderScope.containerOf(
      tester.element(find.byType(FilterSheet)),
    );
    await tester.tap(find.byKey(const Key('filter-interferer-ib')));
    await tester.pumpAndSettle();
    expect(c.read(filterProvider).interfererIds, {'ib'});
    await tester.tap(find.byKey(const Key('filter-dim-others')));
    await tester.pumpAndSettle();
    expect(c.read(filterProvider).dimOthers, isTrue);
    await tester.tap(find.byKey(const Key('filter-interferer-all')));
    await tester.pumpAndSettle();
    expect(c.read(filterProvider).interfererIds, isEmpty);
    await tester.pumpWidget(const SizedBox());
  });
}
