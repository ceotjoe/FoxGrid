import 'radio.dart';

/// Icom CI-V: `FE FE <radio> <controller> 15 02 FD` asks for the S-meter,
/// the answer carries four BCD digits (0000..0255, 0120 = S9, 0241 = S9+60 dB).
class IcomCiv implements RadioProtocol {
  const IcomCiv({this.radioAddress = 0xA4, this.controllerAddress = 0xE0});

  final int radioAddress;
  final int controllerAddress;

  @override
  String get name => 'Icom CI-V';

  @override
  List<int> buildSignalQuery() => [
    0xFE,
    0xFE,
    radioAddress,
    controllerAddress,
    0x15,
    0x02,
    0xFD,
  ];

  @override
  ParseResult parse(List<int> buffer) {
    // Skip anything before the next preamble.
    final start = _indexOfPreamble(buffer);
    if (start < 0) {
      // keep a lone trailing FE: it may be the first byte of a preamble
      final keep = buffer.isNotEmpty && buffer.last == 0xFE ? 1 : 0;
      return ParseResult(consumed: buffer.length - keep);
    }
    if (start > 0) {
      return ParseResult(consumed: start);
    }
    final end = buffer.indexOf(0xFD);
    if (end < 0) {
      return const ParseResult(consumed: 0); // wait for the rest of the frame
    }
    final frame = buffer.sublist(0, end + 1);
    // Answer: FE FE <to=controller> <from=radio> 15 02 <bcd hi> <bcd lo> FD
    final isAnswer =
        frame.length == 9 &&
        frame[2] == controllerAddress &&
        frame[3] == radioAddress &&
        frame[4] == 0x15 &&
        frame[5] == 0x02;
    if (!isAnswer) {
      return ParseResult(consumed: end + 1); // echo of our own query etc.
    }
    final hi = frame[6];
    final lo = frame[7];
    final digits = [hi >> 4, hi & 0xF, lo >> 4, lo & 0xF];
    if (digits.any((d) => d > 9)) return ParseResult(consumed: end + 1);
    final raw = digits[0] * 1000 + digits[1] * 100 + digits[2] * 10 + digits[3];
    return ParseResult(consumed: end + 1, raw: raw);
  }

  static int _indexOfPreamble(List<int> b) {
    for (var i = 0; i + 1 < b.length; i++) {
      if (b[i] == 0xFE && b[i + 1] == 0xFE) return i;
    }
    return -1;
  }
}

/// Kenwood style ASCII CAT, also spoken by Yaesu: `SM0;` is answered by `SM0nnnn;`
/// (Kenwood 0000..0030) or `SM0nnn;` (Yaesu 000..255).
class AsciiSmeter implements RadioProtocol {
  const AsciiSmeter({this.label = 'Kenwood CAT'});

  final String label;

  @override
  String get name => label;

  @override
  List<int> buildSignalQuery() => 'SM0;'.codeUnits;

  @override
  ParseResult parse(List<int> buffer) {
    final end = buffer.indexOf(0x3B); // ';'
    if (end < 0) return const ParseResult(consumed: 0);
    final text = String.fromCharCodes(buffer.sublist(0, end));
    final m = RegExp(r'SM0(\d{3,4})$').firstMatch(text);
    return ParseResult(
      consumed: end + 1,
      raw: m == null ? null : int.parse(m.group(1)!),
    );
  }
}

/// Built-in radio profiles. Raw scales are approximations; the calibration offset in the
/// settings compensates for individual radios.
const radioProfiles = <RadioProfile>[
  RadioProfile(
    id: 'icom-ic705',
    name: 'Icom IC-705',
    protocol: IcomCiv(radioAddress: 0xA4),
    scale: RawScale(s9Raw: 120, plus60Raw: 241),
    baudRate: 19200,
  ),
  RadioProfile(
    id: 'icom-ic9700',
    name: 'Icom IC-9700',
    protocol: IcomCiv(radioAddress: 0xA2),
    scale: RawScale(s9Raw: 120, plus60Raw: 241),
    baudRate: 19200,
  ),
  RadioProfile(
    id: 'kenwood-th-d74',
    name: 'Kenwood (SM0, 0..30)',
    protocol: AsciiSmeter(),
    scale: RawScale(s9Raw: 15, plus60Raw: 30),
    baudRate: 9600,
  ),
  RadioProfile(
    id: 'yaesu-ft991a',
    name: 'Yaesu FT-991A (SM0, 0..255)',
    protocol: AsciiSmeter(label: 'Yaesu CAT'),
    scale: RawScale(s9Raw: 130, plus60Raw: 255),
    baudRate: 38400,
  ),
];
