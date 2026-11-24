import 'package:material_ui/material_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/coords.dart';
import '../core/models.dart';
import '../state/providers.dart';
import 'app_dialogs.dart';
import 'capture_sheet.dart' show SigmaChips;

/// Lead only: enters a bearing received from outside the group (e.g. from the BNetzA) for a
/// [BearingPoint]. Position, compass and GPS play no part: the bearing sits at the point.
///
/// The azimuth is taken as true north ("rechtweisend"), which is how regulators report it.
/// The time of the measurement defaults to now and can be set back, because such values
/// usually arrive some minutes later.
class ExternalBearingSheet extends ConsumerStatefulWidget {
  const ExternalBearingSheet({super.key, required this.pointId});

  final String pointId;

  @override
  ConsumerState<ExternalBearingSheet> createState() =>
      _ExternalBearingSheetState();
}

class _ExternalBearingSheetState extends ConsumerState<ExternalBearingSheet> {
  final _azimuth = TextEditingController();
  final _note = TextEditingController();
  double _sigma = 15;
  DateTime _measuredAt = DateTime.now();
  int _saved = 0;
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _azimuth.addListener(_onTextChanged);
    _note.addListener(_onTextChanged);
  }

  bool _wasDirty = false;

  /// Rebuilds when the form flips between empty and filled so [PopScope.canPop] never goes stale.
  void _onTextChanged() {
    if (_dirty != _wasDirty) setState(() => _wasDirty = _dirty);
  }

  @override
  void dispose() {
    _azimuth.dispose();
    _note.dispose();
    super.dispose();
  }

  double? get _azimuthValue {
    final v = double.tryParse(_azimuth.text.trim().replaceAll(',', '.'));
    if (v == null || v < 0 || v > 360) return null;
    return v % 360;
  }

  String _hhmm(DateTime t) =>
      '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

  Future<void> _pickTime() async {
    final date = await showDatePicker(
      context: context,
      initialDate: _measuredAt,
      firstDate: DateTime.now().subtract(const Duration(days: 7)),
      lastDate: DateTime.now(),
    );
    if (date == null || !mounted) return;
    final time = await showTimePicker(
      context: context,
      initialTime: TimeOfDay.fromDateTime(_measuredAt),
    );
    if (time == null || !mounted) return;
    var at = DateTime(date.year, date.month, date.day, time.hour, time.minute);
    if (at.isAfter(DateTime.now())) at = DateTime.now();
    setState(() => _measuredAt = at);
  }

  Future<bool> _save() async {
    final point = ref.read(missionProvider).points[widget.pointId];
    final az = _azimuthValue;
    if (point == null || !point.isActive) {
      setState(() => _error = 'Peilpunkt ist nicht mehr aktiv');
      return false;
    }
    if (az == null) {
      setState(() => _error = 'Azimut 0–360° eingeben');
      return false;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    final note = _note.text.trim();
    await ref
        .read(missionProvider.notifier)
        .saveExternalBearing(
          point,
          azimuthTrueDeg: double.parse(az.toStringAsFixed(2)) % 360,
          sigmaDeg: _sigma,
          measuredAt: _measuredAt,
          note: note.isEmpty ? null : note,
        );
    if (mounted) setState(() => _saving = false);
    return true;
  }

  /// True while there is typed input that has not been saved yet (cleared after "Speichern + weitere").
  bool get _dirty =>
      _azimuth.text.trim().isNotEmpty || _note.text.trim().isNotEmpty;

  /// Closes without saving; asks first when typed input would be lost.
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
    if (mounted) Navigator.of(context).pop(_saved > 0);
  }

  Future<void> _saveAndClose() async {
    if (await _save() && mounted) Navigator.of(context).pop(true);
  }

  /// Keeps the sheet open for the next value of the same point (regulators often report several).
  Future<void> _saveAndMore() async {
    if (!await _save() || !mounted) return;
    setState(() {
      _saved++;
      _azimuth.clear();
      _note.clear();
      _measuredAt = DateTime.now();
    });
  }

  @override
  Widget build(BuildContext context) {
    final point = ref.watch(
      missionProvider.select((s) => s.points[widget.pointId]),
    );
    final theme = Theme.of(context);
    return PopScope(
      // Back gesture, barrier tap and drag-down all route through _cancel when input would be lost.
      canPop: !_dirty || _saving,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _cancel();
      },
      child: AppSheet(
        actions: [
          AppAction.cancel(
            label: _saved > 0 ? 'Schließen' : 'Abbrechen',
            buttonKey: const Key('ext-cancel'),
            onPressed: _saving ? null : _cancel,
          ),
          AppAction(
            label: 'Weitere',
            role: AppActionRole.secondary,
            buttonKey: const Key('ext-save-more'),
            onPressed: _saving ? null : _saveAndMore,
          ),
          AppAction(
            label: 'Speichern',
            buttonKey: const Key('ext-save'),
            onPressed: _saving ? null : _saveAndClose,
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
                    'Peilung von ${point?.name ?? '?'}',
                    key: const Key('ext-title'),
                    style: theme.textTheme.titleLarge,
                  ),
                ),
                IconButton(
                  key: const Key('close-ext'),
                  tooltip: _saved > 0 ? 'Schließen' : 'Abbrechen',
                  icon: const Icon(Icons.close),
                  onPressed: _saving ? null : _cancel,
                ),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              point == null
                  ? 'Peilpunkt unbekannt'
                  : '${formatCoordinate(point.position.latitude, isLat: true)}  '
                        '${formatCoordinate(point.position.longitude, isLat: false)}',
              style: theme.textTheme.bodySmall,
            ),
            const SizedBox(height: 12),
            TextField(
              key: const Key('ext-azimuth'),
              controller: _azimuth,
              autofocus: true,
              keyboardType: const TextInputType.numberWithOptions(
                decimal: true,
              ),
              style: theme.textTheme.headlineMedium,
              decoration: const InputDecoration(
                labelText: 'Azimut in ° (rechtweisend)',
              ),
              onChanged: (_) => setState(() {}),
            ),
            const SizedBox(height: 12),
            Text('Genauigkeit (Sigma)', style: theme.textTheme.labelLarge),
            const SizedBox(height: 4),
            SigmaChips(
              keyPrefix: 'ext-sigma',
              selected: _sigma,
              onSelected: (v) => setState(() => _sigma = v),
            ),
            const SizedBox(height: 8),
            ListTile(
              key: const Key('ext-time'),
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.schedule),
              title: Text('Gemessen um ${_hhmm(_measuredAt)}'),
              subtitle: const Text('Antippen, um Datum und Uhrzeit zu ändern'),
              onTap: _pickTime,
            ),
            TextField(
              key: const Key('ext-note'),
              controller: _note,
              decoration: const InputDecoration(
                labelText: 'Notiz (Quelle, Bemerkung)',
              ),
            ),
            if (_saved > 0)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text('$_saved gespeichert', key: const Key('ext-saved')),
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
