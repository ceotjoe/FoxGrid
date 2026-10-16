import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:foxgrid/core/session.dart';
import 'package:foxgrid/state/providers.dart';
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
}) async {
  tester.view.physicalSize = const Size(800, 1600);
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
}
