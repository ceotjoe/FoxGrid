import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api.dart';
import '../core/models.dart';
import '../core/permissions.dart';
import '../state/providers.dart';

String roleLabel(String role) => switch (role) {
  'lead' => 'Leitung',
  'fixed' => 'Fest',
  _ => 'Mobil',
};

/// Let joiners in, change roles, set trust, release a device or remove somebody. What each person
/// sees depends on their permissions; the server refuses the rest.
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
    final session = ref.watch(sessionProvider);
    final own = session?.participantId;
    final canManage = session?.can(Perm.participantManage) ?? false;
    final canTrust = session?.can(Perm.trustSet) ?? false;
    final canAssign = session?.can(Perm.roleAssign) ?? false;
    final canQuarantine = session?.can(Perm.quarantine) ?? false;
    final all = ref.watch(missionProvider.select((s) => s.participants)).values;
    final hints = canTrust
        ? ref.watch(plausibilityProvider).value ??
              const <String, List<String>>{}
        : const <String, List<String>>{};
    final waiting = [
      for (final p in all)
        if (p.isPending) p.id,
    ]..sort();
    final codes = waiting.isEmpty || !canManage
        ? const <String, String>{}
        : ref.watch(joinCodesProvider(waiting.join(','))).value ??
              const <String, String>{};
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
          if (canTrust)
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
                    subtitle: Text(
                      codes[p.id] == null
                          ? 'wartet auf Freigabe'
                          : 'wartet auf Freigabe · Code ${codes[p.id]} '
                                '(per Funk abgleichen)',
                    ),
                    trailing: !canManage
                        ? null
                        : Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              IconButton(
                                key: Key('reject-${p.callsign}'),
                                tooltip: 'Ablehnen',
                                icon: const Icon(Icons.close),
                                onPressed: () => _run(
                                  context,
                                  ref,
                                  (api) => api.patchParticipant(
                                    p.id,
                                    status: 'rejected',
                                  ),
                                ),
                              ),
                              IconButton.filled(
                                key: Key('approve-${p.callsign}'),
                                tooltip: 'Freigeben',
                                icon: const Icon(Icons.check),
                                onPressed: () => _run(
                                  context,
                                  ref,
                                  (api) => api.patchParticipant(
                                    p.id,
                                    status: 'active',
                                  ),
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
                    canManage: canManage,
                    canTrust: canTrust,
                    canAssign: canAssign,
                    canQuarantine: canQuarantine,
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
    required bool canManage,
    required bool canTrust,
    required bool canAssign,
    required bool canQuarantine,
    List<String> hints = const [],
  }) {
    final off = !p.isActive || p.status == 'rejected';
    final state = !p.isActive
        ? 'entfernt'
        : p.status == 'rejected'
        ? 'abgelehnt'
        : [
            authorityLabel(p.authority),
            // The source: a person at a fixed location, next to their standing.
            if (p.role == 'fixed' && p.authority != 'station')
              roleLabel(p.role),
          ].join(' · ');
    final hasActions =
        !isSelf && (canManage || canTrust || canAssign || canQuarantine);
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
            if (p.authority == 'observer' && !off)
              'Beobachter (Daten zählen nie)'
            else if (!p.trusted && !off)
              'nicht vertraut (Daten zählen nicht)',
            if (!p.deviceBound && !off) 'Gerät frei',
          ].join(' · '),
          if (!off) ...hints.map((h) => 'Auffällig: $h'),
        ].join('\n'),
      ),
      trailing: !hasActions
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
                        'fixed' => api.patchParticipant(p.id, role: v),
                        _ when assignableAuthorities.contains(v) =>
                          api.patchParticipant(p.id, authority: v),
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
                  if (canAssign) ...[
                    for (final a in assignableAuthorities)
                      if (a != p.authority)
                        PopupMenuItem(
                          key: Key('authority-$a'),
                          value: a,
                          child: Text('Rolle: ${authorityLabel(a)}'),
                        ),
                    for (final r in ['mobile', 'fixed'])
                      if (r != p.role && p.role != 'lead')
                        PopupMenuItem(
                          value: r,
                          child: Text('Rolle: ${roleLabel(r)}'),
                        ),
                  ],
                  if (canTrust)
                    PopupMenuItem(
                      value: p.trusted ? 'untrust' : 'trust',
                      child: Text(
                        p.trusted ? 'Vertrauen entziehen' : 'Vertrauen',
                      ),
                    ),
                  if (canManage && p.deviceBound)
                    const PopupMenuItem(
                      value: 'device',
                      child: Text('Gerät freigeben (neues Handy)'),
                    ),
                  if (canQuarantine)
                    const PopupMenuItem(
                      key: Key('quarantine'),
                      value: 'quarantine',
                      child: Text('Quarantäne …'),
                    ),
                  if (canManage)
                    const PopupMenuItem(
                      value: 'remove',
                      child: Text('Entfernen'),
                    ),
                ] else if (canManage)
                  const PopupMenuItem(
                    value: 'restore',
                    child: Text('Wieder zulassen'),
                  ),
              ],
            ),
    );
  }
}
