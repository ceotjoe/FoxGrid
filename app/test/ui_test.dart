import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:foxgrid/core/models.dart';
import 'package:foxgrid/core/sync.dart';
import 'package:foxgrid/core/tile_cache.dart';
import 'package:foxgrid/state/filter.dart';
import 'package:foxgrid/state/providers.dart';
import 'package:foxgrid/state/settings.dart';
import 'package:foxgrid/state/tiles.dart';
import 'package:foxgrid/ui/chat_screen.dart';
import 'package:foxgrid/ui/filter_sheet.dart';
import 'package:foxgrid/ui/settings_screen.dart';
import 'package:foxgrid/ui/sync_sheet.dart';
import 'package:foxgrid/ui/tasks_screen.dart';
import 'package:latlong2/latlong.dart';

import 'helpers.dart';

Future<void> _unmount(WidgetTester tester) =>
    tester.pumpWidget(const SizedBox());

ProviderContainer _container(WidgetTester tester, Type screen) =>
    ProviderScope.containerOf(tester.element(find.byType(screen)));

void main() {
  group('chat', () {
    testWidgets('sends a message offline-first and shows it as pending', (
      tester,
    ) async {
      final api = FakeApi()
        ..sendResult = const SendResult(SendOutcome.retry, 'offline')
        ..snapshotData = snapshotJson();
      final env = await pumpWith(tester, const ChatScreen(), api: api);
      await tester.pumpAndSettle();
      expect(find.text('Noch keine Nachrichten.'), findsOneWidget);

      await tester.enterText(
        find.byKey(const Key('chat-input')),
        'Aussendung gehört',
      );
      await tester.tap(find.byKey(const Key('chat-send')));
      await tester.pumpAndSettle();

      expect(find.text('Aussendung gehört'), findsOneWidget);
      expect(find.textContaining('wird gesendet'), findsOneWidget);
      final entry = (await env.store.all()).single;
      expect(entry.kind, 'message');
      expect(entry.bodyJson, contains('Aussendung gehört'));
      await _unmount(tester);
    });

    testWidgets('team channel is separate from the mission channel', (
      tester,
    ) async {
      final api = FakeApi()
        ..snapshotData = snapshotJson(
          messages: [
            {
              'id': 'a',
              'author_id': 'p2',
              'author_callsign': 'DL2XYZ',
              'team_id': null,
              'body': 'für alle',
              'sent_at': '2026-01-01T10:00:00Z',
            },
            {
              'id': 'b',
              'author_id': 'p2',
              'author_callsign': 'DL2XYZ',
              'team_id': 't1',
              'body': 'nur Alpha',
              'sent_at': '2026-01-01T10:01:00Z',
            },
          ],
        );
      await pumpWith(tester, const ChatScreen(), api: api);
      await tester.pumpAndSettle();
      expect(find.text('für alle'), findsOneWidget);
      expect(find.text('nur Alpha'), findsNothing);

      await tester.tap(find.text('Team Alpha'));
      await tester.pumpAndSettle();
      expect(find.text('nur Alpha'), findsOneWidget);
      expect(find.text('für alle'), findsNothing);
      await _unmount(tester);
    });
  });

  group('tasks', () {
    testWidgets('create, progress and assign a task', (tester) async {
      final api = FakeApi()
        ..sendResult = const SendResult(SendOutcome.retry, 'offline')
        ..snapshotData = snapshotJson();
      final env = await pumpWith(tester, const TasksScreen(), api: api);
      await tester.pumpAndSettle();
      expect(find.text('Keine Aufgaben.'), findsOneWidget);

      await tester.tap(find.byKey(const Key('new-task')));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('task-title')),
        'Peilung Nordost',
      );
      await tester.tap(find.byKey(const Key('task-save')));
      await tester.pumpAndSettle();
      expect(find.text('Peilung Nordost'), findsOneWidget);
      expect(
        find.textContaining('offen · niemand · wird gesendet'),
        findsOneWidget,
      );

      // status via popup menu
      await tester.tap(find.byType(PopupMenuButton<String>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('in Arbeit'));
      await tester.pumpAndSettle();
      expect(find.textContaining('in Arbeit'), findsOneWidget);

      // assign to a participant
      await tester.tap(find.text('Peilung Nordost'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('DL2XYZ'));
      await tester.pumpAndSettle();
      expect(find.textContaining('DL2XYZ'), findsOneWidget);

      final kinds = (await env.store.all()).map((e) => e.kind).toList();
      expect(kinds, ['task_create', 'task_patch', 'task_patch']);
      await _unmount(tester);
    });

    testWidgets('closed tasks are struck through and sorted last', (
      tester,
    ) async {
      final api = FakeApi()
        ..snapshotData = snapshotJson(
          tasks: [
            {
              'id': 't-done',
              'title': 'A erledigt',
              'description': null,
              'status': 'done',
              'created_by': 'p1',
              'assignee_participant_id': null,
              'assignee_team_id': 't1',
            },
            {
              'id': 't-open',
              'title': 'Z offen',
              'description': null,
              'status': 'open',
              'created_by': 'p1',
              'assignee_participant_id': 'p2',
              'assignee_team_id': null,
            },
          ],
        );
      await pumpWith(tester, const TasksScreen(), api: api);
      await tester.pumpAndSettle();
      final tiles = tester.widgetList<ListTile>(find.byType(ListTile)).toList();
      expect((tiles.first.title! as Text).data, 'Z offen');
      expect(find.textContaining('Team Alpha'), findsOneWidget);
      expect(
        (tester.widget<Text>(find.text('A erledigt'))).style?.decoration,
        TextDecoration.lineThrough,
      );
      await _unmount(tester);
    });
  });

  group('filter', () {
    test('allows() applies transmission, window and outlier rules', () {
      final now = DateTime.utc(2026, 1, 1, 12);
      Bearing b({String? tx, int ageMin = 0, bool outlier = false}) => Bearing(
        id: 'x',
        participantId: 'p',
        station: const LatLng(0, 0),
        azimuthTrueDeg: 1,
        sigmaDeg: 5,
        measuredAt: now.subtract(Duration(minutes: ageMin)),
        isOutlier: outlier,
        isActive: true,
        transmissionId: tx,
      );
      const none = BearingFilter();
      expect(none.needsQuery, isFalse);
      expect(none.allows(b(outlier: true), now), isTrue);
      expect(
        const BearingFilter(hideOutliers: true).allows(b(outlier: true), now),
        isFalse,
      );
      final tx = BearingFilter(transmissionIds: {'t1'});
      expect(tx.needsQuery, isTrue);
      expect(tx.allows(b(tx: 't1'), now), isTrue);
      expect(tx.allows(b(tx: 't2'), now), isFalse);
      expect(tx.allows(b(), now), isFalse);
      final win = BearingFilter(window: const Duration(minutes: 30));
      expect(win.allows(b(ageMin: 10), now), isTrue);
      expect(win.allows(b(ageMin: 45), now), isFalse);
      expect(
        const BearingFilter(halfLife: Duration(minutes: 5)).needsQuery,
        isTrue,
      );
    });

    testWidgets('sheet changes the filter and reset clears it', (tester) async {
      final api = FakeApi()
        ..snapshotData = snapshotJson(
          transmissions: [
            {
              'id': 'tx1',
              'seq': 1,
              'started_at': '2026-01-01T10:00:00Z',
              'ended_at': null,
            },
          ],
        );
      await pumpWith(tester, const Scaffold(body: FilterSheet()), api: api);
      await tester.pumpAndSettle();
      final c = _container(tester, FilterSheet);

      await tester.tap(find.byKey(const Key('filter-tx-1')));
      await tester.pump();
      expect(c.read(filterProvider).transmissionIds, {'tx1'});

      await tester.tap(find.text('30 min').first);
      await tester.pump();
      expect(c.read(filterProvider).window, const Duration(minutes: 30));

      await tester.tap(find.text('15 min').last);
      await tester.pump();
      expect(c.read(filterProvider).halfLife, const Duration(minutes: 15));

      await tester.tap(find.text('Ausreißer ausblenden'));
      await tester.pump();
      expect(c.read(filterProvider).hideOutliers, isTrue);

      await tester.tap(find.text('Wahrscheinlichkeitskonturen'));
      await tester.pump();
      expect(c.read(filterProvider).showContours, isFalse);

      await tester.tap(find.text('Zurücksetzen'));
      await tester.pump();
      expect(c.read(filterProvider).needsQuery, isFalse);
      expect(c.read(filterProvider).showContours, isTrue);
      await _unmount(tester);
    });

    test(
      'filtered estimate asks the server only when a filter is active',
      () async {
        final env = await makeEnv();
        addTearDown(env.container.dispose);
        env.api.queried = Estimate.fromJson(estimateJson(n: 2));
        env.container.read(missionProvider);
        await env.settle();

        expect(
          await env.container.read(filteredEstimateProvider.future),
          isNull,
        );
        expect(env.api.queries, isEmpty);

        env.container
            .read(filterProvider.notifier)
            .set(
              const BearingFilter(
                transmissionIds: {'tx1'},
                halfLife: Duration(minutes: 10),
              ),
            );
        final est = await env.container.read(filteredEstimateProvider.future);
        expect(est!.nBearings, 2);
        expect(env.api.queries.single['transmissions'], ['tx1']);
        expect(env.api.queries.single['halfLifeS'], 600.0);
      },
    );
  });

  group('sync status', () {
    testWidgets(
      'chip and sheet show queue state; failed entries can be retried or discarded',
      (tester) async {
        final api = FakeApi()
          ..sendResult = const SendResult(SendOutcome.rejected, 'ungültig');
        final env = await pumpWith(
          tester,
          const Scaffold(body: SyncChip()),
          api: api,
        );
        final c = _container(tester, SyncChip);
        c.read(missionProvider); // starts the sync notifier via writes
        await env.store.add(
          missionId: 'm1',
          kind: 'bearing',
          method: 'POST',
          path: '/x',
          bodyJson: '{}',
        );
        await tester.pumpAndSettle();
        // the periodic sync run picks the entry up; the server rejects it
        expect(find.text('1 Fehler'), findsOneWidget);

        await tester.tap(find.byKey(const Key('sync-chip')));
        await tester.pumpAndSettle();
        expect(find.text('Peilung'), findsOneWidget);
        expect(find.text('ungültig'), findsOneWidget);

        api.sendResult = const SendResult(SendOutcome.ok);
        await tester.tap(find.text('Erneut'));
        await tester.pumpAndSettle();
        expect(await env.store.all(), isEmpty);
        expect(find.text('Alles übertragen'), findsOneWidget);
        await _unmount(tester);
      },
    );

    testWidgets('pending entries show as waiting and can be flushed', (
      tester,
    ) async {
      final api = FakeApi()
        ..sendResult = const SendResult(SendOutcome.retry, 'offline');
      final env = await pumpWith(
        tester,
        const Scaffold(body: SyncChip()),
        api: api,
      );
      final c = _container(tester, SyncChip);
      await env.store.add(
        missionId: 'm1',
        kind: 'tx_start',
        method: 'POST',
        path: '/x',
        bodyJson: '{}',
      );
      c.read(syncProvider);
      await tester.pumpAndSettle();
      expect(find.text('1 offen'), findsOneWidget);
      await _unmount(tester);
    });
  });

  group('settings', () {
    testWidgets('night mode and tile server are persisted', (tester) async {
      await pumpWith(tester, const SettingsScreen());
      final c = _container(tester, SettingsScreen);
      await tester.tap(find.byKey(const Key('night-mode')));
      await tester.pump();
      expect(c.read(settingsProvider).nightMode, isTrue);
      await tester.enterText(
        find.byKey(const Key('tile-url')),
        'https://tiles.example.org/{z}/{x}/{y}.png',
      );
      await tester.pump();
      expect(c.read(settingsProvider).hasCustomTiles, isTrue);
      await tester.tap(find.text('Eigener Server'));
      await tester.pump();
      expect(
        c.read(settingsProvider).tileUrl,
        'https://tiles.example.org/{z}/{x}/{y}.png',
      );
      await _unmount(tester);
    });

    test('settings survive a restart', () async {
      final env = await makeEnv();
      addTearDown(env.container.dispose);
      final n = env.container.read(settingsProvider.notifier);
      await n.setNight(true);
      await n.setCustomTileUrl(' https://t/{z}/{x}/{y}.png ');
      await n.setBaseMap(BaseMap.custom);
      final prefs = env.container.read(sharedPrefsProvider);
      final again = ProviderContainer(
        overrides: [sharedPrefsProvider.overrideWithValue(prefs)],
      );
      addTearDown(again.dispose);
      final s = again.read(settingsProvider);
      expect(s.nightMode, isTrue);
      expect(s.baseMap, BaseMap.custom);
      expect(s.tileUrl, 'https://t/{z}/{x}/{y}.png');
    });

    test('the default tile URLs and the public-server check', () {
      expect(const AppSettings().tileUrl, osmTileUrl);
      expect(const AppSettings(baseMap: BaseMap.topo).tileUrl, topoTileUrl);
      // custom without a URL falls back to OSM rather than breaking the map
      expect(const AppSettings(baseMap: BaseMap.custom).tileUrl, osmTileUrl);
      expect(isPublicTileServer(osmTileUrl), isTrue);
      expect(
        isPublicTileServer('https://tiles.example.org/{z}/{x}/{y}.png'),
        isFalse,
      );
    });

    test(
      'region download refuses public OSM servers and oversized areas',
      () async {
        final tmp = Directory.systemTemp.createTempSync('fg_dl');
        addTearDown(() => tmp.deleteSync(recursive: true));
        final env = await makeEnv(
          extra: [
            tileCacheProvider.overrideWith(
              (ref) async => TileCache(
                directory: tmp,
                fetch: (_) async => Uint8List.fromList([1, 2, 3]),
              ),
            ),
          ],
        );
        addTearDown(env.container.dispose);
        const view = MapView(LatLng(48.0, 11.0), LatLng(48.3, 11.6), 14);
        final dl = env.container.read(regionDownloadProvider.notifier);

        expect(dl.estimate(view, 2), greaterThan(dl.estimate(view, 0)));

        await dl.start(view, 2); // default OSM tile server
        expect(
          env.container.read(regionDownloadProvider).message,
          contains('Nutzungsrichtlinie'),
        );

        await env.container
            .read(settingsProvider.notifier)
            .setCustomTileUrl('https://tiles.example.org/{z}/{x}/{y}.png');
        await env.container
            .read(settingsProvider.notifier)
            .setBaseMap(BaseMap.custom);
        await env.container.read(tileCacheProvider.future);
        await dl.start(view, 4); // far too many tiles
        expect(
          env.container.read(regionDownloadProvider).message,
          contains('Zu viele Kacheln'),
        );
      },
    );
  });
}
