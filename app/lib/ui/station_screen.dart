import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:latlong2/latlong.dart';

import '../core/models.dart';
import '../core/signal.dart';
import '../state/providers.dart';

/// Fixed station with an omnidirectional antenna: reports the S-meter value of the interferer on
/// the repeater *input* frequency. Without a bearing this still narrows the area down, because
/// the level falls off with the distance to the interferer.
class StationScreen extends ConsumerStatefulWidget {
  const StationScreen({super.key});

  @override
  ConsumerState<StationScreen> createState() => _StationScreenState();
}

class _StationScreenState extends ConsumerState<StationScreen> {
  final _dbm = TextEditingController();
  bool _calibration = false;

  @override
  void dispose() {
    _dbm.dispose();
    super.dispose();
  }

  /// The typed-in fixed location wins over GPS.
  PositionFix? _position() {
    final fixed = ref.read(stationPositionProvider);
    if (fixed != null) {
      return PositionFix(
        participantId: ref.read(sessionProvider)!.participantId,
        point: fixed,
        recordedAt: DateTime.now().toUtc(),
      );
    }
    return ref.read(ownPositionProvider);
  }

  Future<void> _editPosition() async {
    final result = await showDialog<LatLng>(
      context: context,
      builder: (_) => _PositionDialog(
        current: ref.read(stationPositionProvider),
        gps: ref.read(ownPositionProvider)?.point,
      ),
    );
    if (result != null) {
      await ref.read(stationPositionProvider.notifier).set(result);
    }
  }

  Future<void> _log(double dbm) async {
    final fix = _position();
    if (fix == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Noch kein Standort verfügbar')),
      );
      return;
    }
    await ref
        .read(missionProvider.notifier)
        .logRssi(
          rssiDbm: dbm,
          at: fix,
          attenuationDb: ref.read(attenuationProvider).toDouble(),
          receiver: 'omni',
          isCalibration: _calibration,
        );
  }

  Future<void> _editRepeater(Repeater? current) async {
    final own = ref.read(ownPositionProvider);
    final result = await showDialog<Repeater>(
      context: context,
      builder: (_) => _RepeaterDialog(current: current, own: own?.point),
    );
    if (result != null) {
      await ref.read(missionProvider.notifier).setRepeater(result);
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(missionProvider);
    final session = ref.watch(sessionProvider)!;
    final own = ref.watch(ownPositionProvider);
    final fixed = ref.watch(stationPositionProvider);
    final attenuation = ref.watch(attenuationProvider);
    final repeater = state.mission?.repeater;
    final theme = Theme.of(context);

    final mine = state.rssi
        .where((r) => r.participantId == session.participantId && r.isStation)
        .toList();
    final recent = mine.reversed.take(5).toList();
    final offset = (state.estimates['current'] ?? state.estimates['all'])
        ?.rssi
        ?.stationOffsetsDb[session.participantId];
    final inputMhz = repeater?.inputMhz;
    final outputMhz = repeater?.outputMhz;

    return Scaffold(
      appBar: AppBar(title: const Text('Rundstrahl-Station')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(12),
          children: [
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Text(
                  _calibration
                      ? 'Kalibrierung: Auf der Ausgabefrequenz des Relais'
                            '${outputMhz == null ? '' : ' (${outputMhz.toStringAsFixed(4)} MHz)'}'
                            ' messen, während das Relais sendet. Das gleicht '
                            'Antenne und Empfänger gegenüber den anderen Stationen ab.'
                      : 'Auf der Eingabefrequenz des Relais'
                            '${inputMhz == null ? '' : ' (${inputMhz.toStringAsFixed(4)} MHz)'}'
                            ' messen (Reverse-Taste), während der Störer sendet. '
                            'Auf der Ausgabefrequenz hörst du nur das Relais, nicht den Störer.',
                  key: const Key('station-hint'),
                ),
              ),
            ),
            const SizedBox(height: 8),
            Text(
              fixed != null
                  ? 'Fester Standort: ${fixed.latitude.toStringAsFixed(5)}, '
                        '${fixed.longitude.toStringAsFixed(5)}'
                  : own == null
                  ? 'Standort: GPS wird ermittelt …'
                  : 'Standort (GPS): ${own.point.latitude.toStringAsFixed(5)}, '
                        '${own.point.longitude.toStringAsFixed(5)}'
                        '${own.accuracyM == null ? '' : ' (±${own.accuracyM!.round()} m)'}',
              key: const Key('station-position'),
              style: theme.textTheme.bodyMedium,
            ),
            Wrap(
              spacing: 8,
              children: [
                TextButton.icon(
                  key: const Key('station-set-position'),
                  onPressed: _editPosition,
                  icon: const Icon(Icons.edit_location_alt),
                  label: Text(
                    fixed == null
                        ? 'Festen Standort eingeben'
                        : 'Standort ändern',
                  ),
                ),
                if (fixed != null)
                  TextButton(
                    key: const Key('station-clear-position'),
                    onPressed: () =>
                        ref.read(stationPositionProvider.notifier).set(null),
                    child: const Text('GPS verwenden'),
                  ),
              ],
            ),
            const SizedBox(height: 12),
            Text(
              _calibration ? 'S-Wert des Relais' : 'S-Wert des Störers',
              style: theme.textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final q in quickReadings)
                  FilledButton.tonal(
                    key: Key('station-${q.label}'),
                    onPressed: () => _log(q.dbm),
                    child: Text(q.label),
                  ),
              ],
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    key: const Key('station-dbm'),
                    controller: _dbm,
                    keyboardType: const TextInputType.numberWithOptions(
                      decimal: true,
                      signed: true,
                    ),
                    decoration: const InputDecoration(
                      labelText: 'oder Pegel in dBm',
                      border: OutlineInputBorder(),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                SizedBox(
                  height: 56,
                  child: FilledButton(
                    key: const Key('station-log-dbm'),
                    onPressed: () {
                      final v = double.tryParse(
                        _dbm.text.trim().replaceAll(',', '.'),
                      );
                      if (v == null || v > 20 || v < -200) {
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(
                            content: Text(
                              'dBm-Wert zwischen -200 und 20 eingeben',
                            ),
                          ),
                        );
                        return;
                      }
                      _log(v);
                      _dbm.clear();
                    },
                    child: const Text('Erfassen'),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            const Text('Dämpfungsglied vor dem Empfänger'),
            const SizedBox(height: 4),
            Wrap(
              spacing: 8,
              children: [
                for (final db in attenuatorSteps)
                  ChoiceChip(
                    key: Key('station-att-$db'),
                    label: Text(db == 0 ? 'keins' : '$db dB'),
                    selected: attenuation == db,
                    onSelected: (_) =>
                        ref.read(attenuationProvider.notifier).set(db),
                  ),
              ],
            ),
            SwitchListTile(
              key: const Key('station-calibration'),
              contentPadding: EdgeInsets.zero,
              title: const Text('Kalibrierung (Relais-Ausgabe)'),
              subtitle: Text(
                repeater == null
                    ? 'Erst möglich, wenn die Einsatzleitung den Relais-Standort gesetzt hat'
                    : 'Einmal pro Station: Pegel des Relais auf der Ausgabefrequenz',
              ),
              value: _calibration,
              onChanged: repeater == null
                  ? null
                  : (v) => setState(() => _calibration = v),
            ),
            if (offset != null)
              Text(
                'Geschätzter Offset deiner Station: '
                '${offset >= 0 ? '+' : ''}${offset.toStringAsFixed(1)} dB',
                key: const Key('station-offset'),
                style: theme.textTheme.bodySmall,
              ),
            const Divider(height: 24),
            Text('Zuletzt gemeldet', style: theme.textTheme.titleMedium),
            if (recent.isEmpty)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 8),
                child: Text('Noch keine Meldung', key: Key('station-empty')),
              ),
            for (final r in recent)
              ListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                leading: Icon(
                  r.isCalibration ? Icons.tune : Icons.sensors,
                  color: rssiColor(r.correctedDbm),
                ),
                title: Text(
                  '${dbmToSLabel(r.correctedDbm)} (${r.correctedDbm.round()} dBm)'
                  '${r.isCalibration ? ' · Kalibrierung' : ''}',
                ),
                trailing: r.pending
                    ? const Icon(Icons.schedule, size: 16)
                    : const Icon(Icons.check, size: 16),
              ),
            if (session.isLead) ...[
              const Divider(height: 24),
              Text('Relais', style: theme.textTheme.titleMedium),
              const SizedBox(height: 4),
              Text(
                repeater == null
                    ? 'Noch nicht gesetzt'
                    : '${repeater.point.latitude.toStringAsFixed(5)}, '
                          '${repeater.point.longitude.toStringAsFixed(5)} · '
                          'Eingabe ${inputMhz ?? '–'} MHz · '
                          'Ausgabe ${outputMhz ?? '–'} MHz',
                key: const Key('repeater-summary'),
              ),
              const SizedBox(height: 8),
              OutlinedButton.icon(
                key: const Key('edit-repeater'),
                onPressed: () => _editRepeater(repeater),
                icon: const Icon(Icons.cell_tower),
                label: const Text('Relais festlegen'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _RepeaterDialog extends StatefulWidget {
  const _RepeaterDialog({this.current, this.own});

  final Repeater? current;
  final LatLng? own;

  @override
  State<_RepeaterDialog> createState() => _RepeaterDialogState();
}

class _RepeaterDialogState extends State<_RepeaterDialog> {
  late final _lat = TextEditingController(
    text: widget.current?.point.latitude.toString() ?? '',
  );
  late final _lon = TextEditingController(
    text: widget.current?.point.longitude.toString() ?? '',
  );
  late final _in = TextEditingController(
    text: widget.current?.inputMhz?.toString() ?? '',
  );
  late final _out = TextEditingController(
    text: widget.current?.outputMhz?.toString() ?? '',
  );
  String? _error;

  double? _num(TextEditingController c) =>
      double.tryParse(c.text.trim().replaceAll(',', '.'));

  void _submit() {
    final lat = _num(_lat);
    final lon = _num(_lon);
    if (lat == null || lon == null || lat.abs() > 90 || lon.abs() > 180) {
      setState(() => _error = 'Breite und Länge als Dezimalgrad eingeben');
      return;
    }
    Navigator.of(context).pop(
      Repeater(
        point: LatLng(lat, lon),
        inputMhz: _num(_in),
        outputMhz: _num(_out),
      ),
    );
  }

  @override
  void dispose() {
    _lat.dispose();
    _lon.dispose();
    _in.dispose();
    _out.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    Widget field(String key, String label, TextEditingController c) => Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: TextField(
        key: Key(key),
        controller: c,
        keyboardType: const TextInputType.numberWithOptions(
          decimal: true,
          signed: true,
        ),
        decoration: InputDecoration(
          labelText: label,
          border: const OutlineInputBorder(),
        ),
      ),
    );
    return AlertDialog(
      title: const Text('Relais festlegen'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            field('repeater-lat', 'Breite', _lat),
            field('repeater-lon', 'Länge', _lon),
            if (widget.own != null)
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton(
                  key: const Key('repeater-use-own'),
                  onPressed: () => setState(() {
                    _lat.text = widget.own!.latitude.toStringAsFixed(5);
                    _lon.text = widget.own!.longitude.toStringAsFixed(5);
                  }),
                  child: const Text('Eigenen Standort übernehmen'),
                ),
              ),
            field('repeater-input', 'Eingabefrequenz (MHz)', _in),
            field('repeater-output', 'Ausgabefrequenz (MHz)', _out),
            if (_error != null)
              Text(
                _error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Abbrechen'),
        ),
        FilledButton(
          key: const Key('repeater-save'),
          onPressed: _submit,
          child: const Text('Speichern'),
        ),
      ],
    );
  }
}

class _PositionDialog extends StatefulWidget {
  const _PositionDialog({this.current, this.gps});

  final LatLng? current;
  final LatLng? gps;

  @override
  State<_PositionDialog> createState() => _PositionDialogState();
}

class _PositionDialogState extends State<_PositionDialog> {
  late final _lat = TextEditingController(
    text: widget.current?.latitude.toString() ?? '',
  );
  late final _lon = TextEditingController(
    text: widget.current?.longitude.toString() ?? '',
  );
  String? _error;

  double? _num(TextEditingController c) =>
      double.tryParse(c.text.trim().replaceAll(',', '.'));

  @override
  void dispose() {
    _lat.dispose();
    _lon.dispose();
    super.dispose();
  }

  void _submit() {
    final lat = _num(_lat);
    final lon = _num(_lon);
    if (lat == null || lon == null || lat.abs() > 90 || lon.abs() > 180) {
      setState(() => _error = 'Breite und Länge als Dezimalgrad eingeben');
      return;
    }
    Navigator.of(context).pop(LatLng(lat, lon));
  }

  @override
  Widget build(BuildContext context) {
    Widget field(String key, String label, TextEditingController c) => Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: TextField(
        key: Key(key),
        controller: c,
        keyboardType: const TextInputType.numberWithOptions(
          decimal: true,
          signed: true,
        ),
        decoration: InputDecoration(
          labelText: label,
          border: const OutlineInputBorder(),
        ),
      ),
    );
    return AlertDialog(
      title: const Text('Fester Standort'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            field('position-lat', 'Breite', _lat),
            field('position-lon', 'Länge', _lon),
            if (widget.gps != null)
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton(
                  key: const Key('position-use-gps'),
                  onPressed: () => setState(() {
                    _lat.text = widget.gps!.latitude.toStringAsFixed(5);
                    _lon.text = widget.gps!.longitude.toStringAsFixed(5);
                  }),
                  child: const Text('GPS-Position übernehmen'),
                ),
              ),
            if (_error != null)
              Text(
                _error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Abbrechen'),
        ),
        FilledButton(
          key: const Key('position-save'),
          onPressed: _submit,
          child: const Text('Speichern'),
        ),
      ],
    );
  }
}
