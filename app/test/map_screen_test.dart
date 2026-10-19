import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:foxgrid/core/session.dart';
import 'package:foxgrid/state/providers.dart';
import 'package:foxgrid/ui/filter_sheet.dart';
import 'package:foxgrid/ui/map_screen.dart';
import 'package:foxgrid/ui/sensors_screen.dart';
import 'package:foxgrid/ui/suggestions_sheet.dart';

import 'helpers.dart';

Future<void> _unmount(WidgetTester tester) =>
    tester.pumpWidget(const SizedBox());

Future<WidgetEnv> _open(
  WidgetTester tester, {
  Session? session,
  FakeApi? api,
  Size size = const Size(800, 1600),
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final env = await pumpWith(tester, const MapScreen(), api: api);
  if (session != null) {
    ProviderScope.containerOf(tester.element(find.byType(MapScreen)))
        .read(sessionProvider.notifier)
        .set(session);
  }
  await tester.pumpAndSettle();
  return env;
}

void main() {
  testWidgets('leads find the sensors in the menu and can open the screen', (
    tester,
  ) async {
    await _open(
      tester,
      api: FakeApi()..sensorList = [sensorInfo(name: 'Nord', online: true)],
    );
    await tester.tap(find.byType(PopupMenuButton<String>));
    await tester.pumpAndSettle();
    expect(find.text('Sensoren'), findsOneWidget);
    await tester.tap(find.text('Sensoren'));
    await tester.pumpAndSettle();
    expect(find.byType(SensorsScreen), findsOneWidget);
    expect(find.byKey(const Key('sensor-Nord')), findsOneWidget);
    await _unmount(tester);
  });

  testWidgets('ordinary participants do not see the sensor management', (
    tester,
  ) async {
    await _open(
      tester,
      session: const Session(
        baseUrl: 'http://localhost:8000',
        token: 't',
        missionId: 'm1',
        participantId: 'p2',
        callsign: 'DL2XYZ',
        role: 'mobile',
      ),
    );
    await tester.tap(find.byType(PopupMenuButton<String>));
    await tester.pumpAndSettle();
    expect(find.text('Sensoren'), findsNothing);
    expect(find.text('Einstellungen'), findsOneWidget);
    await _unmount(tester);
  });

  testWidgets('the suggestion toggle fetches advice and opens the sheet', (
    tester,
  ) async {
    final api = FakeApi()
      ..suggestionList = [suggestion(0.7), suggestion(0.5), suggestion(0.3)];
    await _open(tester, api: api);
    expect(api.suggestionCalls, isEmpty); // off by default: no requests
    await tester.tap(find.byKey(const Key('toggle-suggestions')));
    await tester.pumpAndSettle();
    expect(api.suggestionCalls, isNotEmpty);
    expect(find.byType(SuggestionsSheet), findsOneWidget);
    expect(find.byKey(const Key('suggestion-3')), findsOneWidget);
    await _unmount(tester);
  });

  testWidgets('the app bar offers chat, tasks, filter and homing', (
    tester,
  ) async {
    await _open(tester);
    for (final key in [
      'open-chat',
      'open-tasks',
      'open-filter',
      'open-homing',
    ]) {
      expect(find.byKey(Key(key)), findsOneWidget, reason: key);
    }
    expect(find.byKey(const Key('sync-chip')), findsOneWidget);
    await _unmount(tester);
  });

  for (final width in [320.0, 360.0, 412.0]) {
    testWidgets('narrow app bar at $width dp keeps the title readable', (
      tester,
    ) async {
      tester.platformDispatcher.textScaleFactorTestValue = 1.3;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      final api = FakeApi()
        ..snapshotData = (snapshotJson()
          ..['mission'] = {
            'id': 'm1',
            'name': 'Stoerer am Repeater DB0XYZ im Raum Stuttgart Nord',
            'frequency_mhz': 433.5,
            'status': 'active',
          });
      await _open(tester, api: api, size: Size(width, 800));
      expect(tester.takeException(), isNull);
      expect(find.text('433.500 MHz'), findsOneWidget);
      // filter and tasks moved into the menu
      expect(find.byKey(const Key('open-tasks')), findsNothing);
      expect(find.byKey(const Key('open-filter')), findsNothing);
      await tester.tap(find.byType(PopupMenuButton<String>));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('menu-tasks')), findsOneWidget);
      expect(find.byKey(const Key('menu-filter')), findsOneWidget);
      await tester.tap(find.byKey(const Key('menu-filter')));
      await tester.pumpAndSettle();
      expect(find.byType(FilterSheet), findsOneWidget);
      await _unmount(tester);
    });
  }

  testWidgets('tapping the title shows the full mission name', (tester) async {
    await _open(tester);
    await tester.tap(find.byKey(const Key('mission-title')));
    await tester.pumpAndSettle();
    expect(find.text('Test hunt'), findsWidgets);
    expect(find.textContaining('Frequenz: 433.500 MHz'), findsOneWidget);
    await _unmount(tester);
  });
}
