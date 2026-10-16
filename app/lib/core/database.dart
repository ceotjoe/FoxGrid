import 'package:drift/drift.dart';
import 'package:drift_flutter/drift_flutter.dart';

part 'database.g.dart';

/// A write that still has to reach the server (the offline sync queue).
class OutboxRows extends Table {
  IntColumn get id => integer().autoIncrement()();
  TextColumn get missionId => text()();

  /// bearing | message | task_create | task_patch | outlier | tx_start | tx_stop
  TextColumn get kind => text()();
  TextColumn get method => text()();
  TextColumn get path => text()();
  TextColumn get bodyJson => text().nullable()();
  DateTimeColumn get createdAt => dateTime()();
  IntColumn get attempts => integer().withDefault(const Constant(0))();
  DateTimeColumn get nextAttemptAt => dateTime()();

  /// pending | failed
  TextColumn get status => text().withDefault(const Constant('pending'))();
  TextColumn get lastError => text().nullable()();
}

/// Small key/value cache (last mission snapshot for offline start).
class KeyValueRows extends Table {
  TextColumn get key => text()();
  TextColumn get value => text()();

  @override
  Set<Column<Object>> get primaryKey => {key};
}

@DriftDatabase(tables: [OutboxRows, KeyValueRows])
class AppDatabase extends _$AppDatabase {
  AppDatabase([QueryExecutor? executor])
    : super(executor ?? driftDatabase(name: 'foxgrid'));

  @override
  int get schemaVersion => 1;
}
