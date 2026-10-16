import 'package:latlong2/latlong.dart';

DateTime _time(Object? v) => DateTime.parse(v! as String).toUtc();
double? _d(Object? v) => (v as num?)?.toDouble();

class Mission {
  const Mission({
    required this.id,
    required this.name,
    required this.frequencyMhz,
    required this.status,
    this.searchArea,
  });

  final String id;
  final String name;
  final double frequencyMhz;
  final String status;
  final List<LatLng>? searchArea;

  bool get isActive => status == 'active';

  factory Mission.fromJson(Map<String, dynamic> j) => Mission(
    id: j['id'] as String,
    name: j['name'] as String,
    frequencyMhz: _d(j['frequency_mhz'])!,
    status: j['status'] as String,
    searchArea: (j['search_area'] as List?)
        ?.map((p) => LatLng((p as List)[1] as double, p[0] as double))
        .toList(),
  );
}

class Participant {
  const Participant({
    required this.id,
    required this.callsign,
    required this.role,
    this.team,
  });

  final String id;
  final String callsign;
  final String role;
  final String? team;

  factory Participant.fromJson(Map<String, dynamic> j) => Participant(
    id: j['id'] as String,
    callsign: j['callsign'] as String,
    role: j['role'] as String,
    team: j['team'] as String?,
  );
}

class PositionFix {
  const PositionFix({
    required this.participantId,
    required this.point,
    required this.recordedAt,
    this.accuracyM,
    this.headingDeg,
  });

  final String participantId;
  final LatLng point;
  final DateTime recordedAt;
  final double? accuracyM;
  final double? headingDeg;

  factory PositionFix.fromJson(Map<String, dynamic> j) => PositionFix(
    participantId: j['participant_id'] as String,
    point: LatLng(_d(j['lat'])!, _d(j['lon'])!),
    recordedAt: _time(j['recorded_at']),
    accuracyM: _d(j['accuracy_m']),
    headingDeg: _d(j['heading_deg']),
  );
}

class Bearing {
  const Bearing({
    required this.id,
    required this.participantId,
    required this.station,
    required this.azimuthTrueDeg,
    required this.sigmaDeg,
    required this.measuredAt,
    required this.isOutlier,
    required this.isActive,
    this.transmissionId,
    this.rssiDbm,
    this.note,
  });

  final String id;
  final String participantId;
  final String? transmissionId;
  final LatLng station;
  final double azimuthTrueDeg;
  final double sigmaDeg;
  final DateTime measuredAt;
  final bool isOutlier;
  final bool isActive;
  final double? rssiDbm;
  final String? note;

  factory Bearing.fromJson(Map<String, dynamic> j) => Bearing(
    id: j['id'] as String,
    participantId: j['participant_id'] as String,
    transmissionId: j['transmission_id'] as String?,
    station: LatLng(_d(j['lat'])!, _d(j['lon'])!),
    azimuthTrueDeg: _d(j['azimuth_true_deg'])!,
    sigmaDeg: _d(j['sigma_deg'])!,
    measuredAt: _time(j['measured_at']),
    isOutlier: j['is_outlier'] as bool,
    isActive: j['is_active'] as bool,
    rssiDbm: _d(j['rssi_dbm']),
    note: j['note'] as String?,
  );
}

class Transmission {
  const Transmission({
    required this.id,
    required this.seq,
    required this.startedAt,
    this.endedAt,
  });

  final String id;
  final int seq;
  final DateTime startedAt;
  final DateTime? endedAt;

  bool get isRunning => endedAt == null;

  factory Transmission.fromJson(Map<String, dynamic> j) => Transmission(
    id: j['id'] as String,
    seq: j['seq'] as int,
    startedAt: _time(j['started_at']),
    endedAt: j['ended_at'] == null ? null : _time(j['ended_at']),
  );
}

class EllipseShape {
  const EllipseShape({
    required this.semiMajorM,
    required this.semiMinorM,
    required this.orientationDeg,
    required this.ring,
  });

  final double semiMajorM;
  final double semiMinorM;
  final double orientationDeg;
  final List<LatLng> ring;

  factory EllipseShape.fromJson(Map<String, dynamic> j) {
    final coords = ((j['polygon'] as Map)['coordinates'] as List).first as List;
    return EllipseShape(
      semiMajorM: _d(j['semi_major_m'])!,
      semiMinorM: _d(j['semi_minor_m'])!,
      orientationDeg: _d(j['orientation_deg'])!,
      ring: coords.map((p) => LatLng(_d((p as List)[1])!, _d(p[0])!)).toList(),
    );
  }
}

class Estimate {
  const Estimate({
    required this.scope,
    required this.nBearings,
    required this.point,
    required this.ellipse1s,
    required this.ellipse2s,
    required this.computedAt,
  });

  final String scope;
  final int nBearings;
  final LatLng point;
  final EllipseShape ellipse1s;
  final EllipseShape ellipse2s;
  final DateTime computedAt;

  factory Estimate.fromJson(Map<String, dynamic> j) => Estimate(
    scope: j['scope'] as String,
    nBearings: j['n_bearings'] as int,
    point: LatLng(_d(j['lat'])!, _d(j['lon'])!),
    ellipse1s: EllipseShape.fromJson(j['ellipse_1s'] as Map<String, dynamic>),
    ellipse2s: EllipseShape.fromJson(j['ellipse_2s'] as Map<String, dynamic>),
    computedAt: _time(j['computed_at']),
  );
}
