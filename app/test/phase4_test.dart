import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:foxgrid/core/api.dart';
import 'package:foxgrid/core/models.dart';
import 'package:foxgrid/state/providers.dart';
import 'package:foxgrid/ui/sensors_screen.dart';
import 'package:foxgrid/ui/suggestions_sheet.dart';
import 'package:latlong2/latlong.dart';

import 'helpers.dart';

Future<void> _unmount(WidgetTester tester) =>
    tester.pumpWidget(const SizedBox());

void _tall(WidgetTester tester) {
  tester.view.physicalSize = const Size(800, 2400);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
}

void main() {
  group('models', () {
    test('suggestion parses', () {
      final s = Suggestion.fromJson({
        'lat': 48.1,
        'lon': 11.5,
        'expected_reduction': 0.62,
        'expected_semi_major_m': 300.5,
        'expected_semi_minor_m': 120,
        'azimuth_to_target_deg': 181.2,
        'distance_to_target_m': 1245,
      });
      expect(s.point, const LatLng(48.1, 11.5));
      expect(s.expectedReduction, 0.62);
      expect(s.expectedSemiMinorM, 120);
    });

    test('sensor parses with and without position and key', () {
      final a = SensorInfo.fromJson({
        'id': 'a',
        'name': 'Nord',
        'kind': 'relay',
        'callsign': 'NORD',
        'lat': null,
        'lon': null,
        'is_active': true,
        'last_seen_at': '2026-01-01T10:00:00Z',
        'online': true,
        'topic_prefix': 'foxgrid/m/a',
        'api_key': 'fgs_x',
      });
      expect(a.isRelay, isTrue);
      expect(a.point, isNull);
      expect(a.apiKey, 'fgs_x');
      expect(a.lastSeenAt!.isUtc, isTrue);
      final b = SensorInfo.fromJson({
        'id': 'b',
        'name': 'Sued',
        'kind': 'station',
        'callsign': 'SUED',
        'lat': 48.1,
        'lon': 11.5,
        'is_active': false,
        'last_seen_at': null,
        'online': false,
        'topic_prefix': 'foxgrid/m/b',
      });
      expect(b.isRelay, isFalse);
      expect(b.point, const LatLng(48.1, 11.5));
      expect(b.apiKey, isNull);
      expect(b.lastSeenAt, isNull);
    });
  });

  group('suggestions provider', () {
    test('nothing is requested while the toggle is off', () async {
      final env = await makeEnv();
      addTearDown(env.container.dispose);
      env.container.read(missionProvider);
      await env.settle();
      expect(await env.container.read(suggestionsProvider.future), isEmpty);
      expect(env.api.suggestionCalls, isEmpty);
    });

    test(
      'on: fetched for the shown scope and refreshed when the estimate changes',
      () async {
        final env = await makeEnv();
        addTearDown(env.container.dispose);
        env.api.suggestionList = [suggestion(0.7), suggestion(0.5)];
        env.container.read(missionProvider);
        await env.settle();
        env.container.read(showSuggestionsProvider.notifier).set(true);
        final sub = env.container.listen(suggestionsProvider, (_, _) {});
        addTearDown(sub.close);

        expect(
          (await env.container.read(suggestionsProvider.future)).length,
          2,
        );
        expect(env.api.suggestionCalls, ['current']);

        env.channel.push(
          'estimate_updated',
          estimateJson(scope: 'current', n: 4),
        );
        await env.settle();
        await env.container.read(suggestionsProvider.future);
        expect(
          env.api.suggestionCalls.length,
          2,
        ); // a new estimate means new advice

        env.container
            .read(estimateScopeProvider.notifier)
            .select(EstimateScope.all);
        await env.settle();
        await env.container.read(suggestionsProvider.future);
        expect(env.api.suggestionCalls.last, 'all');
      },
    );
  });

  group('suggestions sheet', () {
    Future<WidgetEnv> open(WidgetTester tester, FakeApi api) async {
      final env = await pumpWith(
        tester,
        const Scaffold(body: SuggestionsSheet()),
        api: api,
        extra: [showSuggestionsProvider.overrideWith(() => _On())],
      );
      await tester.pumpAndSettle();
      return env;
    }

    testWidgets('lists the proposals with gain, distance and bearing', (
      tester,
    ) async {
      final api = FakeApi()
        ..suggestionList = [
          suggestion(0.81, az: 315, dist: 1245),
          suggestion(0.55, az: 135, dist: 2500),
        ];
      await open(tester, api);
      expect(find.text('Wo peilen als Nächstes?'), findsOneWidget);
      expect(
        find.textContaining('−81 % Fläche · 1.2 km vom Ziel'),
        findsOneWidget,
      );
      expect(find.textContaining('Peilung von dort: 315°'), findsOneWidget);
      expect(
        find.textContaining('Vorschläge, keine Anweisungen'),
        findsOneWidget,
      );
      expect(find.byKey(const Key('suggestion-2')), findsOneWidget);
      await _unmount(tester);
    });

    testWidgets('shows an empty and an error state', (tester) async {
      await open(tester, FakeApi());
      expect(find.byKey(const Key('suggestions-empty')), findsOneWidget);
      await _unmount(tester);
      await open(
        tester,
        FakeApi()..suggestionsError = ApiException(500, 'kaputt'),
      );
      expect(find.byKey(const Key('suggestions-error')), findsOneWidget);
      await _unmount(tester);
    });
  });

  group('sensors screen', () {
    testWidgets('empty state points to the documentation', (tester) async {
      await pumpWith(tester, const SensorsScreen());
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('sensors-empty')), findsOneWidget);
      await _unmount(tester);
    });

    testWidgets('shows online state and switches sensors off and on', (
      tester,
    ) async {
      final api = FakeApi()
        ..sensorList = [
          sensorInfo(name: 'Station Nord', online: true),
          sensorInfo(name: 'Relais Huegel', kind: 'relay'),
        ];
      await pumpWith(tester, const SensorsScreen(), api: api);
      await tester.pumpAndSettle();
      expect(
        find.textContaining('Peilstation · online · zuletzt'),
        findsOneWidget,
      );
      expect(
        find.textContaining('Relais-Hook · offline · noch nie gemeldet'),
        findsOneWidget,
      );

      await tester.tap(find.byKey(const Key('sensor-Station Nord')));
      await tester.pumpAndSettle();
      expect(api.toggled, [('sensor-Station Nord', false)]);
      await _unmount(tester);
    });

    testWidgets('creating a sensor shows its key once', (tester) async {
      _tall(tester);
      final api = FakeApi();
      await pumpWith(tester, const SensorsScreen(), api: api);
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('add-sensor')));
      await tester.pumpAndSettle();
      await tester.tap(
        find.byKey(const Key('sensor-save')),
      ); // name too short: nothing happens
      await tester.pump();
      expect(api.createdSensors, isEmpty);

      await tester.enterText(
        find.byKey(const Key('sensor-name')),
        'Station Nord',
      );
      await tester.tap(find.byKey(const Key('use-here')));
      await tester.pump();
      await tester.tap(find.byKey(const Key('sensor-save')));
      await tester.pumpAndSettle();

      expect(api.createdSensors.single['name'], 'Station Nord');
      expect(api.createdSensors.single['kind'], 'station');
      expect(
        api.createdSensors.single['lat'],
        48.137,
      ); // own position of the test fixture
      expect(find.byKey(const Key('api-key')), findsOneWidget);
      expect(find.text('fgs_secret_key'), findsOneWidget);
      expect(find.byKey(const Key('topic-prefix')), findsOneWidget);
      await tester.tap(find.text('Fertig'));
      await tester.pumpAndSettle();
      expect(find.text('fgs_secret_key'), findsNothing); // gone for good
      expect(find.byKey(const Key('sensor-Station Nord')), findsOneWidget);
      await _unmount(tester);
    });

    testWidgets(
      'a relay hook has no fixed position option; duplicates are reported',
      (tester) async {
        _tall(tester);
        final api = FakeApi();
        await pumpWith(tester, const SensorsScreen(), api: api);
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('add-sensor')));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Relais-Hook'));
        await tester.pump();
        expect(find.byKey(const Key('use-here')), findsNothing);
        await tester.enterText(find.byKey(const Key('sensor-name')), 'Relais');
        api.createSensorError = ApiException(409, 'exists');
        await tester.tap(find.byKey(const Key('sensor-save')));
        await tester.pumpAndSettle();
        expect(find.text('Den Namen gibt es schon.'), findsOneWidget);

        api.createSensorError = null;
        await tester.tap(find.byKey(const Key('add-sensor')));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Relais-Hook'));
        await tester.enterText(find.byKey(const Key('sensor-name')), 'Relais');
        await tester.tap(find.byKey(const Key('sensor-save')));
        await tester.pumpAndSettle();
        expect(api.createdSensors.single['kind'], 'relay');
        expect(api.createdSensors.single['lat'], isNull);
        await _unmount(tester);
      },
    );

    testWidgets('a failing list is reported', (tester) async {
      final api = _FailingSensors();
      await pumpWith(tester, const SensorsScreen(), api: api);
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('sensors-error')), findsOneWidget);
      await _unmount(tester);
    });
  });
}

class _On extends ShowSuggestionsNotifier {
  @override
  bool build() => true;
}

class _FailingSensors extends FakeApi {
  @override
  Future<List<SensorInfo>> listSensors() async =>
      throw ApiException(500, 'offline');
}
