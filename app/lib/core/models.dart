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
    this.speedMps,
  });

  final String participantId;
  final LatLng point;
  final DateTime recordedAt;
  final double? accuracyM;
  final double? headingDeg;
  final double? speedMps;

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
    this.local = false,
  });

  final String id;
  final int seq;
  final DateTime startedAt;
  final DateTime? endedAt;

  /// Created on this device and not yet confirmed by the server.
  final bool local;

  Transmission copyWith({DateTime? endedAt}) => Transmission(
    id: id,
    seq: seq,
    startedAt: startedAt,
    endedAt: endedAt ?? this.endedAt,
    local: local,
  );

  bool get isRunning => endedAt == null;

  factory Transmission.fromJson(Map<String, dynamic> j) => Transmission(
    id: j['id'] as String,
    seq: j['seq'] as int,
    startedAt: _time(j['started_at']),
    endedAt: j['ended_at'] == null ? null : _time(j['ended_at']),
  );
}

/// Path loss model fitted by the server: `level = p0 - 10 * n * log10(distance_m)`.
class RssiFit {
  const RssiFit({
    required this.p0Dbm,
    required this.exponent,
    required this.residualDb,
    required this.nSamples,
  });

  final double p0Dbm;
  final double exponent;
  final double residualDb;
  final int nSamples;

  factory RssiFit.fromJson(Map<String, dynamic> j) => RssiFit(
    p0Dbm: _d(j['p0_dbm'])!,
    exponent: _d(j['exponent'])!,
    residualDb: _d(j['residual_db'])!,
    nSamples: j['n_samples'] as int,
  );
}

/// One signal strength reading of the homing track.
class RssiSample {
  const RssiSample({
    required this.id,
    required this.participantId,
    required this.point,
    required this.rssiDbm,
    required this.measuredAt,
    this.attenuationDb = 0,
    this.pending = false,
  });

  final String id;
  final String participantId;
  final LatLng point;

  /// As read from the receiver.
  final double rssiDbm;
  final double attenuationDb;
  final DateTime measuredAt;
  final bool pending;

  /// Level at the antenna: the attenuator reduced what the receiver saw.
  double get correctedDbm => rssiDbm + attenuationDb;

  factory RssiSample.fromJson(Map<String, dynamic> j) => RssiSample(
    id: j['id'] as String,
    participantId: (j['participant_id'] as String?) ?? '',
    point: LatLng(_d(j['lat'])!, _d(j['lon'])!),
    rssiDbm: _d(j['rssi_dbm'])!,
    attenuationDb: _d(j['attenuation_db']) ?? 0,
    measuredAt: _time(j['measured_at']),
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
    this.contours = const {},
    this.rssi,
  });

  final String scope;
  final int nBearings;
  final LatLng point;
  final EllipseShape ellipse1s;
  final EllipseShape ellipse2s;
  final DateTime computedAt;

  /// Probability mass in percent ("50", "80", "95") -> closed rings.
  final Map<String, List<List<LatLng>>> contours;

  /// Present when the RSSI track contributed to the estimate.
  final RssiFit? rssi;

  factory Estimate.fromJson(Map<String, dynamic> j) => Estimate(
    rssi: j['rssi'] == null
        ? null
        : RssiFit.fromJson(j['rssi'] as Map<String, dynamic>),
    contours: {
      for (final e in ((j['contours'] as Map?) ?? const {}).entries)
        e.key as String: [
          for (final poly in e.value as List)
            [
              for (final p
                  in ((poly as Map)['coordinates'] as List).first as List)
                LatLng(_d((p as List)[1])!, _d(p[0])!),
            ],
        ],
    },
    scope: j['scope'] as String,
    nBearings: j['n_bearings'] as int,
    point: LatLng(_d(j['lat'])!, _d(j['lon'])!),
    ellipse1s: EllipseShape.fromJson(j['ellipse_1s'] as Map<String, dynamic>),
    ellipse2s: EllipseShape.fromJson(j['ellipse_2s'] as Map<String, dynamic>),
    computedAt: _time(j['computed_at']),
  );
}

class Team {
  const Team({required this.id, required this.name});

  final String id;
  final String name;

  factory Team.fromJson(Map<String, dynamic> j) =>
      Team(id: j['id'] as String, name: j['name'] as String);
}

class ChatMessage {
  const ChatMessage({
    required this.id,
    required this.authorId,
    required this.authorCallsign,
    required this.body,
    required this.sentAt,
    this.teamId,
    this.pending = false,
  });

  final String id;
  final String authorId;
  final String authorCallsign;
  final String? teamId;
  final String body;
  final DateTime sentAt;

  /// Still in the offline queue.
  final bool pending;

  factory ChatMessage.fromJson(Map<String, dynamic> j) => ChatMessage(
    id: j['id'] as String,
    authorId: j['author_id'] as String,
    authorCallsign: j['author_callsign'] as String,
    teamId: j['team_id'] as String?,
    body: j['body'] as String,
    sentAt: _time(j['sent_at']),
  );
}

class TaskItem {
  const TaskItem({
    required this.id,
    required this.title,
    required this.status,
    required this.createdBy,
    this.description,
    this.assigneeParticipantId,
    this.assigneeTeamId,
    this.pending = false,
  });

  final String id;
  final String title;
  final String? description;
  final String status;
  final String createdBy;
  final String? assigneeParticipantId;
  final String? assigneeTeamId;
  final bool pending;

  TaskItem copyWith({
    String? title,
    String? status,
    String? assigneeParticipantId,
    String? assigneeTeamId,
    bool clearAssignee = false,
    bool? pending,
  }) => TaskItem(
    id: id,
    title: title ?? this.title,
    description: description,
    status: status ?? this.status,
    createdBy: createdBy,
    assigneeParticipantId: clearAssignee
        ? assigneeParticipantId
        : (assigneeParticipantId ?? this.assigneeParticipantId),
    assigneeTeamId: clearAssignee
        ? assigneeTeamId
        : (assigneeTeamId ?? this.assigneeTeamId),
    pending: pending ?? this.pending,
  );

  factory TaskItem.fromJson(Map<String, dynamic> j) => TaskItem(
    id: j['id'] as String,
    title: j['title'] as String,
    description: j['description'] as String?,
    status: j['status'] as String,
    createdBy: j['created_by'] as String,
    assigneeParticipantId: j['assignee_participant_id'] as String?,
    assigneeTeamId: j['assignee_team_id'] as String?,
  );
}
