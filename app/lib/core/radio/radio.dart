import 'dart:async';

/// A raw signal strength reading with its calibrated level.
class SignalReading {
  const SignalReading({
    required this.dbm,
    required this.at,
    required this.source,
  });

  final double dbm;
  final DateTime at;
  final String source;
}

/// Byte pipe to a radio (USB OTG serial, Bluetooth SPP, ...). Platform plugins implement this;
/// the protocol and calibration code below does not care which one is used.
abstract class RadioTransport {
  Future<void> open();

  Future<void> write(List<int> bytes);

  Stream<List<int>> get input;

  Future<void> close();
}

/// Result of feeding received bytes to a protocol parser.
class ParseResult {
  const ParseResult({required this.consumed, this.raw});

  /// Bytes to drop from the front of the receive buffer.
  final int consumed;

  /// Raw S-meter value if a complete answer was found.
  final int? raw;
}

/// CAT dialect of a radio family.
abstract class RadioProtocol {
  String get name;

  /// Bytes that ask the radio for its current S-meter value.
  List<int> buildSignalQuery();

  /// Looks for an S-meter answer at the start of [buffer].
  ParseResult parse(List<int> buffer);
}

/// Raw S-meter scale of a radio: where S9 and S9+60 dB sit in the raw range.
class RawScale {
  const RawScale({required this.s9Raw, required this.plus60Raw});

  final int s9Raw;
  final int plus60Raw;

  /// Piecewise linear: S0..S9 (-147..-93 dBm, 6 dB per S unit), then S9..S9+60 dB.
  double toDbm(int raw, {double offsetDb = 0}) {
    final r = raw.toDouble();
    final dbm = r <= s9Raw
        ? -147.0 + r * 54.0 / s9Raw
        : -93.0 + (r - s9Raw) * 60.0 / (plus60Raw - s9Raw);
    return dbm + offsetDb;
  }
}

/// A radio model: protocol, scale and defaults for the serial link.
class RadioProfile {
  const RadioProfile({
    required this.id,
    required this.name,
    required this.protocol,
    required this.scale,
    this.baudRate = 19200,
  });

  final String id;
  final String name;
  final RadioProtocol protocol;
  final RawScale scale;
  final int baudRate;
}

/// Polls a radio over a [RadioTransport] and emits calibrated readings.
class RadioSignalSource {
  RadioSignalSource({
    required this.transport,
    required this.profile,
    this.offsetDb = 0,
    DateTime Function()? clock,
  }) : _clock = clock ?? DateTime.now;

  final RadioTransport transport;
  final RadioProfile profile;

  /// Per radio calibration offset (antenna, cable, S-meter tolerance).
  final double offsetDb;
  final DateTime Function() _clock;

  final _controller = StreamController<SignalReading>.broadcast();
  final List<int> _buffer = [];
  StreamSubscription<List<int>>? _sub;
  Timer? _timer;

  Stream<SignalReading> get readings => _controller.stream;

  /// Opens the link and asks the radio every [interval].
  Future<void> start({Duration interval = const Duration(seconds: 1)}) async {
    await transport.open();
    _sub = transport.input.listen(_onBytes);
    _timer = Timer.periodic(interval, (_) => poll());
    await poll();
  }

  Future<void> poll() => transport.write(profile.protocol.buildSignalQuery());

  void _onBytes(List<int> bytes) {
    _buffer.addAll(bytes);
    // Drain the buffer; garbage and echoed commands are skipped by the parser.
    while (_buffer.isNotEmpty) {
      final r = profile.protocol.parse(_buffer);
      if (r.consumed <= 0) break;
      _buffer.removeRange(0, r.consumed);
      final raw = r.raw;
      if (raw != null) {
        _controller.add(
          SignalReading(
            dbm: profile.scale.toDbm(raw, offsetDb: offsetDb),
            at: _clock().toUtc(),
            source: profile.name,
          ),
        );
      }
    }
    if (_buffer.length > 256) {
      _buffer.clear(); // never grow without bound on noise
    }
  }

  Future<void> stop() async {
    _timer?.cancel();
    await _sub?.cancel();
    await transport.close();
  }

  Future<void> dispose() async {
    await stop();
    await _controller.close();
  }
}
