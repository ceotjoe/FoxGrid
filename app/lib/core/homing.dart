import 'dart:math';

import 'package:latlong2/latlong.dart';

const _distance = Distance();

/// Initial true bearing from [from] to [to] in degrees, 0..360.
double bearingTo(LatLng from, LatLng to) =>
    (_distance.bearing(from, to) + 360) % 360;

double distanceTo(LatLng from, LatLng to) => _distance(from, to);

/// Smallest signed difference `a - b` in degrees, -180..180.
double angleDiff(double a, double b) => ((a - b + 540) % 360) - 180;

/// True heading of the device.
///
/// While moving, the GPS course is the most reliable source; when standing still the
/// compass (magnetic) corrected with the declination is used.
double? chooseHeading({
  double? gpsCourse,
  double? speedMps,
  double? compassMagnetic,
  double declinationDeg = 0,
  double minSpeedMps = 1.5,
}) {
  if (gpsCourse != null && (speedMps ?? 0) >= minSpeedMps) {
    return (gpsCourse + 360) % 360;
  }
  if (compassMagnetic != null) {
    return (compassMagnetic + declinationDeg + 360) % 360;
  }
  if (gpsCourse != null) return (gpsCourse + 360) % 360;
  return null;
}

/// Human readable distance: `340 m`, `1.2 km`, `12 km`.
String formatDistance(double meters) {
  if (meters < 1000) return '${meters.round()} m';
  final km = meters / 1000;
  return km < 10 ? '${km.toStringAsFixed(1)} km' : '${km.round()} km';
}

class HomingGuidance {
  const HomingGuidance({
    required this.distanceM,
    required this.bearingDeg,
    required this.arrowDeg,
    required this.insideOneSigma,
    required this.insideTwoSigma,
  });

  final double distanceM;

  /// True bearing from the own position to the estimate.
  final double bearingDeg;

  /// Arrow rotation relative to the device (0 = straight ahead), -180..180.
  /// Equals [bearingDeg] when the heading is unknown (north-up arrow).
  final double arrowDeg;
  final bool insideOneSigma;
  final bool insideTwoSigma;
}

/// Guidance to the estimated emitter position; [headingDeg] may be null.
HomingGuidance guidance({
  required LatLng own,
  required LatLng target,
  required double semiMajor1sM,
  required double semiMajor2sM,
  double? headingDeg,
}) {
  final d = distanceTo(own, target);
  final b = bearingTo(own, target);
  return HomingGuidance(
    distanceM: d,
    bearingDeg: b,
    arrowDeg: headingDeg == null ? b : angleDiff(b, headingDeg),
    insideOneSigma: d <= semiMajor1sM,
    insideTwoSigma: d <= max(semiMajor2sM, semiMajor1sM),
  );
}
