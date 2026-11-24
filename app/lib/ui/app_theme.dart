import 'package:material_ui/material_ui.dart';

/// Minimum height of every button; large enough for gloved or one-handed use in the field.
const double kButtonHeight = 52;

/// Applies the shared component styling (buttons, inputs, dialogs, sheets) to a colour theme.
///
/// Colours stay with the base theme, so the red night theme keeps its palette. Everything else
/// (sizes, shapes, label style) is defined here once so no screen needs hard-coded font sizes
/// or button heights.
ThemeData withAppStyle(ThemeData base) {
  final shape = RoundedRectangleBorder(borderRadius: BorderRadius.circular(12));
  const padding = EdgeInsets.symmetric(horizontal: 20);
  const minimumSize = Size(64, kButtonHeight);
  final label = base.textTheme.titleMedium?.copyWith(
    fontWeight: FontWeight.w600,
  );
  return base.copyWith(
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: minimumSize,
        padding: padding,
        shape: shape,
        textStyle: label,
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: minimumSize,
        padding: padding,
        shape: shape,
        textStyle: label,
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        minimumSize: minimumSize,
        padding: padding,
        shape: shape,
        textStyle: label,
      ),
    ),
    inputDecorationTheme: const InputDecorationTheme(
      border: OutlineInputBorder(),
    ),
    dialogTheme: DialogThemeData(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      insetPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 24),
    ),
    bottomSheetTheme: const BottomSheetThemeData(
      showDragHandle: true,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
    ),
  );
}
