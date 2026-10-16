import 'package:flutter/painting.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:foxgrid/core/homing.dart';
import 'package:foxgrid/core/models.dart';
import 'package:foxgrid/core/signal.dart';
import 'package:latlong2/latlong.dart';

void main() {
  group('S-meter', () {
    test('S9 is -93 dBm with 6 dB per S unit (VHF/UHF)', () {
      expect(sMeterToDbm(9), -93);
      expect(sMeterToDbm(8), -99);
      expect(sMeterToDbm(1), -141);
      expect(sMeterToDbm(9, over: 20), -73);
      expect(sMeterToDbm(15), -93); // clamped
      expect(sMeterToDbm(-3), -147);
    });

    test('labels round trip', () {
      expect(dbmToSLabel(-93), 'S9');
      expect(dbmToSLabel(-73), 'S9+20');
      expect(dbmToSLabel(-117), 'S5');
      expect(dbmToSLabel(-160), 'S0');
      for (final q in quickReadings) {
        expect(dbmToSLabel(q.dbm), q.label);
      }
    });

    test('quick readings are ordered from weak to strong', () {
      final dbm = quickReadings.map((q) => q.dbm).toList();
      expect(dbm, [...dbm]..sort());
      expect(quickReadings.first.label, 'S1');
      expect(quickReadings.last.label, 'S9+60');
    });

    test('colour runs from blue (weak) to red (strong)', () {
      final weak = HSVColor.fromColor(rssiColor(-120));
      final strong = HSVColor.fromColor(rssiColor(-30));
      expect(weak.hue, closeTo(240, 1));
      expect(strong.hue, closeTo(0, 1));
      final (lo, hi) = levelRange([-80, -78]);
      expect(hi - lo, 20); // never a degenerate range
      expect(levelRange(const []), (-110.0, -40.0));
      expect(levelRange([-100, -50]), (-100.0, -50.0));
    });
  });

  group('homing', () {
    const own = LatLng(48.0, 11.0);

    test('bearing and distance to a target due east', () {
      const target = LatLng(48.0, 11.01);
      expect(bearingTo(own, target), closeTo(90, 0.2));
      expect(distanceTo(own, target), closeTo(745, 5));
      expect(bearingTo(target, own), closeTo(270, 0.2));
    });

    test('angle difference wraps over north', () {
      expect(angleDiff(10, 350), 20);
      expect(angleDiff(350, 10), -20);
      expect(angleDiff(180, 0).abs(), 180);
    });

    test('arrow is relative to the heading', () {
      const target = LatLng(48.01, 11.0); // due north
      final g = guidance(
        own: own,
        target: target,
        semiMajor1sM: 100,
        semiMajor2sM: 200,
        headingDeg: 90, // facing east: the target is 90 deg to the left
      );
      expect(g.bearingDeg, closeTo(0, 0.5));
      expect(g.arrowDeg, closeTo(-90, 0.5));
      expect(g.insideOneSigma, isFalse);
      expect(g.distanceM, closeTo(1112, 10));
    });

    test('without a heading the arrow is north-up', () {
      final g = guidance(
        own: own,
        target: const LatLng(48.0, 11.01),
        semiMajor1sM: 100,
        semiMajor2sM: 200,
      );
      expect(g.arrowDeg, closeTo(90, 0.5));
    });

    test('inside the error ellipse is reported', () {
      final near = guidance(
        own: own,
        target: const LatLng(48.0005, 11.0),
        semiMajor1sM: 80,
        semiMajor2sM: 160,
      );
      expect(near.insideOneSigma, isTrue);
      final mid = guidance(
        own: own,
        target: const LatLng(48.0012, 11.0),
        semiMajor1sM: 80,
        semiMajor2sM: 160,
      );
      expect(mid.insideOneSigma, isFalse);
      expect(mid.insideTwoSigma, isTrue);
    });

    test(
      'heading: GPS course while moving, compass plus declination when still',
      () {
        expect(
          chooseHeading(
            gpsCourse: 120,
            speedMps: 5,
            compassMagnetic: 100,
            declinationDeg: 4,
          ),
          120,
        );
        expect(
          chooseHeading(
            gpsCourse: 120,
            speedMps: 0.2,
            compassMagnetic: 100,
            declinationDeg: 4,
          ),
          104,
        );
        expect(chooseHeading(compassMagnetic: 358, declinationDeg: 5), 3);
        expect(chooseHeading(gpsCourse: 45, speedMps: 0), 45);
        expect(chooseHeading(), isNull);
      },
    );

    test('distances are formatted for the field', () {
      expect(formatDistance(340.4), '340 m');
      expect(formatDistance(1234), '1.2 km');
      expect(formatDistance(12500), '13 km');
    });
  });

  group('RSSI models', () {
    test('sample parses and exposes the corrected level', () {
      final s = RssiSample.fromJson({
        'id': 'r1',
        'participant_id': 'p1',
        'lat': 48.1,
        'lon': 11.5,
        'rssi_dbm': -90.0,
        'attenuation_db': 20,
        'measured_at': '2026-01-01T10:00:00Z',
      });
      expect(s.correctedDbm, -70);
      expect(s.point, const LatLng(48.1, 11.5));
    });

    test('estimate carries the path loss fit', () {
      final fit = RssiFit.fromJson({
        'p0_dbm': -20.5,
        'exponent': 2.8,
        'residual_db': 3.1,
        'n_samples': 40,
      });
      expect(fit.exponent, 2.8);
      expect(fit.nSamples, 40);
    });
  });
}
