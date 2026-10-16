import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:foxgrid/core/radio/protocols.dart';
import 'package:foxgrid/core/radio/radio.dart';

/// Radio simulator: answers S-meter queries like the real protocols do.
class LoopbackTransport implements RadioTransport {
  LoopbackTransport(this.answer);

  /// Maps a written query to the bytes the radio sends back (possibly several chunks).
  final List<List<int>> Function(List<int> query) answer;
  final _in = StreamController<List<int>>.broadcast();
  final written = <List<int>>[];
  bool opened = false;
  bool closed = false;

  @override
  Future<void> open() async => opened = true;

  @override
  Future<void> write(List<int> bytes) async {
    written.add(bytes);
    for (final chunk in answer(bytes)) {
      scheduleMicrotask(() => _in.add(chunk));
    }
  }

  @override
  Stream<List<int>> get input => _in.stream;

  @override
  Future<void> close() async => closed = true;

  void inject(List<int> bytes) => _in.add(bytes);
}

List<int> icomAnswer(int raw, {int radio = 0xA4}) {
  final d = [raw ~/ 1000, raw ~/ 100 % 10, raw ~/ 10 % 10, raw % 10];
  return [
    0xFE,
    0xFE,
    0xE0,
    radio,
    0x15,
    0x02,
    d[0] << 4 | d[1],
    d[2] << 4 | d[3],
    0xFD,
  ];
}

void main() {
  group('Icom CI-V', () {
    const icom = IcomCiv();

    test('builds the S-meter query', () {
      expect(icom.buildSignalQuery(), [
        0xFE,
        0xFE,
        0xA4,
        0xE0,
        0x15,
        0x02,
        0xFD,
      ]);
      expect(const IcomCiv(radioAddress: 0xA2).buildSignalQuery()[2], 0xA2);
    });

    test('parses the BCD answer', () {
      final r = icom.parse(icomAnswer(120));
      expect(r.raw, 120);
      expect(r.consumed, 9);
      expect(icom.parse(icomAnswer(241)).raw, 241);
      expect(icom.parse(icomAnswer(0)).raw, 0);
    });

    test('skips the echo of our own query', () {
      final echo = icom.buildSignalQuery();
      final r = icom.parse([...echo, ...icomAnswer(77)]);
      expect(r.raw, isNull);
      expect(r.consumed, echo.length);
    });

    test('waits for incomplete frames and drops garbage', () {
      final frame = icomAnswer(55);
      expect(icom.parse(frame.sublist(0, 5)).consumed, 0);
      final junk = icom.parse([0x01, 0x02, 0x03, ...frame]);
      expect(junk.consumed, 3);
      expect(icom.parse([0x01, 0x02]).consumed, 2);
      expect(
        icom.parse([0x01, 0xFE]).consumed,
        1,
      ); // keeps a possible preamble start
    });

    test('rejects non-BCD digits and other commands', () {
      final bad = icomAnswer(0)..[6] = 0xAB;
      expect(icom.parse(bad).raw, isNull);
      final other = icomAnswer(10)..[4] = 0x14;
      expect(icom.parse(other).raw, isNull);
    });
  });

  group('ASCII CAT', () {
    const kenwood = AsciiSmeter();

    test('query and answers', () {
      expect(String.fromCharCodes(kenwood.buildSignalQuery()), 'SM0;');
      expect(kenwood.parse('SM00015;'.codeUnits).raw, 15);
      expect(kenwood.parse('SM0128;'.codeUnits).raw, 128);
      expect(kenwood.parse('SM0128'.codeUnits).consumed, 0); // incomplete
      final other = kenwood.parse('FA00433500000;'.codeUnits);
      expect(other.raw, isNull);
      expect(other.consumed, 14);
      expect(kenwood.name, 'Kenwood CAT');
      expect(const AsciiSmeter(label: 'Yaesu CAT').name, 'Yaesu CAT');
    });
  });

  group('calibration', () {
    test('raw values map onto dBm piecewise-linearly', () {
      const icom = RawScale(s9Raw: 120, plus60Raw: 241);
      expect(icom.toDbm(0), -147);
      expect(icom.toDbm(120), closeTo(-93, 1e-9));
      expect(icom.toDbm(241), closeTo(-33, 1e-9));
      expect(icom.toDbm(60), closeTo(-120, 1e-9));
      expect(icom.toDbm(120, offsetDb: -3), closeTo(-96, 1e-9));
      const kenwood = RawScale(s9Raw: 15, plus60Raw: 30);
      expect(kenwood.toDbm(15), closeTo(-93, 1e-9));
      expect(kenwood.toDbm(30), closeTo(-33, 1e-9));
    });

    test('profiles are consistent', () {
      final ids = radioProfiles.map((p) => p.id).toSet();
      expect(ids.length, radioProfiles.length);
      for (final p in radioProfiles) {
        expect(p.protocol.buildSignalQuery(), isNotEmpty);
        expect(p.scale.plus60Raw, greaterThan(p.scale.s9Raw));
        expect(p.baudRate, greaterThan(0));
      }
    });
  });

  group('RadioSignalSource', () {
    test('polls an Icom and emits calibrated readings', () async {
      final profile = radioProfiles.firstWhere((p) => p.id == 'icom-ic705');
      final transport = LoopbackTransport((q) {
        // real radios echo the command, then answer; split across two chunks
        final answer = icomAnswer(120);
        return [q, answer.sublist(0, 4), answer.sublist(4)];
      });
      final source = RadioSignalSource(
        transport: transport,
        profile: profile,
        offsetDb: 2,
        clock: () => DateTime.utc(2026, 1, 1),
      );
      final readings = <SignalReading>[];
      source.readings.listen(readings.add);
      await source.start(interval: const Duration(milliseconds: 20));
      await Future<void>.delayed(const Duration(milliseconds: 70));
      await source.dispose();

      expect(transport.opened, isTrue);
      expect(transport.closed, isTrue);
      expect(transport.written.first, profile.protocol.buildSignalQuery());
      expect(readings.length, greaterThanOrEqualTo(2));
      expect(readings.first.dbm, closeTo(-91, 1e-9)); // S9 + 2 dB offset
      expect(readings.first.source, 'Icom IC-705');
      expect(readings.first.at, DateTime.utc(2026, 1, 1));
    });

    test('works with ASCII CAT and ignores noise', () async {
      final profile = radioProfiles.firstWhere((p) => p.id == 'kenwood-th-d74');
      final transport = LoopbackTransport((_) => ['SM00030;'.codeUnits]);
      final source = RadioSignalSource(transport: transport, profile: profile);
      final readings = <SignalReading>[];
      source.readings.listen(readings.add);
      await source.start(interval: const Duration(seconds: 5));
      transport.inject([0x00, 0xFF, 0x13]); // line noise without a terminator
      transport.inject('XX;'.codeUnits);
      await Future<void>.delayed(const Duration(milliseconds: 20));
      await source.dispose();
      expect(readings.single.dbm, closeTo(-33, 1e-9)); // full scale = S9+60
    });

    test('the receive buffer cannot grow without bound', () async {
      final profile = radioProfiles.firstWhere((p) => p.id == 'kenwood-th-d74');
      final transport = LoopbackTransport((_) => const []);
      final source = RadioSignalSource(transport: transport, profile: profile);
      await source.start(interval: const Duration(seconds: 5));
      for (var i = 0; i < 40; i++) {
        transport.inject(List.filled(20, 0x41)); // never a ';'
      }
      await Future<void>.delayed(const Duration(milliseconds: 10));
      transport.inject('SM00015;'.codeUnits);
      final r = await source.readings.first.timeout(
        const Duration(milliseconds: 200),
      );
      expect(r.dbm, closeTo(-93, 1e-9));
      await source.dispose();
    });
  });
}
