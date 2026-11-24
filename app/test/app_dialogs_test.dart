import 'package:material_ui/material_ui.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:foxgrid/ui/app_dialogs.dart';
import 'package:foxgrid/ui/app_theme.dart';

Widget _host(Widget child, {double width = 360, double scale = 1}) =>
    MaterialApp(
      theme: withAppStyle(ThemeData(useMaterial3: true)),
      home: MediaQuery(
        data: MediaQueryData(
          size: Size(width, 800),
          textScaler: TextScaler.linear(scale),
        ),
        child: Scaffold(
          body: Center(
            child: SizedBox(width: width, child: child),
          ),
        ),
      ),
    );

ActionBar _bar() => ActionBar(
  actions: [
    AppAction.cancel(buttonKey: const Key('cancel'), onPressed: () {}),
    AppAction(
      label: 'Speichern',
      buttonKey: const Key('save'),
      onPressed: () {},
    ),
  ],
);

void main() {
  for (final width in [320.0, 360.0, 411.0]) {
    for (final scale in [1.0, 1.5]) {
      testWidgets(
        'ActionBar buttons are equal and unwrapped at $width/$scale',
        (tester) async {
          await tester.pumpWidget(_host(_bar(), width: width, scale: scale));
          final cancel = tester.getSize(find.byKey(const Key('cancel')));
          final save = tester.getSize(find.byKey(const Key('save')));
          expect(cancel.height, save.height);
          expect(cancel.height, closeTo(kButtonHeight, 0.01));
          // Side by side: equal width. Stacked: both span the bar.
          expect(cancel.width, closeTo(save.width, 0.01));
          // A single line of text: the button is not taller than its minimum.
          expect(tester.takeException(), isNull);
        },
      );
    }
  }

  testWidgets('ActionBar stacks long labels instead of wrapping', (
    tester,
  ) async {
    await tester.pumpWidget(
      _host(
        ActionBar(
          actions: [
            AppAction.cancel(buttonKey: const Key('cancel'), onPressed: () {}),
            AppAction(
              label: 'Quarantäne und entfernen',
              buttonKey: const Key('save'),
              onPressed: () {},
            ),
          ],
        ),
        width: 320,
      ),
    );
    final cancel = tester.getRect(find.byKey(const Key('cancel')));
    final save = tester.getRect(find.byKey(const Key('save')));
    expect(save.top, lessThan(cancel.top)); // main action on top
    expect(save.height, closeTo(kButtonHeight, 0.01));
  });

  testWidgets('confirmDialog resolves on confirm and cancel', (tester) async {
    bool? result;
    await tester.pumpWidget(
      MaterialApp(
        theme: withAppStyle(ThemeData(useMaterial3: true)),
        home: Builder(
          builder: (context) => TextButton(
            onPressed: () async => result = await confirmDialog(
              context,
              title: 'Beenden?',
              message: 'Wirklich?',
              confirmLabel: 'Beenden',
              destructive: true,
              confirmKey: const Key('ok'),
            ),
            child: const Text('open'),
          ),
        ),
      ),
    );
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('ok')));
    await tester.pumpAndSettle();
    expect(result, isTrue);

    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Abbrechen'));
    await tester.pumpAndSettle();
    expect(result, isFalse);
  });

  testWidgets('FieldRow stacks when narrow', (tester) async {
    Widget row(double w) => _host(
      FieldRow(
        first: const TextField(key: Key('a')),
        second: const TextField(key: Key('b')),
      ),
      width: w,
    );
    await tester.pumpWidget(row(400));
    expect(
      tester.getTopLeft(find.byKey(const Key('a'))).dy,
      tester.getTopLeft(find.byKey(const Key('b'))).dy,
    );
    await tester.pumpWidget(row(260));
    expect(
      tester.getTopLeft(find.byKey(const Key('b'))).dy,
      greaterThan(tester.getTopLeft(find.byKey(const Key('a'))).dy),
    );
  });
}
