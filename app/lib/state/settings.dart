import 'package:flutter/material.dart' show ThemeMode;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

const osmTileUrl = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
const topoTileUrl = 'https://tile.opentopomap.org/{z}/{x}/{y}.png';

bool isPublicTileServer(String url) =>
    url.contains('tile.openstreetmap.org') ||
    url.contains('opentopomap.org') ||
    url.contains('tile.osm.org');

enum BaseMap { osm, topo, custom }

class AppSettings {
  const AppSettings({
    this.nightMode = false,
    this.themeMode = ThemeMode.system,
    this.customTileUrl = '',
    this.baseMap = BaseMap.osm,
    this.radioId,
    this.radioOffsetDb = 0,
  });

  /// Red-on-black scheme that keeps night vision in the field.
  final bool nightMode;

  /// Light, dark or system appearance; the red night mode takes precedence.
  final ThemeMode themeMode;

  /// Own tile server, e.g. `https://tiles.example.org/{z}/{x}/{y}.png`.
  final String customTileUrl;
  final BaseMap baseMap;

  /// Selected radio profile for CAT S-meter readout (see `radioProfiles`), `null` = none.
  final String? radioId;

  /// Calibration offset added to the radio's S-meter level, in dB.
  final double radioOffsetDb;

  bool get hasCustomTiles => customTileUrl.trim().isNotEmpty;

  String get tileUrl => switch (baseMap) {
    BaseMap.osm => osmTileUrl,
    BaseMap.topo => topoTileUrl,
    BaseMap.custom => hasCustomTiles ? customTileUrl.trim() : osmTileUrl,
  };

  AppSettings copyWith({
    bool? nightMode,
    ThemeMode? themeMode,
    String? customTileUrl,
    BaseMap? baseMap,
    String? radioId,
    bool clearRadio = false,
    double? radioOffsetDb,
  }) => AppSettings(
    nightMode: nightMode ?? this.nightMode,
    themeMode: themeMode ?? this.themeMode,
    customTileUrl: customTileUrl ?? this.customTileUrl,
    baseMap: baseMap ?? this.baseMap,
    radioId: clearRadio ? null : (radioId ?? this.radioId),
    radioOffsetDb: radioOffsetDb ?? this.radioOffsetDb,
  );
}

class SettingsNotifier extends Notifier<AppSettings> {
  static const _night = 'foxgrid.night';
  static const _theme = 'foxgrid.themeMode';
  static const _tiles = 'foxgrid.tileUrl';
  static const _base = 'foxgrid.baseMap';
  static const _radio = 'foxgrid.radio';
  static const _radioOffset = 'foxgrid.radioOffset';

  late SharedPreferences _prefs;

  @override
  AppSettings build() {
    _prefs = ref.watch(sharedPrefsProvider);
    final base = _prefs.getString(_base);
    final theme = _prefs.getString(_theme);
    return AppSettings(
      nightMode: _prefs.getBool(_night) ?? false,
      themeMode: ThemeMode.values.firstWhere(
        (m) => m.name == theme,
        orElse: () => ThemeMode.system,
      ),
      customTileUrl: _prefs.getString(_tiles) ?? '',
      baseMap: BaseMap.values.firstWhere(
        (b) => b.name == base,
        orElse: () => BaseMap.osm,
      ),
      radioId: _prefs.getString(_radio),
      radioOffsetDb: _prefs.getDouble(_radioOffset) ?? 0,
    );
  }

  Future<void> setNight(bool v) async {
    state = state.copyWith(nightMode: v);
    await _prefs.setBool(_night, v);
  }

  Future<void> setThemeMode(ThemeMode m) async {
    state = state.copyWith(themeMode: m);
    await _prefs.setString(_theme, m.name);
  }

  Future<void> setCustomTileUrl(String v) async {
    state = state.copyWith(customTileUrl: v.trim());
    await _prefs.setString(_tiles, v.trim());
  }

  Future<void> setRadio(String? id) async {
    state = id == null
        ? state.copyWith(clearRadio: true)
        : state.copyWith(radioId: id);
    if (id == null) {
      await _prefs.remove(_radio);
    } else {
      await _prefs.setString(_radio, id);
    }
  }

  Future<void> setRadioOffset(double db) async {
    state = state.copyWith(radioOffsetDb: db);
    await _prefs.setDouble(_radioOffset, db);
  }

  Future<void> setBaseMap(BaseMap b) async {
    state = state.copyWith(baseMap: b);
    await _prefs.setString(_base, b.name);
  }
}

final sharedPrefsProvider = Provider<SharedPreferences>(
  (ref) => throw UnimplementedError('override in main()'),
);

final settingsProvider = NotifierProvider<SettingsNotifier, AppSettings>(
  SettingsNotifier.new,
);
