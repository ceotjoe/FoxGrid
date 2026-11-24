import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

import '../core/signal.dart';
import '../state/providers.dart';

/// Shown when a level field holds an unusable value.
const levelRangeError =
    'dBm-Wert zwischen -200 und 20 oder S-Wert (S0–S9+60) eingeben';

/// Parses a level typed in dBm (comma or dot as decimal separator).
///
/// Received levels are practically always negative, so a value typed without
/// a sign (e.g. `90`) is read as `-90`. A leading `+` keeps the value positive
/// (e.g. `+5`). Returns null when not a number.
double? parseDbm(String text) {
  final t = text.trim().replaceAll(',', '.').replaceAll('−', '-');
  final v = double.tryParse(t);
  if (v == null) return null;
  if (t.startsWith('+')) return v;
  return v > 0 ? -v : v;
}

/// Parses a typed level in dBm, or as S value (`7`, `S9+20`) when [sMode] is
/// set. Text starting with `S` is an S value in either mode. Returns dBm.
double? parseLevel(String text, {required bool sMode}) {
  final t = text.trim();
  if (sMode || t.toLowerCase().startsWith('s')) return parseSLevel(t);
  return parseDbm(t);
}

/// Whether [dbm] is a plausible received level.
bool isPlausibleLevel(double? dbm) => dbm != null && dbm <= 20 && dbm >= -200;

/// Text field for a level, either in dBm or as S value (S7, S9+20).
///
/// A unit button switches between the two and the choice is remembered
/// (settings). In dBm mode a button cycles the sign (none, `-`, `+`), because
/// some on-screen number keyboards (iOS, Samsung) offer no minus key and none
/// has a convenient plus; in S mode the same button adds or removes the `+`
/// of `S9+20`. [label] is the field name without the unit.
class DbmField extends ConsumerWidget {
  const DbmField({super.key, required this.controller, required this.label});

  final TextEditingController controller;
  final String label;

  void _set(String text) {
    controller.value = TextEditingValue(
      text: text,
      selection: TextSelection.collapsed(offset: text.length),
    );
  }

  void _toggleSign(bool sMode) {
    final t = controller.text.trim().replaceAll('−', '-');
    if (sMode) {
      _set(t.endsWith('+') ? t.substring(0, t.length - 1) : '$t+');
    } else if (t.startsWith('-')) {
      _set('+${t.substring(1)}');
    } else if (t.startsWith('+')) {
      _set(t.substring(1));
    } else {
      _set('-$t');
    }
  }

  void _switchUnit(WidgetRef ref, bool sMode) {
    // Carry the typed value over to the other unit.
    final v = controller.text.trim().isEmpty
        ? null
        : parseLevel(controller.text, sMode: sMode);
    if (v != null) {
      _set(sMode ? '${v.round()}' : dbmToSInput(v));
    }
    ref.read(settingsProvider.notifier).setLevelInS(!sMode);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final sMode = ref.watch(settingsProvider.select((s) => s.levelInS));
    return TextField(
      controller: controller,
      keyboardType: sMode
          ? const TextInputType.numberWithOptions()
          : const TextInputType.numberWithOptions(decimal: true, signed: true),
      decoration: InputDecoration(
        labelText: sMode ? '$label (S-Wert)' : '$label in dBm',
        prefixText: sMode ? 'S ' : null,
        helperText: sMode
            ? 'z. B. 7 oder 9+20'
            : 'ohne Vorzeichen = negativ, + für positiv',
        suffixIcon: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextButton(
              key: const Key('level-unit'),
              style: TextButton.styleFrom(
                minimumSize: const Size(48, 40),
                padding: const EdgeInsets.symmetric(horizontal: 8),
              ),
              onPressed: () => _switchUnit(ref, sMode),
              child: Text(sMode ? 'S' : 'dBm'),
            ),
            IconButton(
              key: const Key('dbm-sign'),
              tooltip: sMode ? '„+“ umschalten' : 'Vorzeichen umschalten',
              icon: Icon(sMode ? Icons.add : Icons.exposure),
              onPressed: () => _toggleSign(sMode),
            ),
          ],
        ),
      ),
    );
  }
}
