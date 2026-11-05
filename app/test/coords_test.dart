import 'package:flutter_test/flutter_test.dart';
import 'package:foxgrid/core/coords.dart';

void main() {
  double? lat(String s) => parseCoordinate(s, isLat: true);
  double? lon(String s) => parseCoordinate(s, isLat: false);

  test('decimal degrees with point or comma', () {
    expect(lat('50.9'), 50.9);
    expect(lat(' 50,9 '), 50.9);
    expect(lon('-6.9'), -6.9);
    expect(lon('+6.9'), 6.9);
  });

  test('hemisphere letters', () {
    expect(lat('50.9 N'), 50.9);
    expect(lat('50.9S'), -50.9);
    expect(lon('6.9 e'), 6.9);
    expect(lon('6.9 W'), -6.9);
    expect(lon('6.9 O'), 6.9);
  });

  test('degrees and decimal minutes', () {
    expect(lat("50° 54.5' N"), closeTo(50 + 54.5 / 60, 1e-9));
    expect(lat('50 54,5 N'), closeTo(50 + 54.5 / 60, 1e-9));
    expect(lon("6° 57.0' W"), closeTo(-(6 + 57 / 60), 1e-9));
  });

  test('degrees, minutes and seconds', () {
    expect(lat('50° 54\' 30" N'), closeTo(50 + 54 / 60 + 30 / 3600, 1e-9));
  });

  test('a negative value below one degree keeps its sign', () {
    expect(lon('-0 30'), closeTo(-0.5, 1e-9));
  });

  test('rejects what is not a coordinate', () {
    expect(lat(''), isNull);
    expect(lat('abc'), isNull);
    expect(lat('50.9.1'), isNull);
    expect(lat('50 N 6'), isNull);
    expect(lat('1 2 3 4'), isNull);
    expect(lat('50 61'), isNull);
    expect(lat("50 54 61"), isNull);
  });

  test('rejects the wrong axis, contradictions and out of range', () {
    expect(lat('50.9 E'), isNull);
    expect(lon('6.9 N'), isNull);
    expect(lat('-50.9 S'), isNull);
    expect(lat('90.1'), isNull);
    expect(lon('180.1'), isNull);
    expect(lat('90'), 90);
    expect(lon('-180'), -180);
  });

  test('formats degrees and decimal minutes', () {
    expect(formatCoordinate(50.9, isLat: true), "50° 54.000' N");
    expect(formatCoordinate(-6.95, isLat: false), "6° 57.000' W");
    expect(formatCoordinate(10.999999999, isLat: false), "11° 0.000' E");
    final back = parseCoordinate(
      formatCoordinate(48.137154, isLat: true),
      isLat: true,
    );
    expect(back, closeTo(48.137154, 1e-5));
  });
}
