import 'dart:convert';

import 'package:material_ui/material_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:foxgrid/core/models.dart';
import 'package:foxgrid/core/sync.dart';
import 'package:foxgrid/state/providers.dart';
import 'package:foxgrid/ui/capture_sheet.dart';
import 'package:latlong2/latlong.dart';

import 'helpers.dart';

/// Opens the capture sheet like the map does and returns the environment.
Future<WidgetEnv> _open(
  WidgetTester tester, {
  PositionFix? fix,
  Stream<double?>? compass,
  FakeApi? api,
  bool noFix = false,
  bool retroactive = false,
}) async {
  final env = await pumpWith(
    tester,
    Builder(
      builder: (context) => TextButton(
        onPressed: () => showModalBottomSheet<bool>(
          context: context,
          isScrollControlled: true,
          builder: (_) =>
              CaptureSheet(compassHeading: compass, retroactive: retroactive),
        ),
        child: const Text('open'),
      ),
    ),
    fix: fix,
    api: api,
    noFix: noFix,
  );
  await tester.tap(find.text('open'));
  await tester.pumpAndSettle();
  return env;
}

/// The bearing handed to the sync service (it is written to the queue first and
/// delivered right away when the server is reachable).
Future<Map<String, dynamic>> _queuedBearing(WidgetEnv env) async {
  expect(env.api.sent, hasLength(1));
  expect(env.api.sent.single.kind, 'bearing');
  return jsonDecode(env.api.sent.single.bodyJson!) as Map<String, dynamic>;
}

Future<void> _unmount(WidgetTester tester) =>
    tester.pumpWidget(const SizedBox());

void main() {
  testWidgets('saves a true bearing with default sigma in one step', (
    tester,
  ) async {
    final env = await _open(tester);
    await tester.enterText(find.byKey(const Key('azimuth')), '123');
    await tester.tap(find.byKey(const Key('save-bearing')));
    await tester.pumpAndSettle();

    final p = await _queuedBearing(env);
    expect(p['azimuth_true_deg'], 123.0);
    expect(p['azimuth_input_ref'], 'true');
    expect(p['sigma_deg'], 15.0); // sigma is always sent
    expect(p['lat'], 48.137);
    expect((p['id'] as String).length, 36); // client UUID for idempotency
    expect(DateTime.parse(p['measured_at'] as String).isUtc, isTrue);
    expect(find.byKey(const Key('save-bearing')), findsNothing); // sheet closed
    await _unmount(tester);
  });

  testWidgets('works while the server is unreachable', (tester) async {
    final api = FakeApi()
      ..sendResult = const SendResult(SendOutcome.retry, 'offline');
    final env = await _open(tester, api: api);
    await tester.enterText(find.byKey(const Key('azimuth')), '77');
    await tester.tap(find.byKey(const Key('save-bearing')));
    await tester.pumpAndSettle();
    expect((await _queuedBearing(env))['azimuth_true_deg'], 77.0);
    // still queued because the server did not accept it
    expect(await env.store.all(), hasLength(1));
    await _unmount(tester);
  });

  testWidgets('sigma presets are selectable', (tester) async {
    final env = await _open(tester);
    await tester.enterText(find.byKey(const Key('azimuth')), '10');
    await tester.tap(find.byKey(const Key('sigma-5')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('save-bearing')));
    await tester.pumpAndSettle();
    expect((await _queuedBearing(env))['sigma_deg'], 5.0);
    await _unmount(tester);
  });

  testWidgets('magnetic input is converted with the declination', (
    tester,
  ) async {
    final env = await _open(tester);
    await tester.enterText(find.byKey(const Key('azimuth')), '355');
    await tester.tap(find.text('magnetisch'));
    await tester.pump();
    await tester.enterText(find.byKey(const Key('declination')), '4.5');
    await tester.pump();
    expect(find.textContaining('rechtweisend 359.5'), findsOneWidget);
    await tester.tap(find.byKey(const Key('save-bearing')));
    await tester.pumpAndSettle();

    final p = await _queuedBearing(env);
    expect(p['azimuth_true_deg'], 359.5);
    expect(p['azimuth_input_ref'], 'magnetic');
    expect(p['declination_deg_applied'], 4.5);
    await _unmount(tester);
  });

  testWidgets('the cached WMM declination pre-fills the field', (tester) async {
    final env = await _open(tester);
    // The declination provider is fed by the map screen; emulate a fetched value.
    final container = ProviderScope.containerOf(
      tester.element(find.byType(CaptureSheet)),
    );
    await container
        .read(declinationProvider.notifier)
        .refresh(const LatLng(48, 11));
    await tester.enterText(find.byKey(const Key('azimuth')), '100');
    await tester.tap(find.text('magnetisch'));
    await tester.pump();
    final field = tester.widget<TextField>(
      find.byKey(const Key('declination')),
    );
    expect(field.controller!.text, '4.5');
    await tester.tap(find.byKey(const Key('save-bearing')));
    await tester.pumpAndSettle();
    expect((await _queuedBearing(env))['azimuth_true_deg'], 104.5);
    await _unmount(tester);
  });

  testWidgets('a manually typed declination is not overwritten', (
    tester,
  ) async {
    final env = await _open(tester);
    final container = ProviderScope.containerOf(
      tester.element(find.byType(CaptureSheet)),
    );
    await container
        .read(declinationProvider.notifier)
        .refresh(const LatLng(48, 11));
    await tester.enterText(find.byKey(const Key('azimuth')), '100');
    await tester.tap(find.text('magnetisch'));
    await tester.pump();
    await tester.enterText(find.byKey(const Key('declination')), '-2');
    final refButtons = find.byKey(const Key('ref'));
    await tester.tap(
      find.descendant(of: refButtons, matching: find.text('rechtweisend')),
    );
    await tester.pump();
    await tester.tap(
      find.descendant(of: refButtons, matching: find.text('magnetisch')),
    );
    await tester.pump();
    final field = tester.widget<TextField>(
      find.byKey(const Key('declination')),
    );
    expect(field.controller!.text, '-2');
    await tester.tap(find.byKey(const Key('save-bearing')));
    await tester.pumpAndSettle();
    expect((await _queuedBearing(env))['azimuth_true_deg'], 98.0);
    await _unmount(tester);
  });

  testWidgets('magnetic input wraps over north', (tester) async {
    final env = await _open(tester);
    await tester.enterText(find.byKey(const Key('azimuth')), '358');
    await tester.tap(find.text('magnetisch'));
    await tester.pump();
    await tester.enterText(find.byKey(const Key('declination')), '4');
    await tester.tap(find.byKey(const Key('save-bearing')));
    await tester.pumpAndSettle();
    expect((await _queuedBearing(env))['azimuth_true_deg'], 2.0);
    await _unmount(tester);
  });

  testWidgets('S mode: typed S value and S buttons, choice is remembered', (
    tester,
  ) async {
    final env = await _open(tester);
    await tester.enterText(find.byKey(const Key('azimuth')), '200');
    await tester.ensureVisible(find.byKey(const Key('level-unit')));
    await tester.tap(find.byKey(const Key('level-unit')));
    await tester.pump();
    expect(
      ProviderScope.containerOf(tester.element(find.byType(CaptureSheet)))
          .read(settingsProvider)
          .levelInS,
      isTrue,
    );
    await tester.enterText(find.byKey(const Key('rssi')), '9+20');
    await tester.tap(find.byKey(const Key('save-bearing')));
    await tester.pumpAndSettle();
    expect((await _queuedBearing(env))['rssi_dbm'], -73.0);
    await _unmount(tester);
  });

  testWidgets('an S button fills the level field', (tester) async {
    final env = await _open(tester);
    await tester.enterText(find.byKey(const Key('azimuth')), '200');
    await tester.ensureVisible(find.byKey(const Key('capture-S7')));
    await tester.tap(find.byKey(const Key('capture-S7')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('save-bearing')));
    await tester.pumpAndSettle();
    expect((await _queuedBearing(env))['rssi_dbm'], -105.0);
    await _unmount(tester);
  });

  testWidgets('optional fields are sent when filled in', (tester) async {
    final env = await _open(tester);
    await tester.enterText(find.byKey(const Key('azimuth')), '200');
    await tester.enterText(find.byKey(const Key('rssi')), '-87');
    await tester.enterText(find.byKey(const Key('attenuation')), '20');
    await tester.enterText(find.byKey(const Key('note')), 'Reflexion?');
    await tester.ensureVisible(find.text('horiz.'));
    await tester.tap(find.text('horiz.'));
    await tester.pump();
    await tester.tap(find.byKey(const Key('save-bearing')));
    await tester.pumpAndSettle();
    final p = await _queuedBearing(env);
    expect(p['rssi_dbm'], -87.0);
    expect(p['attenuation_db'], 20.0);
    expect(p['note'], 'Reflexion?');
    expect(p['polarization'], 'h');
    await _unmount(tester);
  });

  testWidgets('rejects missing or out of range azimuth', (tester) async {
    final env = await _open(tester);
    await tester.tap(find.byKey(const Key('save-bearing')));
    await tester.pump();
    expect(find.text('Azimut 0–360° eingeben'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('azimuth')), '400');
    await tester.tap(find.byKey(const Key('save-bearing')));
    await tester.pump();
    expect(find.text('Azimut 0–360° eingeben'), findsOneWidget);
    expect(env.api.sent, isEmpty);
    await _unmount(tester);
  });

  testWidgets('needs a position fix', (tester) async {
    final env = await _open(tester, noFix: true);
    await tester.enterText(find.byKey(const Key('azimuth')), '90');
    await tester.tap(find.byKey(const Key('save-bearing')));
    await tester.pump();
    expect(find.text('Noch kein Standort verfügbar'), findsOneWidget);
    expect(env.api.sent, isEmpty);
    await _unmount(tester);
  });

  testWidgets('compass button takes the live heading as magnetic reading', (
    tester,
  ) async {
    final env = await _open(tester, compass: Stream.value(87.4));
    await tester.pump();
    await tester.tap(find.byKey(const Key('use-compass')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('save-bearing')));
    await tester.pumpAndSettle();
    final p = await _queuedBearing(env);
    expect(p['azimuth_input_ref'], 'magnetic');
    expect(p['azimuth_true_deg'], 87.0);
    await _unmount(tester);
  });

  testWidgets('cancel button closes an untouched sheet without saving', (
    tester,
  ) async {
    final env = await _open(tester);
    await tester.tap(find.byKey(const Key('cancel-bearing')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('save-bearing')), findsNothing);
    expect(env.api.sent, isEmpty);
    await _unmount(tester);
  });

  testWidgets('X button asks before discarding typed input', (tester) async {
    final env = await _open(tester);
    await tester.enterText(find.byKey(const Key('azimuth')), '123');
    await tester.tap(find.byKey(const Key('close-capture')));
    await tester.pumpAndSettle();
    expect(find.text('Eingaben verwerfen?'), findsOneWidget);

    await tester.tap(find.byKey(const Key('keep-editing')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('save-bearing')), findsOneWidget);

    await tester.tap(find.byKey(const Key('close-capture')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('discard-bearing')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('save-bearing')), findsNothing);
    expect(env.api.sent, isEmpty);
    await _unmount(tester);
  });

  testWidgets('back gesture also guards input typed only in the note', (
    tester,
  ) async {
    await _open(tester);
    await tester.enterText(find.byKey(const Key('note')), 'Hinweis');
    await tester.pump();
    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    expect(find.text('Eingaben verwerfen?'), findsOneWidget);
    await _unmount(tester);
  });

  testWidgets('back gesture with typed input asks instead of closing', (
    tester,
  ) async {
    await _open(tester);
    await tester.enterText(find.byKey(const Key('azimuth')), '45');
    await tester.pump();
    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    expect(find.text('Eingaben verwerfen?'), findsOneWidget);
    expect(find.byKey(const Key('save-bearing')), findsOneWidget);
    await _unmount(tester);
  });

  group('retroactive bearing', () {
    testWidgets('sends chosen time, typed position and entry_mode', (
      tester,
    ) async {
      final env = await _open(tester, retroactive: true);
      expect(find.text('Peilung nachträglich erfassen'), findsOneWidget);
      await tester.enterText(find.byKey(const Key('azimuth')), '200');
      await tester.enterText(find.byKey(const Key('retro-lat')), '50.5');
      await tester.enterText(find.byKey(const Key('retro-lon')), '8.25');
      await tester.tap(find.byKey(const Key('save-bearing')));
      await tester.pumpAndSettle();

      final p = await _queuedBearing(env);
      expect(p['entry_mode'], 'retroactive');
      expect(p['lat'], 50.5);
      expect(p['lon'], 8.25); // not the GPS fix (48.137, 11.575)
      expect(p['station_accuracy_m'], isNull);
      expect(p['sigma_deg'], 15.0);
      await _unmount(tester);
    });

    testWidgets('needs a position before saving', (tester) async {
      final env = await _open(tester, retroactive: true);
      await tester.enterText(find.byKey(const Key('azimuth')), '200');
      await tester.tap(find.byKey(const Key('save-bearing')));
      await tester.pumpAndSettle();
      expect(find.textContaining('Standort wählen'), findsOneWidget);
      expect(env.api.sent, isEmpty);
      await _unmount(tester);
    });

    testWidgets('takes the nearest own track point', (tester) async {
      final api = FakeApi();
      final env = await _open(tester, retroactive: true, api: api);
      final now = DateTime.now().toUtc();
      api.trackFixes = [
        PositionFix(
          participantId: 'p1',
          point: const LatLng(49.0, 9.0),
          recordedAt: now.subtract(const Duration(minutes: 10)),
          accuracyM: 8,
        ),
        PositionFix(
          participantId: 'p1',
          point: const LatLng(49.5, 9.5),
          recordedAt: now.subtract(const Duration(minutes: 1)),
          accuracyM: 6,
        ),
      ];
      await tester.enterText(find.byKey(const Key('azimuth')), '10');
      await tester.tap(find.byKey(const Key('retro-track')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('save-bearing')));
      await tester.pumpAndSettle();

      final p = await _queuedBearing(env);
      expect(p['lat'], 49.5);
      expect(p['station_accuracy_m'], 6.0);
      await _unmount(tester);
    });

    testWidgets('says so when the track has nothing near the time', (
      tester,
    ) async {
      final env = await _open(tester, retroactive: true);
      await tester.tap(find.byKey(const Key('retro-track')));
      await tester.pumpAndSettle();
      expect(find.textContaining('Kein Track-Punkt'), findsOneWidget);
      expect(env.api.sent, isEmpty);
      await _unmount(tester);
    });
  });
}
