import 'package:flutter/foundation.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter_compass/flutter_compass.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';

import 'package:latlong2/latlong.dart';

import '../core/api.dart';
import '../core/coords.dart';
import '../core/geo.dart';
import 'position_picker_screen.dart';
import '../core/permissions.dart';
import '../state/providers.dart';
import 'interferers_screen.dart';
import '../core/signal.dart';
import 'app_dialogs.dart';
import 'dbm_field.dart';
import 'quick_readings.dart';

enum AzimuthRef { trueNorth, magnetic }

const sigmaPresets = <({String label, double sigma})>[
  (label: 'scharf ±5°', sigma: 5),
  (label: 'mittel ±15°', sigma: 15),
  (label: 'schlecht ±30°', sigma: 30),
];

/// The three accuracy presets in one row of equally wide chips. Labels shrink instead of
/// wrapping, and the selection shows as fill (no checkmark, which would widen the chip).
class SigmaChips extends StatelessWidget {
  const SigmaChips({
    super.key,
    required this.keyPrefix,
    required this.selected,
    required this.onSelected,
  });

  /// Chips are keyed `<keyPrefix>-<sigma>`.
  final String keyPrefix;
  final double selected;
  final ValueChanged<double> onSelected;

  @override
  Widget build(BuildContext context) => Row(
    children: [
      for (var i = 0; i < sigmaPresets.length; i++) ...[
        if (i > 0) const SizedBox(width: 8),
        Expanded(
          child: ChoiceChip(
            key: Key('$keyPrefix-${sigmaPresets[i].sigma.round()}'),
            showCheckmark: false,
            padding: const EdgeInsets.symmetric(vertical: 10),
            labelPadding: const EdgeInsets.symmetric(horizontal: 4),
            label: SizedBox(
              width: double.infinity,
              child: FittedBox(
                fit: BoxFit.scaleDown,
                child: Text(sigmaPresets[i].label, maxLines: 1),
              ),
            ),
            selected: selected == sigmaPresets[i].sigma,
            onSelected: (_) => onSelected(sigmaPresets[i].sigma),
          ),
        ),
      ],
    ],
  );
}

/// Bottom sheet to record one bearing with big, one-handed controls.
class CaptureSheet extends ConsumerStatefulWidget {
  const CaptureSheet({
    super.key,
    this.compassHeading,
    this.retroactive = false,
  });

  /// Enter a bearing afterwards: the participant sets time and position (at most 7 days back).
  final bool retroactive;

  /// Injected in tests; defaults to the device compass.
  final Stream<double?>? compassHeading;

  @override
  ConsumerState<CaptureSheet> createState() => _CaptureSheetState();
}

class _CaptureSheetState extends ConsumerState<CaptureSheet> {
  final _azimuth = TextEditingController();
  final _declination = TextEditingController(text: '0');
  final _rssi = TextEditingController();
  final _attenuation = TextEditingController();
  final _note = TextEditingController();
  AzimuthRef _ref = AzimuthRef.trueNorth;
  double _sigma = 15;
  String _polarization = 'unknown';
  bool _saving = false;
  String? _error;
  double? _liveHeading;

  // Retroactive mode only.
  final _lat = TextEditingController();
  final _lon = TextEditingController();
  DateTime _measuredAt = DateTime.now();
  LatLng? _pos;
  double? _posAccuracyM;
  String? _trackHint;

  @override
  void initState() {
    super.initState();
    final stream =
        widget.compassHeading ??
        (kIsWeb ? null : FlutterCompass.events?.map((e) => e.heading));
    for (final c in [_azimuth, _rssi, _attenuation, _note]) {
      c.addListener(_onTextChanged);
    }
    stream?.listen((h) {
      if (mounted) setState(() => _liveHeading = h);
    });
  }

  bool _wasDirty = false;

  /// Rebuilds when the form flips between empty and filled so [PopScope.canPop] never goes stale.
  void _onTextChanged() {
    if (_dirty != _wasDirty) setState(() => _wasDirty = _dirty);
  }

  @override
  void dispose() {
    for (final c in [
      _azimuth,
      _declination,
      _rssi,
      _attenuation,
      _note,
      _lat,
      _lon,
    ]) {
      c.dispose();
    }
    super.dispose();
  }

  double? get _azimuthValue {
    final v = double.tryParse(_azimuth.text.trim().replaceAll(',', '.'));
    if (v == null || v < 0 || v > 360) return null;
    return v;
  }

  double get _declinationValue =>
      double.tryParse(_declination.text.trim().replaceAll(',', '.')) ?? 0;

  double? get _trueAzimuth {
    final v = _azimuthValue;
    if (v == null) return null;
    return _ref == AzimuthRef.trueNorth
        ? normalizeAzimuth(v)
        : magneticToTrue(v, _declinationValue);
  }

  bool _declinationTouched = false;

  /// Pre-fill the cached WMM declination unless the user typed their own value.
  void _fillDeclination() {
    final d = ref.read(declinationProvider);
    if (d != null && !_declinationTouched) {
      _declination.text = d.toStringAsFixed(1);
    }
  }

  void _useCompass() {
    final h = _liveHeading;
    if (h == null) return;
    setState(() {
      _azimuth.text = normalizeAzimuth(h).round().toString();
      _ref = AzimuthRef.magnetic;
      _fillDeclination();
    });
  }

  String _stamp(DateTime t) {
    String two(int v) => v.toString().padLeft(2, '0');
    return '${two(t.day)}.${two(t.month)}.${t.year} ${two(t.hour)}:${two(t.minute)}';
  }

  Future<void> _pickTime() async {
    final now = DateTime.now();
    final date = await showDatePicker(
      context: context,
      initialDate: _measuredAt,
      firstDate: now.subtract(const Duration(days: 7)),
      lastDate: now,
    );
    if (date == null || !mounted) return;
    final time = await showTimePicker(
      context: context,
      initialTime: TimeOfDay.fromDateTime(_measuredAt),
    );
    if (time == null || !mounted) return;
    var at = DateTime(date.year, date.month, date.day, time.hour, time.minute);
    if (at.isAfter(DateTime.now())) at = DateTime.now();
    final oldest = DateTime.now().subtract(const Duration(days: 7));
    if (at.isBefore(oldest)) at = oldest;
    setState(() {
      _measuredAt = at;
      _trackHint = null;
    });
  }

  /// Sets the position (map, typed, GPS or track) and refreshes the declination for it.
  void _setPosition(LatLng p, {double? accuracyM, bool syncFields = true}) {
    setState(() {
      _pos = p;
      _posAccuracyM = accuracyM;
      if (syncFields) {
        _lat.text = p.latitude.toStringAsFixed(5);
        _lon.text = p.longitude.toStringAsFixed(5);
      }
    });
    _declinationFor(p);
  }

  Future<void> _declinationFor(LatLng p) async {
    try {
      final d = await ref
          .read(apiProvider)
          .declination(p.latitude, p.longitude);
      if (!mounted || _declinationTouched || _pos != p) return;
      setState(() => _declination.text = d.toStringAsFixed(1));
    } on ApiException {
      // offline: the cached value stays
    }
  }

  void _typedPosition() {
    final la = parseCoordinate(_lat.text, isLat: true);
    final lo = parseCoordinate(_lon.text, isLat: false);
    if (la == null || lo == null) {
      setState(() => _pos = null);
      return;
    }
    _setPosition(LatLng(la, lo), syncFields: false);
  }

  Future<void> _pickOnMap() async {
    final p = await Navigator.of(context).push<LatLng>(
      MaterialPageRoute(builder: (_) => PositionPickerScreen(initial: _pos)),
    );
    if (p != null && mounted) _setPosition(p);
  }

  void _useDevicePosition() {
    final fix = ref.read(ownPositionProvider);
    if (fix == null) {
      setState(() => _error = 'Noch kein Standort verfügbar');
      return;
    }
    setState(() => _error = null);
    _setPosition(fix.point, accuracyM: fix.accuracyM);
  }

  /// The own position closest to the chosen time (within 15 minutes) from the recorded track.
  Future<void> _useTrack() async {
    final me = ref.read(sessionProvider)?.participantId;
    if (me == null) return;
    const window = Duration(minutes: 15);
    setState(() {
      _error = null;
      _trackHint = null;
    });
    try {
      final fixes = await ref
          .read(apiProvider)
          .positionsSince(me, _measuredAt.subtract(window));
      if (!mounted) return;
      final near = [
        for (final f in fixes)
          if (f.recordedAt.difference(_measuredAt.toUtc()).abs() <= window) f,
      ];
      if (near.isEmpty) {
        setState(
          () => _trackHint =
              'Kein Track-Punkt in ±15 min um ${_stamp(_measuredAt)}',
        );
        return;
      }
      near.sort(
        (a, b) => a.recordedAt
            .difference(_measuredAt.toUtc())
            .abs()
            .compareTo(b.recordedAt.difference(_measuredAt.toUtc()).abs()),
      );
      final f = near.first;
      _setPosition(f.point, accuracyM: f.accuracyM);
      setState(
        () => _trackHint =
            'Track-Punkt von ${_stamp(f.recordedAt.toLocal())} übernommen',
      );
    } on ApiException {
      if (mounted) {
        setState(() => _trackHint = 'Track nicht abrufbar (offline?)');
      }
    }
  }

  /// True once the user typed something worth keeping (the declination is pre-filled, so it does not count).
  bool get _dirty => [
    _azimuth,
    _rssi,
    _attenuation,
    _note,
  ].any((c) => c.text.trim().isNotEmpty);

  /// Closes without saving; asks first when there is typed input that would be lost.
  Future<void> _cancel() async {
    if (_saving) return;
    if (_dirty) {
      final discard = await confirmDialog(
        context,
        title: 'Eingaben verwerfen?',
        message: 'Die Peilung wurde noch nicht gespeichert.',
        cancelLabel: 'Weiter bearbeiten',
        cancelKey: const Key('keep-editing'),
        confirmLabel: 'Verwerfen',
        confirmKey: const Key('discard-bearing'),
        destructive: true,
      );
      if (!discard) return;
    }
    if (mounted) Navigator.of(context).pop(false);
  }

  Future<void> _save() async {
    final fix = widget.retroactive ? null : ref.read(ownPositionProvider);
    final az = _trueAzimuth;
    if (az == null) {
      setState(() => _error = 'Azimut 0–360° eingeben');
      return;
    }
    final pos = widget.retroactive ? _pos : fix?.point;
    if (pos == null) {
      setState(
        () => _error = widget.retroactive
            ? 'Standort wählen (Karte, Koordinaten oder Track)'
            : 'Noch kein Standort verfügbar',
      );
      return;
    }
    final accuracyM = widget.retroactive ? _posAccuracyM : fix?.accuracyM;
    final rssi = _rssi.text.trim().isEmpty
        ? null
        : parseLevel(_rssi.text, sMode: ref.read(settingsProvider).levelInS);
    if (_rssi.text.trim().isNotEmpty && !isPlausibleLevel(rssi)) {
      setState(() => _error = levelRangeError);
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    final payload = <String, dynamic>{
      'id': const Uuid().v4(),
      'lat': pos.latitude,
      'lon': pos.longitude,
      'station_accuracy_m': accuracyM,
      'azimuth_true_deg': double.parse(az.toStringAsFixed(2)) % 360,
      'azimuth_input_ref': _ref == AzimuthRef.trueNorth ? 'true' : 'magnetic',
      'declination_deg_applied': _ref == AzimuthRef.magnetic
          ? _declinationValue
          : 0.0,
      'sigma_deg': _sigma,
      'polarization': _polarization,
      'measured_at': (widget.retroactive ? _measuredAt : DateTime.now())
          .toUtc()
          .toIso8601String(),
      if (widget.retroactive) 'entry_mode': 'retroactive',
      'rssi_dbm': ?rssi,
      if (_attenuation.text.trim().isNotEmpty)
        'attenuation_db':
            double.tryParse(_attenuation.text.trim().replaceAll(',', '.')) ?? 0,
      if (_note.text.trim().isNotEmpty) 'note': _note.text.trim(),
    };
    // Always succeeds locally; the sync queue delivers it (also when offline).
    await ref.read(missionProvider.notifier).saveBearing(payload);
    if (mounted) Navigator.of(context).pop(true);
  }

  /// Time and position inputs of the retroactive mode.
  Widget _retroactiveBlock(ThemeData theme) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        OutlinedButton.icon(
          key: const Key('retro-time'),
          onPressed: _pickTime,
          icon: const Icon(Icons.schedule),
          label: Text('Gemessen am ${_stamp(_measuredAt)}'),
        ),
        const SizedBox(height: 8),
        CoordinateFields(
          latitude: _lat,
          longitude: _lon,
          latKey: const Key('retro-lat'),
          lonKey: const Key('retro-lon'),
          onChanged: _typedPosition,
        ),
        const SizedBox(height: 8),
        Wrap(
          spacing: 8,
          runSpacing: 4,
          children: [
            ActionChip(
              key: const Key('retro-map'),
              avatar: const Icon(Icons.map, size: 18),
              label: const Text('Auf Karte'),
              onPressed: _pickOnMap,
            ),
            ActionChip(
              key: const Key('retro-track'),
              avatar: const Icon(Icons.timeline, size: 18),
              label: const Text('Aus meinem Track'),
              onPressed: _useTrack,
            ),
            ActionChip(
              key: const Key('retro-gps'),
              avatar: const Icon(Icons.my_location, size: 18),
              label: const Text('Mein Standort jetzt'),
              onPressed: _useDevicePosition,
            ),
          ],
        ),
        if (_trackHint != null)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(_trackHint!, style: theme.textTheme.bodySmall),
          ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final fix = ref.watch(ownPositionProvider);
    final theme = Theme.of(context);
    final az = _trueAzimuth;
    return PopScope(
      // Back gesture, barrier tap and drag-down all route through _cancel when input would be lost.
      canPop: !_dirty || _saving,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _cancel();
      },
      child: AppSheet(
        actions: [
          AppAction.cancel(
            buttonKey: const Key('cancel-bearing'),
            onPressed: _saving ? null : _cancel,
          ),
          AppAction(
            label: 'Speichern',
            buttonKey: const Key('save-bearing'),
            busy: _saving,
            onPressed: _save,
          ),
        ],
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    widget.retroactive
                        ? 'Peilung nachträglich erfassen'
                        : 'Peilung erfassen',
                    style: theme.textTheme.titleLarge,
                  ),
                ),
                _InterfererChip(),
                IconButton(
                  key: const Key('close-capture'),
                  tooltip: 'Abbrechen',
                  icon: const Icon(Icons.close),
                  onPressed: _saving ? null : _cancel,
                ),
              ],
            ),
            const SizedBox(height: 4),
            if (widget.retroactive)
              _retroactiveBlock(theme)
            else
              Text(
                fix == null
                    ? 'Warte auf Standort …'
                    : 'Standort ${fix.point.latitude.toStringAsFixed(5)}, '
                          '${fix.point.longitude.toStringAsFixed(5)}'
                          '${fix.accuracyM != null ? ' (±${fix.accuracyM!.round()} m)' : ''}',
                style: theme.textTheme.bodySmall,
              ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    key: const Key('azimuth'),
                    controller: _azimuth,
                    autofocus: true,
                    keyboardType: const TextInputType.numberWithOptions(
                      decimal: true,
                    ),
                    style: theme.textTheme.headlineMedium,
                    decoration: const InputDecoration(labelText: 'Azimut in °'),
                    onChanged: (_) => setState(() {}),
                  ),
                ),
                if (!kIsWeb || widget.compassHeading != null) ...[
                  const SizedBox(width: 8),
                  SizedBox(
                    height: 64,
                    child: FilledButton.tonalIcon(
                      key: const Key('use-compass'),
                      onPressed: _liveHeading == null ? null : _useCompass,
                      icon: const Icon(Icons.explore),
                      label: Text(
                        _liveHeading == null
                            ? 'Kompass'
                            : '${normalizeAzimuth(_liveHeading!).round()}°',
                      ),
                    ),
                  ),
                ],
              ],
            ),
            const SizedBox(height: 8),
            SegmentedButton<AzimuthRef>(
              key: const Key('ref'),
              segments: const [
                ButtonSegment(
                  value: AzimuthRef.trueNorth,
                  label: Text('rechtweisend'),
                ),
                ButtonSegment(
                  value: AzimuthRef.magnetic,
                  label: Text('magnetisch'),
                ),
              ],
              selected: {_ref},
              onSelectionChanged: (s) => setState(() {
                _ref = s.first;
                _fillDeclination();
              }),
            ),
            if (_ref == AzimuthRef.magnetic) ...[
              const SizedBox(height: 8),
              TextField(
                key: const Key('declination'),
                controller: _declination,
                keyboardType: const TextInputType.numberWithOptions(
                  decimal: true,
                  signed: true,
                ),
                decoration: const InputDecoration(
                  labelText: 'Missweisung in ° (Ost positiv)',
                  helperText: 'WMM-Wert vorbelegt, überschreibbar',
                ),
                onChanged: (_) => setState(() => _declinationTouched = true),
              ),
            ],
            if (az != null && _ref == AzimuthRef.magnetic)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text('→ rechtweisend ${az.toStringAsFixed(1)}°'),
              ),
            const SizedBox(height: 12),
            Text('Genauigkeit (Sigma)', style: theme.textTheme.labelLarge),
            const SizedBox(height: 4),
            SigmaChips(
              keyPrefix: 'sigma',
              selected: _sigma,
              onSelected: (v) => setState(() => _sigma = v),
            ),
            const SizedBox(height: 12),
            DbmField(key: const Key('rssi'), controller: _rssi, label: 'RSSI'),
            const SizedBox(height: 8),
            QuickReadingGrid(
              keyPrefix: 'capture',
              onPick: (q) {
                final sMode = ref.read(settingsProvider).levelInS;
                final text = sMode ? dbmToSInput(q.dbm) : '${q.dbm.round()}';
                _rssi.value = TextEditingValue(
                  text: text,
                  selection: TextSelection.collapsed(offset: text.length),
                );
              },
            ),
            const SizedBox(height: 8),
            TextField(
              key: const Key('attenuation'),
              controller: _attenuation,
              keyboardType: const TextInputType.numberWithOptions(
                decimal: true,
              ),
              decoration: const InputDecoration(labelText: 'Dämpfung in dB'),
            ),
            const SizedBox(height: 12),
            SegmentedButton<String>(
              key: const Key('polarization'),
              segments: const [
                ButtonSegment(value: 'h', label: Text('horiz.')),
                ButtonSegment(value: 'v', label: Text('vert.')),
                ButtonSegment(value: 'unknown', label: Text('?')),
              ],
              selected: {_polarization},
              onSelectionChanged: (s) =>
                  setState(() => _polarization = s.first),
            ),
            const SizedBox(height: 8),
            TextField(
              key: const Key('note'),
              controller: _note,
              decoration: const InputDecoration(labelText: 'Notiz'),
            ),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(
                  _error!,
                  style: TextStyle(color: theme.colorScheme.error),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

/// Result of the picker for "new interferer" (real ids are UUIDs).
const _newInterferer = 'new';

/// Shows which interferer the bearing is for and switches it with one tap. Hidden while the
/// mission has a single interferer and the user cannot add one.
class _InterfererChip extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(missionProvider);
    final activeId = ref.watch(activeInterfererIdProvider);
    final active = activeId == null ? null : state.interferers[activeId];
    final canManage =
        ref.watch(sessionProvider)?.can(Perm.interfererManage) ?? false;
    if (active == null || (state.activeInterferers.length < 2 && !canManage)) {
      return const SizedBox.shrink();
    }
    return ActionChip(
      key: const Key('interferer-chip'),
      avatar: InterfererBadge(active, radius: 11),
      label: Text(active.name),
      onPressed: () async {
        final picked = await showModalBottomSheet<String>(
          context: context,
          showDragHandle: true,
          builder: (ctx) => SafeArea(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                for (final i in state.activeInterferers)
                  ListTile(
                    key: Key('pick-interferer-${i.id}'),
                    leading: InterfererBadge(i),
                    title: Text(i.name),
                    selected: i.id == active.id,
                    trailing: i.id == active.id
                        ? const Icon(Icons.check)
                        : null,
                    onTap: () => Navigator.pop(ctx, i.id),
                  ),
                if (canManage)
                  ListTile(
                    key: const Key('pick-interferer-new'),
                    leading: const Icon(Icons.add),
                    title: const Text('Neuer Störer …'),
                    onTap: () => Navigator.pop(ctx, _newInterferer),
                  ),
              ],
            ),
          ),
        );
        if (picked == null || !context.mounted) return;
        if (picked == _newInterferer) {
          await createInterfererDialog(context, ref);
        } else {
          await ref.read(activeInterfererProvider.notifier).select(picked);
        }
      },
    );
  }
}
