import 'package:material_ui/material_ui.dart';

import '../core/signal.dart';
import '../state/settings.dart';

/// Colours for everything drawn on the map, matching day, dark and red night mode.
class MapPalette {
  const MapPalette._(this._mode);

  factory MapPalette.of(BuildContext context, AppSettings settings) =>
      MapPalette._(
        settings.nightMode
            ? _Mode.night
            : Theme.of(context).brightness == Brightness.dark
            ? _Mode.dark
            : _Mode.day,
      );

  final _Mode _mode;

  bool get isNight => _mode == _Mode.night;
  bool get isDark => _mode != _Mode.day;

  static const _day = [
    Colors.indigo,
    Colors.teal,
    Colors.deepOrange,
    Colors.purple,
    Colors.brown,
    Colors.blueGrey,
    Colors.pink,
    Colors.green,
  ];
  static final _dark = [
    Colors.indigo.shade200,
    Colors.teal.shade200,
    Colors.deepOrange.shade300,
    Colors.purple.shade200,
    Colors.amber.shade300,
    Colors.blueGrey.shade200,
    Colors.pink.shade200,
    Colors.green.shade300,
  ];
  // Red night mode: only red hues, told apart by brightness.
  static const _night = [
    Color(0xFFFF3B30),
    Color(0xFFFF6B60),
    Color(0xFFFF8A80),
    Color(0xFFD32F2F),
    Color(0xFFFF5252),
    Color(0xFFE57373),
    Color(0xFFFFA39A),
    Color(0xFFC62828),
  ];

  // One colour family per interferer slot. Participants keep their own colours while a mission
  // has a single interferer; with several, the family says *which* interferer, the shade how
  // strong the signal was.
  static const _interfererDay = [
    Color(0xFFD32F2F), // A red
    Color(0xFF1976D2), // B blue
    Color(0xFF2E7D32), // C green
    Color(0xFF7B1FA2), // D purple
    Color(0xFFEF6C00), // E orange
    Color(0xFF00838F), // F teal
  ];
  static const _interfererDark = [
    Color(0xFFFF8A80),
    Color(0xFF64B5F6),
    Color(0xFF81C784),
    Color(0xFFCE93D8),
    Color(0xFFFFB74D),
    Color(0xFF4DD0E1),
  ];
  // Red night mode: only red hues, told apart by brightness, dash pattern and the letter badge.
  static const _interfererNight = [
    Color(0xFFFF3B30),
    Color(0xFFFF8A80),
    Color(0xFFD32F2F),
    Color(0xFFFFA39A),
    Color(0xFFC62828),
    Color(0xFFFF5252),
  ];

  /// Colour family of interferer [slot] at full strength.
  Color interferer(int slot) {
    final list = switch (_mode) {
      _Mode.day => _interfererDay,
      _Mode.dark => _interfererDark,
      _Mode.night => _interfererNight,
    };
    return list[slot % list.length];
  }

  /// The family of [slot], shaded by field strength: weak readings are pale (day) or dim (dark
  /// and night), strong ones take the full colour. Without a reading: full colour.
  Color interfererSignal(
    int slot,
    double? dbm, {
    double min = -110,
    double max = -40,
  }) {
    final base = interferer(slot);
    if (dbm == null) return base;
    final t = ((dbm - min) / (max - min)).clamp(0.0, 1.0);
    final weak = isDark ? Colors.black : Colors.white;
    return Color.lerp(weak, base, 0.45 + 0.55 * t)!;
  }

  /// Dash pattern that tells interferers apart where colour cannot (red night mode): solid,
  /// dashed, dotted. Day and dark mode stay solid.
  List<double>? interfererDash(int slot) {
    if (!isNight) return null;
    return switch (slot % 3) {
      1 => const [12, 6],
      2 => const [3, 6],
      _ => null,
    };
  }

  Color participant(String id) {
    final list = switch (_mode) {
      _Mode.day => _day,
      _Mode.dark => _dark,
      _Mode.night => _night,
    };
    return list[id.hashCode.abs() % list.length];
  }

  /// The estimated interferer location (ellipses, marker).
  Color get estimate => switch (_mode) {
    _Mode.day => Colors.red,
    _Mode.dark => const Color(0xFFFF5252),
    _Mode.night => const Color(0xFFFF3B30),
  };

  /// Contour areas.
  Color get contour => switch (_mode) {
    _Mode.day => Colors.deepOrange,
    _Mode.dark => Colors.orange.shade300,
    _Mode.night => const Color(0xFFFF6B60),
  };

  Color get searchArea => isDark ? Colors.white70 : Colors.black54;
  Color get repeater => switch (_mode) {
    _Mode.day => Colors.deepPurple,
    _Mode.dark => Colors.deepPurple.shade200,
    _Mode.night => const Color(0xFFFF8A80),
  };
  Color get self => switch (_mode) {
    _Mode.day => Colors.blue,
    _Mode.dark => Colors.lightBlue.shade200,
    _Mode.night => const Color(0xFFFFB4AB),
  };
  Color get suggestion => switch (_mode) {
    _Mode.day => Colors.green.shade700,
    _Mode.dark => Colors.green.shade400,
    _Mode.night => const Color(0xFFB71C1C),
  };

  /// Label bubbles and badges on the map.
  Color get labelBackground => switch (_mode) {
    _Mode.day => Colors.white.withValues(alpha: 0.85),
    _Mode.dark => Colors.black.withValues(alpha: 0.75),
    _Mode.night => Colors.black.withValues(alpha: 0.85),
  };
  Color get labelText => switch (_mode) {
    _Mode.day => Colors.black,
    _Mode.dark => Colors.white,
    _Mode.night => const Color(0xFFFF6B60),
  };

  /// Outline of dots and badges.
  Color get outline => isNight ? const Color(0xFFFF6B60) : Colors.white;

  /// Field strength colour; the night mode uses a dark-to-bright red ramp.
  Color signal(double dbm, {double min = -110, double max = -40}) {
    if (!isNight) return rssiColor(dbm, min: min, max: max);
    final t = ((dbm - min) / (max - min)).clamp(0.0, 1.0);
    return Color.lerp(const Color(0xFF6B0000), const Color(0xFFFF8A80), t)!;
  }
}

enum _Mode { day, dark, night }
