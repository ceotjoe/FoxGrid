import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api.dart';
import '../core/models.dart';
import '../state/providers.dart';

String roleLabel(String role) => switch (role) {
  'lead' => 'Leitung',
  'fixed' => 'Fest',
  _ => 'Mobil',
};

/// Lead only: let joiners in, change roles, release a device or remove somebody.
class ParticipantsScreen extends ConsumerWidget {
  const ParticipantsScreen({super.key});

  Future<void> _run(
    BuildContext context,
    WidgetRef ref,
    Future<Participant> Function(FoxGridApi api) action,
  ) async {
    try {
      final p = await action(ref.read(apiProvider));
      ref.read(missionProvider.notifier).applyParticipant(p);
    } on ApiException catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              e.statusCode == 409
                  ? 'Das geht für dieses Konto nicht (Sensor oder eigenes Konto).'
                  : e.message,
            ),
          ),
        );
      }
    }
  }

  /// Takes everything the participant contributed out of the estimate (stays in the log).
  Future<void> _quarantine(
    BuildContext context,
    WidgetRef ref,
    Participant p,
  ) async {
    final remove = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Quarantäne für ${p.callsign}?'),
        content: const Text(
          'Alle Peilungen und Messwerte dieses Teilnehmers werden aus der '
          'Schätzung genommen und sein Vertrauen entzogen. Sie bleiben im '
          'Protokoll. Das Zurücknehmen geht nur einzeln pro Peilung.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Abbrechen'),
          ),
          TextButton(
            key: const Key('quarantine-only'),
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Quarantäne'),
          ),
          FilledButton(
            key: const Key('quarantine-remove'),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Quarantäne und entfernen'),
          ),
        ],
      ),
    );
    if (remove == null || !context.mounted) return;
    try {
      final r = await ref.read(apiProvider).quarantine(p.id, remove: remove);
      ref.read(missionProvider.notifier).applyParticipant(r.participant);
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              '${r.bearings} Peilungen und ${r.rssi} Messwerte '
              'aus der Schätzung genommen.',
            ),
          ),
        );
      }
    } on ApiException catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(e.message)));
      }
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final own = ref.watch(sessionProvider)?.participantId;
    final all = ref.watch(missionProvider.select((s) => s.participants)).values;
    final hints = ref.watch(plausibilityProvider).value ?? const {};
    int rank(Participant p) => p.isPending ? 0 : (p.isActive ? 1 : 2);
    final list = [...all]
      ..sort((a, b) {
        final r = rank(a).compareTo(rank(b));
        return r != 0 ? r : a.callsign.compareTo(b.callsign);
      });
    return Scaffold(
      appBar: AppBar(
        title: const Text('Teilnehmer'),
        actions: [
          IconButton(
            key: const Key('refresh-hints'),
            tooltip: 'Auffälligkeiten prüfen',
            icon: const Icon(Icons.fact_check_outlined),
            onPressed: () => ref.invalidate(plausibilityProvider),
          ),
        ],
      ),
      body: ListView(
        children: [
          for (final p in list)
            p.isPending
                ? ListTile(
                    key: Key('pending-${p.callsign}'),
                    leading: const Icon(Icons.hourglass_top),
                    title: Text(p.callsign),
                    subtitle: const Text('wartet auf Freigabe'),
                    trailing: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        IconButton(
                          key: Key('reject-${p.callsign}'),
                          tooltip: 'Ablehnen',
                          icon: const Icon(Icons.close),
                          onPressed: () => _run(
                            context,
                            ref,
                            (api) =>
                                api.patchParticipant(p.id, status: 'rejected'),
                          ),
                        ),
                        IconButton.filled(
                          key: Key('approve-${p.callsign}'),
                          tooltip: 'Freigeben',
                          icon: const Icon(Icons.check),
                          onPressed: () => _run(
                            context,
                            ref,
                            (api) =>
                                api.patchParticipant(p.id, status: 'active'),
                          ),
                        ),
                      ],
                    ),
                  )
                : _row(
                    context,
                    ref,
                    p,
                    isSelf: p.id == own,
                    hints: hints[p.id] ?? const [],
                  ),
        ],
      ),
    );
  }

  Widget _row(
    BuildContext context,
    WidgetRef ref,
    Participant p, {
    required bool isSelf,
    List<String> hints = const [],
  }) {
    final off = !p.isActive || p.status == 'rejected';
    final state = !p.isActive
        ? 'entfernt'
        : p.status == 'rejected'
        ? 'abgelehnt'
        : roleLabel(p.role);
    return ListTile(
      key: Key('participant-${p.callsign}'),
      enabled: !off || !isSelf,
      leading: hints.isNotEmpty && !off
          ? const Icon(Icons.warning_amber, color: Colors.orange)
          : Icon(off ? Icons.person_off : Icons.person),
      title: Text(isSelf ? '${p.callsign} (du)' : p.callsign),
      isThreeLine: hints.isNotEmpty && !off,
      subtitle: Text(
        [
          [
            state,
            if (p.team != null) p.team!,
            if (!p.trusted && !off) 'nicht vertraut (Daten zählen nicht)',
            if (!p.deviceBound && !off) 'Gerät frei',
          ].join(' · '),
          if (!off) ...hints.map((h) => 'Auffällig: $h'),
        ].join('\n'),
      ),
      trailing: isSelf
          ? null
          : PopupMenuButton<String>(
              key: Key('menu-${p.callsign}'),
              onSelected: (v) => v == 'quarantine'
                  ? _quarantine(context, ref, p)
                  : _run(
                      context,
                      ref,
                      (api) => switch (v) {
                        'mobile' ||
                        'fixed' ||
                        'lead' => api.patchParticipant(p.id, role: v),
                        'trust' => api.patchParticipant(p.id, trusted: true),
                        'untrust' => api.patchParticipant(p.id, trusted: false),
                        'device' => api.patchParticipant(
                          p.id,
                          resetDevice: true,
                        ),
                        'remove' => api.patchParticipant(p.id, isActive: false),
                        'restore' => api.patchParticipant(
                          p.id,
                          isActive: true,
                          status: 'active',
                        ),
                        _ => throw StateError(v),
                      },
                    ),
              itemBuilder: (_) => [
                if (!off) ...[
                  for (final r in ['mobile', 'fixed', 'lead'])
                    if (r != p.role)
                      PopupMenuItem(
                        value: r,
                        child: Text('Rolle: ${roleLabel(r)}'),
                      ),
                  PopupMenuItem(
                    value: p.trusted ? 'untrust' : 'trust',
                    child: Text(
                      p.trusted ? 'Vertrauen entziehen' : 'Vertrauen',
                    ),
                  ),
                  if (p.deviceBound)
                    const PopupMenuItem(
                      value: 'device',
                      child: Text('Gerät freigeben (neues Handy)'),
                    ),
                  const PopupMenuItem(
                    key: Key('quarantine'),
                    value: 'quarantine',
                    child: Text('Quarantäne …'),
                  ),
                  const PopupMenuItem(
                    value: 'remove',
                    child: Text('Entfernen'),
                  ),
                ] else
                  const PopupMenuItem(
                    value: 'restore',
                    child: Text('Wieder zulassen'),
                  ),
              ],
            ),
    );
  }
}
