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

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final own = ref.watch(sessionProvider)?.participantId;
    final all = ref.watch(missionProvider.select((s) => s.participants)).values;
    int rank(Participant p) => p.isPending ? 0 : (p.isActive ? 1 : 2);
    final list = [...all]
      ..sort((a, b) {
        final r = rank(a).compareTo(rank(b));
        return r != 0 ? r : a.callsign.compareTo(b.callsign);
      });
    return Scaffold(
      appBar: AppBar(title: const Text('Teilnehmer')),
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
                : _row(context, ref, p, isSelf: p.id == own),
        ],
      ),
    );
  }

  Widget _row(
    BuildContext context,
    WidgetRef ref,
    Participant p, {
    required bool isSelf,
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
      leading: Icon(off ? Icons.person_off : Icons.person),
      title: Text(isSelf ? '${p.callsign} (du)' : p.callsign),
      subtitle: Text(
        [
          state,
          if (p.team != null) p.team!,
          if (!p.deviceBound && !off) 'Gerät frei',
        ].join(' · '),
      ),
      trailing: isSelf
          ? null
          : PopupMenuButton<String>(
              key: Key('menu-${p.callsign}'),
              onSelected: (v) => _run(
                context,
                ref,
                (api) => switch (v) {
                  'mobile' ||
                  'fixed' ||
                  'lead' => api.patchParticipant(p.id, role: v),
                  'device' => api.patchParticipant(p.id, resetDevice: true),
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
                  if (p.deviceBound)
                    const PopupMenuItem(
                      value: 'device',
                      child: Text('Gerät freigeben (neues Handy)'),
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
