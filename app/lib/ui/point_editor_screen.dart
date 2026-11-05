import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:latlong2/latlong.dart';

import '../core/coords.dart';
import '../state/providers.dart';
import 'app_tile_layer.dart';

/// Lead only: adds a named external bearing point (e.g. "BNetzA Köln").
///
/// The location is picked on the map, typed in (decimal degrees or degrees and minutes) or
/// taken from the device; the three ways keep one marker and the two fields in sync.
/// Pops with the new point's id.
class PointEditorScreen extends ConsumerStatefulWidget {
  const PointEditorScreen({super.key});

  @override
  ConsumerState<PointEditorScreen> createState() => _PointEditorScreenState();
}

class _PointEditorScreenState extends ConsumerState<PointEditorScreen> {
  final _map = MapController();
  final _name = TextEditingController();
  final _lat = TextEditingController();
  final _lon = TextEditingController();
  final _note = TextEditingController();
  LatLng? _position;
  double? _accuracyM;
  bool _useInEstimate = true;
  bool _showErrors = false;
  bool _saving = false;

  @override
  void dispose() {
    _map.dispose();
    _name.dispose();
    _lat.dispose();
    _lon.dispose();
    _note.dispose();
    super.dispose();
  }

  LatLng get _initialCenter {
    final state = ref.read(missionProvider);
    return ref.read(ownPositionProvider)?.point ??
        state.mission?.searchArea?.first ??
        const LatLng(51.0, 10.0);
  }

  /// Sets marker and fields from a map tap or the device location.
  void _pick(LatLng p, {double? accuracyM}) {
    setState(() {
      _position = p;
      _accuracyM = accuracyM;
      _lat.text = p.latitude.toStringAsFixed(5);
      _lon.text = p.longitude.toStringAsFixed(5);
    });
  }

  /// Reads the typed fields; the marker follows once both are valid.
  void _typed() {
    final la = parseCoordinate(_lat.text, isLat: true);
    final lo = parseCoordinate(_lon.text, isLat: false);
    setState(() {
      _accuracyM = null;
      _position = (la != null && lo != null) ? LatLng(la, lo) : null;
    });
    final p = _position;
    if (p != null) _map.move(p, _map.camera.zoom);
  }

  void _useDevice() {
    final fix = ref.read(ownPositionProvider);
    if (fix == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Noch kein Standort verfügbar')),
      );
      return;
    }
    _pick(fix.point, accuracyM: fix.accuracyM);
    _map.move(fix.point, _map.camera.zoom < 13 ? 15 : _map.camera.zoom);
  }

  String? _nameError() {
    final name = _name.text.trim();
    if (name.isEmpty) return 'Name fehlt';
    if (name.length > 60) return 'Höchstens 60 Zeichen';
    final taken = ref
        .read(missionProvider)
        .points
        .values
        .any((p) => p.name.toLowerCase() == name.toLowerCase());
    return taken ? 'Diesen Namen gibt es schon' : null;
  }

  String? _coordError(TextEditingController c, {required bool isLat}) {
    if (c.text.trim().isEmpty) return 'Fehlt';
    return parseCoordinate(c.text, isLat: isLat) == null
        ? 'Ungültig (z. B. 50.9 oder 50° 54.5\' N)'
        : null;
  }

  Future<void> _save() async {
    setState(() => _showErrors = true);
    final p = _position;
    if (_nameError() != null || p == null) return;
    setState(() => _saving = true);
    final note = _note.text.trim();
    final id = await ref
        .read(missionProvider.notifier)
        .createPoint(
          name: _name.text,
          position: p,
          accuracyM: _accuracyM,
          note: note.isEmpty ? null : note,
          useInEstimate: _useInEstimate,
        );
    if (mounted) Navigator.of(context).pop(id);
  }

  @override
  Widget build(BuildContext context) {
    final p = _position;
    final latError = _showErrors || _lat.text.isNotEmpty
        ? _coordError(_lat, isLat: true)
        : null;
    final lonError = _showErrors || _lon.text.isNotEmpty
        ? _coordError(_lon, isLat: false)
        : null;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Neuer Peilpunkt'),
        actions: [
          TextButton(
            key: const Key('point-save'),
            onPressed: _saving ? null : _save,
            child: const Text('Speichern'),
          ),
        ],
      ),
      body: Column(
        children: [
          SizedBox(
            height: 260,
            child: FlutterMap(
              mapController: _map,
              options: MapOptions(
                initialCenter: _initialCenter,
                initialZoom: ref.read(ownPositionProvider) != null ? 13 : 7,
                interactionOptions: const InteractionOptions(
                  flags: InteractiveFlag.all & ~InteractiveFlag.rotate,
                ),
                onTap: (_, point) => _pick(point),
              ),
              children: [
                const AppTileLayer(),
                if (p != null)
                  MarkerLayer(
                    markers: [
                      Marker(
                        point: p,
                        width: 44,
                        height: 44,
                        alignment: Alignment.topCenter,
                        child: Icon(
                          Icons.location_on,
                          key: const Key('point-marker'),
                          size: 44,
                          color: Theme.of(context).colorScheme.error,
                        ),
                      ),
                    ],
                  ),
              ],
            ),
          ),
          Expanded(
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                Text(
                  'Auf die Karte tippen, Koordinaten eingeben oder den '
                  'Gerätestandort nehmen.',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                const SizedBox(height: 12),
                TextField(
                  key: const Key('point-name'),
                  controller: _name,
                  maxLength: 60,
                  // Names like "BNetzA" must not be "corrected" by the keyboard.
                  autocorrect: false,
                  enableSuggestions: false,
                  textCapitalization: TextCapitalization.sentences,
                  decoration: InputDecoration(
                    labelText: 'Name',
                    hintText: 'z. B. BNetzA Köln',
                    border: const OutlineInputBorder(),
                    // Once saving, the new point itself would count as a duplicate.
                    errorText: _showErrors && !_saving ? _nameError() : null,
                  ),
                ),
                const SizedBox(height: 4),
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      child: TextField(
                        key: const Key('point-lat'),
                        controller: _lat,
                        onChanged: (_) => _typed(),
                        keyboardType: TextInputType.text,
                        decoration: InputDecoration(
                          labelText: 'Breite',
                          border: const OutlineInputBorder(),
                          errorText: latError,
                          errorMaxLines: 2,
                        ),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: TextField(
                        key: const Key('point-lon'),
                        controller: _lon,
                        onChanged: (_) => _typed(),
                        keyboardType: TextInputType.text,
                        decoration: InputDecoration(
                          labelText: 'Länge',
                          border: const OutlineInputBorder(),
                          errorText: lonError,
                          errorMaxLines: 2,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                Align(
                  alignment: Alignment.centerLeft,
                  child: OutlinedButton.icon(
                    key: const Key('point-use-device'),
                    onPressed: _useDevice,
                    icon: const Icon(Icons.my_location),
                    label: const Text('Mein Standort'),
                  ),
                ),
                if (p != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(
                      '${formatCoordinate(p.latitude, isLat: true)}   '
                      '${formatCoordinate(p.longitude, isLat: false)}',
                      key: const Key('point-dm'),
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ),
                if (_showErrors && p == null && latError == null)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(
                      'Standort wählen',
                      key: const Key('point-no-position'),
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.error,
                      ),
                    ),
                  ),
                const SizedBox(height: 12),
                TextField(
                  key: const Key('point-note'),
                  controller: _note,
                  maxLength: 1000,
                  decoration: const InputDecoration(
                    labelText: 'Notiz (optional)',
                    border: OutlineInputBorder(),
                  ),
                ),
                SwitchListTile(
                  key: const Key('point-use-in-estimate'),
                  contentPadding: EdgeInsets.zero,
                  title: const Text('In Schätzung einbeziehen'),
                  subtitle: const Text(
                    'Aus: Peilungen bleiben sichtbar, verschieben das '
                    'Ergebnis aber nicht. Später umschaltbar.',
                  ),
                  value: _useInEstimate,
                  onChanged: (v) => setState(() => _useInEstimate = v),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
