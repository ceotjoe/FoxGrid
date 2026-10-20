import 'package:flutter_test/flutter_test.dart';
import 'package:foxgrid/core/geo.dart';
import 'package:foxgrid/core/models.dart';
import 'package:foxgrid/core/session.dart';
import 'package:foxgrid/state/providers.dart';
import 'package:latlong2/latlong.dart';

void main() {
  test('only the starter and the lead may stop a transmission', () {
    final tx = Transmission.fromJson({
      'id': 't1',
      'seq': 1,
      'started_at': '2026-01-01T10:00:00Z',
      'ended_at': null,
      'started_by': 'p1',
    });
    expect(tx.startedBy, 'p1');
    final s = MissionState(transmissions: [tx]);
    expect(s.canStopRunning('p1', 'mobile'), isTrue);
    expect(s.canStopRunning('p2', 'mobile'), isFalse);
    expect(s.canStopRunning('p2', 'fixed'), isFalse);
    expect(s.canStopRunning('p2', 'lead'), isTrue);
    expect(const MissionState().canStopRunning('p1', 'lead'), isFalse);
  });

  test('estimate parses GeoJSON ring as lat/lon', () {
    final e = Estimate.fromJson({
      'scope': 'all',
      'n_bearings': 3,
      'lat': 48.1,
      'lon': 11.5,
      'computed_at': '2026-01-01T10:00:00Z',
      'ellipse_1s': _ellipse(),
      'ellipse_2s': _ellipse(),
    });
    expect(e.ellipse1s.ring.first, const LatLng(48.0, 11.0));
    expect(e.point.latitude, 48.1);
  });

  test('invite parsing accepts tokens and links', () {
    expect(parseInvite('  abc ').token, 'abc');
    final link = inviteLink('http://10.0.2.2:8000', 'tok-1');
    final parsed = parseInvite(link);
    expect(parsed.token, 'tok-1');
    expect(parsed.server, 'http://10.0.2.2:8000');
  });

  test('azimuth helpers wrap over north', () {
    expect(magneticToTrue(358, 4), 2);
    expect(magneticToTrue(2, -4), 358);
    expect(normalizeAzimuth(-10), 350);
  });

  test('fan polygon opens at the station', () {
    const station = LatLng(48, 11);
    final fan = fanPolygon(station, 90, 10, 10000);
    expect(fan.first, station);
    expect(fan.length, 6);
    expect(distanceMeters(station, fan[3]), closeTo(10000, 50));
  });

  test('session derives websocket uri', () {
    const s = Session(
      baseUrl: 'https://fox.example',
      token: 'x',
      missionId: 'm',
      participantId: 'p',
      callsign: 'DL1ABC',
      role: 'lead',
    );
    expect(s.wsUri.toString(), 'wss://fox.example/ws/missions/m?token=x');
    expect(s.isLead, isTrue);
  });
}

Map<String, dynamic> _ellipse() => {
  'semi_major_m': 100.0,
  'semi_minor_m': 50.0,
  'orientation_deg': 10.0,
  'polygon': {
    'type': 'Polygon',
    'coordinates': [
      [
        [11.0, 48.0],
        [11.1, 48.0],
        [11.0, 48.0],
      ],
    ],
  },
};
