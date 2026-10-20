import 'package:latlong2/latlong.dart';

DateTime _time(Object? v) => DateTime.parse(v! as String).toUtc();
double? _d(Object? v) => (v as num?)?.toDouble();

/// The repeater the interferer is heard on. Fixed stations measure its *input* frequency.
class Repeater {
  const Repeater({required this.point, this.inputMhz, this.outputMhz});

  final LatLng point;
  final double? inputMhz;
  final double? outputMhz;

  factory Repeater.fromJson(Map<String, dynamic> j) => Repeater(
    point: LatLng(_d(j['lat'])!, _d(j['lon'])!),
    inputMhz: _d(j['input_mhz']),
    outputMhz: _d(j['output_mhz']),
  );

  Map<String, dynamic> toJson() => {
    'lat': point.latitude,
    'lon': point.longitude,
    'input_mhz': inputMhz,
    'output_mhz': outputMhz,
  };
}

class Mission {
  const Mission({
    required this.id,
    required this.name,
    required this.frequencyMhz,
    required this.status,
    this.searchArea,
    this.repeater,
  });

  final String id;
  final String name;
  final double frequencyMhz;
  final String status;
  final List<LatLng>? searchArea;
  final Repeater? repeater;

  Mission withRepeater(Repeater? value) => Mission(
    id: id,
    name: name,
    frequencyMhz: frequencyMhz,
    status: status,
    searchArea: searchArea,
    repeater: value,
  );

  Mission withStatus(String value) => Mission(
    id: id,
    name: name,
    frequencyMhz: frequencyMhz,
    status: value,
    searchArea: searchArea,
    repeater: repeater,
  );

  bool get isActive => status == 'active';

  factory Mission.fromJson(Map<String, dynamic> j) => Mission(
    id: j['id'] as String,
    name: j['name'] as String,
    frequencyMhz: _d(j['frequency_mhz'])!,
    status: j['status'] as String,
    searchArea: (j['search_area'] as List?)
        ?.map((p) => LatLng((p as List)[1] as double, p[0] as double))
        .toList(),
    repeater: j['repeater'] == null
        ? null
        : Repeater.fromJson(j['repeater'] as Map<String, dynamic>),
  );
}

class Participant {
  const Participant({
    required this.id,
    required this.callsign,
    required this.role,
    this.team,
    this.status = 'active',
    this.isActive = true,
    this.deviceBound = false,
    this.trusted = true,
    this.joinCode,
  });

  final String id;
  final String callsign;
  final String role;
  final String? team;

  /// 4 digits to compare by radio while the join is pending (own and lead view only).
  final String? joinCode;

  /// Only trusted participants' data moves the estimate; the rest is logged and shown.
  final bool trusted;

  /// `pending` (waiting for the lead), `active` or `rejected`.
  final String status;

  /// `false` once the lead removed the participant.
  final bool isActive;
  final bool deviceBound;

  bool get isPending => status == 'pending' && isActive;

  factory Participant.fromJson(Map<String, dynamic> j) => Participant(
    id: j['id'] as String,
    callsign: j['callsign'] as String,
    role: j['role'] as String,
    team: j['team'] as String?,
    status: j['status'] as String? ?? 'active',
    isActive: j['is_active'] as bool? ?? true,
    deviceBound: j['device_bound'] as bool? ?? false,
    trusted: j['trusted'] as bool? ?? true,
    joinCode: j['join_code'] as String?,
  );
}

/// One line of the lead's security log.
class AuditEntry {
  const AuditEntry({
    required this.id,
    required this.at,
    required this.action,
    required this.entity,
    this.actor,
    this.subject,
    this.detail = const {},
  });

  final int id;
  final DateTime at;
  final String action;
  final String entity;
  final String? actor;

  /// Callsign when the entry is about a participant.
  final String? subject;
  final Map<String, dynamic> detail;

  factory AuditEntry.fromJson(Map<String, dynamic> j) => AuditEntry(
    id: j['id'] as int,
    at: DateTime.parse(j['at'] as String),
    action: j['action'] as String,
    entity: j['entity'] as String,
    actor: j['actor'] as String?,
    subject: j['subject'] as String?,
    detail: (j['detail'] as Map?)?.cast<String, dynamic>() ?? const {},
  );
}

/// Outcome of a quarantine: how much the participant had contributed.
class QuarantineResult {
  const QuarantineResult({
    required this.participant,
    required this.bearings,
    required this.rssi,
  });

  final Participant participant;
  final int bearings;
  final int rssi;
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
    this.stationOffsetsDb = const {},
  });

  final double p0Dbm;
  final double exponent;
  final double residualDb;
  final int nSamples;

  /// Estimated receiver offset (dB) per fixed station, keyed by participant id.
  final Map<String, double> stationOffsetsDb;

  factory RssiFit.fromJson(Map<String, dynamic> j) => RssiFit(
    p0Dbm: _d(j['p0_dbm'])!,
    exponent: _d(j['exponent'])!,
    residualDb: _d(j['residual_db'])!,
    nSamples: j['n_samples'] as int,
    stationOffsetsDb: {
      for (final e in ((j['station_offsets_db'] as Map?) ?? const {}).entries)
        e.key as String: _d(e.value)!,
    },
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
    this.receiver = 'mobile',
    this.isCalibration = false,
  });

  final String id;
  final String participantId;
  final LatLng point;

  /// `mobile` = the moving homing device, `omni` = a fixed omnidirectional station.
  final String receiver;

  /// A reading of the repeater output (not the interferer) used to calibrate a station.
  final bool isCalibration;
  bool get isStation => receiver == 'omni';

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
    receiver: (j['receiver'] as String?) ?? 'mobile',
    isCalibration: (j['is_calibration'] as bool?) ?? false,
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

/// A place where one more bearing would shrink the error ellipse the most.
class Suggestion {
  const Suggestion({
    required this.point,
    required this.expectedReduction,
    required this.expectedSemiMajorM,
    required this.expectedSemiMinorM,
    required this.azimuthToTargetDeg,
    required this.distanceToTargetM,
  });

  final LatLng point;

  /// Share of the 1 sigma ellipse area that goes away, 0..1.
  final double expectedReduction;
  final double expectedSemiMajorM;
  final double expectedSemiMinorM;

  /// True bearing from that place to the current estimate.
  final double azimuthToTargetDeg;
  final double distanceToTargetM;

  factory Suggestion.fromJson(Map<String, dynamic> j) => Suggestion(
    point: LatLng(_d(j['lat'])!, _d(j['lon'])!),
    expectedReduction: _d(j['expected_reduction'])!,
    expectedSemiMajorM: _d(j['expected_semi_major_m'])!,
    expectedSemiMinorM: _d(j['expected_semi_minor_m'])!,
    azimuthToTargetDeg: _d(j['azimuth_to_target_deg'])!,
    distanceToTargetM: _d(j['distance_to_target_m'])!,
  );
}

/// An automatic station or repeater hook registered for the mission.
class SensorInfo {
  const SensorInfo({
    required this.id,
    required this.name,
    required this.kind,
    required this.callsign,
    required this.isActive,
    required this.online,
    required this.topicPrefix,
    this.lastSeenAt,
    this.point,
    this.apiKey,
  });

  final String id;
  final String name;

  /// `station` or `relay`.
  final String kind;
  final String callsign;
  final bool isActive;
  final bool online;
  final String topicPrefix;
  final DateTime? lastSeenAt;
  final LatLng? point;

  /// Only present right after creation: it is never shown again.
  final String? apiKey;

  bool get isRelay => kind == 'relay';

  factory SensorInfo.fromJson(Map<String, dynamic> j) => SensorInfo(
    id: j['id'] as String,
    name: j['name'] as String,
    kind: j['kind'] as String,
    callsign: j['callsign'] as String,
    isActive: j['is_active'] as bool,
    online: j['online'] as bool,
    topicPrefix: j['topic_prefix'] as String,
    lastSeenAt: j['last_seen_at'] == null ? null : _time(j['last_seen_at']),
    point: j['lat'] == null || j['lon'] == null
        ? null
        : LatLng(_d(j['lat'])!, _d(j['lon'])!),
    apiKey: j['api_key'] as String?,
  );
}
