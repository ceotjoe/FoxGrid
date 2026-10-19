import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/radio/protocols.dart';
import '../state/providers.dart';
import '../state/settings.dart';
import '../state/tiles.dart';

class SettingsScreen extends ConsumerStatefulWidget {
  const SettingsScreen({super.key});

  @override
  ConsumerState<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends ConsumerState<SettingsScreen> {
  late final TextEditingController _tiles;
  int _extraZoom = 2;

  @override
  void initState() {
    super.initState();
    _tiles = TextEditingController(
      text: ref.read(settingsProvider).customTileUrl,
    );
  }

  @override
  void dispose() {
    _tiles.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final settings = ref.watch(settingsProvider);
    final notifier = ref.read(settingsProvider.notifier);
    final view = ref.watch(mapViewProvider);
    final download = ref.watch(regionDownloadProvider);
    final downloader = ref.read(regionDownloadProvider.notifier);
    final declination = ref.watch(declinationProvider);
    final theme = Theme.of(context);
    final estimate = view == null ? 0 : downloader.estimate(view, _extraZoom);

    return Scaffold(
      appBar: AppBar(title: const Text('Einstellungen')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text('Darstellung', style: theme.textTheme.titleMedium),
          const SizedBox(height: 8),
          SegmentedButton<ThemeMode>(
            key: const Key('theme-mode'),
            segments: const [
              ButtonSegment(value: ThemeMode.system, label: Text('System')),
              ButtonSegment(value: ThemeMode.light, label: Text('Hell')),
              ButtonSegment(value: ThemeMode.dark, label: Text('Dunkel')),
            ],
            selected: {settings.themeMode},
            onSelectionChanged: (v) => notifier.setThemeMode(v.first),
          ),
          const SizedBox(height: 8),
          SwitchListTile(
            key: const Key('night-mode'),
            title: const Text('Nachtmodus (rot)'),
            subtitle: const Text(
              'Dunkles rotes Farbschema, schont die Nachtsicht',
            ),
            value: settings.nightMode,
            onChanged: notifier.setNight,
          ),
          const Divider(),
          Text('Karte', style: theme.textTheme.titleMedium),
          const SizedBox(height: 8),
          SegmentedButton<BaseMap>(
            segments: const [
              ButtonSegment(value: BaseMap.osm, label: Text('OSM')),
              ButtonSegment(value: BaseMap.topo, label: Text('Topo')),
              ButtonSegment(
                value: BaseMap.custom,
                label: Text('Eigener Server'),
              ),
            ],
            selected: {settings.baseMap},
            onSelectionChanged: (s) => notifier.setBaseMap(s.first),
          ),
          const SizedBox(height: 12),
          TextField(
            key: const Key('tile-url'),
            controller: _tiles,
            decoration: const InputDecoration(
              labelText: 'Eigener Tile-Server',
              hintText: 'https://tiles.example.org/{z}/{x}/{y}.png',
              border: OutlineInputBorder(),
            ),
            onChanged: notifier.setCustomTileUrl,
          ),
          const SizedBox(height: 16),
          Text(
            'Kartenausschnitt offline laden',
            style: theme.textTheme.titleMedium,
          ),
          const SizedBox(height: 4),
          Text(
            'Angesehene Kacheln werden automatisch zwischengespeichert. Ein '
            'gezielter Download ist nur mit eigenem Tile-Server erlaubt; die '
            'öffentlichen OSM-Server untersagen Massen-Downloads.',
            style: theme.textTheme.bodySmall,
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              const Text('Zusätzliche Zoomstufen:'),
              Expanded(
                child: Slider(
                  value: _extraZoom.toDouble(),
                  min: 0,
                  max: 4,
                  divisions: 4,
                  label: '$_extraZoom',
                  onChanged: (v) => setState(() => _extraZoom = v.round()),
                ),
              ),
            ],
          ),
          Text(
            view == null
                ? 'Öffne zuerst die Karte, um einen Ausschnitt zu wählen.'
                : 'Aktueller Ausschnitt: ca. $estimate Kacheln (max. $maxDownloadTiles)',
          ),
          const SizedBox(height: 8),
          if (download.running) ...[
            LinearProgressIndicator(
              value: download.total == 0
                  ? null
                  : download.done / download.total,
            ),
            const SizedBox(height: 8),
            OutlinedButton(
              onPressed: downloader.cancel,
              child: const Text('Abbrechen'),
            ),
          ] else
            FilledButton.icon(
              key: const Key('download-region'),
              onPressed: view == null
                  ? null
                  : () => downloader.start(view, _extraZoom),
              icon: const Icon(Icons.download),
              label: const Text('Ausschnitt laden'),
            ),
          if (download.message != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(download.message!),
            ),
          const Divider(height: 32),
          Text('Funkgerät (CAT-S-Meter)', style: theme.textTheme.titleMedium),
          const SizedBox(height: 8),
          DropdownButtonFormField<String?>(
            key: const Key('radio-profile'),
            initialValue: settings.radioId,
            decoration: const InputDecoration(
              labelText: 'Funkgerät',
              border: OutlineInputBorder(),
            ),
            items: [
              const DropdownMenuItem(
                value: null,
                child: Text('keins (manuelle Eingabe)'),
              ),
              for (final p in radioProfiles)
                DropdownMenuItem(value: p.id, child: Text(p.name)),
            ],
            onChanged: notifier.setRadio,
          ),
          const SizedBox(height: 8),
          TextFormField(
            key: const Key('radio-offset'),
            initialValue: settings.radioOffsetDb.toString(),
            keyboardType: const TextInputType.numberWithOptions(
              decimal: true,
              signed: true,
            ),
            decoration: const InputDecoration(
              labelText: 'Kalibrierung in dB',
              helperText: 'Wird auf den S-Meter-Pegel des Geräts addiert',
              border: OutlineInputBorder(),
            ),
            onChanged: (v) {
              final d = double.tryParse(v.replaceAll(',', '.'));
              if (d != null) notifier.setRadioOffset(d);
            },
          ),
          const SizedBox(height: 4),
          Text(
            'Protokolle (Icom CI-V, Kenwood/Yaesu CAT) und Kalibrierung sind vorbereitet. '
            'Die Verbindung per USB-OTG oder Bluetooth braucht ein Transport-Plugin und ist '
            'in dieser Version noch nicht enthalten; bis dahin gibst du Werte von Hand ein.',
            key: const Key('radio-note'),
            style: theme.textTheme.bodySmall,
          ),
          const Divider(height: 32),
          Text('Missweisung', style: theme.textTheme.titleMedium),
          Text(
            declination == null
                ? 'Noch nicht geladen (wird beim ersten Standort online abgerufen).'
                : 'Zuletzt abgerufen: ${declination.toStringAsFixed(1)}° '
                      '(WMM, positiv = magnetisch Nord liegt östlich)',
          ),
        ],
      ),
    );
  }
}
