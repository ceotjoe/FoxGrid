import 'dart:math' as math;

import 'package:material_ui/material_ui.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app_dialogs.dart';
import 'app_tile_layer.dart';
import 'interferers_screen.dart';
import 'map_palette.dart';
import '../core/geo.dart';
import '../core/models.dart';
import '../core/permissions.dart';
import '../state/providers.dart';

/// Gate state of a bearing as the filter and the list show it (ADR 0010).
enum GateFilter {
  counted('Zählt'),
  stored('Nur gespeichert'),
  included('Manuell gezählt'),
  excluded('Manuell ausgeschlossen');

  const GateFilter(this.label);
  final String label;

  bool matches(Bearing b) => switch (this) {
    GateFilter.counted => b.gateCounts,
    GateFilter.stored => b.gateState == 'outside' && b.gateOverride == null,
    GateFilter.included => b.gateOverride == true,
    GateFilter.excluded => b.gateOverride == false,
  };
}

/// Short German state of one bearing for the list.
String gateLabel(Bearing b) {
  if (b.gateOverride == true) return 'manuell gezählt';
  if (b.gateOverride == false) return 'manuell ausgeschlossen';
  if (b.gateState == 'outside') return 'außerhalb Aussendung';
  if (b.gateState == 'inside') return 'in Aussendung';
  return 'zählt';
}

String _hms(DateTime t) {
  final l = t.toLocal();
  String two(int v) => v.toString().padLeft(2, '0');
  return '${two(l.hour)}:${two(l.minute)}:${two(l.second)}';
}

/// *Peilungen verwalten*: many (sensor) bearings at once. A timeline of azimuth over time,
/// filters, a selection and bulk actions: assign an interferer, count, do not count, back to
/// automatic. Every action shows the selected rays on a map before it is applied.
///
/// Works on the bearings the app already holds (snapshot plus live events), so it also works
/// offline; the actions go through the outbox like every other write.
class ManageBearingsScreen extends ConsumerStatefulWidget {
  const ManageBearingsScreen({super.key});

  @override
  ConsumerState<ManageBearingsScreen> createState() =>
      _ManageBearingsScreenState();
}

class _ManageBearingsScreenState extends ConsumerState<ManageBearingsScreen> {
  bool _sensorsOnly = true;
  final _sensors = <String>{}; // sensor ids; empty = all
  final _interferers = <String>{}; // empty = all
  final _states = <GateFilter>{}; // empty = all
  final _selected = <String>{};

  List<Bearing> _filtered(MissionState state) {
    final list = [
      for (final b in state.bearings.values)
        if ((!_sensorsOnly || b.sensorId != null) &&
            (_sensors.isEmpty || _sensors.contains(b.sensorId)) &&
            (_interferers.isEmpty || _interferers.contains(b.interfererId)) &&
            (_states.isEmpty || _states.any((s) => s.matches(b))))
          b,
    ]..sort((a, b) => a.measuredAt.compareTo(b.measuredAt));
    return list;
  }

  /// Sensors that sent bearings, with the callsign of their virtual participant.
  Map<String, String> _sensorNames(MissionState state) => {
    for (final b in state.bearings.values)
      if (b.sensorId != null)
        b.sensorId!: state.participants[b.participantId]?.callsign ?? 'Station',
  };

  void _selectRange(List<Bearing> shown, DateTime from, DateTime to) {
    setState(() {
      _selected
        ..clear()
        ..addAll([
          for (final b in shown)
            if (!b.measuredAt.isBefore(from) && !b.measuredAt.isAfter(to)) b.id,
        ]);
    });
  }

  void _selectTransmission(List<Bearing> shown, Transmission t) {
    // The same slack the server uses to decide "inside".
    const slack = Duration(seconds: 5);
    _selectRange(
      shown,
      t.startedAt.subtract(slack),
      (t.endedAt ?? DateTime.now().toUtc()).add(slack),
    );
  }

  Future<void> _act(
    String title,
    List<Bearing> chosen, {
    String? interfererId,
    bool setGate = false,
    bool? gate,
  }) async {
    if (chosen.isEmpty) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AppDialog(
        maxWidth: 560,
        title: Text('${chosen.length} Peilungen: $title'),
        content: _Preview(bearings: chosen),
        actions: [
          AppAction.cancel(onPressed: () => Navigator.pop(ctx, false)),
          AppAction(
            label: 'Anwenden',
            buttonKey: const Key('bulk-apply'),
            onPressed: () => Navigator.pop(ctx, true),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    await ref
        .read(missionProvider.notifier)
        .bulkUpdateBearings(
          [for (final b in chosen) b.id],
          interfererId: interfererId,
          setGate: setGate,
          gate: gate,
        );
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('${chosen.length} Peilungen: $title')),
    );
  }

  Future<void> _assign(List<Bearing> chosen) async {
    final state = ref.read(missionProvider);
    final target = await showModalBottomSheet<String>(
      context: context,
      builder: (ctx) => AppSheet(
        title: 'Störer zuweisen',
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            for (final i in state.activeInterferers)
              ListTile(
                key: Key('bulk-interferer-${i.id}'),
                leading: InterfererBadge(i),
                title: Text(i.name),
                onTap: () => Navigator.pop(ctx, i.id),
              ),
          ],
        ),
      ),
    );
    if (target == null) return;
    final name = state.interferers[target]?.name ?? 'Störer';
    await _act('$name zuweisen', chosen, interfererId: target);
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(missionProvider);
    final session = ref.watch(sessionProvider);
    final settings = ref.watch(settingsProvider);
    final pal = MapPalette.of(context, settings);
    final theme = Theme.of(context);
    final shown = _filtered(state);
    final shownIds = {for (final b in shown) b.id};
    _selected.retainWhere(state.bearings.containsKey);
    final chosen = [
      for (final b in shown)
        if (_selected.contains(b.id)) b,
    ];
    final hidden = _selected.length - chosen.length;
    final gateable = [
      for (final b in chosen)
        if (b.sensorId != null) b,
    ];
    final canGate = session?.can(Perm.bearingFlag) ?? false;
    final canAssign = session?.can(Perm.interfererManage) ?? false;
    final sensorNames = _sensorNames(state);

    Color colorOf(Bearing b) {
      final i = state.interferers[b.interfererId];
      return i == null
          ? theme.colorScheme.outline
          : pal.interferer(i.colorSlot);
    }

    return Scaffold(
      appBar: AppBar(
        title: const Text('Peilungen verwalten'),
        actions: [
          IconButton(
            key: const Key('select-all'),
            tooltip: 'Alle gezeigten auswählen',
            icon: const Icon(Icons.select_all),
            onPressed: () => setState(() => _selected.addAll(shownIds)),
          ),
          IconButton(
            key: const Key('select-none'),
            tooltip: 'Auswahl aufheben',
            icon: const Icon(Icons.deselect),
            onPressed: _selected.isEmpty
                ? null
                : () => setState(_selected.clear),
          ),
        ],
      ),
      body: Column(
        children: [
          // A Row in a scroll view (not a lazy list): there are only a few chips.
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            child: Row(
              children: [
                _chip(
                  'Nur Stationen',
                  _sensorsOnly,
                  (v) => setState(() => _sensorsOnly = v),
                  key: const Key('filter-sensors-only'),
                ),
                for (final e in sensorNames.entries)
                  _chip(
                    e.value,
                    _sensors.contains(e.key),
                    (v) => setState(
                      () => v ? _sensors.add(e.key) : _sensors.remove(e.key),
                    ),
                    icon: Icons.sensors,
                  ),
                for (final i in state.interferers.values)
                  _chip(
                    '${i.letter} ${i.name}',
                    _interferers.contains(i.id),
                    (v) => setState(
                      () => v
                          ? _interferers.add(i.id)
                          : _interferers.remove(i.id),
                    ),
                    color: pal.interferer(i.colorSlot),
                  ),
                for (final s in GateFilter.values)
                  _chip(
                    s.label,
                    _states.contains(s),
                    (v) =>
                        setState(() => v ? _states.add(s) : _states.remove(s)),
                    key: Key('filter-${s.name}'),
                  ),
              ],
            ),
          ),
          if (state.transmissions.isNotEmpty)
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 8),
              child: Row(
                children: [
                  for (final t in state.transmissions)
                    Padding(
                      padding: const EdgeInsets.only(right: 6),
                      child: ActionChip(
                        key: Key('select-tx-${t.seq}'),
                        avatar: const Icon(Icons.podcasts, size: 16),
                        label: Text(
                          '#${t.seq} ${_hms(t.startedAt)}–'
                          '${t.endedAt == null ? 'läuft' : _hms(t.endedAt!)}',
                        ),
                        onPressed: () => _selectTransmission(shown, t),
                      ),
                    ),
                ],
              ),
            ),
          SizedBox(
            height: 180,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(8, 4, 8, 4),
              child: _Timeline(
                bearings: shown,
                transmissions: state.transmissions,
                selected: _selected,
                colorOf: colorOf,
                onRange: (from, to) => _selectRange(shown, from, to),
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    '${shown.length} Peilungen · ${chosen.length} ausgewählt'
                    '${hidden > 0 ? ' (+$hidden ausgeblendet)' : ''}',
                    key: const Key('bulk-summary'),
                    style: theme.textTheme.bodySmall,
                  ),
                ),
                Text(
                  'Zeitbereich ziehen wählt aus',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: theme.colorScheme.outline,
                  ),
                ),
              ],
            ),
          ),
          const Divider(height: 1),
          Expanded(
            child: shown.isEmpty
                ? const Center(
                    child: Padding(
                      padding: EdgeInsets.all(24),
                      child: Text(
                        'Keine Peilungen für diese Filter.',
                        key: Key('bulk-empty'),
                      ),
                    ),
                  )
                : ListView.builder(
                    itemCount: shown.length,
                    itemExtent: 64,
                    itemBuilder: (_, index) {
                      final b = shown[index];
                      final i = state.interferers[b.interfererId];
                      final who = b.sensorId != null
                          ? sensorNames[b.sensorId] ?? 'Station'
                          : state.participants[b.participantId]?.callsign ??
                                '?';
                      return CheckboxListTile(
                        key: Key('bulk-row-${b.id}'),
                        dense: true,
                        controlAffinity: ListTileControlAffinity.leading,
                        value: _selected.contains(b.id),
                        onChanged: (v) => setState(
                          () => v == true
                              ? _selected.add(b.id)
                              : _selected.remove(b.id),
                        ),
                        title: Text(
                          '${_hms(b.measuredAt)}  '
                          '${b.azimuthTrueDeg.toStringAsFixed(0)}° '
                          '±${b.sigmaDeg.toStringAsFixed(0)}°  $who',
                        ),
                        subtitle: Text(
                          '${i == null ? '' : '${i.letter} ${i.name} · '}'
                          '${gateLabel(b)}'
                          '${b.isOutlier ? ' · Ausreißer' : ''}'
                          '${b.isActive ? '' : ' · inaktiv'}',
                        ),
                        secondary: Icon(
                          b.gateCounts && b.isActive
                              ? Icons.circle
                              : Icons.circle_outlined,
                          color: colorOf(b),
                          size: 16,
                        ),
                      );
                    },
                  ),
          ),
        ],
      ),
      bottomNavigationBar: chosen.isEmpty
          ? null
          : SafeArea(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(8, 4, 8, 8),
                child: Wrap(
                  alignment: WrapAlignment.center,
                  spacing: 8,
                  runSpacing: 4,
                  children: [
                    if (canAssign && state.activeInterferers.isNotEmpty)
                      OutlinedButton.icon(
                        key: const Key('bulk-assign'),
                        icon: const Icon(Icons.radio_button_checked),
                        label: const Text('Störer …'),
                        onPressed: () => _assign(chosen),
                      ),
                    if (canGate && gateable.isNotEmpty) ...[
                      FilledButton.tonalIcon(
                        key: const Key('bulk-count'),
                        icon: const Icon(Icons.check_circle_outline),
                        label: const Text('Zählen'),
                        onPressed: () =>
                            _act('zählen', gateable, setGate: true, gate: true),
                      ),
                      FilledButton.tonalIcon(
                        key: const Key('bulk-exclude'),
                        icon: const Icon(Icons.block),
                        label: const Text('Nicht zählen'),
                        onPressed: () => _act(
                          'nicht zählen',
                          gateable,
                          setGate: true,
                          gate: false,
                        ),
                      ),
                      TextButton.icon(
                        key: const Key('bulk-auto'),
                        icon: const Icon(Icons.autorenew),
                        label: const Text('Automatisch'),
                        onPressed: () =>
                            _act('automatisch', gateable, setGate: true),
                      ),
                    ],
                  ],
                ),
              ),
            ),
    );
  }

  Widget _chip(
    String label,
    bool selected,
    ValueChanged<bool> onSelected, {
    Key? key,
    IconData? icon,
    Color? color,
  }) => Padding(
    padding: const EdgeInsets.only(right: 6),
    child: FilterChip(
      key: key,
      avatar: color != null
          ? CircleAvatar(backgroundColor: color, radius: 6)
          : icon != null
          ? Icon(icon, size: 16)
          : null,
      label: Text(label),
      selected: selected,
      onSelected: onSelected,
    ),
  );
}

/// Azimuth (0° top … 360° bottom) over time. Filled dots count, hollow ones do not;
/// transmissions are bands, the selection is ringed. Dragging selects a time range.
class _Timeline extends StatefulWidget {
  const _Timeline({
    required this.bearings,
    required this.transmissions,
    required this.selected,
    required this.colorOf,
    required this.onRange,
  });

  final List<Bearing> bearings;
  final List<Transmission> transmissions;
  final Set<String> selected;
  final Color Function(Bearing) colorOf;
  final void Function(DateTime from, DateTime to) onRange;

  @override
  State<_Timeline> createState() => _TimelineState();
}

class _TimelineState extends State<_Timeline> {
  double? _dragStart;
  double? _dragEnd;

  (DateTime, DateTime)? _span() {
    if (widget.bearings.isEmpty) return null;
    var from = widget.bearings.first.measuredAt;
    var to = widget.bearings.last.measuredAt;
    if (!to.isAfter(from)) {
      from = from.subtract(const Duration(minutes: 1));
      to = to.add(const Duration(minutes: 1));
    }
    final pad = Duration(
      milliseconds: (to.difference(from).inMilliseconds * 0.03).round(),
    );
    return (from.subtract(pad), to.add(pad));
  }

  DateTime _timeAt(double x, double width, (DateTime, DateTime) span) {
    final ms = span.$2.difference(span.$1).inMilliseconds;
    final f = (x / width).clamp(0.0, 1.0);
    return span.$1.add(Duration(milliseconds: (ms * f).round()));
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final span = _span();
    return LayoutBuilder(
      builder: (context, constraints) {
        final width = constraints.maxWidth;
        return GestureDetector(
          key: const Key('bulk-timeline'),
          behavior: HitTestBehavior.opaque,
          onHorizontalDragStart: (d) => setState(() {
            _dragStart = d.localPosition.dx;
            _dragEnd = d.localPosition.dx;
          }),
          onHorizontalDragUpdate: (d) =>
              setState(() => _dragEnd = d.localPosition.dx),
          onHorizontalDragEnd: (_) {
            final a = _dragStart, b = _dragEnd;
            setState(() => _dragStart = _dragEnd = null);
            if (span == null || a == null || b == null) return;
            widget.onRange(
              _timeAt(math.min(a, b), width, span),
              _timeAt(math.max(a, b), width, span),
            );
          },
          child: CustomPaint(
            size: Size(width, constraints.maxHeight),
            painter: _TimelinePainter(
              bearings: widget.bearings,
              transmissions: widget.transmissions,
              selected: widget.selected,
              colorOf: widget.colorOf,
              span: span,
              drag: _dragStart == null ? null : (_dragStart!, _dragEnd!),
              grid: theme.colorScheme.outlineVariant,
              band: theme.colorScheme.tertiary.withValues(alpha: 0.15),
              ring: theme.colorScheme.primary,
              label: theme.textTheme.labelSmall ?? const TextStyle(),
            ),
          ),
        );
      },
    );
  }
}

class _TimelinePainter extends CustomPainter {
  _TimelinePainter({
    required this.bearings,
    required this.transmissions,
    required this.selected,
    required this.colorOf,
    required this.span,
    required this.drag,
    required this.grid,
    required this.band,
    required this.ring,
    required this.label,
  });

  final List<Bearing> bearings;
  final List<Transmission> transmissions;
  final Set<String> selected;
  final Color Function(Bearing) colorOf;
  final (DateTime, DateTime)? span;
  final (double, double)? drag;
  final Color grid;
  final Color band;
  final Color ring;
  final TextStyle label;

  @override
  void paint(Canvas canvas, Size size) {
    final gridPaint = Paint()
      ..color = grid
      ..strokeWidth = 1;
    for (final deg in const [0, 90, 180, 270, 360]) {
      final y = size.height * deg / 360;
      canvas.drawLine(Offset(0, y), Offset(size.width, y), gridPaint);
      if (deg < 360) {
        TextPainter(
            text: TextSpan(text: '$deg°', style: label),
            textDirection: TextDirection.ltr,
          )
          ..layout()
          ..paint(canvas, Offset(2, y + 1));
      }
    }
    final s = span;
    if (s == null) return;
    final ms = s.$2.difference(s.$1).inMilliseconds.toDouble();
    double x(DateTime t) => size.width * t.difference(s.$1).inMilliseconds / ms;

    final bandPaint = Paint()..color = band;
    for (final t in transmissions) {
      final end = t.endedAt ?? DateTime.now().toUtc();
      final left = x(t.startedAt).clamp(0.0, size.width);
      final right = x(end).clamp(0.0, size.width);
      if (right > left) {
        canvas.drawRect(
          Rect.fromLTRB(left, 0, math.max(right, left + 2), size.height),
          bandPaint,
        );
      }
    }
    final ringPaint = Paint()
      ..color = ring
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2;
    for (final b in bearings) {
      final p = Offset(x(b.measuredAt), size.height * b.azimuthTrueDeg / 360);
      final counts = b.gateCounts && b.isActive;
      canvas.drawCircle(
        p,
        3.5,
        Paint()
          ..color = colorOf(b)
          ..style = counts ? PaintingStyle.fill : PaintingStyle.stroke
          ..strokeWidth = 1.5,
      );
      if (selected.contains(b.id)) canvas.drawCircle(p, 6, ringPaint);
    }
    final d = drag;
    if (d != null) {
      canvas.drawRect(
        Rect.fromLTRB(
          math.min(d.$1, d.$2),
          0,
          math.max(d.$1, d.$2),
          size.height,
        ),
        Paint()..color = ring.withValues(alpha: 0.15),
      );
    }
  }

  @override
  bool shouldRepaint(_TimelinePainter old) => true;
}

/// The selected rays on a small map, shown before a bulk action is applied.
class _Preview extends ConsumerWidget {
  const _Preview({required this.bearings});

  final List<Bearing> bearings;

  static const _rayM = 25000.0;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(missionProvider);
    final pal = MapPalette.of(context, ref.watch(settingsProvider));
    final stations = [for (final b in bearings) b.station];
    final fit = [
      ...stations,
      for (final b in bearings) destination(b.station, b.azimuthTrueDeg, 3000),
    ];
    final sensors = bearings.where((b) => b.sensorId != null).length;
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          height: 260,
          child: ClipRRect(
            borderRadius: BorderRadius.circular(8),
            child: FlutterMap(
              key: const Key('bulk-preview'),
              options: MapOptions(
                initialCameraFit: CameraFit.bounds(
                  bounds: LatLngBounds.fromPoints(fit),
                  padding: const EdgeInsets.all(16),
                ),
                interactionOptions: const InteractionOptions(
                  flags: InteractiveFlag.all & ~InteractiveFlag.rotate,
                ),
              ),
              children: [
                const AppTileLayer(),
                PolylineLayer(
                  polylines: [
                    for (final b in bearings)
                      Polyline(
                        points: [
                          b.station,
                          destination(b.station, b.azimuthTrueDeg, _rayM),
                        ],
                        strokeWidth: 2,
                        color: () {
                          final i = state.interferers[b.interfererId];
                          return i == null
                              ? Colors.grey
                              : pal.interferer(i.colorSlot);
                        }(),
                      ),
                  ],
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 8),
        Text(
          sensors == bearings.length
              ? '${bearings.length} Strahlen von automatischen Stationen.'
              : '${bearings.length} Strahlen, davon $sensors von automatischen '
                    'Stationen.',
        ),
      ],
    );
  }
}
