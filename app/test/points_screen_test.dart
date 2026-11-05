import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:foxgrid/ui/map_screen.dart';
import 'package:foxgrid/ui/point_editor_screen.dart';
import 'package:foxgrid/ui/points_screen.dart';

import 'helpers.dart';

void _tall(WidgetTester tester) {
  tester.view.physicalSize = const Size(800, 1800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
}

Future<void> _unmount(WidgetTester tester) =>
    tester.pumpWidget(const SizedBox());

Future<WidgetEnv> _openList(
  WidgetTester tester, {
  List<Map<String, dynamic>> points = const [],
  List<Map<String, dynamic>> bearings = const [],
}) async {
  _tall(tester);
  final env = await pumpWith(
    tester,
    const PointsScreen(),
    api: FakeApi()
      ..snapshotData = snapshotJson(points: points, bearings: bearings),
  );
  await tester.pumpAndSettle();
  return env;
}

Future<WidgetEnv> _openEditor(
  WidgetTester tester, {
  List<Map<String, dynamic>> points = const [],
  bool noFix = false,
}) async {
  _tall(tester);
  final env = await pumpWith(
    tester,
    const PointEditorScreen(),
    noFix: noFix,
    api: FakeApi()..snapshotData = snapshotJson(points: points),
  );
  await tester.pumpAndSettle();
  return env;
}

Future<Map<String, dynamic>> _queuedBody(WidgetEnv env, String kind) async {
  final e = env.api.sent.firstWhere((x) => x.kind == kind);
  return jsonDecode(e.bodyJson!) as Map<String, dynamic>;
}

void main() {
  testWidgets('leads find the points in the manage menu', (tester) async {
    _tall(tester);
    await pumpWith(tester, const MapScreen());
    await tester.pumpAndSettle();
    await tester.tap(find.byType(PopupMenuButton<String>));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('open-manage')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('open-points')));
    await tester.pumpAndSettle();
    expect(find.byType(PointsScreen), findsOneWidget);
    await _unmount(tester);
  });

  testWidgets('the list shows points with their bearing count', (tester) async {
    await _openList(
      tester,
      points: [
        pointJson('pt1'),
        pointJson('pt2', name: 'Alt', active: false),
      ],
      bearings: [
        {...bearingJson('b1'), 'point_id': 'pt1'},
        {...bearingJson('b2'), 'point_id': 'pt1'},
        bearingJson('b3'),
      ],
    );
    expect(find.text('BNetzA Köln'), findsOneWidget);
    expect(find.textContaining('2 Peilungen'), findsOneWidget);
    expect(find.textContaining('deaktiviert'), findsOneWidget);
    await _unmount(tester);
  });

  testWidgets('an empty list explains itself', (tester) async {
    await _openList(tester);
    expect(find.byKey(const Key('points-empty')), findsOneWidget);
    await _unmount(tester);
  });

  testWidgets('the switch and the menu queue patches', (tester) async {
    final env = await _openList(tester, points: [pointJson('pt1')]);
    await tester.tap(find.byKey(const Key('point-switch-pt1')));
    await tester.pumpAndSettle();
    final first = env.api.sent.first;
    expect(first.kind, 'point_patch');
    expect(jsonDecode(first.bodyJson!), {'use_in_estimate': false});
    expect(find.textContaining('nicht in Schätzung'), findsOneWidget);

    await tester.tap(find.byKey(const Key('point-menu-pt1')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('point-toggle-active-pt1')));
    await tester.pumpAndSettle();
    final last = env.api.sent.last;
    expect(jsonDecode(last.bodyJson!), {'is_active': false});
    expect(find.textContaining('deaktiviert'), findsOneWidget);
    await _unmount(tester);
  });

  testWidgets('typed coordinates create a point (degrees and minutes)', (
    tester,
  ) async {
    final env = await _openEditor(tester);
    await tester.enterText(find.byKey(const Key('point-name')), 'BNetzA Köln');
    await tester.enterText(find.byKey(const Key('point-lat')), "50° 54.0' N");
    await tester.enterText(find.byKey(const Key('point-lon')), '6,95');
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('point-marker')), findsOneWidget);
    await tester.tap(find.byKey(const Key('point-save')));
    await tester.pumpAndSettle();

    final body = await _queuedBody(env, 'point_create');
    expect(body['name'], 'BNetzA Köln');
    expect(body['lat'], closeTo(50.9, 1e-9));
    expect(body['lon'], 6.95);
    expect(body['accuracy_m'], isNull);
    expect(body['use_in_estimate'], true);
    await _unmount(tester);
  });

  testWidgets('a tap on the map sets the position', (tester) async {
    final env = await _openEditor(tester);
    await tester.tapAt(tester.getCenter(find.byType(FlutterMap)));
    await tester.pump(const Duration(milliseconds: 600));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('point-marker')), findsOneWidget);
    final lat = double.parse(
      tester
          .widget<TextField>(find.byKey(const Key('point-lat')))
          .controller!
          .text,
    );
    expect(lat, closeTo(48.137, 0.02)); // map starts on the own position
    await tester.enterText(find.byKey(const Key('point-name')), 'Karte');
    await tester.tap(find.byKey(const Key('point-save')));
    await tester.pumpAndSettle();
    expect((await _queuedBody(env, 'point_create'))['name'], 'Karte');
    await _unmount(tester);
  });

  testWidgets('the device location fills the fields with its accuracy', (
    tester,
  ) async {
    final env = await _openEditor(tester);
    await tester.tap(find.byKey(const Key('point-use-device')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('point-name')), 'Hier');
    await tester.tap(find.byKey(const Key('point-save')));
    await tester.pumpAndSettle();
    final body = await _queuedBody(env, 'point_create');
    expect(body['lat'], closeTo(48.137, 1e-4));
    expect(body['lon'], closeTo(11.575, 1e-4));
    expect(body['accuracy_m'], 5);
    await _unmount(tester);
  });

  testWidgets('without a device fix the button says so', (tester) async {
    await _openEditor(tester, noFix: true);
    await tester.tap(find.byKey(const Key('point-use-device')));
    await tester.pump();
    expect(find.text('Noch kein Standort verfügbar'), findsOneWidget);
    await _unmount(tester);
  });

  testWidgets('invalid input is not saved', (tester) async {
    final env = await _openEditor(
      tester,
      points: [pointJson('pt1', name: 'BNetzA Köln')],
    );
    await tester.tap(find.byKey(const Key('point-save')));
    await tester.pumpAndSettle();
    expect(find.text('Name fehlt'), findsOneWidget);
    expect(find.text('Fehlt'), findsNWidgets(2));

    await tester.enterText(find.byKey(const Key('point-name')), 'bnetza köln');
    await tester.enterText(find.byKey(const Key('point-lat')), '95');
    await tester.enterText(find.byKey(const Key('point-lon')), '6.9 N');
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('point-save')));
    await tester.pumpAndSettle();
    expect(find.text('Diesen Namen gibt es schon'), findsOneWidget);
    expect(find.textContaining('Ungültig'), findsNWidgets(2));
    expect(env.api.sent, isEmpty);
    await _unmount(tester);
  });

  testWidgets('the estimate switch is carried into the new point', (
    tester,
  ) async {
    final env = await _openEditor(tester);
    await tester.tap(find.byKey(const Key('point-use-device')));
    await tester.enterText(find.byKey(const Key('point-name')), 'Nur Anzeige');
    await tester.tap(find.byKey(const Key('point-use-in-estimate')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('point-save')));
    await tester.pumpAndSettle();
    expect((await _queuedBody(env, 'point_create'))['use_in_estimate'], false);
    await _unmount(tester);
  });
}
