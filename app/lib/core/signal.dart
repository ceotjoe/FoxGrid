import 'dart:math';

import 'package:flutter/painting.dart';

/// IARU Region 1 recommendation for VHF and above: S9 = -93 dBm, 6 dB per S unit.
/// (HF uses -73 dBm for S9; FoxGrid is built for VHF/UHF, the create form warns below 30 MHz.)
const s9Dbm = -93.0;
const dbPerSUnit = 6.0;

/// Converts an S-meter reading to dBm. [s] is 0..9; [over] adds "S9+X" dB.
double sMeterToDbm(int s, {int over = 0}) {
  final unit = s.clamp(0, 9);
  return s9Dbm - (9 - unit) * dbPerSUnit + over;
}

/// Human readable S value: `S7`, `S9+20`.
String dbmToSLabel(double dbm) {
  if (dbm > s9Dbm + 0.5) return 'S9+${(dbm - s9Dbm).round()}';
  final s = (9 - (s9Dbm - dbm) / dbPerSUnit).round().clamp(0, 9);
  return 'S$s';
}

/// A reading that can be logged with one tap.
class QuickReading {
  const QuickReading(this.label, this.dbm);

  final String label;
  final double dbm;
}

final quickReadings = <QuickReading>[
  for (final s in [1, 3, 5, 7, 9]) QuickReading('S$s', sMeterToDbm(s)),
  for (final over in [10, 20, 30, 40, 60])
    QuickReading('S9+$over', sMeterToDbm(9, over: over)),
];

/// Attenuator steps offered in the homing screen.
const attenuatorSteps = [0, 10, 20, 30, 40];

/// Maps a level to blue (weak) .. red (strong) for the track dots.
Color rssiColor(double dbm, {double min = -110, double max = -40}) {
  final t = ((dbm - min) / (max - min)).clamp(0.0, 1.0);
  // hue 240 (blue) -> 0 (red) through cyan, green and yellow
  return HSVColor.fromAHSV(1, 240 - 240 * t, 0.85, 0.95).toColor();
}

/// Range for colouring: min/max of the (corrected) samples with a minimum span of 20 dB.
(double, double) levelRange(Iterable<double> levels) {
  if (levels.isEmpty) return (-110, -40);
  final lo = levels.reduce(min);
  final hi = levels.reduce(max);
  if (hi - lo >= 20) return (lo, hi);
  final mid = (hi + lo) / 2;
  return (mid - 10, mid + 10);
}
