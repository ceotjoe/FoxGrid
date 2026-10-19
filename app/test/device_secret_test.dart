import 'package:flutter_test/flutter_test.dart';
import 'package:foxgrid/core/device_secret.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  test('generates a long random secret once and keeps it', () async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    final first = deviceSecret(prefs);
    expect(first.length, greaterThanOrEqualTo(16));
    expect(deviceSecret(prefs), first);
  });

  test('two installations get different secrets', () async {
    SharedPreferences.setMockInitialValues({});
    final a = deviceSecret(await SharedPreferences.getInstance());
    SharedPreferences.setMockInitialValues({});
    final b = deviceSecret(await SharedPreferences.getInstance());
    expect(a, isNot(b));
  });
}
