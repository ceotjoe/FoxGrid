import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/models.dart';
import '../state/providers.dart';

/// One line of plain German for a log entry.
String describeAudit(AuditEntry e) {
  final who = e.actor ?? 'System';
  final target = e.subject ?? '?';
  final d = e.detail;
  switch ((e.entity, e.action)) {
    case ('participant', 'join'):
      return '$who ist beigetreten';
    case ('participant', 'join_denied'):
      return 'Beitritt als $target von einem anderen Gerät abgewiesen';
    case ('participant', 'quarantine'):
      final removed = d['removed'] == true ? ', entfernt' : '';
      return '$who: Quarantäne für $target '
          '(${d['bearings'] ?? 0} Peilungen, ${d['rssi_samples'] ?? 0} Messwerte$removed)';
    case ('participant', 'update'):
      final parts = <String>[];
      final status = d['status'];
      if (status is List && status.length == 2) {
        parts.add(
          status[1] == 'active'
              ? 'freigegeben'
              : status[1] == 'rejected'
              ? 'abgelehnt'
              : 'Status ${status[1]}',
        );
      }
      final role = d['role'];
      if (role is List && role.length == 2) {
        parts.add('Rolle ${role[0]} → ${role[1]}');
      }
      if (d['is_active'] == false) parts.add('entfernt');
      if (d['is_active'] == true) parts.add('wieder zugelassen');
      if (d['trusted'] == true) parts.add('Vertrauen erteilt');
      if (d['trusted'] == false) parts.add('Vertrauen entzogen');
      if (d['device_released'] == true) parts.add('Gerät freigegeben');
      return '$who: $target ${parts.isEmpty ? 'geändert' : parts.join(', ')}';
    case ('invite', 'create'):
      return '$who hat eine Einladung erstellt';
    case ('invite', 'rotate'):
      return '$who hat eine Einladung ersetzt';
    case ('invite', 'replace'):
      return '$who hat alle Einladungen durch eine neue ersetzt';
    case ('invite', 'revoke'):
      return '$who hat eine Einladung widerrufen';
  }
  return '$who: ${e.action} ${e.entity}';
}

/// Lead only: who joined, who was approved, removed or quarantined, which invites were issued.
class AuditScreen extends ConsumerWidget {
  const AuditScreen({super.key});

  String _time(DateTime t) {
    final l = t.toLocal();
    String two(int n) => n.toString().padLeft(2, '0');
    return '${two(l.day)}.${two(l.month)}. ${two(l.hour)}:${two(l.minute)}:${two(l.second)}';
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(auditProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Sicherheitsprotokoll'),
        actions: [
          IconButton(
            tooltip: 'Aktualisieren',
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(auditProvider),
          ),
        ],
      ),
      body: async.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(
          child: Text('Nicht erreichbar: $e', key: const Key('audit-error')),
        ),
        data: (entries) => entries.isEmpty
            ? const Center(child: Text('Noch keine Einträge.'))
            : ListView.separated(
                itemCount: entries.length,
                separatorBuilder: (_, _) => const Divider(height: 1),
                itemBuilder: (_, i) => ListTile(
                  key: Key('audit-${entries[i].id}'),
                  dense: true,
                  title: Text(describeAudit(entries[i])),
                  subtitle: Text(_time(entries[i].at)),
                ),
              ),
      ),
    );
  }
}
