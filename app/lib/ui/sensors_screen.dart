import 'package:material_ui/material_ui.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app_dialogs.dart';
import '../core/api.dart';
import '../core/models.dart';
import '../state/providers.dart';

/// Lead only: register automatic stations and the repeater hook, see who is online.
class SensorsScreen extends ConsumerWidget {
  const SensorsScreen({super.key});

  String _seen(SensorInfo s) {
    final t = s.lastSeenAt?.toLocal();
    if (t == null) return 'noch nie gemeldet';
    return 'zuletzt ${t.hour.toString().padLeft(2, '0')}:'
        '${t.minute.toString().padLeft(2, '0')}:${t.second.toString().padLeft(2, '0')}';
  }

  /// Weight, default interferer and gate in one line.
  String _settingsLine(SensorInfo s, WidgetRef ref) {
    final interferer = ref.read(missionProvider).interferers[s.interfererId];
    return '\nGewicht ${s.weight.toStringAsFixed(1)}'
        '${interferer == null ? '' : ' · ${interferer.letter} ${interferer.name}'}'
        '${s.gated ? ' · zählt nur bei Aussendung' : ''}';
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(sensorsProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Sensoren'),
        actions: [
          IconButton(
            tooltip: 'Aktualisieren',
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(sensorsProvider),
          ),
        ],
      ),
      body: async.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(
          child: Text('Nicht erreichbar: $e', key: const Key('sensors-error')),
        ),
        data: (sensors) => sensors.isEmpty
            ? const Center(
                child: Padding(
                  padding: EdgeInsets.all(24),
                  child: Text(
                    'Noch keine Sensoren. Lege eine Peilstation oder den Relais-Hook an; '
                    'die Anleitung steht in docs/reference/mqtt.md.',
                    key: Key('sensors-empty'),
                    textAlign: TextAlign.center,
                  ),
                ),
              )
            : ListView(
                children: [
                  for (final s in sensors)
                    ListTile(
                      key: Key('sensor-tile-${s.name}'),
                      leading: Icon(
                        s.isRelay
                            ? Icons.cell_tower
                            : s.isMobile
                            ? Icons.directions_car
                            : Icons.sensors,
                        color: s.online ? Colors.green : Colors.grey,
                      ),
                      title: Text('${s.name} · ${s.callsign}'),
                      subtitle: Text(
                        '${s.isRelay
                            ? 'Relais-Hook'
                            : s.isMobile
                            ? 'Mobile Peilstation'
                            : 'Peilstation'} · '
                        '${s.online ? 'online' : 'offline'} · ${_seen(s)}'
                        '${s.isRelay ? '' : _settingsLine(s, ref)}',
                      ),
                      onTap: s.isRelay
                          ? null
                          : () => showModalBottomSheet<void>(
                              context: context,
                              isScrollControlled: true,
                              showDragHandle: true,
                              builder: (_) => SensorSettingsSheet(sensor: s),
                            ),
                      trailing: Switch(
                        key: Key('sensor-${s.name}'),
                        value: s.isActive,
                        onChanged: (on) async {
                          try {
                            await ref
                                .read(apiProvider)
                                .setSensorActive(s.id, active: on);
                          } on ApiException catch (e) {
                            if (context.mounted) {
                              ScaffoldMessenger.of(context).showSnackBar(
                                SnackBar(content: Text(e.message)),
                              );
                            }
                          }
                          ref.invalidate(sensorsProvider);
                        },
                      ),
                    ),
                ],
              ),
      ),
      floatingActionButton: FloatingActionButton.extended(
        key: const Key('add-sensor'),
        icon: const Icon(Icons.add),
        label: const Text('Sensor'),
        onPressed: () => _create(context, ref),
      ),
    );
  }

  Future<void> _create(BuildContext context, WidgetRef ref) async {
    final result = await showDialog<_NewSensor>(
      context: context,
      builder: (_) => _NewSensorDialog(own: ref.read(ownPositionProvider)),
    );
    if (result == null || !context.mounted) return;
    try {
      final created = await ref
          .read(apiProvider)
          .createSensor(
            name: result.name,
            kind: result.kind,
            lat: result.lat,
            lon: result.lon,
          );
      ref.invalidate(sensorsProvider);
      if (!context.mounted) return;
      await showDialog<void>(
        context: context,
        builder: (_) => KeyDialog(sensor: created),
      );
    } on ApiException catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              e.statusCode == 409 ? 'Den Namen gibt es schon.' : e.message,
            ),
          ),
        );
      }
    }
  }
}

class _NewSensor {
  const _NewSensor(this.name, this.kind, this.lat, this.lon);

  final String name;
  final String kind;
  final double? lat;
  final double? lon;
}

class _NewSensorDialog extends StatefulWidget {
  const _NewSensorDialog({required this.own});

  final PositionFix? own;

  @override
  State<_NewSensorDialog> createState() => _NewSensorDialogState();
}

class _NewSensorDialogState extends State<_NewSensorDialog> {
  final _name = TextEditingController();
  String _kind = 'station';
  bool _useHere = false;

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AppDialog(
      title: const Text('Neuer Sensor'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          TextField(
            key: const Key('sensor-name'),
            controller: _name,
            autofocus: true,
            decoration: const InputDecoration(
              labelText: 'Name, z. B. Station Nord',
            ),
          ),
          const SizedBox(height: 12),
          SegmentedButton<String>(
            segments: const [
              ButtonSegment(value: 'station', label: Text('Peilstation')),
              ButtonSegment(value: 'relay', label: Text('Relais-Hook')),
            ],
            selected: {_kind},
            onSelectionChanged: (s) => setState(() => _kind = s.first),
          ),
          if (_kind == 'station' && widget.own != null)
            CheckboxListTile(
              key: const Key('use-here'),
              contentPadding: EdgeInsets.zero,
              title: const Text('Feste Station an meinem Standort'),
              value: _useHere,
              onChanged: (v) => setState(() => _useHere = v ?? false),
            ),
        ],
      ),
      actions: [
        AppAction.cancel(onPressed: () => Navigator.pop(context)),
        AppAction(
          label: 'Anlegen',
          buttonKey: const Key('sensor-save'),
          onPressed: () {
            final name = _name.text.trim();
            if (name.length < 2) return;
            final here = _useHere ? widget.own : null;
            Navigator.pop(
              context,
              _NewSensor(
                name,
                _kind,
                here?.point.latitude,
                here?.point.longitude,
              ),
            );
          },
        ),
      ],
    );
  }
}

/// Shows the API key exactly once.
class KeyDialog extends StatelessWidget {
  const KeyDialog({super.key, required this.sensor});

  final SensorInfo sensor;

  @override
  Widget build(BuildContext context) {
    final key = sensor.apiKey ?? '';
    return AppDialog(
      title: Text('${sensor.name} angelegt'),
      content: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text(
              'Der Schlüssel wird nur jetzt angezeigt. Kopiere ihn ins Gerät.',
            ),
            const SizedBox(height: 12),
            const Text('API-Schlüssel'),
            SelectableText(key, key: const Key('api-key')),
            const SizedBox(height: 8),
            const Text('Topic-Präfix'),
            SelectableText(sensor.topicPrefix, key: const Key('topic-prefix')),
          ],
        ),
      ),
      actions: [
        AppAction(
          label: 'Kopieren',
          role: AppActionRole.secondary,
          onPressed: () => Clipboard.setData(ClipboardData(text: key)),
        ),
        AppAction(label: 'Fertig', onPressed: () => Navigator.pop(context)),
      ],
    );
  }
}

/// Settings of one bearing station (ADR 0010): weight in the estimate, default interferer and
/// whether its bearings count only while the interferer transmits.
class SensorSettingsSheet extends ConsumerStatefulWidget {
  const SensorSettingsSheet({super.key, required this.sensor});

  final SensorInfo sensor;

  @override
  ConsumerState<SensorSettingsSheet> createState() =>
      _SensorSettingsSheetState();
}

class _SensorSettingsSheetState extends ConsumerState<SensorSettingsSheet> {
  late double _weight = widget.sensor.weight;
  late String? _interferer = widget.sensor.interfererId;
  late bool _gated = widget.sensor.gated;
  bool _busy = false;

  Map<String, dynamic> get _changes => {
    if (_weight != widget.sensor.weight) 'weight': _weight,
    if (_interferer != widget.sensor.interfererId) 'interferer_id': _interferer,
    if (_gated != widget.sensor.gated) 'gated': _gated,
  };

  Future<void> _save() async {
    final changes = _changes;
    if (changes.isEmpty) {
      Navigator.pop(context);
      return;
    }
    setState(() => _busy = true);
    try {
      await ref.read(apiProvider).patchSensor(widget.sensor.id, changes);
      ref.invalidate(sensorsProvider);
      if (mounted) Navigator.pop(context);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _busy = false);
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(missionProvider);
    final theme = Theme.of(context);
    final interferers = state.activeInterferers;
    // A deactivated default stays visible until changed.
    final current = state.interferers[widget.sensor.interfererId];
    return AppSheet(
      title: widget.sensor.name,
      actions: [
        AppAction.cancel(onPressed: () => Navigator.pop(context)),
        AppAction(
          label: 'Speichern',
          buttonKey: const Key('sensor-settings-save'),
          busy: _busy,
          onPressed: _busy ? null : _save,
        ),
      ],
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text('Gewicht ${_weight.toStringAsFixed(1)}'),
          Slider(
            key: const Key('sensor-weight'),
            value: _weight,
            max: 2,
            divisions: 20,
            label: _weight.toStringAsFixed(1),
            onChanged: (v) =>
                setState(() => _weight = (v * 10).roundToDouble() / 10),
          ),
          Text(
            _weight == 0
                ? 'Die Peilungen fließen nicht in die Schätzung ein.'
                : 'Wie stark die Peilungen in der Schätzung zählen (1 = normal). '
                      'In der Stadt mit vielen Reflexionen z. B. 0,5.',
            style: theme.textTheme.bodySmall,
          ),
          const SizedBox(height: 16),
          DropdownButtonFormField<String?>(
            key: const Key('sensor-interferer'),
            initialValue: _interferer,
            decoration: const InputDecoration(labelText: 'Standard-Störer'),
            items: [
              const DropdownMenuItem<String?>(
                child: Text('Keiner (Aussendung bzw. Standard)'),
              ),
              for (final i in {...interferers, ?current})
                DropdownMenuItem<String?>(
                  value: i.id,
                  child: Text('${i.letter} ${i.name}'),
                ),
            ],
            onChanged: (v) => setState(() => _interferer = v),
          ),
          const SizedBox(height: 8),
          SwitchListTile(
            key: const Key('sensor-gated'),
            contentPadding: EdgeInsets.zero,
            title: const Text('Nur bei „Störer sendet“ zählen'),
            subtitle: const Text(
              'Peilungen außerhalb einer Aussendung werden gespeichert, '
              'fließen aber nicht ein. Gegen Relaisnutzer auf der Frequenz.',
            ),
            value: _gated,
            onChanged: (v) => setState(() => _gated = v),
          ),
        ],
      ),
    );
  }
}
