import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:foxgrid/core/database.dart';
import 'package:foxgrid/core/outbox.dart';
import 'package:foxgrid/core/sync.dart';

Future<void> _add(
  OutboxStore s,
  String kind, {
  String mission = 'm1',
  DateTime? now,
}) => s.add(
  missionId: mission,
  kind: kind,
  method: 'POST',
  path: '/x/$kind',
  bodyJson: '{"k":"$kind"}',
  now: now,
);

void main() {
  late MemoryOutboxStore store;
  late DateTime now;
  late List<String> sent;
  final plan = <String, SendResult>{};

  SyncService service() => SyncService(
    store: store,
    clock: () => now,
    send: (e) async {
      sent.add(e.kind);
      return plan[e.kind] ?? const SendResult(SendOutcome.ok);
    },
  );

  setUp(() {
    store = MemoryOutboxStore();
    now = DateTime.utc(2026, 1, 1, 12);
    sent = [];
    plan.clear();
  });

  test('delivers in order and empties the queue', () async {
    for (final k in ['a', 'b', 'c']) {
      await _add(store, k, now: now);
    }
    expect(await service().run(), 3);
    expect(sent, ['a', 'b', 'c']);
    expect(await store.all(), isEmpty);
  });

  test(
    'a transient failure stops the run and backs off exponentially',
    () async {
      await _add(store, 'a', now: now);
      await _add(store, 'b', now: now);
      plan['a'] = const SendResult(SendOutcome.retry, 'offline');
      final s = service();

      expect(await s.run(), 0);
      expect(sent, ['a']); // b must not overtake a
      var entries = await store.all();
      expect(entries.first.attempts, 1);
      expect(entries.first.lastError, 'offline');
      expect(entries.first.nextAttemptAt, now.add(const Duration(seconds: 2)));

      await s.run(); // still backing off: nothing is sent
      expect(sent, ['a']);

      now = now.add(const Duration(seconds: 3));
      await s.run();
      entries = await store.all();
      expect(entries.first.attempts, 2);
      expect(entries.first.nextAttemptAt, now.add(const Duration(seconds: 4)));

      plan['a'] = const SendResult(SendOutcome.ok);
      now = now.add(const Duration(seconds: 5));
      expect(await s.run(), 2);
      expect(await store.all(), isEmpty);
    },
  );

  test('backoff is capped', () {
    expect(SyncService.backoff(1, const Duration(seconds: 60)).inSeconds, 2);
    expect(SyncService.backoff(5, const Duration(seconds: 60)).inSeconds, 32);
    expect(SyncService.backoff(9, const Duration(seconds: 60)).inSeconds, 60);
  });

  test(
    'rejected writes are kept as failed but do not block the queue',
    () async {
      await _add(store, 'bad', now: now);
      await _add(store, 'good', now: now);
      plan['bad'] = const SendResult(SendOutcome.rejected, '422');
      final s = service();
      expect(await s.run(), 1);
      final entries = await store.all();
      expect(entries.single.isFailed, isTrue);
      expect(entries.single.lastError, '422');

      sent.clear();
      await s.run(); // failed entries are not retried automatically
      expect(sent, isEmpty);

      plan['bad'] = const SendResult(SendOutcome.ok);
      await s.retry(entries.single);
      expect(await s.run(), 1);
      expect(await store.all(), isEmpty);
    },
  );

  test('discard removes a failed entry', () async {
    await _add(store, 'bad', now: now);
    plan['bad'] = const SendResult(SendOutcome.rejected, 'no');
    final s = service();
    await s.run();
    await s.discard((await store.all()).single);
    expect(await store.all(), isEmpty);
  });

  test('only entries of the given mission are sent', () async {
    await _add(store, 'mine', now: now);
    await _add(store, 'other', mission: 'm2', now: now);
    await service().run(missionId: 'm1');
    expect(sent, ['mine']);
    expect((await store.all()).single.missionId, 'm2');
  });

  test('concurrent runs do not double send', () async {
    await _add(store, 'a', now: now);
    final s = service();
    final results = await Future.wait([s.run(), s.run()]);
    expect(results.reduce((a, b) => a + b), 1);
    expect(sent, ['a']);
  });

  group('DriftOutboxStore (sqlite)', () {
    late AppDatabase db;
    late DriftOutboxStore drift;

    setUp(() {
      db = AppDatabase(NativeDatabase.memory());
      drift = DriftOutboxStore(db);
    });

    tearDown(() => db.close());

    test('persists entries in insertion order and updates them', () async {
      await _add(drift, 'a', now: now);
      await _add(drift, 'b', now: now);
      var all = await drift.all();
      expect(all.map((e) => e.kind), ['a', 'b']);
      expect(all.first.status, 'pending');
      expect(all.first.bodyJson, '{"k":"a"}');

      await drift.update(
        all.first.copyWith(attempts: 3, status: 'failed', lastError: 'x'),
      );
      all = await drift.all();
      expect(all.first.attempts, 3);
      expect(all.first.isFailed, isTrue);

      await drift.remove(all.first.id);
      expect((await drift.all()).single.kind, 'b');
    });

    test('works with the sync service and watch stream', () async {
      final events = <int>[];
      final sub = drift.watch().listen((l) => events.add(l.length));
      await _add(drift, 'a', now: now);
      final s = SyncService(
        store: drift,
        clock: () => now,
        send: (_) async => const SendResult(SendOutcome.ok),
      );
      expect(await s.run(), 1);
      await Future<void>.delayed(const Duration(milliseconds: 50));
      await sub.cancel();
      expect(events, contains(1));
      expect(events.last, 0);
    });

    test('key value cache upserts', () async {
      expect(await drift.getCached('k'), isNull);
      await drift.putCached('k', 'one');
      await drift.putCached('k', 'two');
      expect(await drift.getCached('k'), 'two');
    });
  });

  test('memory store watch emits changes and cache works', () async {
    final lengths = <int>[];
    final sub = store.watch().listen((l) => lengths.add(l.length));
    await _add(store, 'a', now: now);
    await store.remove((await store.all()).single.id);
    await Future<void>.delayed(Duration.zero);
    await sub.cancel();
    expect(lengths, [0, 1, 0]);
    await store.putCached('x', 'y');
    expect(await store.getCached('x'), 'y');
  });
}
