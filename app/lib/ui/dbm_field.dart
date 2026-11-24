import 'package:material_ui/material_ui.dart';

/// Parses a level typed in dBm (comma or dot as decimal separator).
///
/// Received levels are practically always negative, so a value typed without
/// a sign (e.g. `90`) is read as `-90`. A leading `+` keeps the value positive
/// (e.g. `+5`). Returns null when not a number.
double? parseDbm(String text) {
  final t = text.trim().replaceAll(',', '.').replaceAll('\u2212', '-');
  final v = double.tryParse(t);
  if (v == null) return null;
  if (t.startsWith('+')) return v;
  return v > 0 ? -v : v;
}

/// Text field for a level in dBm with a button that cycles the sign
/// (none, `-`, `+`), because some on-screen number keyboards (iOS, Samsung)
/// offer no minus key and none has a convenient plus.
class DbmField extends StatelessWidget {
  const DbmField({super.key, required this.controller, required this.label});

  final TextEditingController controller;
  final String label;

  void _toggleSign() {
    final t = controller.text.trim().replaceAll('\u2212', '-');
    final String next;
    if (t.startsWith('-')) {
      next = '+${t.substring(1)}';
    } else if (t.startsWith('+')) {
      next = t.substring(1);
    } else {
      next = '-$t';
    }
    controller.value = TextEditingValue(
      text: next,
      selection: TextSelection.collapsed(offset: next.length),
    );
  }

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
      keyboardType: const TextInputType.numberWithOptions(
        decimal: true,
        signed: true,
      ),
      decoration: InputDecoration(
        labelText: label,
        helperText: 'ohne Vorzeichen = negativ, + für positiv',
        border: const OutlineInputBorder(),
        suffixIcon: IconButton(
          key: const Key('dbm-sign'),
          tooltip: 'Vorzeichen umschalten',
          icon: const Icon(Icons.exposure),
          onPressed: _toggleSign,
        ),
      ),
    );
  }
}
