import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:foxgrid/core/models.dart';
import 'package:foxgrid/core/signal.dart';
import 'package:foxgrid/ui/map_screen.dart';
import 'package:foxgrid/ui/station_screen.dart';

import 'helpers.dart';

void _tallScreen(WidgetTester tester) {
  tester.view.physicalSize = const Size(800, 3000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
}

Future<void> _unmount(WidgetTester tester) =>
    tester.pumpWidget(const SizedBox());

const _repeater = {
  'lat': 48.2,
  'lon': 11.6,
  'input_mhz': 145.0,
  'output_mhz': 145.6,
};

Future<WidgetEnv> _open(
  WidgetTester tester, {
  Map<String, dynamic>? repeater,
  List<Map<String, dynamic>> rssi = const [],
}) async {
  _tallScreen(tester);
  final api = FakeApi()
    ..snapshotData = snapshotJson(repeater: repeater, rssi: rssi);
  final env = await pumpWith(tester, const StationScreen(), api: api);
  await tester.pumpAndSettle();
  return env;
}

List<dynamic> _body(WidgetEnv env, int i) => jsonDecode(
  env.api.sent.where((e) => e.kind == 'rssi').toList()[i].bodyJson!,
) as List<dynamic>;

void main() {
  test('parses the repeater and the station fields', () {
    final m = Mission.fromJson({
      'id': 'm',
      'name': 'x',
      'frequency_mhz': 145.0,
      'status': 'active',
      'repeater': _repeater,
    });
    expect(m.repeater!.inputMhz, 145.0);
    expect(m.repeater!.outputMhz, 145.6);
    final s = RssiSample.fromJson({
      'id': 'a',
      'participant_id': 'p9',
      'lat': 48.0,
      'lon': 11.0,
      'rssi_dbm': -80.0,
      'measured_at': '2026-01-01T10:00:00Z',
      'receiver': 'omni',
      'is_calibration': true,
    });
    expect(s.isStation && s.isCalibration, isTrue);
    final fit = RssiFit.fromJson({
      'p0_dbm': -20.0,
      'exponent': 3.0,
      'residual_db': 2.0,
      'n_samples': 6,
      'station_offsets_db': {'p9': 2.5},
    });
    expect(fit.stationOffsetsDb['p9'], 2.5);
  });

  testWidgets('an S value is queued as an omni reading', (tester) async {
    final env = await _open(tester, repeater: _repeater);
    expect(find.byKey(const Key('station-empty')), findsOneWidget);
    expect(
      find.textContaining('Eingabefrequenz des Relais (145.0000 MHz)'),
      findsOneWidget,
    );
    await tester.tap(find.byKey(const Key('station-S5')));
    await tester.pumpAndSettle();
    final body = _body(env, 0).single as Map<String, dynamic>;
    expect(body['receiver'], 'omni');
    expect(body['rssi_dbm'], sMeterToDbm(5));
    expect(body.containsKey('is_calibration'), isFalse);
    expect(find.textContaining('S5'), findsWidgets);
    await _unmount(tester);
  });

  testWidgets('attenuation and calibration are sent along', (tester) async {
    final env = await _open(tester, repeater: _repeater);
    await tester.tap(find.byKey(const Key('station-att-20')));
    await tester.tap(find.byKey(const Key('station-calibration')));
    await tester.pumpAndSettle();
    expect(
      find.textContaining('Ausgabefrequenz des Relais (145.6000 MHz)'),
      findsOneWidget,
    );
    await tester.tap(find.byKey(const Key('station-S7')));
    await tester.pumpAndSettle();
    final body = _body(env, 0).single as Map<String, dynamic>;
    expect(body['is_calibration'], isTrue);
    expect(body['attenuation_db'], 20);
    expect(find.textContaining('Kalibrierung'), findsWidgets);
    await _unmount(tester);
  });

  testWidgets('calibration needs the repeater position', (tester) async {
    await _open(tester);
    final tile = tester.widget<SwitchListTile>(
      find.byKey(const Key('station-calibration')),
    );
    expect(tile.onChanged, isNull);
    await _unmount(tester);
  });

  testWidgets('a typed dBm value is validated', (tester) async {
    final env = await _open(tester);
    await tester.enterText(find.byKey(const Key('station-dbm')), '40');
    await tester.tap(find.byKey(const Key('station-log-dbm')));
    await tester.pump();
    expect(find.textContaining('zwischen -200 und 20'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('station-dbm')), '-97,5');
    await tester.tap(find.byKey(const Key('station-log-dbm')));
    await tester.pumpAndSettle();
    expect(_body(env, 0).single['rssi_dbm'], -97.5);
    await _unmount(tester);
  });

  testWidgets('the lead sets the repeater, queued as a PATCH', (tester) async {
    final env = await _open(tester);
    expect(find.text('Noch nicht gesetzt'), findsOneWidget);
    await tester.tap(find.byKey(const Key('edit-repeater')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('repeater-save')));
    await tester.pump();
    expect(find.textContaining('Dezimalgrad'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('repeater-lat')), '48,2');
    await tester.enterText(find.byKey(const Key('repeater-lon')), '11.6');
    await tester.enterText(find.byKey(const Key('repeater-input')), '145.0');
    await tester.tap(find.byKey(const Key('repeater-save')));
    await tester.pumpAndSettle();
    final sent = env.api.sent.where((e) => e.kind == 'mission').single;
    expect(sent.method, 'PATCH');
    expect(jsonDecode(sent.bodyJson!)['repeater']['lat'], 48.2);
    expect(find.byKey(const Key('repeater-summary')), findsOneWidget);
    expect(find.textContaining('Eingabe 145.0 MHz'), findsOneWidget);
    await _unmount(tester);
  });

  testWidgets('a typed fixed location replaces GPS and survives', (
    tester,
  ) async {
    _tallScreen(tester);
    final api = FakeApi()..snapshotData = snapshotJson();
    final env = await pumpWith(
      tester,
      const StationScreen(),
      api: api,
      noFix: true,
    );
    await tester.pumpAndSettle();
    // without GPS and without a fixed location nothing can be reported
    await tester.tap(find.byKey(const Key('station-S5')));
    await tester.pump();
    expect(find.text('Noch kein Standort verfügbar'), findsOneWidget);
    expect(env.api.sent.where((e) => e.kind == 'rssi'), isEmpty);

    await tester.tap(find.byKey(const Key('station-set-position')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('position-save')));
    await tester.pump();
    expect(find.textContaining('Dezimalgrad'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('position-lat')), '48,5');
    await tester.enterText(find.byKey(const Key('position-lon')), '11.25');
    await tester.tap(find.byKey(const Key('position-save')));
    await tester.pumpAndSettle();
    expect(
      find.textContaining('Fester Standort: 48.50000, 11.25000'),
      findsOneWidget,
    );

    await tester.tap(find.byKey(const Key('station-S7')));
    await tester.pumpAndSettle();
    final body = _body(env, 0).single as Map<String, dynamic>;
    expect(body['lat'], 48.5);
    expect(body['lon'], 11.25);
    expect(body['accuracy_m'], isNull);

    await tester.tap(find.byKey(const Key('station-clear-position')));
    await tester.pumpAndSettle();
    expect(find.textContaining('GPS wird ermittelt'), findsOneWidget);
    await _unmount(tester);
  });

  testWidgets('the own offset from the estimate is shown', (tester) async {
    _tallScreen(tester);
    final est = estimateJson()
      ..['rssi'] = {
        'p0_dbm': -20.0,
        'exponent': 3.0,
        'residual_db': 2.0,
        'n_samples': 6,
        'station_offsets_db': {'p1': -3.2},
      };
    final api = FakeApi()..snapshotData = snapshotJson(estimates: [est]);
    await pumpWith(tester, const StationScreen(), api: api);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('station-offset')), findsOneWidget);
    expect(find.textContaining('-3.2 dB'), findsOneWidget);
    await _unmount(tester);
  });

  testWidgets('the map shows station levels and the repeater', (tester) async {
    tester.view.physicalSize = const Size(1000, 1600);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final api = FakeApi()
      ..snapshotData = snapshotJson(
        repeater: _repeater,
        rssi: [
          {
            'id': 'r1',
            'participant_id': 'p2',
            'lat': 48.1,
            'lon': 11.5,
            'rssi_dbm': sMeterToDbm(6),
            'attenuation_db': 0,
            'measured_at': '2026-01-01T10:00:00Z',
            'receiver': 'omni',
          },
        ],
      );
    await pumpWith(tester, const MapScreen(), api: api);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('open-station')), findsOneWidget);
    expect(find.byKey(const Key('repeater-marker')), findsOneWidget);
    expect(find.byKey(const Key('station-marker-p2')), findsOneWidget);
    expect(find.text('S6'), findsOneWidget);
    await _unmount(tester);
  });
}
