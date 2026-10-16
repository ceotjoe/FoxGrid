import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:latlong2/latlong.dart';

import '../core/homing.dart';
import '../core/models.dart';
import '../core/signal.dart';
import '../state/providers.dart';
import 'app_tile_layer.dart';
import 'rssi_chart.dart';

/// Close-range homing: arrow and distance to the estimated emitter, signal strength history,
/// quick entry of S-meter values and the own track coloured by field strength.
class HomingScreen extends ConsumerStatefulWidget {
  const HomingScreen({super.key});

  @override
  ConsumerState<HomingScreen> createState() => _HomingScreenState();
}

class _HomingScreenState extends ConsumerState<HomingScreen> {
  final _dbm = TextEditingController();
  final _map = MapController();
  Timer? _auto;
  bool _autoLog = false;
  double? _lastDbm; // last value typed or tapped, repeated by auto logging

  @override
  void dispose() {
    _auto?.cancel();
    _dbm.dispose();
    super.dispose();
  }

  Future<void> _log(double dbm) async {
    final fix = ref.read(ownPositionProvider);
    if (fix == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Noch kein Standort verfügbar')),
      );
      return;
    }
    _lastDbm = dbm;
    await ref
        .read(missionProvider.notifier)
        .logRssi(
          rssiDbm: dbm,
          at: fix,
          attenuationDb: ref.read(attenuationProvider).toDouble(),
        );
    if (mounted) setState(() {});
  }

  void _setAuto(bool on) {
    _auto?.cancel();
    setState(() => _autoLog = on);
    if (on) {
      _auto = Timer.periodic(const Duration(seconds: 2), (_) {
        final v = _lastDbm;
        if (v != null) _log(v);
      });
    }
  }

  Estimate? _estimate(MissionState s) =>
      s.estimates['current'] ?? s.estimates['all'];

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(missionProvider);
    final session = ref.watch(sessionProvider)!;
    final own = ref.watch(ownPositionProvider);
    final heading = ref.watch(headingProvider);
    final attenuation = ref.watch(attenuationProvider);
    final estimate = _estimate(state);
    final theme = Theme.of(context);

    final mine = state.rssi
        .where((r) => r.participantId == session.participantId)
        .toList();
    final recent = mine.length > 60 ? mine.sublist(mine.length - 60) : mine;
    final levels = recent.map((r) => r.correctedDbm).toList();

    final HomingGuidance? g = (estimate != null && own != null)
        ? guidance(
            own: own.point,
            target: estimate.point,
            semiMajor1sM: estimate.ellipse1s.semiMajorM,
            semiMajor2sM: estimate.ellipse2s.semiMajorM,
            headingDeg: heading,
          )
        : null;

    return Scaffold(
      appBar: AppBar(title: const Text('Nahpeilung')),
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: ListView(
                padding: const EdgeInsets.all(12),
                children: [
                  _GuidanceCard(
                    guidance: g,
                    hasHeading: heading != null,
                    estimate: estimate,
                    hasOwn: own != null,
                  ),
                  const SizedBox(height: 12),
                  Text(
                    levels.isEmpty
                        ? 'Signalpegel'
                        : 'Signalpegel: ${levels.last.round()} dBm (${dbmToSLabel(levels.last)}), '
                              'am Antenne',
                    key: const Key('rssi-current'),
                    style: theme.textTheme.titleMedium,
                  ),
                  const SizedBox(height: 4),
                  RssiChart(levels: levels),
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      Expanded(
                        child: TextField(
                          key: const Key('rssi-dbm'),
                          controller: _dbm,
                          keyboardType: const TextInputType.numberWithOptions(
                            decimal: true,
                            signed: true,
                          ),
                          decoration: const InputDecoration(
                            labelText: 'Pegel in dBm',
                            border: OutlineInputBorder(),
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      SizedBox(
                        height: 56,
                        child: FilledButton(
                          key: const Key('log-dbm'),
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
                  SwitchListTile(
                    key: const Key('auto-log'),
                    contentPadding: EdgeInsets.zero,
                    title: const Text('Letzten Wert alle 2 s mitschreiben'),
                    subtitle: const Text(
                      'Praktisch beim Gehen mit konstantem S-Meter',
                    ),
                    value: _autoLog,
                    onChanged: _lastDbm == null && !_autoLog ? null : _setAuto,
                  ),
                  if (estimate?.rssi != null)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Text(
                        'Pegelmodell: n = ${estimate!.rssi!.exponent.toStringAsFixed(1)}, '
                        'P0 = ${estimate.rssi!.p0Dbm.round()} dBm bei 1 m, '
                        'Streuung ${estimate.rssi!.residualDb.toStringAsFixed(1)} dB '
                        '(${estimate.rssi!.nSamples} Messwerte)',
                        key: const Key('rssi-model'),
                        style: theme.textTheme.bodySmall,
                      ),
                    ),
                  SizedBox(
                    height: 280,
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(12),
                      child: _TrackMap(
                        controller: _map,
                        samples: state.rssi,
                        own: own,
                        estimate: estimate,
                      ),
                    ),
                  ),
                ],
              ),
            ),
            _EntryPanel(
              attenuation: attenuation,
              onLog: _log,
              onAttenuation: (db) =>
                  ref.read(attenuationProvider.notifier).set(db),
            ),
          ],
        ),
      ),
    );
  }
}

/// Always visible while walking: one tap logs an S-meter value, the attenuator is one tap away.
class _EntryPanel extends StatelessWidget {
  const _EntryPanel({
    required this.attenuation,
    required this.onLog,
    required this.onAttenuation,
  });

  final int attenuation;
  final void Function(double dbm) onLog;
  final void Function(int db) onAttenuation;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Material(
      elevation: 8,
      color: theme.colorScheme.surface,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                children: [
                  for (final q in quickReadings)
                    Padding(
                      padding: const EdgeInsets.only(right: 8),
                      child: SizedBox(
                        width: 84,
                        height: 56,
                        child: FilledButton.tonal(
                          key: Key('quick-${q.label}'),
                          onPressed: () => onLog(q.dbm),
                          child: Text(
                            q.label,
                            style: const TextStyle(fontSize: 18),
                          ),
                        ),
                      ),
                    ),
                ],
              ),
            ),
            const SizedBox(height: 6),
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                children: [
                  Text('Dämpfung:', style: theme.textTheme.labelLarge),
                  const SizedBox(width: 8),
                  for (final db in attenuatorSteps)
                    Padding(
                      padding: const EdgeInsets.only(right: 8),
                      child: ChoiceChip(
                        key: Key('att-$db'),
                        label: Text(db == 0 ? 'aus' : '$db dB'),
                        selected: attenuation == db,
                        onSelected: (_) => onAttenuation(db),
                      ),
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _GuidanceCard extends StatelessWidget {
  const _GuidanceCard({
    required this.guidance,
    required this.hasHeading,
    required this.estimate,
    required this.hasOwn,
  });

  final HomingGuidance? guidance;
  final bool hasHeading;
  final Estimate? estimate;
  final bool hasOwn;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final g = guidance;
    if (g == null) {
      return Card(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text(
            estimate == null
                ? 'Noch keine Schätzung. Erfasse Peilungen oder Messwerte.'
                : 'Warte auf deinen Standort …',
            key: const Key('guidance-empty'),
            style: theme.textTheme.titleMedium,
          ),
        ),
      );
    }
    final inside = g.insideOneSigma
        ? 'Im 1σ-Bereich: Quelle ist ganz in der Nähe'
        : g.insideTwoSigma
        ? 'Im 2σ-Bereich der Schätzung'
        : null;
    return Card(
      color: g.insideOneSigma ? Colors.green.withValues(alpha: 0.25) : null,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          children: [
            Transform.rotate(
              key: const Key('arrow'),
              angle: g.arrowDeg * math.pi / 180,
              child: Icon(
                Icons.navigation,
                size: 140,
                color: theme.colorScheme.primary,
              ),
            ),
            Text(
              formatDistance(g.distanceM),
              key: const Key('distance'),
              style: theme.textTheme.displayMedium,
            ),
            Text(
              'Peilung ${g.bearingDeg.round()}° rechtweisend · '
              'Schätzung ±${estimate!.ellipse1s.semiMajorM.round()} m (1σ)',
              key: const Key('bearing-text'),
              textAlign: TextAlign.center,
            ),
            if (inside != null)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(
                  inside,
                  key: const Key('inside'),
                  style: theme.textTheme.titleSmall,
                ),
              ),
            if (!hasHeading)
              const Padding(
                padding: EdgeInsets.only(top: 6),
                child: Text(
                  'Keine Blickrichtung verfügbar: Pfeil zeigt relativ zu Norden.',
                  key: Key('no-heading'),
                  textAlign: TextAlign.center,
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _TrackMap extends ConsumerWidget {
  const _TrackMap({
    required this.controller,
    required this.samples,
    required this.own,
    required this.estimate,
  });

  final MapController controller;
  final List<RssiSample> samples;
  final PositionFix? own;
  final Estimate? estimate;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final points = [
      for (final s in samples) s.point,
      if (own != null) own!.point,
      if (estimate != null) estimate!.point,
    ];
    final (lo, hi) = levelRange(samples.map((s) => s.correctedDbm));
    return FlutterMap(
      mapController: controller,
      options: MapOptions(
        initialCenter: points.isEmpty ? const LatLng(51.0, 10.0) : points.last,
        initialZoom: points.isEmpty ? 5 : 15,
        initialCameraFit: points.length >= 2
            ? CameraFit.coordinates(
                coordinates: points,
                padding: const EdgeInsets.all(32),
                maxZoom: 17,
              )
            : null,
      ),
      children: [
        const AppTileLayer(),
        if (own != null && estimate != null)
          PolylineLayer(
            polylines: [
              Polyline(
                points: [own!.point, estimate!.point],
                strokeWidth: 2,
                color: Colors.red.withValues(alpha: 0.6),
                pattern: StrokePattern.dashed(segments: const [8, 8]),
              ),
            ],
          ),
        if (estimate != null)
          PolygonLayer(
            polygons: [
              Polygon(
                points: estimate!.ellipse1s.ring,
                color: Colors.red.withValues(alpha: 0.18),
                borderColor: Colors.red,
                borderStrokeWidth: 2,
              ),
            ],
          ),
        CircleLayer(
          circles: [
            for (final s
                in samples.length > 400
                    ? samples.sublist(samples.length - 400)
                    : samples)
              CircleMarker(
                point: s.point,
                radius: 6,
                color: rssiColor(s.correctedDbm, min: lo, max: hi),
                borderColor: Colors.white,
                borderStrokeWidth: 1,
              ),
          ],
        ),
        MarkerLayer(
          markers: [
            if (estimate != null)
              Marker(
                point: estimate!.point,
                width: 40,
                height: 40,
                child: const Icon(Icons.gps_fixed, color: Colors.red, size: 36),
              ),
            if (own != null)
              Marker(
                point: own!.point,
                width: 36,
                height: 36,
                child: const Icon(
                  Icons.navigation,
                  color: Colors.blue,
                  size: 32,
                ),
              ),
          ],
        ),
      ],
    );
  }
}
