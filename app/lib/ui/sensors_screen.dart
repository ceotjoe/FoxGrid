import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

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
                    'die Anleitung steht in docs/mqtt.md.',
                    key: Key('sensors-empty'),
                    textAlign: TextAlign.center,
                  ),
                ),
              )
            : ListView(
                children: [
                  for (final s in sensors)
                    SwitchListTile(
                      key: Key('sensor-${s.name}'),
                      secondary: Icon(
                        s.isRelay ? Icons.cell_tower : Icons.sensors,
                        color: s.online ? Colors.green : Colors.grey,
                      ),
                      title: Text('${s.name} · ${s.callsign}'),
                      subtitle: Text(
                        '${s.isRelay ? 'Relais-Hook' : 'Peilstation'} · '
                        '${s.online ? 'online' : 'offline'} · ${_seen(s)}',
                      ),
                      value: s.isActive,
                      onChanged: (on) async {
                        try {
                          await ref
                              .read(apiProvider)
                              .setSensorActive(s.id, active: on);
                        } on ApiException catch (e) {
                          if (context.mounted) {
                            ScaffoldMessenger.of(
                              context,
                            ).showSnackBar(SnackBar(content: Text(e.message)));
                          }
                        }
                        ref.invalidate(sensorsProvider);
                      },
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
    return AlertDialog(
      title: const Text('Neuer Sensor'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
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
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Abbrechen'),
        ),
        FilledButton(
          key: const Key('sensor-save'),
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
          child: const Text('Anlegen'),
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
    return AlertDialog(
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
        TextButton(
          onPressed: () => Clipboard.setData(ClipboardData(text: key)),
          child: const Text('Schlüssel kopieren'),
        ),
        FilledButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Fertig'),
        ),
      ],
    );
  }
}
