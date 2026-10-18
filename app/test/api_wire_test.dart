import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:foxgrid/core/api.dart';
import 'package:foxgrid/core/outbox.dart';
import 'package:foxgrid/core/session.dart';

/// Records what actually goes over the wire.
class _Capture implements HttpClientAdapter {
  RequestOptions? options;
  String? body;

  @override
  void close({bool force = false}) {}

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    this.options = options;
    if (requestStream != null) {
      final bytes = <int>[];
      await for (final chunk in requestStream) {
        bytes.addAll(chunk);
      }
      body = utf8.decode(bytes);
    }
    return ResponseBody.fromString(
      '{}',
      200,
      headers: {
        'content-type': ['application/json'],
      },
    );
  }
}

OutboxEntry _entry(String method, Object? body) => OutboxEntry(
  id: 1,
  missionId: 'm',
  kind: 'x',
  method: method,
  path: '/api/v1/missions/m/rssi',
  bodyJson: body == null ? null : jsonEncode(body),
  createdAt: DateTime.utc(2026),
  attempts: 0,
  nextAttemptAt: DateTime.utc(2026),
  status: 'pending',
);

void main() {
  const session = Session(
    baseUrl: 'http://server',
    token: 't',
    missionId: 'm',
    participantId: 'p',
    callsign: 'DL1ABC',
    role: 'fixed',
  );

  Future<_Capture> send(String method, Object? body) async {
    final capture = _Capture();
    final api = DioFoxGridApi(
      session: session,
      dio: Dio()..httpClientAdapter = capture,
    );
    await api.sendQueued(_entry(method, body));
    return capture;
  }

  test('a list body goes out as JSON, not as Dart toString', () async {
    final c = await send('POST', [
      {'id': 'a', 'receiver': 'omni', 'rssi_dbm': -93.0},
    ]);
    expect(c.options!.contentType, startsWith('application/json'));
    expect(jsonDecode(c.body!), [
      {'id': 'a', 'receiver': 'omni', 'rssi_dbm': -93.0},
    ]);
  });

  test('a map body is still JSON', () async {
    final c = await send('PATCH', {
      'repeater': {'lat': 48.2},
    });
    expect(jsonDecode(c.body!), {
      'repeater': {'lat': 48.2},
    });
  });

  test('a request without body sends none', () async {
    final c = await send('POST', null);
    expect(c.body, isNull);
  });
}
