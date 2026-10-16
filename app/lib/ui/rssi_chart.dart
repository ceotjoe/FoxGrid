import 'package:flutter/material.dart';

import '../core/signal.dart';

/// Line chart of the last signal levels (oldest left), coloured like the track dots.
class RssiChart extends StatelessWidget {
  const RssiChart({super.key, required this.levels});

  /// Levels in dBm at the antenna, oldest first.
  final List<double> levels;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return SizedBox(
      key: const Key('rssi-chart'),
      height: 120,
      child: CustomPaint(
        painter: _ChartPainter(
          levels: levels,
          axisColor: theme.colorScheme.outline,
          textStyle:
              theme.textTheme.labelSmall ?? const TextStyle(fontSize: 11),
          lineColor: theme.colorScheme.primary,
        ),
        child: const SizedBox.expand(),
      ),
    );
  }
}

class _ChartPainter extends CustomPainter {
  _ChartPainter({
    required this.levels,
    required this.axisColor,
    required this.textStyle,
    required this.lineColor,
  });

  final List<double> levels;
  final Color axisColor;
  final TextStyle textStyle;
  final Color lineColor;

  void _label(Canvas canvas, String text, Offset at, {bool right = false}) {
    final tp = TextPainter(
      text: TextSpan(
        text: text,
        style: textStyle.copyWith(color: axisColor),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    canvas.drawCanvasText(tp, right ? at - Offset(tp.width, 0) : at);
  }

  @override
  void paint(Canvas canvas, Size size) {
    const left = 40.0;
    final plot = Rect.fromLTWH(
      left,
      6,
      size.width - left - 6,
      size.height - 12,
    );
    final axis = Paint()
      ..color = axisColor.withValues(alpha: 0.5)
      ..strokeWidth = 1;
    canvas.drawRect(plot, axis..style = PaintingStyle.stroke);
    if (levels.length < 2) {
      _label(canvas, 'Noch keine Messwerte', plot.center - const Offset(50, 6));
      return;
    }
    final (lo, hi) = levelRange(levels);
    double y(double v) => plot.bottom - (v - lo) / (hi - lo) * plot.height;
    double x(int i) => plot.left + i / (levels.length - 1) * plot.width;
    _label(
      canvas,
      '${hi.round()}',
      Offset(left - 4, plot.top - 2),
      right: true,
    );
    _label(
      canvas,
      '${lo.round()}',
      Offset(left - 4, plot.bottom - 10),
      right: true,
    );

    final path = Path()..moveTo(x(0), y(levels.first));
    for (var i = 1; i < levels.length; i++) {
      path.lineTo(x(i), y(levels[i]));
    }
    canvas.drawPath(
      path,
      Paint()
        ..color = lineColor
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2,
    );
    for (var i = 0; i < levels.length; i++) {
      canvas.drawCircle(
        Offset(x(i), y(levels[i])),
        3,
        Paint()..color = rssiColor(levels[i], min: lo, max: hi),
      );
    }
  }

  @override
  bool shouldRepaint(_ChartPainter old) =>
      old.levels != levels || old.lineColor != lineColor;
}

extension on Canvas {
  void drawCanvasText(TextPainter tp, Offset at) => tp.paint(this, at);
}
