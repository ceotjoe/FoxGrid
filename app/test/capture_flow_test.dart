import 'dart:convert';

import 'package:flutter/material.dart';
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
}) async {
  final env = await pumpWith(
    tester,
    Builder(
      builder: (context) => TextButton(
        onPressed: () => showModalBottomSheet<bool>(
          context: context,
          isScrollControlled: true,
          builder: (_) => CaptureSheet(compassHeading: compass),
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
}
