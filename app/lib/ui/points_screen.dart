import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/coords.dart';
import '../core/models.dart';
import '../state/providers.dart';
import 'external_bearing_sheet.dart';
import 'point_editor_screen.dart';

/// Lead only: external bearing points (bearings received from outside the group, e.g. from the
/// BNetzA). The estimate switch and (de)activation are the only things that can change later;
/// a wrong position is replaced by a new point.
class PointsScreen extends ConsumerWidget {
  const PointsScreen({super.key});

  /// Adds a point and goes straight on to its first bearing.
  Future<void> _add(BuildContext context) async {
    final id = await Navigator.of(context).push<String>(
      MaterialPageRoute(builder: (_) => const PointEditorScreen()),
    );
    if (id != null && context.mounted) await _enterBearing(context, id);
  }

  Future<void> _enterBearing(BuildContext context, String pointId) =>
      showModalBottomSheet<bool>(
        context: context,
        isScrollControlled: true,
        showDragHandle: true,
        builder: (_) => ExternalBearingSheet(pointId: pointId),
      );

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(missionProvider);
    final notifier = ref.read(missionProvider.notifier);
    final points = state.points.values.toList()
      ..sort((a, b) {
        if (a.isActive != b.isActive) return a.isActive ? -1 : 1;
        return a.name.toLowerCase().compareTo(b.name.toLowerCase());
      });
    int bearingsOf(BearingPoint p) =>
        state.bearings.values.where((b) => b.pointId == p.id).length;

    return Scaffold(
      appBar: AppBar(title: const Text('Externe Peilpunkte')),
      floatingActionButton: FloatingActionButton.extended(
        key: const Key('point-add'),
        onPressed: () => _add(context),
        icon: const Icon(Icons.add_location_alt_outlined),
        label: const Text('Peilpunkt'),
      ),
      body: points.isEmpty
          ? const Center(
              child: Padding(
                padding: EdgeInsets.all(24),
                child: Text(
                  'Noch keine Peilpunkte. Lege einen Punkt an, wenn Peilungen '
                  'von außerhalb der Gruppe kommen, z. B. von der BNetzA.',
                  key: Key('points-empty'),
                  textAlign: TextAlign.center,
                ),
              ),
            )
          : ListView(
              padding: const EdgeInsets.only(bottom: 96),
              children: [
                for (final p in points)
                  ListTile(
                    key: Key('point-${p.id}'),
                    enabled: p.isActive,
                    leading: Icon(
                      p.isActive
                          ? Icons.location_on_outlined
                          : Icons.location_off_outlined,
                    ),
                    title: Text(p.name),
                    subtitle: Text(
                      '${formatCoordinate(p.position.latitude, isLat: true)}  '
                      '${formatCoordinate(p.position.longitude, isLat: false)}\n'
                      '${bearingsOf(p)} Peilungen'
                      '${p.isActive ? '' : ' · deaktiviert'}'
                      '${p.isActive && !p.useInEstimate ? ' · nicht in Schätzung' : ''}',
                    ),
                    isThreeLine: true,
                    onTap: p.isActive
                        ? () => _enterBearing(context, p.id)
                        : null,
                    trailing: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        IconButton(
                          key: Key('point-bearing-${p.id}'),
                          tooltip: 'Peilung eintragen',
                          icon: const Icon(Icons.add_circle_outline),
                          onPressed: p.isActive
                              ? () => _enterBearing(context, p.id)
                              : null,
                        ),
                        Switch(
                          key: Key('point-switch-${p.id}'),
                          value: p.useInEstimate,
                          onChanged: p.isActive
                              ? (v) => notifier.patchPoint(p.id, {
                                  'use_in_estimate': v,
                                })
                              : null,
                        ),
                        PopupMenuButton<String>(
                          key: Key('point-menu-${p.id}'),
                          onSelected: (v) => notifier.patchPoint(p.id, {
                            'is_active': v == 'activate',
                          }),
                          itemBuilder: (_) => [
                            PopupMenuItem(
                              key: Key('point-toggle-active-${p.id}'),
                              value: p.isActive ? 'deactivate' : 'activate',
                              child: Text(
                                p.isActive ? 'Deaktivieren' : 'Aktivieren',
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
              ],
            ),
    );
  }
}
