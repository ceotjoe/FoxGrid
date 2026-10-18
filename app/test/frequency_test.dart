import 'package:flutter_test/flutter_test.dart';
import 'package:foxgrid/ui/join_screen.dart';

void main() {
  test('parses frequencies with decimal point or comma', () {
    expect(parseFrequencyMhz('145.500'), 145.5);
    expect(parseFrequencyMhz(' 433,5 '), 433.5);
    expect(parseFrequencyMhz(''), isNull);
    expect(parseFrequencyMhz('abc'), isNull);
  });

  test('accepts VHF, UHF and microwave, rejects nonsense', () {
    for (final mhz in [145.5, 433.5, 1296.0, 2320.0]) {
      expect(frequencyError(mhz), isNull, reason: '$mhz MHz');
    }
    expect(frequencyError(null), isNotNull);
    expect(frequencyError(0), isNotNull);
    expect(frequencyError(10000), isNotNull);
  });

  test('warns only below 30 MHz', () {
    expect(frequencyHint(7.1), isNotNull);
    expect(frequencyHint(29.6), isNotNull);
    expect(frequencyHint(30), isNull);
    expect(frequencyHint(145.5), isNull);
    expect(frequencyHint(null), isNull);
  });
}
