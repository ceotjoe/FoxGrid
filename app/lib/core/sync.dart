import 'dart:math';

import 'outbox.dart';

enum SendOutcome {
  /// Delivered (or the server already has it): drop from the queue.
  ok,

  /// Network/server problem: keep and retry later.
  retry,

  /// The server rejected the write for good (4xx): keep visible as failed.
  rejected,
}

class SendResult {
  const SendResult(this.outcome, [this.message]);

  final SendOutcome outcome;
  final String? message;
}

typedef Sender = Future<SendResult> Function(OutboxEntry entry);

/// Drains the outbox in order with exponential backoff.
///
/// A transient failure stops the run (head-of-line) so later writes never overtake
/// the one they may depend on, e.g. a task patch after its creation.
class SyncService {
  SyncService({
    required this.store,
    required this.send,
    DateTime Function()? clock,
    this.maxBackoff = const Duration(seconds: 60),
  }) : _clock = clock ?? (() => DateTime.now().toUtc());

  final OutboxStore store;
  final Sender send;
  final Duration maxBackoff;
  final DateTime Function() _clock;
  bool _running = false;

  static Duration backoff(int attempts, Duration max) {
    final secs = min(pow(2, attempts).toInt(), max.inSeconds);
    return Duration(seconds: secs);
  }

  /// Returns the number of delivered entries.
  Future<int> run({String? missionId}) async {
    if (_running) return 0;
    _running = true;
    var delivered = 0;
    try {
      for (final entry in await store.all()) {
        if (entry.isFailed) continue;
        if (missionId != null && entry.missionId != missionId) continue;
        if (entry.nextAttemptAt.isAfter(_clock())) break; // still backing off
        final result = await send(entry);
        switch (result.outcome) {
          case SendOutcome.ok:
            await store.remove(entry.id);
            delivered++;
          case SendOutcome.rejected:
            await store.update(
              entry.copyWith(status: 'failed', lastError: result.message),
            );
          case SendOutcome.retry:
            final attempts = entry.attempts + 1;
            await store.update(
              entry.copyWith(
                attempts: attempts,
                nextAttemptAt: _clock().add(backoff(attempts, maxBackoff)),
                lastError: result.message,
              ),
            );
            return delivered;
        }
      }
    } finally {
      _running = false;
    }
    return delivered;
  }

  /// Puts a failed entry back into the queue.
  Future<void> retry(OutboxEntry entry) => store.update(
    entry.copyWith(status: 'pending', attempts: 0, nextAttemptAt: _clock()),
  );

  Future<void> discard(OutboxEntry entry) => store.remove(entry.id);
}
