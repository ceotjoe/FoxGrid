import 'package:latlong2/latlong.dart';

const _distance = Distance();

/// Point [meters] away from [origin] along true azimuth [azimuthDeg].
LatLng destination(LatLng origin, double azimuthDeg, double meters) =>
    _distance.offset(origin, meters, azimuthDeg);

double distanceMeters(LatLng a, LatLng b) => _distance(a, b);

/// Wedge polygon covering azimuth ± [sigmaDeg] out to [meters]; the station is the apex.
List<LatLng> fanPolygon(
  LatLng station,
  double azimuthDeg,
  double sigmaDeg,
  double meters,
) => [
  station,
  for (final f in const [-1.0, -0.5, 0.0, 0.5, 1.0])
    destination(station, azimuthDeg + f * sigmaDeg, meters),
];

/// Converts a magnetic reading to true north.
/// [declinationDeg] is positive when magnetic north lies east of true north.
double magneticToTrue(double magneticDeg, double declinationDeg) =>
    normalizeAzimuth(magneticDeg + declinationDeg);

double normalizeAzimuth(double deg) => ((deg % 360) + 360) % 360;
