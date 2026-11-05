/// Parses one coordinate as typed by a person.
///
/// Accepted: decimal degrees (`50.9`, `50,9`, `-6.9`, `50.9 N`, `6.9 W`), degrees with decimal
/// minutes (`50° 54.5' N`, `50 54,5 N`) and degrees, minutes, seconds (`50° 54' 30" N`).
/// A hemisphere letter (N/S for latitude, E/W/O for longitude; O is German "Ost") makes the
/// value negative for S and W. Returns `null` for anything else, for a hemisphere that does not
/// fit the axis, for a sign that contradicts the hemisphere and for values out of range.
double? parseCoordinate(String text, {required bool isLat}) {
  var s = text.trim().toUpperCase();
  if (s.isEmpty) return null;

  final hemis = RegExp('[NSEWO]').allMatches(s).toList();
  if (hemis.length > 1) return null;
  var negativeHemi = false;
  if (hemis.isNotEmpty) {
    final m = hemis.single;
    // Only at the very start or end: "50 N 6" is not a coordinate.
    if (m.start != 0 && m.end != s.length) return null;
    final h = m.group(0)!;
    final fits = isLat ? (h == 'N' || h == 'S') : (h != 'N' && h != 'S');
    if (!fits) return null;
    negativeHemi = h == 'S' || h == 'W';
    s = s.replaceFirst(h, ' ');
  }

  s = s.replaceAll(RegExp('[°º′´`\'’″"]'), ' ').replaceAll(',', '.').trim();
  final parts = s.split(RegExp(r'\s+'));
  if (parts.isEmpty || parts.length > 3) return null;

  final negativeSign = parts.first.startsWith('-');
  final numbers = <double>[];
  for (var i = 0; i < parts.length; i++) {
    final raw = i == 0 ? parts[i].replaceFirst(RegExp('^[-+]'), '') : parts[i];
    if (!RegExp(r'^\d+(\.\d*)?$|^\.\d+$').hasMatch(raw)) return null;
    numbers.add(double.parse(raw));
  }
  if (negativeSign && negativeHemi) return null;
  if (numbers.length > 1 && numbers[1] >= 60) return null;
  if (numbers.length > 2 && numbers[2] >= 60) return null;

  var value = numbers[0];
  if (numbers.length > 1) value += numbers[1] / 60;
  if (numbers.length > 2) value += numbers[2] / 3600;
  if (negativeSign || negativeHemi) value = -value;
  return value.abs() <= (isLat ? 90 : 180) ? value : null;
}

/// Degrees with decimal minutes for display, e.g. `50° 54.500' N`.
String formatCoordinate(double value, {required bool isLat}) {
  final hemi = isLat ? (value < 0 ? 'S' : 'N') : (value < 0 ? 'W' : 'E');
  final abs = value.abs();
  var deg = abs.floor();
  var min = double.parse(((abs - deg) * 60).toStringAsFixed(3));
  if (min >= 60) {
    deg += 1;
    min = 0;
  }
  return '$deg° ${min.toStringAsFixed(3)}\' $hemi';
}
