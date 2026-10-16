import 'dart:async';

import 'package:drift/drift.dart';

import 'database.dart';

/// One queued write.
class OutboxEntry {
  const OutboxEntry({
    required this.id,
    required this.missionId,
    required this.kind,
    required this.method,
    required this.path,
    required this.bodyJson,
    required this.createdAt,
    required this.attempts,
    required this.nextAttemptAt,
    required this.status,
    this.lastError,
  });

  final int id;
  final String missionId;
  final String kind;
  final String method;
  final String path;
  final String? bodyJson;
  final DateTime createdAt;
  final int attempts;
  final DateTime nextAttemptAt;
  final String status;
  final String? lastError;

  bool get isFailed => status == 'failed';

  OutboxEntry copyWith({
    int? attempts,
    DateTime? nextAttemptAt,
    String? status,
    String? lastError,
  }) => OutboxEntry(
    id: id,
    missionId: missionId,
    kind: kind,
    method: method,
    path: path,
    bodyJson: bodyJson,
    createdAt: createdAt,
    attempts: attempts ?? this.attempts,
    nextAttemptAt: nextAttemptAt ?? this.nextAttemptAt,
    status: status ?? this.status,
    lastError: lastError ?? this.lastError,
  );
}

/// Persistent queue plus a tiny key/value cache.
abstract class OutboxStore {
  Future<void> add({
    required String missionId,
    required String kind,
    required String method,
    required String path,
    String? bodyJson,
    DateTime? now,
  });

  /// All entries, oldest first.
  Future<List<OutboxEntry>> all();

  Stream<List<OutboxEntry>> watch();

  Future<void> update(OutboxEntry entry);

  Future<void> remove(int id);

  Future<String?> getCached(String key);

  Future<void> putCached(String key, String value);
}

class DriftOutboxStore implements OutboxStore {
  DriftOutboxStore(this._db);

  final AppDatabase _db;

  OutboxEntry _map(OutboxRow r) => OutboxEntry(
    id: r.id,
    missionId: r.missionId,
    kind: r.kind,
    method: r.method,
    path: r.path,
    bodyJson: r.bodyJson,
    createdAt: r.createdAt,
    attempts: r.attempts,
    nextAttemptAt: r.nextAttemptAt,
    status: r.status,
    lastError: r.lastError,
  );

  SimpleSelectStatement<$OutboxRowsTable, OutboxRow> get _ordered =>
      _db.select(_db.outboxRows)..orderBy([(t) => OrderingTerm.asc(t.id)]);

  @override
  Future<void> add({
    required String missionId,
    required String kind,
    required String method,
    required String path,
    String? bodyJson,
    DateTime? now,
  }) async {
    final t = now ?? DateTime.now().toUtc();
    await _db
        .into(_db.outboxRows)
        .insert(
          OutboxRowsCompanion.insert(
            missionId: missionId,
            kind: kind,
            method: method,
            path: path,
            bodyJson: Value(bodyJson),
            createdAt: t,
            nextAttemptAt: t,
          ),
        );
  }

  @override
  Future<List<OutboxEntry>> all() async =>
      (await _ordered.get()).map(_map).toList();

  @override
  Stream<List<OutboxEntry>> watch() =>
      _ordered.watch().map((rows) => rows.map(_map).toList());

  @override
  Future<void> update(OutboxEntry e) =>
      (_db.update(_db.outboxRows)..where((t) => t.id.equals(e.id))).write(
        OutboxRowsCompanion(
          attempts: Value(e.attempts),
          nextAttemptAt: Value(e.nextAttemptAt),
          status: Value(e.status),
          lastError: Value(e.lastError),
        ),
      );

  @override
  Future<void> remove(int id) =>
      (_db.delete(_db.outboxRows)..where((t) => t.id.equals(id))).go();

  @override
  Future<String?> getCached(String key) async {
    final row = await (_db.select(
      _db.keyValueRows,
    )..where((t) => t.key.equals(key))).getSingleOrNull();
    return row?.value;
  }

  @override
  Future<void> putCached(String key, String value) => _db
      .into(_db.keyValueRows)
      .insertOnConflictUpdate(
        KeyValueRowsCompanion.insert(key: key, value: value),
      );
}

/// In-memory store: used on the web (no sqlite wasm bundled yet) and in tests.
class MemoryOutboxStore implements OutboxStore {
  final List<OutboxEntry> _entries = [];
  final Map<String, String> _cache = {};
  final _changes = StreamController<void>.broadcast();
  int _nextId = 1;

  @override
  Future<void> add({
    required String missionId,
    required String kind,
    required String method,
    required String path,
    String? bodyJson,
    DateTime? now,
  }) async {
    final t = now ?? DateTime.now().toUtc();
    _entries.add(
      OutboxEntry(
        id: _nextId++,
        missionId: missionId,
        kind: kind,
        method: method,
        path: path,
        bodyJson: bodyJson,
        createdAt: t,
        attempts: 0,
        nextAttemptAt: t,
        status: 'pending',
      ),
    );
    _changes.add(null);
  }

  @override
  Future<List<OutboxEntry>> all() async => List.of(_entries);

  @override
  Stream<List<OutboxEntry>> watch() {
    // Not an async* generator: cancelling those only takes effect at the next yield.
    late final StreamController<List<OutboxEntry>> controller;
    StreamSubscription<void>? sub;
    controller = StreamController<List<OutboxEntry>>(
      onListen: () {
        controller.add(List.of(_entries));
        sub = _changes.stream.listen((_) => controller.add(List.of(_entries)));
      },
      onCancel: () => sub?.cancel(),
    );
    return controller.stream;
  }

  @override
  Future<void> update(OutboxEntry e) async {
    final i = _entries.indexWhere((x) => x.id == e.id);
    if (i >= 0) _entries[i] = e;
    _changes.add(null);
  }

  @override
  Future<void> remove(int id) async {
    _entries.removeWhere((x) => x.id == id);
    _changes.add(null);
  }

  @override
  Future<String?> getCached(String key) async => _cache[key];

  @override
  Future<void> putCached(String key, String value) async => _cache[key] = value;
}
