import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/homing.dart';
import '../core/models.dart';
import '../state/providers.dart';

/// "Peile als Nächstes hier": the proposals are only shown, nobody is sent anywhere.
class SuggestionsSheet extends ConsumerWidget {
  const SuggestionsSheet({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(suggestionsProvider);
    final theme = Theme.of(context);
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Wo peilen als Nächstes?', style: theme.textTheme.titleLarge),
            const SizedBox(height: 4),
            Text(
              'Von diesen Punkten aus verkleinert eine weitere Peilung (±10°) die '
              'Fehlerellipse am stärksten. Das sind Vorschläge, keine Anweisungen.',
              style: theme.textTheme.bodySmall,
            ),
            const SizedBox(height: 8),
            async.when(
              loading: () => const Padding(
                padding: EdgeInsets.all(24),
                child: Center(child: CircularProgressIndicator()),
              ),
              error: (e, _) => Text(
                'Nicht verfügbar: $e',
                key: const Key('suggestions-error'),
              ),
              data: (list) => list.isEmpty
                  ? const Text(
                      'Noch keine Vorschläge: erst Peilungen erfassen.',
                      key: Key('suggestions-empty'),
                    )
                  : Column(
                      children: [
                        for (var i = 0; i < list.length; i++)
                          SuggestionTile(index: i + 1, s: list[i]),
                      ],
                    ),
            ),
          ],
        ),
      ),
    );
  }
}

class SuggestionTile extends StatelessWidget {
  const SuggestionTile({super.key, required this.index, required this.s});

  final int index;
  final Suggestion s;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      key: Key('suggestion-$index'),
      contentPadding: EdgeInsets.zero,
      leading: CircleAvatar(
        backgroundColor: Colors.green.shade700,
        foregroundColor: Colors.white,
        child: Text('$index'),
      ),
      title: Text(
        '−${(s.expectedReduction * 100).round()} % Fläche · '
        '${formatDistance(s.distanceToTargetM)} vom Ziel',
      ),
      subtitle: Text(
        'Peilung von dort: ${s.azimuthToTargetDeg.round()}° · danach ca. '
        '${s.expectedSemiMajorM.round()} × ${s.expectedSemiMinorM.round()} m (1σ)',
      ),
    );
  }
}
