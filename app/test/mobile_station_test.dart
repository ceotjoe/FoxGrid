import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:foxgrid/core/models.dart';
import 'package:foxgrid/state/filter.dart';
import 'package:foxgrid/state/providers.dart';
import 'package:foxgrid/ui/map_screen.dart';
import 'package:foxgrid/ui/sensors_screen.dart';
import 'package:latlong2/latlong.dart';
import 'package:material_ui/material_ui.dart';

import 'helpers.dart';

/// Snapshot with a Kraken vehicle (virtual participant `k1`) at a known position.
Map<String, dynamic> _vehicleSnapshot({double speed = 12}) {
  final s = snapshotJson(
    bearings: [
      {
        ...bearingJson('counted'),
        'participant_id': 'k1',
        'source': 'sensor',
        'sensor_id': 's1',
        'gate_state': 'inside',
      },
      {
        ...bearingJson('stored', az: 200),
        'participant_id': 'k1',
        'source': 'sensor',
        'sensor_id': 's1',
        'gate_state': 'outside',
      },
    ],
  );
  (s['participants'] as List).add({
    'id': 'k1',
    'callsign': 'KRAKEN',
    'role': 'fixed',
    'authority': 'station',
  });
  s['positions'] = [
    {
      'participant_id': 'k1',
      'lat': 48.14,
      'lon': 11.58,
      'recorded_at': DateTime.now().toUtc().toIso8601String(),
      'heading_deg': 90.0,
      'speed_mps': speed,
    },
  ];
  return s;
}

Bearing _sensorBearing({String? gate, bool? override}) => Bearing.fromJson({
  ...bearingJson('x'),
  'sensor_id': 's1',
  'source': 'sensor',
  'gate_state': gate,
  'gate_override': override,
});

void main() {
  group('filter', () {
    final now = DateTime.utc(2026, 1, 1, 10);
    test('stored sensor bearings are hidden unless asked for', () {
      const f = BearingFilter();
      expect(f.allows(_sensorBearing(gate: 'inside'), now), isTrue);
      expect(f.allows(_sensorBearing(gate: 'outside'), now), isFalse);
      expect(
        f.allows(_sensorBearing(gate: 'outside', override: true), now),
        isTrue,
      );
      expect(
        f.allows(_sensorBearing(gate: 'inside', override: false), now),
        isFalse,
      );
      final all = f.copyWith(showStoredSensor: true);
      expect(all.allows(_sensorBearing(gate: 'outside'), now), isTrue);
      // hand bearings never have a gate
      expect(f.allows(Bearing.fromJson(bearingJson('h')), now), isTrue);
    });
  });

  group('sensor settings', () {
    testWidgets('weight, default interferer and gate are saved together', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(900, 1600);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      final api = FakeApi()
        ..snapshotData = snapshotJson(
          interferers: [
            interfererJson('i1'),
            interfererJson('i2', name: 'Störer B', slot: 1),
          ],
        )
        ..sensorList = [sensorInfo(name: 'Kraken', online: true)];
      await pumpWith(tester, const SensorsScreen(), api: api);
      await tester.pumpAndSettle();
      expect(find.textContaining('Mobile Peilstation'), findsOneWidget);

      await tester.tap(find.byKey(const Key('sensor-tile-Kraken')));
      await tester.pumpAndSettle();
      // nothing changed: saving sends nothing
      await tester.tap(find.byKey(const Key('sensor-settings-save')));
      await tester.pumpAndSettle();
      expect(api.sensorPatches, isEmpty);

      await tester.tap(find.byKey(const Key('sensor-tile-Kraken')));
      await tester.pumpAndSettle();
      final slider = find.byKey(const Key('sensor-weight'));
      await tester.tapAt(tester.getTopLeft(slider) + const Offset(30, 20));
      await tester.tap(find.byKey(const Key('sensor-gated')));
      await tester.tap(find.byKey(const Key('sensor-interferer')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('B Störer B').last);
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('sensor-settings-save')));
      await tester.pumpAndSettle();

      final (id, changes) = api.sensorPatches.single;
      expect(id, 'sensor-Kraken');
      expect(changes['gated'], isTrue);
      expect(changes['interferer_id'], 'i2');
      expect(changes['weight'] as double, lessThan(1.0));
      await tester.pumpWidget(const SizedBox());
    });
  });

  group('map', () {
    Future<WidgetEnv> open(WidgetTester tester, FakeApi api) async {
      tester.view.physicalSize = const Size(800, 1600);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      final env = await pumpWith(tester, const MapScreen(), api: api);
      await tester.pumpAndSettle();
      return env;
    }

    testWidgets('a moving station is a vehicle with course and speed', (
      tester,
    ) async {
      await open(tester, FakeApi()..snapshotData = _vehicleSnapshot());
      expect(find.byKey(const Key('vehicle-marker-k1')), findsOneWidget);
      expect(find.text('KRAKEN 43 km/h'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
    });

    testWidgets('its last hour of track is loaded and kept longer', (
      tester,
    ) async {
      final start = DateTime.now().toUtc().subtract(
        const Duration(minutes: 30),
      );
      final api = FakeApi()
        ..snapshotData = _vehicleSnapshot(speed: 0)
        ..trackFixes = [
          for (var i = 0; i < 400; i++)
            PositionFix(
              participantId: 'k1',
              point: LatLng(48.1 + i * 1e-4, 11.58),
              recordedAt: start.add(Duration(seconds: 5 * i)),
            ),
        ];
      await open(tester, api);
      final state = ProviderScope.containerOf(
        tester.element(find.byType(MapScreen)),
      ).read(missionProvider);
      expect(state.trails['k1'], hasLength(360));
      expect(find.text('KRAKEN'), findsOneWidget); // parked: no speed
      await tester.pumpWidget(const SizedBox());
    });
  });
}
