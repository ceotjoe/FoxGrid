import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/outbox.dart';
import '../state/providers.dart';

const _kindLabels = {
  'bearing': 'Peilung',
  'message': 'Nachricht',
  'task_create': 'Neue Aufgabe',
  'task_patch': 'Aufgabe geändert',
  'outlier': 'Ausreißer-Markierung',
  'tx_start': 'Aussendung Start',
  'tx_stop': 'Aussendung Ende',
  'rssi': 'RSSI-Messwert',
  'mission': 'Relais-Standort',
};

/// Status chip for the app bar: shows whether everything reached the server.
class SyncChip extends ConsumerWidget {
  const SyncChip({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(syncProvider);
    final compact = MediaQuery.sizeOf(context).width < 600;
    final (icon, color, label) = s.failed > 0
        ? (Icons.error_outline, Colors.red, '${s.failed} Fehler')
        : s.pending > 0
        ? (
            s.syncing ? Icons.sync : Icons.cloud_upload_outlined,
            Colors.orange,
            '${s.pending} offen',
          )
        : (Icons.cloud_done_outlined, Colors.green, 'synchron');
    final shortLabel = compact
        ? (s.failed > 0
              ? '${s.failed}'
              : (s.pending > 0 ? '${s.pending}' : null))
        : label;
    return Tooltip(
      message: label,
      child: InkWell(
        key: const Key('sync-chip'),
        onTap: () => showModalBottomSheet<void>(
          context: context,
          isScrollControlled: true,
          showDragHandle: true,
          builder: (_) => const SyncSheet(),
        ),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 6),
          child: Row(
            children: [
              Icon(icon, color: color, size: 20),
              if (shortLabel != null) ...[
                const SizedBox(width: 3),
                Text(shortLabel, style: const TextStyle(fontSize: 12)),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class SyncSheet extends ConsumerWidget {
  const SyncSheet({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final entries =
        ref.watch(outboxEntriesProvider).value ?? const <OutboxEntry>[];
    final sync = ref.watch(syncProvider);
    return SizedBox(
      height: MediaQuery.of(context).size.height * 0.55,
      child: Column(
        children: [
          ListTile(
            title: Text(
              entries.isEmpty
                  ? 'Alles übertragen'
                  : '${entries.length} Einträge in der Warteschlange',
            ),
            subtitle: Text(
              sync.lastSuccess == null
                  ? 'Noch nichts übertragen'
                  : 'Zuletzt übertragen: ${sync.lastSuccess!.toLocal().toString().substring(11, 19)}',
            ),
            trailing: FilledButton.tonal(
              onPressed: () => ref.read(syncProvider.notifier).kick(),
              child: const Text('Jetzt senden'),
            ),
          ),
          const Divider(height: 1),
          Expanded(
            child: ListView.builder(
              itemCount: entries.length,
              itemBuilder: (_, i) {
                final e = entries[i];
                return ListTile(
                  leading: Icon(
                    e.isFailed ? Icons.error_outline : Icons.schedule,
                    color: e.isFailed ? Colors.red : Colors.orange,
                  ),
                  title: Text(_kindLabels[e.kind] ?? e.kind),
                  subtitle: Text(
                    e.lastError ??
                        (e.attempts == 0 ? 'wartet' : 'Versuch ${e.attempts}'),
                  ),
                  trailing: e.isFailed
                      ? Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            TextButton(
                              onPressed: () =>
                                  ref.read(syncProvider.notifier).retry(e),
                              child: const Text('Erneut'),
                            ),
                            TextButton(
                              onPressed: () =>
                                  ref.read(syncProvider.notifier).discard(e),
                              child: const Text('Verwerfen'),
                            ),
                          ],
                        )
                      : null,
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}
