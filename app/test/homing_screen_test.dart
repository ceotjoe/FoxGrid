import 'dart:convert';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:foxgrid/core/models.dart';
import 'package:foxgrid/core/radio/protocols.dart';
import 'package:foxgrid/state/providers.dart';
import 'package:foxgrid/ui/homing_screen.dart';
import 'package:foxgrid/ui/rssi_chart.dart';
import 'package:foxgrid/ui/settings_screen.dart';
import 'package:latlong2/latlong.dart';

import 'helpers.dart';

/// The screens are lazy lists: use a tall viewport so every control is built.
void _tallScreen(WidgetTester tester) {
  tester.view.physicalSize = const Size(800, 3000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
}

Future<void> _unmount(WidgetTester tester) =>
    tester.pumpWidget(const SizedBox());

/// An estimate 1.1 km north of (48.10, 11.5) with a 100 m / 200 m ellipse.
Map<String, dynamic> _estimate({bool withFit = false}) {
  Map<String, dynamic> ellipse(double major) => {
    'semi_major_m': major,
    'semi_minor_m': 50.0,
    'orientation_deg': 0.0,
    'polygon': {
      'type': 'Polygon',
      'coordinates': [
        [
          [11.499, 48.109],
          [11.501, 48.109],
          [11.5, 48.111],
          [11.499, 48.109],
        ],
      ],
    },
  };
  return {
    'id': 'e',
    'scope': 'all',
    'n_bearings': 3,
    'lat': 48.11,
    'lon': 11.5,
    'computed_at': '2026-01-01T10:00:00Z',
    'ellipse_1s': ellipse(100),
    'ellipse_2s': ellipse(200),
    'contours': <String, dynamic>{},
    if (withFit)
      'rssi': {
        'p0_dbm': -21.0,
        'exponent': 2.9,
        'residual_db': 3.2,
        'n_samples': 25,
      },
  };
}

PositionFix _fix(double lat, double lon) => PositionFix(
  participantId: 'p1',
  point: LatLng(lat, lon),
  recordedAt: DateTime.utc(2026),
  accuracyM: 4,
);

Future<WidgetEnv> _open(
  WidgetTester tester, {
  Map<String, dynamic>? estimate,
  PositionFix? fix,
  bool noFix = false,
  double? compass,
  FakeApi? api,
}) async {
  _tallScreen(tester);
  final fake = api ?? FakeApi();
  fake.snapshotData ??= snapshotJson(estimates: [?estimate]);
  final env = await pumpWith(
    tester,
    const HomingScreen(),
    fix: fix ?? _fix(48.10, 11.5),
    noFix: noFix,
    api: fake,
    extra: [compassProvider.overrideWith((ref) => Stream.value(compass))],
  );
  await tester.pumpAndSettle();
  return env;
}

double _arrowAngle(WidgetTester tester) {
  final t = tester.widget<Transform>(find.byKey(const Key('arrow')));
  final m = t.transform.storage;
  return math.atan2(m[1], m[0]) * 180 / math.pi;
}

List<dynamic> _rssiBody(WidgetEnv env, int index) => jsonDecode(
  env.api.sent.where((e) => e.kind == 'rssi').toList()[index].bodyJson!,
) as List<dynamic>;

void main() {
  testWidgets('shows distance, bearing and an arrow relative to the heading', (
    tester,
  ) async {
    await _open(
      tester,
      estimate: _estimate(),
      compass: 90,
    ); // facing east, target is north
    expect(find.byKey(const Key('distance')), findsOneWidget);
    expect(
      tester.widget<Text>(find.byKey(const Key('distance'))).data,
      '1.1 km',
    );
    expect(find.textContaining('Peilung 0° rechtweisend'), findsOneWidget);
    expect(find.textContaining('±100 m'), findsOneWidget);
    expect(_arrowAngle(tester), closeTo(-90, 0.6)); // 90 deg to the left
    expect(find.byKey(const Key('no-heading')), findsNothing);
    expect(find.byKey(const Key('inside')), findsNothing);
    await _unmount(tester);
  });

  testWidgets('without a compass the arrow points relative to north', (
    tester,
  ) async {
    await _open(tester, estimate: _estimate());
    expect(find.byKey(const Key('no-heading')), findsOneWidget);
    expect(_arrowAngle(tester), closeTo(0, 0.6));
    await _unmount(tester);
  });

  testWidgets('tells when the user is inside the error ellipse', (
    tester,
  ) async {
    await _open(
      tester,
      estimate: _estimate(),
      fix: _fix(48.1095, 11.5),
      compass: 0,
    );
    expect(tester.widget<Text>(find.byKey(const Key('distance'))).data, '56 m');
    expect(find.byKey(const Key('inside')), findsOneWidget);
    expect(find.textContaining('1σ'), findsWidgets);
    await _unmount(tester);
  });

  testWidgets('empty states', (tester) async {
    await _open(tester);
    expect(
      find.text('Noch keine Schätzung. Erfasse Peilungen oder Messwerte.'),
      findsOneWidget,
    );
    await _unmount(tester);
    await _open(tester, estimate: _estimate(), noFix: true);
    expect(find.text('Warte auf deinen Standort …'), findsOneWidget);
    await _unmount(tester);
  });

  testWidgets(
    'quick S-meter buttons log a reading with position and attenuator',
    (tester) async {
      final env = await _open(tester, estimate: _estimate());
      await tester.tap(find.byKey(const Key('quick-S9')));
      await tester.pumpAndSettle();
      var body = _rssiBody(env, 0).single as Map<String, dynamic>;
      expect(body['rssi_dbm'], -93);
      expect(body['attenuation_db'], 0);
      expect(body['lat'], 48.10);

      await tester.tap(find.byKey(const Key('att-20')));
      await tester.pump();
      await tester.tap(find.byKey(const Key('quick-S5')));
      await tester.pumpAndSettle();
      body = _rssiBody(env, 1).single as Map<String, dynamic>;
      expect(body['rssi_dbm'], -117);
      expect(body['attenuation_db'], 20);
      // the chart and headline show the level at the antenna (attenuator added back)
      expect(find.textContaining('-97 dBm'), findsOneWidget);
      expect(find.byType(RssiChart), findsOneWidget);
      await _unmount(tester);
    },
  );

  testWidgets('manual dBm entry is validated', (tester) async {
    final env = await _open(tester, estimate: _estimate());
    await tester.enterText(find.byKey(const Key('rssi-dbm')), '-85,5');
    await tester.tap(find.byKey(const Key('log-dbm')));
    await tester.pumpAndSettle();
    expect(
      (_rssiBody(env, 0).single as Map<String, dynamic>)['rssi_dbm'],
      -85.5,
    );

    await tester.enterText(find.byKey(const Key('rssi-dbm')), '5000');
    await tester.tap(find.byKey(const Key('log-dbm')));
    await tester.pump();
    expect(find.text('dBm-Wert zwischen -200 und 20 eingeben'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('rssi-dbm')), 'abc');
    await tester.tap(find.byKey(const Key('log-dbm')));
    await tester.pump();
    expect(env.api.sent.where((e) => e.kind == 'rssi'), hasLength(1));
    await _unmount(tester);
  });

  testWidgets('nothing is logged without a position fix', (tester) async {
    final env = await _open(tester, estimate: _estimate(), noFix: true);
    await tester.tap(find.byKey(const Key('quick-S7')));
    await tester.pump();
    expect(find.text('Noch kein Standort verfügbar'), findsOneWidget);
    expect(env.api.sent, isEmpty);
    await _unmount(tester);
  });

  testWidgets('auto logging repeats the last value every two seconds', (
    tester,
  ) async {
    final env = await _open(tester, estimate: _estimate());
    final auto = find.byKey(const Key('auto-log'));
    expect(
      tester.widget<SwitchListTile>(auto).onChanged,
      isNull,
    ); // needs a first reading
    await tester.tap(find.byKey(const Key('quick-S7')));
    await tester.pumpAndSettle();
    await tester.tap(auto);
    await tester.pump();
    await tester.pump(const Duration(seconds: 2));
    await tester.pump(const Duration(seconds: 2));
    await tester.pump(const Duration(seconds: 2));
    final count = env.api.sent.where((e) => e.kind == 'rssi').length;
    expect(count, 4); // the tap plus three automatic readings
    await tester.tap(auto); // switch off
    await tester.pump();
    await tester.pump(const Duration(seconds: 6));
    expect(env.api.sent.where((e) => e.kind == 'rssi').length, count);
    await _unmount(tester);
  });

  testWidgets('shows the fitted path loss model', (tester) async {
    await _open(tester, estimate: _estimate(withFit: true));
    final text = tester.widget<Text>(find.byKey(const Key('rssi-model'))).data!;
    expect(text, contains('n = 2.9'));
    expect(text, contains('P0 = -21 dBm'));
    expect(text, contains('25 Messwerte'));
    await _unmount(tester);
  });

  testWidgets('track samples of the mission appear in the chart headline', (
    tester,
  ) async {
    final snap = snapshotJson(estimates: [_estimate()])
      ..['rssi'] = [
        for (var i = 0; i < 5; i++)
          {
            'id': 's$i',
            'participant_id': 'p1',
            'lat': 48.1,
            'lon': 11.5,
            'rssi_dbm': -100.0 + 5 * i,
            'attenuation_db': 0,
            'measured_at': '2026-01-01T10:00:0${i}Z',
          },
      ];
    await _open(tester, api: FakeApi()..snapshotData = snap);
    expect(
      tester.widget<Text>(find.byKey(const Key('rssi-current'))).data,
      contains('-80 dBm (S9+13)'),
    );
    await _unmount(tester);
  });

  testWidgets('radio profile and calibration are stored in the settings', (
    tester,
  ) async {
    _tallScreen(tester);
    await pumpWith(tester, const SettingsScreen());
    final c = ProviderScope.containerOf(
      tester.element(find.byType(SettingsScreen)),
    );
    await tester.tap(find.byKey(const Key('radio-profile')));
    await tester.pumpAndSettle();
    await tester.tap(find.text(radioProfiles.first.name).last);
    await tester.pumpAndSettle();
    expect(c.read(settingsProvider).radioId, radioProfiles.first.id);

    await tester.enterText(find.byKey(const Key('radio-offset')), '-2,5');
    await tester.pump();
    expect(c.read(settingsProvider).radioOffsetDb, -2.5);
    expect(find.byKey(const Key('radio-note')), findsOneWidget);

    await c.read(settingsProvider.notifier).setRadio(null);
    expect(c.read(settingsProvider).radioId, isNull);
    await _unmount(tester);
  });

  test('settings remember the radio across restarts', () async {
    final env = await makeEnv();
    addTearDown(env.container.dispose);
    final n = env.container.read(settingsProvider.notifier);
    await n.setRadio('icom-ic705');
    await n.setRadioOffset(3);
    final again = ProviderContainer(
      overrides: [
        sharedPrefsProvider.overrideWithValue(
          env.container.read(sharedPrefsProvider),
        ),
      ],
    );
    addTearDown(again.dispose);
    expect(again.read(settingsProvider).radioId, 'icom-ic705');
    expect(again.read(settingsProvider).radioOffsetDb, 3);
  });
}
