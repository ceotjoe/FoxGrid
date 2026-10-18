import 'package:flutter_test/flutter_test.dart';
import 'package:foxgrid/ui/join_screen.dart';

void main() {
  test('release builds accept https only', () {
    expect(
      serverUrlError('https://fox.example.org', releaseMode: true),
      isNull,
    );
    expect(
      serverUrlError('http://fox.example.org', releaseMode: true),
      isNotNull,
    );
    expect(
      serverUrlError('http://10.0.2.2:8000', releaseMode: true),
      isNotNull,
    );
  });

  test('debug builds also accept http for the dev stack', () {
    expect(serverUrlError('http://localhost:8000', releaseMode: false), isNull);
  });

  test('rejects empty or hostless input', () {
    expect(serverUrlError('', releaseMode: false), isNotNull);
    expect(serverUrlError('foxgrid', releaseMode: false), isNotNull);
    expect(serverUrlError('ftp://x.org', releaseMode: false), isNotNull);
  });
}
