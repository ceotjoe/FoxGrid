import 'package:material_ui/material_ui.dart';

/// Parses a level typed in dBm (comma or dot as decimal separator).
///
/// Received levels are practically always negative, so a value typed without
/// a minus sign (e.g. `90`) is read as `-90`. Returns null when not a number.
double? parseDbm(String text) {
  final v = double.tryParse(text.trim().replaceAll(',', '.'));
  if (v == null) return null;
  return v > 0 ? -v : v;
}

/// Text field for a level in dBm with a button that toggles the minus sign,
/// because some on-screen number keyboards (iOS, Samsung) offer no minus key.
class DbmField extends StatelessWidget {
  const DbmField({super.key, required this.controller, required this.label});

  final TextEditingController controller;
  final String label;

  void _toggleSign() {
    final t = controller.text.trim();
    final next = t.startsWith('-') || t.startsWith('−')
        ? t.substring(1)
        : '-$t';
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
        helperText: 'ohne Vorzeichen = negativ',
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
