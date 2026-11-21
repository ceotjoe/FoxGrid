import 'package:material_ui/material_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/models.dart';
import '../core/permissions.dart';
import '../state/providers.dart';
import 'interferers_screen.dart';

Future<void> _reassign(
  BuildContext context,
  WidgetRef ref,
  Bearing b,
  MissionState state,
) async {
  final picked = await showModalBottomSheet<String>(
    context: context,
    showDragHandle: true,
    builder: (ctx) => SafeArea(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const ListTile(title: Text('Peilung zuordnen zu')),
          for (final i in state.activeInterferers)
            ListTile(
              key: Key('reassign-${i.id}'),
              leading: InterfererBadge(i),
              title: Text(i.name),
              trailing: i.id == b.interfererId ? const Icon(Icons.check) : null,
              onTap: () => Navigator.pop(ctx, i.id),
            ),
        ],
      ),
    ),
  );
  if (picked != null && picked != b.interfererId) {
    await ref.read(missionProvider.notifier).reassignBearing(b.id, picked);
  }
}

/// Lists all bearings of the mission (never deleted) and lets users flag outliers.
class BearingsSheet extends ConsumerWidget {
  const BearingsSheet({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(missionProvider);
    final session = ref.watch(sessionProvider);
    final bearings = state.bearings.values.toList()
      ..sort((a, b) => b.measuredAt.compareTo(a.measuredAt));
    if (bearings.isEmpty) {
      return const Padding(
        padding: EdgeInsets.all(32),
        child: Text('Noch keine Peilungen.'),
      );
    }
    final hint = state.activeInterferers.length > 1;
    return SizedBox(
      height: MediaQuery.of(context).size.height * 0.6,
      child: Column(
        children: [
          if (hint)
            const Padding(
              padding: EdgeInsets.fromLTRB(16, 0, 16, 8),
              child: Text(
                'Lange drücken: Peilung einem anderen Störer zuordnen',
                key: Key('reassign-hint'),
              ),
            ),
          Expanded(
            child: ListView.builder(
              itemCount: bearings.length,
              itemBuilder: (_, i) {
                final b = bearings[i];
                final point = b.pointId == null
                    ? null
                    : state.points[b.pointId];
                final who = b.isExternal
                    ? 'extern: ${point?.name ?? '?'}'
                    : state.participants[b.participantId]?.callsign ?? '?';
                final time = b.measuredAt.toLocal();
                final interferer = b.interfererId == null
                    ? null
                    : state.interferers[b.interfererId];
                final showInterferer = state.interferers.length > 1;
                final mayReassign =
                    showInterferer &&
                    state.activeInterferers.length > 1 &&
                    (b.participantId == session?.participantId ||
                        (session?.can(Perm.interfererManage) ?? false));
                final tile = SwitchListTile(
                  title: Text(
                    '$who · ${b.azimuthTrueDeg.toStringAsFixed(0)}° ±${b.sigmaDeg.toStringAsFixed(0)}°',
                  ),
                  subtitle: Text(
                    '${time.hour.toString().padLeft(2, '0')}:'
                    '${time.minute.toString().padLeft(2, '0')}'
                    '${showInterferer && interferer != null ? ' · ${interferer.name}' : ''}'
                    '${b.rssiDbm != null ? ' · ${b.rssiDbm!.round()} dBm' : ''}'
                    '${b.note != null ? ' · ${b.note}' : ''}'
                    '${!b.isExternal && state.participants[b.participantId]?.trusted == false ? ' · nicht vertraut' : ''}'
                    '${point != null && !(point.useInEstimate && point.isActive) ? ' · nicht in Schätzung' : ''}',
                  ),
                  secondary: Icon(
                    b.isOutlier ? Icons.report : Icons.check_circle_outline,
                    color: b.isOutlier ? Colors.orange : Colors.green,
                  ),
                  value: b.isOutlier,
                  onChanged: (v) => ref
                      .read(missionProvider.notifier)
                      .setOutlier(b.id, outlier: v),
                );
                if (!mayReassign) return tile;
                return GestureDetector(
                  key: Key('bearing-${b.id}'),
                  onLongPress: () => _reassign(context, ref, b, state),
                  child: tile,
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}
