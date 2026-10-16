import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_compass/flutter_compass.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';

import '../core/api.dart';
import '../core/geo.dart';
import '../core/models.dart';
import '../state/providers.dart';

enum AzimuthRef { trueNorth, magnetic }

const sigmaPresets = <({String label, double sigma})>[
  (label: 'scharf ±5°', sigma: 5),
  (label: 'mittel ±15°', sigma: 15),
  (label: 'schlecht ±30°', sigma: 30),
];

/// Bottom sheet to record one bearing with big, one-handed controls.
class CaptureSheet extends ConsumerStatefulWidget {
  const CaptureSheet({super.key, this.compassHeading});

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

  @override
  void initState() {
    super.initState();
    final stream =
        widget.compassHeading ??
        (kIsWeb ? null : FlutterCompass.events?.map((e) => e.heading));
    stream?.listen((h) {
      if (mounted) setState(() => _liveHeading = h);
    });
  }

  @override
  void dispose() {
    for (final c in [_azimuth, _declination, _rssi, _attenuation, _note]) {
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

  void _useCompass() {
    final h = _liveHeading;
    if (h == null) return;
    setState(() {
      _azimuth.text = normalizeAzimuth(h).round().toString();
      _ref = AzimuthRef.magnetic;
    });
  }

  Future<void> _save() async {
    final fix = ref.read(ownPositionProvider);
    final az = _trueAzimuth;
    if (az == null) {
      setState(() => _error = 'Azimut 0–360° eingeben');
      return;
    }
    if (fix == null) {
      setState(() => _error = 'Noch kein Standort verfügbar');
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    final session = ref.read(sessionProvider)!;
    final payload = <String, dynamic>{
      'id': const Uuid().v4(),
      'lat': fix.point.latitude,
      'lon': fix.point.longitude,
      'station_accuracy_m': fix.accuracyM,
      'azimuth_true_deg': double.parse(az.toStringAsFixed(2)) % 360,
      'azimuth_input_ref': _ref == AzimuthRef.trueNorth ? 'true' : 'magnetic',
      'declination_deg_applied': _ref == AzimuthRef.magnetic
          ? _declinationValue
          : 0.0,
      'sigma_deg': _sigma,
      'polarization': _polarization,
      'measured_at': DateTime.now().toUtc().toIso8601String(),
      if (_rssi.text.trim().isNotEmpty)
        'rssi_dbm': double.tryParse(_rssi.text.trim().replaceAll(',', '.')),
      if (_attenuation.text.trim().isNotEmpty)
        'attenuation_db':
            double.tryParse(_attenuation.text.trim().replaceAll(',', '.')) ?? 0,
      if (_note.text.trim().isNotEmpty) 'note': _note.text.trim(),
    };
    try {
      await ref.read(apiProvider).postBearing(payload);
      ref
          .read(missionProvider.notifier)
          .addLocalBearing(
            Bearing(
              id: payload['id'] as String,
              participantId: session.participantId,
              station: fix.point,
              azimuthTrueDeg: payload['azimuth_true_deg'] as double,
              sigmaDeg: _sigma,
              measuredAt: DateTime.parse(payload['measured_at'] as String),
              isOutlier: false,
              isActive: true,
            ),
          );
      if (mounted) Navigator.of(context).pop(true);
    } on ApiException catch (e) {
      setState(() {
        _saving = false;
        _error = e.message;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final fix = ref.watch(ownPositionProvider);
    final theme = Theme.of(context);
    final az = _trueAzimuth;
    return Padding(
      padding: EdgeInsets.only(
        left: 16,
        right: 16,
        top: 8,
        bottom: MediaQuery.of(context).viewInsets.bottom + 16,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Flexible(
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text('Peilung erfassen', style: theme.textTheme.titleLarge),
                  const SizedBox(height: 4),
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
                          decoration: const InputDecoration(
                            labelText: 'Azimut in °',
                            border: OutlineInputBorder(),
                          ),
                          onChanged: (_) => setState(() {}),
                        ),
                      ),
                      if (!kIsWeb || widget.compassHeading != null) ...[
                        const SizedBox(width: 8),
                        SizedBox(
                          height: 64,
                          child: FilledButton.tonalIcon(
                            key: const Key('use-compass'),
                            onPressed: _liveHeading == null
                                ? null
                                : _useCompass,
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
                    onSelectionChanged: (s) => setState(() => _ref = s.first),
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
                        helperText: 'Automatische Missweisung folgt in Phase 2',
                        border: OutlineInputBorder(),
                      ),
                      onChanged: (_) => setState(() {}),
                    ),
                  ],
                  if (az != null && _ref == AzimuthRef.magnetic)
                    Padding(
                      padding: const EdgeInsets.only(top: 4),
                      child: Text('→ rechtweisend ${az.toStringAsFixed(1)}°'),
                    ),
                  const SizedBox(height: 12),
                  Text(
                    'Genauigkeit (Sigma)',
                    style: theme.textTheme.labelLarge,
                  ),
                  const SizedBox(height: 4),
                  Wrap(
                    spacing: 8,
                    children: [
                      for (final p in sigmaPresets)
                        ChoiceChip(
                          key: Key('sigma-${p.sigma.round()}'),
                          label: Padding(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 6,
                              vertical: 10,
                            ),
                            child: Text(p.label),
                          ),
                          selected: _sigma == p.sigma,
                          onSelected: (_) => setState(() => _sigma = p.sigma),
                        ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      Expanded(
                        child: TextField(
                          key: const Key('rssi'),
                          controller: _rssi,
                          keyboardType: const TextInputType.numberWithOptions(
                            decimal: true,
                            signed: true,
                          ),
                          decoration: const InputDecoration(
                            labelText: 'RSSI dBm',
                            border: OutlineInputBorder(),
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: TextField(
                          key: const Key('attenuation'),
                          controller: _attenuation,
                          keyboardType: const TextInputType.numberWithOptions(
                            decimal: true,
                          ),
                          decoration: const InputDecoration(
                            labelText: 'Dämpfung dB',
                            border: OutlineInputBorder(),
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
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
                    decoration: const InputDecoration(
                      labelText: 'Notiz',
                      border: OutlineInputBorder(),
                    ),
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
          ),
          const SizedBox(height: 12),
          // Pinned below the scrollable form so it is always one thumb tap away.
          SizedBox(
            height: 64,
            child: FilledButton(
              key: const Key('save-bearing'),
              onPressed: _saving ? null : _save,
              child: _saving
                  ? const CircularProgressIndicator()
                  : const Text('Speichern', style: TextStyle(fontSize: 22)),
            ),
          ),
        ],
      ),
    );
  }
}
