import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:foxgrid/state/settings.dart';
import 'package:foxgrid/ui/map_palette.dart';

/// The palette needs a BuildContext only to read the brightness.
Future<MapPalette> _palette(
  WidgetTester tester, {
  Brightness brightness = Brightness.light,
  bool night = false,
}) async {
  late MapPalette pal;
  await tester.pumpWidget(
    MaterialApp(
      theme: ThemeData(brightness: brightness),
      home: Builder(
        builder: (context) {
          pal = MapPalette.of(context, AppSettings(nightMode: night));
          return const SizedBox();
        },
      ),
    ),
  );
  return pal;
}

void main() {
  testWidgets('the six interferer colours differ in every mode', (
    tester,
  ) async {
    for (final (b, n) in [
      (Brightness.light, false),
      (Brightness.dark, false),
      (Brightness.light, true),
    ]) {
      final pal = await _palette(tester, brightness: b, night: n);
      final colors = {for (var s = 0; s < 6; s++) pal.interferer(s).toARGB32()};
      expect(colors, hasLength(6), reason: 'brightness $b night $n');
    }
  });

  testWidgets('night mode stays in red hues', (tester) async {
    final pal = await _palette(tester, night: true);
    for (var s = 0; s < 6; s++) {
      for (final dbm in [null, -100.0, -50.0]) {
        final c = pal.interfererSignal(s, dbm);
        expect(c.r, greaterThanOrEqualTo(c.g), reason: 'slot $s');
        expect(c.r, greaterThanOrEqualTo(c.b), reason: 'slot $s');
      }
    }
    // dash patterns tell the slots apart where colour cannot
    expect(pal.interfererDash(0), isNull);
    expect(pal.interfererDash(1), isNotNull);
    expect(pal.interfererDash(2), isNotNull);
    expect(pal.interfererDash(1), isNot(pal.interfererDash(2)));
  });

  testWidgets('weak readings are paler than strong ones by day', (
    tester,
  ) async {
    final pal = await _palette(tester);
    final strong = pal.interfererSignal(1, -40);
    final weak = pal.interfererSignal(1, -110);
    expect(strong.toARGB32(), pal.interferer(1).toARGB32());
    expect(
      weak.r + weak.g + weak.b,
      greaterThan(strong.r + strong.g + strong.b),
    );
    expect(pal.interfererSignal(1, null).toARGB32(), strong.toARGB32());
    expect(pal.interfererDash(1), isNull); // day mode stays solid
  });
}
