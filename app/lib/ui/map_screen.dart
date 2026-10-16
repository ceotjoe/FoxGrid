import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:latlong2/latlong.dart';

import '../core/geo.dart';
import '../core/live.dart';
import '../core/models.dart';
import '../core/save_file.dart';
import '../core/signal.dart';
import '../core/session.dart';
import '../state/filter.dart';
import '../state/providers.dart';
import '../state/settings.dart';
import '../state/tiles.dart';
import 'app_tile_layer.dart';
import 'bearings_sheet.dart';
import 'capture_sheet.dart';
import 'chat_screen.dart';
import 'filter_sheet.dart';
import 'homing_screen.dart';
import 'settings_screen.dart';
import 'sync_sheet.dart';
import 'tasks_screen.dart';

const _rayLengthM = 25000.0;
const _palette = [
  Colors.indigo,
  Colors.teal,
  Colors.deepOrange,
  Colors.purple,
  Colors.brown,
  Colors.blueGrey,
  Colors.pink,
  Colors.green,
];

Color participantColor(String id) =>
    _palette[id.hashCode.abs() % _palette.length];

class MapScreen extends ConsumerStatefulWidget {
  const MapScreen({super.key});

  @override
  ConsumerState<MapScreen> createState() => _MapScreenState();
}

class _MapScreenState extends ConsumerState<MapScreen> {
  final _controller = MapController();
  bool _centered = false;
  bool _fitted = false;
  bool _declinationRequested = false;

  /// Everything worth showing: estimate area, bearing stations and participants.
  List<LatLng> _interestingPoints(MissionState state, Estimate? estimate) => [
    if (estimate != null) ...estimate.ellipse2s.ring,
    for (final b in state.bearings.values) b.station,
    for (final p in state.positions.values) p.point,
  ];

  void _fit(List<LatLng> points) {
    if (points.length < 2) return;
    _controller.fitCamera(
      CameraFit.coordinates(
        coordinates: points,
        padding: const EdgeInsets.fromLTRB(48, 160, 48, 120),
        maxZoom: 16,
      ),
    );
  }

  void _openCapture() {
    showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => const CaptureSheet(),
    );
  }

  void _showInvite(Session session) {
    final token = session.inviteToken;
    if (token == null) return;
    final link = inviteLink(session.baseUrl, token);
    showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Einladung'),
        content: SelectableText('Token: $token\n\nLink: $link'),
        actions: [
          TextButton(
            onPressed: () => Clipboard.setData(ClipboardData(text: link)),
            child: const Text('Link kopieren'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Schließen'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    ref.watch(positionReporterProvider);
    final session = ref.watch(sessionProvider)!;
    final state = ref.watch(missionProvider);
    final own = ref.watch(ownPositionProvider);
    final scope = ref.watch(estimateScopeProvider);
    final theme = Theme.of(context);
    final running = state.running;
    ref.watch(
      syncProvider,
    ); // keeps the offline queue running while the map is open
    final settings = ref.watch(settingsProvider);
    final filter = ref.watch(filterProvider);
    final filtered = ref.watch(filteredEstimateProvider).value;
    final liveEstimate =
        state.estimates[scope.name] ??
        state.estimates[scope == EstimateScope.current ? 'all' : 'current'];
    final estimate = filter.needsQuery ? filtered : liveEstimate;

    ref.listen<String?>(missionProvider.select((s) => s.error), (_, error) {
      if (error != null) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(error)));
        ref.read(missionProvider.notifier).clearError();
      }
    });

    final interesting = _interestingPoints(state, estimate);
    if (!_fitted && state.loaded && interesting.length >= 2) {
      _fitted = true;
      _centered = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _fit(interesting);
      });
    }
    if (own != null && !_declinationRequested) {
      _declinationRequested = true;
      Future.microtask(
        () => ref.read(declinationProvider.notifier).refresh(own.point),
      );
    }
    if (own != null && !_centered && state.loaded) {
      _centered = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _controller.move(own.point, 13);
      });
    }

    final now = DateTime.now().toUtc();

    return Scaffold(
      appBar: AppBar(
        title: Text(
          state.mission == null
              ? 'FoxGrid'
              : '${state.mission!.name} · '
                    '${state.mission!.frequencyMhz.toStringAsFixed(3)} MHz',
        ),
        actions: [
          _ConnectionDot(status: state.connection),
          const SyncChip(),
          IconButton(
            key: const Key('open-chat'),
            tooltip: 'Chat',
            icon: const Icon(Icons.chat_bubble_outline),
            onPressed: () => Navigator.of(
              context,
            ).push(MaterialPageRoute<void>(builder: (_) => const ChatScreen())),
          ),
          IconButton(
            key: const Key('open-tasks'),
            tooltip: 'Aufgaben',
            icon: const Icon(Icons.checklist),
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(builder: (_) => const TasksScreen()),
            ),
          ),
          IconButton(
            key: const Key('open-filter'),
            tooltip: 'Filter',
            icon: Badge(
              isLabelVisible: filter.needsQuery || filter.hideOutliers,
              child: const Icon(Icons.filter_alt_outlined),
            ),
            onPressed: () => showModalBottomSheet<void>(
              context: context,
              isScrollControlled: true,
              showDragHandle: true,
              builder: (_) => const FilterSheet(),
            ),
          ),
          IconButton(
            key: const Key('open-homing'),
            tooltip: 'Nahpeilung',
            icon: const Icon(Icons.explore),
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(builder: (_) => const HomingScreen()),
            ),
          ),
          PopupMenuButton<String>(
            onSelected: (v) {
              switch (v) {
                case 'leave':
                  ref.read(sessionProvider.notifier).leave();
                case 'invite':
                  _showInvite(session);
                case 'bearings':
                  showModalBottomSheet<void>(
                    context: context,
                    isScrollControlled: true,
                    showDragHandle: true,
                    builder: (_) => const BearingsSheet(),
                  );
                case 'settings':
                  Navigator.of(context).push(
                    MaterialPageRoute<void>(
                      builder: (_) => const SettingsScreen(),
                    ),
                  );
                default:
                  _export(v);
              }
            },
            itemBuilder: (_) => [
              const PopupMenuItem(
                value: 'bearings',
                child: Text('Peilungen (Liste)'),
              ),
              if (session.inviteToken != null)
                const PopupMenuItem(value: 'invite', child: Text('Einladung')),
              const PopupMenuItem(
                value: 'settings',
                child: Text('Einstellungen'),
              ),
              const PopupMenuItem(
                value: 'pdf',
                child: Text('Export: PDF-Protokoll'),
              ),
              const PopupMenuItem(value: 'gpx', child: Text('Export: GPX')),
              const PopupMenuItem(value: 'kml', child: Text('Export: KML')),
              const PopupMenuItem(value: 'json', child: Text('Export: JSON')),
              const PopupMenuItem(
                value: 'leave',
                child: Text('Einsatz verlassen'),
              ),
            ],
          ),
        ],
      ),
      body: Stack(
        children: [
          FlutterMap(
            mapController: _controller,
            options: MapOptions(
              initialCenter:
                  state.mission?.searchArea?.first ?? const LatLng(51.0, 10.0),
              initialZoom: state.mission?.searchArea != null ? 11 : 6,
              interactionOptions: const InteractionOptions(
                flags: InteractiveFlag.all & ~InteractiveFlag.rotate,
              ),
              onPositionChanged: (camera, _) {
                final b = camera.visibleBounds;
                Future.microtask(
                  () => ref
                      .read(mapViewProvider.notifier)
                      .update(MapView(b.southWest, b.northEast, camera.zoom)),
                );
              },
            ),
            children: [
              const AppTileLayer(),
              if (state.mission?.searchArea != null)
                PolygonLayer(
                  polygons: [
                    Polygon(
                      points: state.mission!.searchArea!,
                      color: Colors.transparent,
                      borderColor: Colors.black54,
                      borderStrokeWidth: 2,
                      pattern: StrokePattern.dashed(segments: const [10, 8]),
                    ),
                  ],
                ),
              if (state.rssi.isNotEmpty) _rssiDots(state.rssi),
              if (estimate != null && filter.showContours)
                PolygonLayer(polygons: _contourPolygons(estimate)),
              if (estimate != null)
                PolygonLayer(
                  polygons: [
                    Polygon(
                      points: estimate.ellipse2s.ring,
                      color: Colors.red.withValues(alpha: 0.08),
                      borderColor: Colors.red.withValues(alpha: 0.6),
                      borderStrokeWidth: 1.5,
                    ),
                    Polygon(
                      points: estimate.ellipse1s.ring,
                      color: Colors.red.withValues(alpha: 0.18),
                      borderColor: Colors.red,
                      borderStrokeWidth: 2,
                    ),
                  ],
                ),
              PolygonLayer(polygons: _fans(state, filter, now)),
              PolylineLayer(polylines: _rays(state, filter, now)),
              PolylineLayer(
                polylines: [
                  for (final e in state.trails.entries)
                    if (e.value.length > 1)
                      Polyline(
                        points: e.value,
                        strokeWidth: 3,
                        color: participantColor(e.key).withValues(alpha: 0.6),
                      ),
                ],
              ),
              MarkerLayer(
                markers: [
                  if (estimate != null)
                    Marker(
                      point: estimate.point,
                      width: 44,
                      height: 44,
                      child: const Icon(
                        Icons.gps_fixed,
                        color: Colors.red,
                        size: 40,
                        key: Key('mle-marker'),
                      ),
                    ),
                  for (final e in state.positions.entries)
                    if (e.key != session.participantId)
                      _participantMarker(
                        e.value.point,
                        state.participants[e.key]?.callsign ?? '?',
                        participantColor(e.key),
                      ),
                  if (own != null)
                    _participantMarker(
                      own.point,
                      session.callsign,
                      Colors.blue,
                      self: true,
                    ),
                ],
              ),
              const RichAttributionWidget(
                attributions: [
                  TextSourceAttribution('© OpenStreetMap-Mitwirkende'),
                  TextSourceAttribution('OpenTopoMap (CC-BY-SA)'),
                ],
              ),
            ],
          ),
          Positioned(
            top: 0,
            left: 0,
            right: 0,
            child: Column(
              children: [
                if (running != null) const _TransmissionBanner(),
                Padding(
                  padding: const EdgeInsets.all(8),
                  child: Row(
                    children: [
                      SegmentedButton<EstimateScope>(
                        showSelectedIcon: false,
                        style: const ButtonStyle(
                          visualDensity: VisualDensity.compact,
                        ),
                        segments: const [
                          ButtonSegment(
                            value: EstimateScope.current,
                            label: Text('Aussendung'),
                          ),
                          ButtonSegment(
                            value: EstimateScope.all,
                            label: Text('Alle'),
                          ),
                        ],
                        selected: {scope},
                        onSelectionChanged: (s) => ref
                            .read(estimateScopeProvider.notifier)
                            .select(s.first),
                      ),
                      const Spacer(),
                      IconButton.filledTonal(
                        key: const Key('fit-all'),
                        tooltip: 'Alles zeigen',
                        icon: const Icon(Icons.center_focus_strong),
                        onPressed: () => _fit(interesting),
                      ),
                      const SizedBox(width: 8),
                      IconButton.filledTonal(
                        tooltip: 'Kartenstil',
                        icon: const Icon(Icons.layers),
                        onPressed: () => _cycleBaseMap(settings),
                      ),
                    ],
                  ),
                ),
                if (estimate != null)
                  Card(
                    child: Padding(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 12,
                        vertical: 6,
                      ),
                      child: Text(
                        'Schätzung aus ${estimate.nBearings} Peilungen · '
                        '1σ ${estimate.ellipse1s.semiMajorM.round()} × '
                        '${estimate.ellipse1s.semiMinorM.round()} m'
                        '${estimate.rssi == null ? '' : ' · n=${estimate.rssi!.exponent.toStringAsFixed(1)}'}',
                        key: const Key('estimate-summary'),
                        style: theme.textTheme.bodyMedium,
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
      floatingActionButtonLocation: FloatingActionButtonLocation.centerFloat,
      floatingActionButton: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          FloatingActionButton.extended(
            key: const Key('toggle-transmission'),
            heroTag: 'tx',
            backgroundColor: running != null
                ? Colors.red
                : theme.colorScheme.secondaryContainer,
            foregroundColor: running != null
                ? Colors.white
                : theme.colorScheme.onSecondaryContainer,
            onPressed: state.mission?.isActive ?? false
                ? ref.read(missionProvider.notifier).toggleTransmission
                : null,
            icon: Icon(running != null ? Icons.stop : Icons.podcasts),
            label: Text(
              running != null ? 'Aussendung Ende' : 'Aussendung Start',
            ),
          ),
          const SizedBox(width: 12),
          FloatingActionButton.large(
            key: const Key('open-capture'),
            heroTag: 'capture',
            onPressed: _openCapture,
            child: const Icon(Icons.my_location),
          ),
        ],
      ),
    );
  }

  Marker _participantMarker(
    LatLng point,
    String callsign,
    Color color, {
    bool self = false,
  }) => Marker(
    point: point,
    width: 96,
    height: 56,
    child: Column(
      children: [
        Icon(
          self ? Icons.navigation : Icons.person_pin_circle,
          color: color,
          size: 28,
        ),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 4),
          decoration: BoxDecoration(
            color: Colors.white.withValues(alpha: 0.85),
            borderRadius: BorderRadius.circular(4),
          ),
          child: Text(
            callsign,
            style: const TextStyle(fontSize: 11, color: Colors.black),
          ),
        ),
      ],
    ),
  );

  /// Older bearings fade out over two hours but never disappear completely.
  double _alpha(Bearing b, DateTime now) {
    final ageMin = now.difference(b.measuredAt).inMinutes;
    return (1 - ageMin / 120).clamp(0.25, 1.0);
  }

  void _cycleBaseMap(AppSettings settings) {
    final order = [
      BaseMap.osm,
      BaseMap.topo,
      if (settings.hasCustomTiles) BaseMap.custom,
    ];
    final next = order[(order.indexOf(settings.baseMap) + 1) % order.length];
    ref.read(settingsProvider.notifier).setBaseMap(next);
  }

  /// The homing track as dots coloured by field strength (blue weak, red strong).
  Widget _rssiDots(List<RssiSample> samples) {
    final recent = samples.length > 500
        ? samples.sublist(samples.length - 500)
        : samples;
    final (lo, hi) = levelRange(recent.map((r) => r.correctedDbm));
    return CircleLayer(
      circles: [
        for (final r in recent)
          CircleMarker(
            point: r.point,
            radius: 4,
            color: rssiColor(r.correctedDbm, min: lo, max: hi),
            borderColor: Colors.white,
            borderStrokeWidth: 0.8,
          ),
      ],
    );
  }

  List<Polygon> _contourPolygons(Estimate e) => [
    for (final entry in const [('95', 0.10), ('80', 0.16), ('50', 0.24)])
      for (final ring in e.contours[entry.$1] ?? const <List<LatLng>>[])
        Polygon(
          points: ring,
          color: Colors.deepOrange.withValues(alpha: entry.$2),
          borderColor: Colors.deepOrange.withValues(alpha: 0.7),
          borderStrokeWidth: 1,
        ),
  ];

  Future<void> _export(String format) async {
    final messenger = ScaffoldMessenger.of(context);
    try {
      final bytes = await ref.read(apiProvider).exportBytes(format);
      final mission = ref.read(missionProvider).mission;
      final name =
          'foxgrid_${(mission?.name ?? 'einsatz').replaceAll(RegExp(r'[^A-Za-z0-9]+'), '_')}.$format';
      const mimes = {
        'pdf': 'application/pdf',
        'gpx': 'application/gpx+xml',
        'kml': 'application/vnd.google-earth.kml+xml',
        'json': 'application/json',
      };
      final where = await saveBytes(name, bytes, mimes[format]!);
      messenger.showSnackBar(SnackBar(content: Text('Gespeichert: $where')));
    } on Object catch (e) {
      messenger.showSnackBar(
        SnackBar(content: Text('Export fehlgeschlagen: $e')),
      );
    }
  }

  Iterable<Bearing> _visible(
    MissionState state,
    BearingFilter filter,
    DateTime now,
  ) => state.bearings.values.where((b) => b.isActive && filter.allows(b, now));

  List<Polygon> _fans(MissionState state, BearingFilter filter, DateTime now) =>
      [
        for (final b in _visible(state, filter, now))
          Polygon(
            points: fanPolygon(
              b.station,
              b.azimuthTrueDeg,
              b.sigmaDeg,
              _rayLengthM,
            ),
            color: participantColor(b.participantId)
                .withValues(alpha: 0.10 * _alpha(b, now)),
          ),
      ];

  List<Polyline> _rays(
    MissionState state,
    BearingFilter filter,
    DateTime now,
  ) => [
    for (final b in _visible(state, filter, now))
      Polyline(
        points: [
          b.station,
          destination(b.station, b.azimuthTrueDeg, _rayLengthM),
        ],
        strokeWidth: 2.5,
        color: participantColor(b.participantId)
            .withValues(alpha: (b.isOutlier ? 0.7 : 1) * _alpha(b, now)),
        pattern: b.isOutlier
            ? StrokePattern.dashed(segments: const [8, 8])
            : const StrokePattern.solid(),
      ),
  ];
}

class _ConnectionDot extends StatelessWidget {
  const _ConnectionDot({required this.status});

  final LiveStatus status;

  @override
  Widget build(BuildContext context) {
    final (color, text) = switch (status) {
      LiveStatus.connected => (Colors.green, 'live'),
      LiveStatus.connecting => (Colors.orange, 'verbinde'),
      LiveStatus.reconnecting => (Colors.red, 'offline'),
    };
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 4),
      child: Row(
        key: const Key('connection'),
        children: [
          Icon(Icons.circle, size: 12, color: color),
          const SizedBox(width: 4),
          Text(text, style: const TextStyle(fontSize: 12)),
        ],
      ),
    );
  }
}

class _TransmissionBanner extends StatefulWidget {
  const _TransmissionBanner();

  @override
  State<_TransmissionBanner> createState() => _TransmissionBannerState();
}

class _TransmissionBannerState extends State<_TransmissionBanner>
    with SingleTickerProviderStateMixin {
  late final AnimationController _pulse = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 700),
  )..repeat(reverse: true);

  @override
  void dispose() {
    _pulse.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _pulse,
      builder: (_, _) => Container(
        key: const Key('tx-banner'),
        width: double.infinity,
        padding: const EdgeInsets.symmetric(vertical: 10),
        color: Color.lerp(
          Colors.red.shade700,
          Colors.red.shade400,
          _pulse.value,
        ),
        child: const Text(
          'STÖRER SENDET',
          textAlign: TextAlign.center,
          style: TextStyle(
            color: Colors.white,
            fontWeight: FontWeight.w900,
            fontSize: 22,
            letterSpacing: 2,
          ),
        ),
      ),
    );
  }
}
