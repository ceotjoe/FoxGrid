import 'package:material_ui/material_ui.dart';

import '../core/signal.dart';

/// The S-meter quick values (S1..S9, S9+10..S9+60) as a fixed grid with [columns] equally wide
/// cells per row, so no row ends up with a single orphan and labels never wrap.
///
/// Cells are keyed `<keyPrefix>-<label>`. With [buttons] they are tonal buttons (big targets on
/// the station screen), otherwise compact chips (inside forms).
class QuickReadingGrid extends StatelessWidget {
  const QuickReadingGrid({
    super.key,
    required this.keyPrefix,
    required this.onPick,
    this.buttons = false,
    this.columns = 5,
  });

  final String keyPrefix;
  final ValueChanged<QuickReading> onPick;
  final bool buttons;
  final int columns;

  static const double gap = 6;

  @override
  Widget build(BuildContext context) {
    final rows = <List<QuickReading>>[
      for (var i = 0; i < quickReadings.length; i += columns)
        quickReadings.sublist(i, (i + columns).clamp(0, quickReadings.length)),
    ];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (var r = 0; r < rows.length; r++) ...[
          if (r > 0) const SizedBox(height: gap),
          Row(
            children: [
              for (var c = 0; c < columns; c++) ...[
                if (c > 0) const SizedBox(width: gap),
                Expanded(
                  child: c < rows[r].length
                      ? _cell(rows[r][c])
                      : const SizedBox.shrink(),
                ),
              ],
            ],
          ),
        ],
      ],
    );
  }

  Widget _cell(QuickReading q) {
    final label = FittedBox(
      fit: BoxFit.scaleDown,
      child: Text(q.label, maxLines: 1),
    );
    if (buttons) {
      return FilledButton.tonal(
        key: Key('$keyPrefix-${q.label}'),
        style: FilledButton.styleFrom(
          minimumSize: const Size(0, 48),
          padding: const EdgeInsets.symmetric(horizontal: 4),
        ),
        onPressed: () => onPick(q),
        child: label,
      );
    }
    return ActionChip(
      key: Key('$keyPrefix-${q.label}'),
      padding: const EdgeInsets.symmetric(vertical: 10),
      labelPadding: const EdgeInsets.symmetric(horizontal: 2),
      label: SizedBox(width: double.infinity, child: label),
      onPressed: () => onPick(q),
    );
  }
}
