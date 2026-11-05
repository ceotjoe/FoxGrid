/// What a participant may do in a mission.
///
/// The server decides: every participant record carries `authority` and the effective
/// `permissions`, and the server refuses everything else. The app only uses them to show or hide
/// functions. The names are the server's (`backend/app/services/permissions.py`).
class Perm {
  const Perm._();

  static const viewResult = 'view.result';
  static const viewPositions = 'view.positions';
  static const chatRead = 'chat.read';
  static const chatWrite = 'chat.write';
  static const bearingCreate = 'bearing.create';
  static const bearingExternal = 'bearing.external';
  static const bearingFlag = 'bearing.flag';
  static const rssiSubmit = 'rssi.submit';
  static const positionShare = 'position.share';
  static const transmissionManage = 'transmission.manage';
  static const trustSet = 'trust.set';
  static const quarantine = 'quarantine';
  static const estimateConfigure = 'estimate.configure';
  static const pointManage = 'point.manage';
  static const taskManage = 'task.manage';
  static const taskWork = 'task.work';
  static const inviteCreate = 'invite.create';
  static const inviteManage = 'invite.manage';
  static const participantManage = 'participant.manage';
  static const sensorManage = 'sensor.manage';
  static const auditView = 'audit.view';
  static const roleAssign = 'role.assign';
  static const missionEnd = 'mission.end';
  static const export = 'export';
}

/// The roles a lead can hand out, in the order they are offered.
const assignableAuthorities = [
  'lead',
  'deputy',
  'analyst',
  'coordinator',
  'member',
  'observer',
];

String authorityLabel(String authority) => switch (authority) {
  'lead' => 'Einsatzleiter',
  'deputy' => 'Co-Leiter',
  'analyst' => 'Auswerter',
  'coordinator' => 'Koordinator',
  'member' => 'Peiler',
  'station' => 'Feststation',
  'observer' => 'Beobachter',
  _ => authority,
};

String authorityHint(String authority) => switch (authority) {
  'lead' => 'Alles, auch Rollen vergeben und Einsatz beenden',
  'deputy' => 'Wie die Leitung, aber ohne Rollen und Einsatzende',
  'analyst' => 'Bewertet Daten, trägt externe Peilungen ein',
  'coordinator' => 'Chat, Aufgaben, Einladungen',
  'member' => 'Peilt, chattet, erledigt Aufgaben',
  'observer' => 'Nur lesen: Karte und Ergebnis, kein Chat, keine Positionen',
  _ => '',
};

/// Permissions of a session or participant that came without any (an older server or a session
/// stored by an older app). Only used to decide what to show until the server sends the real list.
Set<String> legacyPermissions(String role) {
  const member = {
    Perm.viewResult,
    Perm.viewPositions,
    Perm.chatRead,
    Perm.chatWrite,
    Perm.bearingCreate,
    Perm.rssiSubmit,
    Perm.positionShare,
    Perm.taskWork,
    Perm.export,
  };
  if (role != 'lead') return member;
  return {
    ...member,
    Perm.bearingExternal,
    Perm.bearingFlag,
    Perm.transmissionManage,
    Perm.trustSet,
    Perm.quarantine,
    Perm.estimateConfigure,
    Perm.pointManage,
    Perm.taskManage,
    Perm.inviteCreate,
    Perm.inviteManage,
    Perm.participantManage,
    Perm.sensorManage,
    Perm.auditView,
    Perm.roleAssign,
    Perm.missionEnd,
  };
}
