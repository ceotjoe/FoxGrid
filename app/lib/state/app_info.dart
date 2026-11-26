import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:package_info_plus/package_info_plus.dart';

/// Version and build number of the running app, from `pubspec.yaml` (`version: x.y.z+build`).
class AppVersion {
  const AppVersion(this.version, this.build);

  final String version;
  final String build;

  /// German label shown in the UI, e.g. "Version 0.7.0 (Build 12)".
  String get label =>
      build.isEmpty ? 'Version $version' : 'Version $version (Build $build)';
}

final appVersionProvider = FutureProvider<AppVersion>((ref) async {
  final info = await PackageInfo.fromPlatform();
  return AppVersion(info.version, info.buildNumber);
});
