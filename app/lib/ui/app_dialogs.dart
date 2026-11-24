import 'dart:math' as math;

import 'package:material_ui/material_ui.dart';

/// Visual weight of an [AppAction]. Buttons of every role share height, shape and label style
/// (see `withAppStyle`); only the colour treatment differs.
enum AppActionRole {
  /// Dismisses without effect ("Abbrechen", "Schließen"). Outlined.
  cancel,

  /// An alternative to the main action. Tonal.
  secondary,

  /// The main action ("Speichern"). Filled.
  primary,

  /// A main action that cannot be undone ("Beenden"). Filled in the error colour.
  destructive,
}

/// One button of an [ActionBar].
class AppAction {
  const AppAction({
    required this.label,
    required this.onPressed,
    this.role = AppActionRole.primary,
    this.buttonKey,
    this.busy = false,
  });

  /// Shorthand for the "Abbrechen" button.
  const AppAction.cancel({
    String label = 'Abbrechen',
    required VoidCallback? onPressed,
    Key? buttonKey,
  }) : this(
         label: label,
         onPressed: onPressed,
         role: AppActionRole.cancel,
         buttonKey: buttonKey,
       );

  final String label;
  final VoidCallback? onPressed;
  final AppActionRole role;
  final Key? buttonKey;

  /// Shows a progress indicator instead of the label and disables the button.
  final bool busy;
}

/// A row of equally sized buttons (cancel on the left, main action on the right).
///
/// Labels never wrap inside a button. When the labels do not fit side by side at equal width
/// (narrow screen, large text scale, long label) the buttons are stacked instead, with the main
/// action on top, rather than squeezed.
class ActionBar extends StatelessWidget {
  const ActionBar({super.key, required this.actions});

  final List<AppAction> actions;

  static const double gap = 12;
  static const double _horizontalPadding = 20;

  @override
  Widget build(BuildContext context) {
    if (actions.isEmpty) return const SizedBox.shrink();
    return LayoutBuilder(
      builder: (context, constraints) {
        final stacked = _needsStacking(context, constraints.maxWidth);
        if (stacked) {
          return Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              for (var i = actions.length - 1; i >= 0; i--) ...[
                _AppActionButton(actions[i]),
                if (i > 0) const SizedBox(height: gap),
              ],
            ],
          );
        }
        return Row(
          children: [
            for (var i = 0; i < actions.length; i++) ...[
              if (i > 0) const SizedBox(width: gap),
              Expanded(child: _AppActionButton(actions[i])),
            ],
          ],
        );
      },
    );
  }

  bool _needsStacking(BuildContext context, double maxWidth) {
    if (actions.length < 2 || !maxWidth.isFinite) return false;
    final style = Theme.of(context).textTheme.titleMedium
        ?.copyWith(fontWeight: FontWeight.w600);
    final scaler = MediaQuery.textScalerOf(context);
    var widest = 0.0;
    for (final a in actions) {
      final painter = TextPainter(
        text: TextSpan(text: a.label, style: style),
        textDirection: TextDirection.ltr,
        textScaler: scaler,
        maxLines: 1,
      )..layout();
      widest = math.max(widest, painter.width);
      painter.dispose();
    }
    final needed =
        actions.length * (widest + 2 * _horizontalPadding) +
        (actions.length - 1) * gap;
    return needed > maxWidth;
  }
}

class _AppActionButton extends StatelessWidget {
  const _AppActionButton(this.action);

  final AppAction action;

  @override
  Widget build(BuildContext context) {
    final onPressed = action.busy ? null : action.onPressed;
    final child = action.busy
        ? const SizedBox.square(
            dimension: 22,
            child: CircularProgressIndicator(strokeWidth: 3),
          )
        : Text(
            action.label,
            maxLines: 1,
            softWrap: false,
            overflow: TextOverflow.ellipsis,
          );
    final scheme = Theme.of(context).colorScheme;
    return switch (action.role) {
      AppActionRole.cancel => OutlinedButton(
        key: action.buttonKey,
        onPressed: onPressed,
        child: child,
      ),
      AppActionRole.secondary => FilledButton.tonal(
        key: action.buttonKey,
        onPressed: onPressed,
        child: child,
      ),
      AppActionRole.primary => FilledButton(
        key: action.buttonKey,
        onPressed: onPressed,
        child: child,
      ),
      AppActionRole.destructive => FilledButton(
        key: action.buttonKey,
        onPressed: onPressed,
        style: FilledButton.styleFrom(
          backgroundColor: scheme.error,
          foregroundColor: scheme.onError,
        ),
        child: child,
      ),
    };
  }
}

/// Standard dialog: title, scrollable content, [ActionBar]. Use instead of `AlertDialog`.
///
/// Built on `Dialog` rather than `AlertDialog`, so content may use `LayoutBuilder` and the
/// buttons are laid out by [ActionBar] (no `OverflowBar` wrapping).
class AppDialog extends StatelessWidget {
  const AppDialog({
    super.key,
    required this.title,
    required this.content,
    required this.actions,
    this.maxWidth = 440,
  });

  final Widget title;
  final Widget content;
  final List<AppAction> actions;
  final double maxWidth;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Dialog(
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: maxWidth),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(24, 24, 24, 20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              DefaultTextStyle(
                style: theme.textTheme.headlineSmall ?? const TextStyle(),
                child: title,
              ),
              const SizedBox(height: 16),
              Flexible(
                child: SingleChildScrollView(
                  child: DefaultTextStyle(
                    style: theme.textTheme.bodyMedium ?? const TextStyle(),
                    child: content,
                  ),
                ),
              ),
              const SizedBox(height: 24),
              ActionBar(actions: actions),
            ],
          ),
        ),
      ),
    );
  }
}

/// Confirmation with a cancel and a confirm button. Resolves to `true` only on confirm.
Future<bool> confirmDialog(
  BuildContext context, {
  required String title,
  required String message,
  required String confirmLabel,
  String cancelLabel = 'Abbrechen',
  bool destructive = false,
  Key? confirmKey,
  Key? cancelKey,
}) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AppDialog(
      title: Text(title),
      content: Text(message),
      actions: [
        AppAction.cancel(
          label: cancelLabel,
          buttonKey: cancelKey,
          onPressed: () => Navigator.pop(ctx, false),
        ),
        AppAction(
          label: confirmLabel,
          buttonKey: confirmKey,
          role: destructive ? AppActionRole.destructive : AppActionRole.primary,
          onPressed: () => Navigator.pop(ctx, true),
        ),
      ],
    ),
  );
  return ok ?? false;
}

/// Standard bottom-sheet body: optional title, scrollable content and a pinned [ActionBar]
/// that stays above the keyboard. Open it with [showAppSheet].
class AppSheet extends StatelessWidget {
  const AppSheet({super.key, this.title, required this.child, this.actions});

  final String? title;
  final Widget child;
  final List<AppAction>? actions;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final actions = this.actions;
    return SafeArea(
      child: Padding(
        padding: EdgeInsets.fromLTRB(
          20,
          0,
          20,
          12 + MediaQuery.viewInsetsOf(context).bottom,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (title != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Text(title!, style: theme.textTheme.titleLarge),
              ),
            Flexible(child: SingleChildScrollView(child: child)),
            if (actions != null && actions.isNotEmpty) ...[
              const SizedBox(height: 16),
              ActionBar(actions: actions),
            ],
          ],
        ),
      ),
    );
  }
}

/// Shows [builder]'s widget (normally an [AppSheet]) as a modal bottom sheet.
Future<T?> showAppSheet<T>(BuildContext context, WidgetBuilder builder) =>
    showModalBottomSheet<T>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: builder,
    );

/// Two form fields side by side at equal width; stacked below [stackBelow] so neither field
/// is squeezed until its label or error text wraps.
class FieldRow extends StatelessWidget {
  const FieldRow({
    super.key,
    required this.first,
    required this.second,
    this.stackBelow = 300,
  });

  final Widget first;
  final Widget second;
  final double stackBelow;

  static const double gap = 12;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      if (constraints.maxWidth < stackBelow) {
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            first,
            const SizedBox(height: gap),
            second,
          ],
        );
      }
      return Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(child: first),
          const SizedBox(width: gap),
          Expanded(child: second),
        ],
      );
    },
  );
}

/// Latitude and longitude inputs as a [FieldRow].
class CoordinateFields extends StatelessWidget {
  const CoordinateFields({
    super.key,
    required this.latitude,
    required this.longitude,
    required this.latKey,
    required this.lonKey,
    this.onChanged,
    this.latError,
    this.lonError,
    this.keyboardType = const TextInputType.numberWithOptions(
      decimal: true,
      signed: true,
    ),
  });

  final TextEditingController latitude;
  final TextEditingController longitude;
  final Key latKey;
  final Key lonKey;
  final VoidCallback? onChanged;
  final String? latError;
  final String? lonError;
  final TextInputType keyboardType;

  @override
  Widget build(BuildContext context) => FieldRow(
    first: TextField(
      key: latKey,
      controller: latitude,
      keyboardType: keyboardType,
      onChanged: onChanged == null ? null : (_) => onChanged!(),
      decoration: InputDecoration(
        labelText: 'Breite',
        errorText: latError,
        errorMaxLines: 2,
      ),
    ),
    second: TextField(
      key: lonKey,
      controller: longitude,
      keyboardType: keyboardType,
      onChanged: onChanged == null ? null : (_) => onChanged!(),
      decoration: InputDecoration(
        labelText: 'Länge',
        errorText: lonError,
        errorMaxLines: 2,
      ),
    ),
  );
}
