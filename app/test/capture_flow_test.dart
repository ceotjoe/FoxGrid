import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:foxgrid/core/api.dart';
import 'package:foxgrid/core/models.dart';
import 'package:foxgrid/core/session.dart';
import 'package:foxgrid/state/providers.dart';
import 'package:foxgrid/ui/capture_sheet.dart';
import 'package:latlong2/latlong.dart';
import 'package:shared_preferences/shared_preferences.dart';

class FakeApi implements FoxGridApi {
  final posted = <Map<String, dynamic>>[];
  Object? failWith;

  @override
  Future<void> postBearing(Map<String, dynamic> payload) async {
    if (failWith != null) throw failWith!;
    posted.add(payload);
  }

  @override
  Future<Map<String, dynamic>> snapshot() async => {
    'mission': {
      'id': 'm1',
      'name': 'Test',
      'frequency_mhz': 433.5,
      'status': 'active',
    },
    'participants': <dynamic>[],
    'positions': <dynamic>[],
    'bearings': <dynamic>[],
    'transmissions': <dynamic>[],
    'estimates': <dynamic>[],
  };

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

/// Mission state without a live connection.
class FakeMission extends MissionNotifier {
  @override
  MissionState build() => const MissionState();
}

class FakePosition extends OwnPositionNotifier {
  FakePosition(this.fix);

  final PositionFix? fix;

  @override
  PositionFix? build() => fix;
}

const _session = Session(
  baseUrl: 'http://localhost:8000',
  token: 't',
  missionId: 'm1',
  participantId: 'p1',
  callsign: 'DL1ABC',
  role: 'mobile',
);

Future<FakeApi> _pump(
  WidgetTester tester, {
  PositionFix? fix,
  Stream<double?>? compass,
}) async {
  SharedPreferences.setMockInitialValues({});
  final prefs = await SharedPreferences.getInstance();
  await SessionStore(prefs).save(_session);
  final api = FakeApi();
  final position =
      fix ??
      PositionFix(
        participantId: 'p1',
        point: const LatLng(48.137, 11.575),
        recordedAt: DateTime.utc(2026, 1, 1),
        accuracyM: 5,
      );
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        sharedPrefsProvider.overrideWithValue(prefs),
        apiProvider.overrideWithValue(api),
        ownPositionProvider.overrideWith(() => FakePosition(position)),
        missionProvider.overrideWith(FakeMission.new),
      ],
      child: MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => TextButton(
              onPressed: () => showModalBottomSheet<bool>(
                context: context,
                isScrollControlled: true,
                builder: (_) => CaptureSheet(compassHeading: compass),
              ),
              child: const Text('open'),
            ),
          ),
        ),
      ),
    ),
  );
  await tester.tap(find.text('open'));
  await tester.pumpAndSettle();
  return api;
}

void main() {
  testWidgets('saves a true bearing with default sigma in one step', (
    tester,
  ) async {
    final api = await _pump(tester);
    await tester.enterText(find.byKey(const Key('azimuth')), '123');
    await tester.tap(find.byKey(const Key('save-bearing')));
    await tester.pumpAndSettle();

    expect(api.posted, hasLength(1));
    final p = api.posted.single;
    expect(p['azimuth_true_deg'], 123.0);
    expect(p['azimuth_input_ref'], 'true');
    expect(p['sigma_deg'], 15.0); // sigma is always sent
    expect(p['lat'], 48.137);
    expect((p['id'] as String).length, 36); // client UUID for idempotency
    final t = DateTime.parse(p['measured_at'] as String);
    expect(t.isUtc, isTrue);
    expect(find.byKey(const Key('save-bearing')), findsNothing); // sheet closed
  });

  testWidgets('sigma presets are selectable', (tester) async {
    final api = await _pump(tester);
    await tester.enterText(find.byKey(const Key('azimuth')), '10');
    await tester.tap(find.byKey(const Key('sigma-5')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('save-bearing')));
    await tester.pumpAndSettle();
    expect(api.posted.single['sigma_deg'], 5.0);
  });

  testWidgets('magnetic input is converted with the declination', (
    tester,
  ) async {
    final api = await _pump(tester);
    await tester.enterText(find.byKey(const Key('azimuth')), '355');
    await tester.tap(find.text('magnetisch'));
    await tester.pump();
    await tester.enterText(find.byKey(const Key('declination')), '4.5');
    await tester.pump();
    expect(find.textContaining('rechtweisend 359.5'), findsOneWidget);
    await tester.tap(find.byKey(const Key('save-bearing')));
    await tester.pumpAndSettle();

    final p = api.posted.single;
    expect(p['azimuth_true_deg'], 359.5);
    expect(p['azimuth_input_ref'], 'magnetic');
    expect(p['declination_deg_applied'], 4.5);
  });

  testWidgets('magnetic input wraps over north', (tester) async {
    final api = await _pump(tester);
    await tester.enterText(find.byKey(const Key('azimuth')), '358');
    await tester.tap(find.text('magnetisch'));
    await tester.pump();
    await tester.enterText(find.byKey(const Key('declination')), '4');
    await tester.tap(find.byKey(const Key('save-bearing')));
    await tester.pumpAndSettle();
    expect(api.posted.single['azimuth_true_deg'], 2.0);
  });

  testWidgets('rejects missing or out of range azimuth', (tester) async {
    final api = await _pump(tester);
    await tester.tap(find.byKey(const Key('save-bearing')));
    await tester.pump();
    expect(find.text('Azimut 0–360° eingeben'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('azimuth')), '400');
    await tester.tap(find.byKey(const Key('save-bearing')));
    await tester.pump();
    expect(find.text('Azimut 0–360° eingeben'), findsOneWidget);
    expect(api.posted, isEmpty);
  });

  testWidgets('needs a position fix', (tester) async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    await SessionStore(prefs).save(_session);
    final api = FakeApi();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          sharedPrefsProvider.overrideWithValue(prefs),
          apiProvider.overrideWithValue(api),
          ownPositionProvider.overrideWith(() => FakePosition(null)),
          missionProvider.overrideWith(FakeMission.new),
        ],
        child: const MaterialApp(
          home: Scaffold(body: CaptureSheet(compassHeading: Stream.empty())),
        ),
      ),
    );
    await tester.enterText(find.byKey(const Key('azimuth')), '90');
    await tester.tap(find.byKey(const Key('save-bearing')));
    await tester.pump();
    expect(find.text('Noch kein Standort verfügbar'), findsOneWidget);
    expect(api.posted, isEmpty);
  });

  testWidgets('shows server errors and keeps the sheet open', (tester) async {
    final api = await _pump(tester);
    api.failWith = ApiException(409, 'bearing id already used');
    await tester.enterText(find.byKey(const Key('azimuth')), '90');
    await tester.tap(find.byKey(const Key('save-bearing')));
    await tester.pumpAndSettle();
    expect(find.text('bearing id already used'), findsOneWidget);
    expect(find.byKey(const Key('save-bearing')), findsOneWidget);
  });

  testWidgets('compass button takes the live heading as magnetic reading', (
    tester,
  ) async {
    final api = await _pump(tester, compass: Stream.value(87.4));
    await tester.pump();
    await tester.tap(find.byKey(const Key('use-compass')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('save-bearing')));
    await tester.pumpAndSettle();
    expect(api.posted.single['azimuth_input_ref'], 'magnetic');
    expect(api.posted.single['azimuth_true_deg'], 87.0);
  });
}
