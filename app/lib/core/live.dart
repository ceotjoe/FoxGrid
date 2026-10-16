import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/web_socket_channel.dart';

enum LiveStatus { connecting, connected, reconnecting }

typedef ChannelFactory = WebSocketChannel Function(Uri uri);

/// WebSocket connection with automatic reconnect (exponential backoff, max 15 s).
class LiveClient {
  LiveClient({
    required this.uri,
    required this.onEvent,
    required this.onStatus,
    ChannelFactory? connect,
  }) : _connect = connect ?? WebSocketChannel.connect;

  final Uri uri;
  final void Function(Map<String, dynamic> event) onEvent;
  final void Function(LiveStatus status) onStatus;
  final ChannelFactory _connect;

  WebSocketChannel? _channel;
  Timer? _retry;
  Timer? _ping;
  int _attempt = 0;
  bool _closed = false;

  void start() {
    onStatus(_attempt == 0 ? LiveStatus.connecting : LiveStatus.reconnecting);
    try {
      final ch = _connect(uri);
      _channel = ch;
      ch.ready
          .then((_) {
            if (_closed) return;
            _attempt = 0;
            onStatus(LiveStatus.connected);
            _ping = Timer.periodic(
              const Duration(seconds: 25),
              (_) => send({'type': 'ping'}),
            );
          })
          .catchError((Object _) {
            // handled by the stream's onError/onDone
          });
      ch.stream.listen(
        (data) {
          try {
            final decoded = jsonDecode(data as String);
            if (decoded is Map<String, dynamic>) onEvent(decoded);
          } on FormatException {
            // ignore malformed frames
          }
        },
        onError: (Object _) => _scheduleReconnect(),
        onDone: _scheduleReconnect,
        cancelOnError: true,
      );
    } on Object {
      _scheduleReconnect();
    }
  }

  void send(Map<String, dynamic> message) {
    if (_closed) return;
    try {
      _channel?.sink.add(jsonEncode(message));
    } on Object {
      // a dead socket is handled by the reconnect logic
    }
  }

  void _scheduleReconnect() {
    if (_closed || (_retry?.isActive ?? false)) return;
    _ping?.cancel();
    _channel = null;
    onStatus(LiveStatus.reconnecting);
    final seconds = (1 << _attempt).clamp(1, 15);
    _attempt = (_attempt + 1).clamp(0, 4);
    _retry = Timer(Duration(seconds: seconds), () {
      _retry = null;
      start();
    });
  }

  void close() {
    _closed = true;
    _retry?.cancel();
    _ping?.cancel();
    _channel?.sink.close();
  }
}
