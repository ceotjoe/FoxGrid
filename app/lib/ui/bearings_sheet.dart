import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../state/providers.dart';

/// Lists all bearings of the mission (never deleted) and lets users flag outliers.
class BearingsSheet extends ConsumerWidget {
  const BearingsSheet({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(missionProvider);
    final bearings = state.bearings.values.toList()
      ..sort((a, b) => b.measuredAt.compareTo(a.measuredAt));
    if (bearings.isEmpty) {
      return const Padding(
        padding: EdgeInsets.all(32),
        child: Text('Noch keine Peilungen.'),
      );
    }
    return SizedBox(
      height: MediaQuery.of(context).size.height * 0.6,
      child: ListView.builder(
        itemCount: bearings.length,
        itemBuilder: (_, i) {
          final b = bearings[i];
          final who = state.participants[b.participantId]?.callsign ?? '?';
          final time = b.measuredAt.toLocal();
          return SwitchListTile(
            title: Text(
              '$who · ${b.azimuthTrueDeg.toStringAsFixed(0)}° ±${b.sigmaDeg.toStringAsFixed(0)}°',
            ),
            subtitle: Text(
              '${time.hour.toString().padLeft(2, '0')}:'
              '${time.minute.toString().padLeft(2, '0')}'
              '${b.rssiDbm != null ? ' · ${b.rssiDbm!.round()} dBm' : ''}'
              '${b.note != null ? ' · ${b.note}' : ''}',
            ),
            secondary: Icon(
              b.isOutlier ? Icons.report : Icons.check_circle_outline,
              color: b.isOutlier ? Colors.orange : Colors.green,
            ),
            value: b.isOutlier,
            onChanged: (v) =>
                ref.read(missionProvider.notifier).setOutlier(b.id, outlier: v),
          );
        },
      ),
    );
  }
}
