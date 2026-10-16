import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../state/filter.dart';
import '../state/providers.dart';

/// Choose which bearings feed the estimate: transmissions, time window, age weighting.
class FilterSheet extends ConsumerWidget {
  const FilterSheet({super.key});

  static const _windows = <(String, Duration?)>[
    ('alle', null),
    ('15 min', Duration(minutes: 15)),
    ('30 min', Duration(minutes: 30)),
    ('60 min', Duration(minutes: 60)),
  ];
  static const _halfLives = <(String, Duration?)>[
    ('aus', null),
    ('5 min', Duration(minutes: 5)),
    ('15 min', Duration(minutes: 15)),
    ('30 min', Duration(minutes: 30)),
  ];

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final f = ref.watch(filterProvider);
    final txs = ref.watch(missionProvider.select((s) => s.transmissions));
    final notifier = ref.read(filterProvider.notifier);
    final theme = Theme.of(context);

    Widget chips<T>(
      List<(String, T?)> options,
      T? selected,
      void Function(T?) onTap,
    ) => Wrap(
      spacing: 8,
      children: [
        for (final o in options)
          ChoiceChip(
            label: Text(o.$1),
            selected: selected == o.$2,
            onSelected: (_) => onTap(o.$2),
          ),
      ],
    );

    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text('Filter', style: theme.textTheme.titleLarge),
              const SizedBox(height: 12),
              Text('Aussendungen', style: theme.textTheme.labelLarge),
              Wrap(
                spacing: 8,
                children: [
                  ChoiceChip(
                    label: const Text('alle'),
                    selected: f.transmissionIds.isEmpty,
                    onSelected: (_) =>
                        notifier.set(f.copyWith(transmissionIds: {})),
                  ),
                  for (final t in txs)
                    FilterChip(
                      key: Key('filter-tx-${t.seq}'),
                      label: Text('#${t.seq}'),
                      selected: f.transmissionIds.contains(t.id),
                      onSelected: (on) {
                        final ids = {...f.transmissionIds};
                        on ? ids.add(t.id) : ids.remove(t.id);
                        notifier.set(f.copyWith(transmissionIds: ids));
                      },
                    ),
                ],
              ),
              const SizedBox(height: 12),
              Text('Zeitfenster', style: theme.textTheme.labelLarge),
              chips<Duration>(
                _windows,
                f.window,
                (d) => notifier.set(
                  d == null
                      ? f.copyWith(clearWindow: true)
                      : f.copyWith(window: d),
                ),
              ),
              const SizedBox(height: 12),
              Text(
                'Alter gewichten (Halbwertszeit)',
                style: theme.textTheme.labelLarge,
              ),
              chips<Duration>(
                _halfLives,
                f.halfLife,
                (d) => notifier.set(
                  d == null
                      ? f.copyWith(clearHalfLife: true)
                      : f.copyWith(halfLife: d),
                ),
              ),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Wahrscheinlichkeitskonturen'),
                subtitle: const Text('50 / 80 / 95 %'),
                value: f.showContours,
                onChanged: (v) => notifier.set(f.copyWith(showContours: v)),
              ),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Ausreißer ausblenden'),
                value: f.hideOutliers,
                onChanged: (v) => notifier.set(f.copyWith(hideOutliers: v)),
              ),
              Align(
                alignment: Alignment.centerRight,
                child: TextButton(
                  onPressed: notifier.reset,
                  child: const Text('Zurücksetzen'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
