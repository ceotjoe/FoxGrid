import 'package:qr_flutter/qr_flutter.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:latlong2/latlong.dart';

import '../core/api.dart';
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
import 'audit_screen.dart';
import 'participants_screen.dart';
import 'station_screen.dart';
import 'settings_screen.dart';
import 'map_palette.dart';
import 'sensors_screen.dart';
import 'suggestions_sheet.dart';
import 'sync_sheet.dart';
import 'tasks_screen.dart';

const _rayLengthM = 25000.0;

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
  late MapPalette _pal;

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

  void _openSuggestions() {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => const SuggestionsSheet(),
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

  /// The token only exists on the device that created the mission (or after a replace), so a lead
  /// who came back via rejoin asks the server for a new link; existing links stay valid.
  Future<void> _openInvite(Session session) async {
    if (session.inviteToken != null) return _showInvite(session);
    try {
      final token = await ref.read(apiProvider).createInvite();
      final next = session.copyWith(inviteToken: token);
      await ref.read(sessionProvider.notifier).set(next);
      if (mounted) _showInvite(next);
    } on ApiException catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(e.message)));
      }
    }
  }

  Future<void> _replaceInvite(Session session) async {
    try {
      final token = await ref.read(apiProvider).replaceInvite();
      final next = session.copyWith(inviteToken: token);
      await ref.read(sessionProvider.notifier).set(next);
      if (mounted) _showInvite(next);
    } on ApiException catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(e.message)));
      }
    }
  }

  void _push(Widget screen) =>
      Navigator.of(context)
          .push(MaterialPageRoute<void>(builder: (_) => screen));

  void _sheet(WidgetBuilder builder) => showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: builder,
  );

  /// Lead tools that are rarely needed during a hunt, grouped in one place.
  void _showManage(Session session, int waiting) {
    _sheet(
      (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              key: const Key('open-participants'),
              leading: Badge(
                isLabelVisible: waiting > 0,
                label: Text('$waiting'),
                child: const Icon(Icons.group_outlined),
              ),
              title: const Text('Teilnehmer'),
              subtitle: Text(
                waiting > 0
                    ? '$waiting warten auf Freigabe'
                    : 'Freigabe, Rollen, Vertrauen',
              ),
              onTap: () {
                Navigator.pop(ctx);
                _push(const ParticipantsScreen());
              },
            ),
            if (session.isLead || session.inviteToken != null)
              ListTile(
                key: const Key('open-invite'),
                leading: const Icon(Icons.qr_code_2),
                title: const Text('Einladung'),
                subtitle: Text(
                  session.inviteToken != null
                      ? 'Link und Token anzeigen'
                      : 'Neuen Einladungslink erzeugen',
                ),
                onTap: () {
                  Navigator.pop(ctx);
                  _openInvite(session);
                },
              ),
            ListTile(
              key: const Key('open-sensors'),
              leading: const Icon(Icons.sensors),
              title: const Text('Sensoren'),
              subtitle: const Text('Feste Peilstationen und API-Schlüssel'),
              onTap: () {
                Navigator.pop(ctx);
                _push(const SensorsScreen());
              },
            ),
            ListTile(
              key: const Key('open-audit'),
              leading: const Icon(Icons.shield_outlined),
              title: const Text('Sicherheitsprotokoll'),
              subtitle: const Text('Beitritte, Entfernungen, Sperren'),
              onTap: () {
                Navigator.pop(ctx);
                _push(const AuditScreen());
              },
            ),
            if (ref.read(missionProvider).mission?.isActive ?? false)
              ListTile(
                key: const Key('end-mission'),
                leading: Icon(
                  Icons.flag_outlined,
                  color: Theme.of(ctx).colorScheme.error,
                ),
                title: Text(
                  'Einsatz beenden',
                  style: TextStyle(color: Theme.of(ctx).colorScheme.error),
                ),
                subtitle: const Text('Für alle Teilnehmer, nicht umkehrbar'),
                onTap: () {
                  Navigator.pop(ctx);
                  _confirmEnd();
                },
              ),
          ],
        ),
      ),
    );
  }

  Future<void> _confirmEnd() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Einsatz für alle beenden?'),
        content: const Text(
          'Danach sind keine neuen Peilungen, Aussendungen oder Beitritte '
          'mehr möglich, auch nicht für andere Teilnehmer. Das lässt sich '
          'nicht rückgängig machen. Die Daten bleiben erhalten und '
          'exportierbar.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Abbrechen'),
          ),
          TextButton(
            key: const Key('confirm-end'),
            onPressed: () => Navigator.pop(ctx, true),
            child: Text(
              'Beenden',
              style: TextStyle(color: Theme.of(ctx).colorScheme.error),
            ),
          ),
        ],
      ),
    );
    if (!(ok ?? false)) return;
    try {
      await ref.read(missionProvider.notifier).endMission();
    } on ApiException catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(e.message)));
      }
    }
  }

  void _showExport() {
    const formats = [
      (
        'pdf',
        Icons.picture_as_pdf_outlined,
        'PDF-Protokoll',
        'Zum Ausdrucken und Archivieren',
      ),
      ('gpx', Icons.route_outlined, 'GPX', 'Für Navi- und Karten-Apps'),
      ('kml', Icons.public, 'KML', 'Für Google Earth'),
      ('json', Icons.data_object, 'JSON', 'Alle Rohdaten des Einsatzes'),
    ];
    _sheet(
      (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            for (final (format, icon, title, hint) in formats)
              ListTile(
                key: Key('export-$format'),
                leading: Icon(icon),
                title: Text(title),
                subtitle: Text(hint),
                onTap: () {
                  Navigator.pop(ctx);
                  _export(format);
                },
              ),
          ],
        ),
      ),
    );
  }

  Future<void> _confirmLeave() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Einsatz verlassen?'),
        content: const Text(
          'Nicht gesendete Einträge bleiben in der Warteschlange, '
          'aber du musst dich danach neu verbinden.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Abbrechen'),
          ),
          TextButton(
            key: const Key('confirm-leave'),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Verlassen'),
          ),
        ],
      ),
    );
    if (ok ?? false) ref.read(sessionProvider.notifier).leave();
  }

  void _showMissionInfo(Mission mission) {
    final repeater = mission.repeater;
    showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: SelectableText(mission.name),
        content: SelectableText(
          'Frequenz: ${mission.frequencyMhz.toStringAsFixed(3)} MHz'
          '${repeater?.inputMhz == null ? '' : '\nRelais-Eingabe: ${repeater!.inputMhz} MHz'}'
          '${repeater?.outputMhz == null ? '' : '\nRelais-Ausgabe: ${repeater!.outputMhz} MHz'}',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Schließen'),
          ),
        ],
      ),
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
        content: SingleChildScrollView(
          child: Wrap(
            spacing: 16,
            runSpacing: 12,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Container(
                key: const Key('invite-qr'),
                color: Colors.white,
                padding: const EdgeInsets.all(8),
                // QrPainter instead of QrImageView: the latter uses a LayoutBuilder, which
                // AlertDialog's intrinsic sizing cannot handle.
                child: CustomPaint(
                  size: const Size.square(160),
                  painter: QrPainter(
                    data: link,
                    version: QrVersions.auto,
                    errorCorrectionLevel: QrErrorCorrectLevel.M,
                    eyeStyle: const QrEyeStyle(color: Colors.black),
                    dataModuleStyle: const QrDataModuleStyle(
                      color: Colors.black,
                    ),
                  ),
                ),
              ),
              ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 260),
                child: SelectableText(
                  'Token: $token\n\nLink: $link\n\n'
                  'Der Link läuft nach 24 Stunden ab. Neue Teilnehmer warten auf deine Freigabe '
                  '(Menü „Teilnehmer“). Ist er in falsche Hände geraten, ersetze ihn: '
                  'der alte Link wird ungültig, wer schon drin ist, bleibt drin.',
                ),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            key: const Key('replace-invite'),
            onPressed: () async {
              Navigator.pop(ctx);
              await _replaceInvite(session);
            },
            child: const Text('Link ersetzen'),
          ),
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
    final canToggleTx =
        running == null ||
        state.canStopRunning(session.participantId, session.role);
    final waiting = session.isLead
        ? state.participants.values.where((p) => p.isPending).length
        : 0;
    ref.watch(
      syncProvider,
    ); // keeps the offline queue running while the map is open
    final settings = ref.watch(settingsProvider);
    _pal = MapPalette.of(context, settings);
    final filter = ref.watch(filterProvider);
    final showSuggestions = ref.watch(showSuggestionsProvider);
    final suggestions = showSuggestions
        ? (ref.watch(suggestionsProvider).value ?? const <Suggestion>[])
        : const <Suggestion>[];
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
    final compact = MediaQuery.sizeOf(context).width < 600;
    final filterActive = filter.needsQuery || filter.hideOutliers;

    return Scaffold(
      appBar: AppBar(
        titleSpacing: 0,
        title: state.mission == null
            ? const Text('FoxGrid')
            : InkWell(
                key: const Key('mission-title'),
                onTap: () => _showMissionInfo(state.mission!),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      state.mission!.name,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    FittedBox(
                      fit: BoxFit.scaleDown,
                      alignment: Alignment.centerLeft,
                      child: Text(
                        '${state.mission!.frequencyMhz.toStringAsFixed(3)} MHz',
                        maxLines: 1,
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                    ),
                  ],
                ),
              ),
        actions: [
          _ConnectionDot(status: state.connection),
          const SyncChip(),
          IconButton(
            visualDensity: VisualDensity.compact,
            key: const Key('open-chat'),
            tooltip: 'Chat',
            icon: const Icon(Icons.chat_bubble_outline),
            onPressed: () => Navigator.of(
              context,
            ).push(MaterialPageRoute<void>(builder: (_) => const ChatScreen())),
          ),
          if (!compact)
            IconButton(
              visualDensity: VisualDensity.compact,
              key: const Key('open-tasks'),
              tooltip: 'Aufgaben',
              icon: const Icon(Icons.checklist),
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute<void>(builder: (_) => const TasksScreen()),
              ),
            ),
          if (!compact)
            IconButton(
              visualDensity: VisualDensity.compact,
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
            visualDensity: VisualDensity.compact,
            key: const Key('open-homing'),
            tooltip: 'Nahpeilung',
            icon: const Icon(Icons.explore),
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(builder: (_) => const HomingScreen()),
            ),
          ),
          PopupMenuButton<String>(
            icon: Badge(
              isLabelVisible: waiting > 0 || (compact && filterActive),
              label: waiting > 0 ? Text('$waiting') : null,
              child: const Icon(Icons.more_vert),
            ),
            onSelected: (v) {
              switch (v) {
                case 'tasks':
                  _push(const TasksScreen());
                case 'filter':
                  _sheet((_) => const FilterSheet());
                case 'bearings':
                  _sheet((_) => const BearingsSheet());
                case 'station':
                  _push(const StationScreen());
                case 'manage':
                  _showManage(session, waiting);
                case 'invite':
                  _showInvite(session);
                case 'export':
                  _showExport();
                case 'settings':
                  _push(const SettingsScreen());
                case 'leave':
                  _confirmLeave();
              }
            },
            itemBuilder: (_) => [
              if (compact) ...[
                const PopupMenuItem(
                  key: Key('menu-tasks'),
                  value: 'tasks',
                  child: _MenuRow(Icons.checklist, 'Aufgaben'),
                ),
                PopupMenuItem(
                  key: const Key('menu-filter'),
                  value: 'filter',
                  child: _MenuRow(
                    Icons.filter_alt_outlined,
                    filterActive ? 'Filter (aktiv)' : 'Filter',
                  ),
                ),
              ],
              const PopupMenuItem(
                value: 'bearings',
                child: _MenuRow(Icons.list_alt, 'Peilungen (Liste)'),
              ),
              if (session.role == 'fixed' || session.isLead)
                const PopupMenuItem(
                  key: Key('open-station'),
                  value: 'station',
                  child: _MenuRow(Icons.cell_tower, 'Rundstrahl-Station'),
                ),
              if (session.isLead)
                PopupMenuItem(
                  key: const Key('open-manage'),
                  value: 'manage',
                  child: _MenuRow(
                    Icons.admin_panel_settings_outlined,
                    waiting > 0
                        ? 'Einsatz verwalten ($waiting warten)'
                        : 'Einsatz verwalten',
                  ),
                )
              else if (session.inviteToken != null)
                const PopupMenuItem(
                  value: 'invite',
                  child: _MenuRow(Icons.qr_code_2, 'Einladung'),
                ),
              const PopupMenuItem(
                key: Key('open-export'),
                value: 'export',
                child: _MenuRow(Icons.ios_share, 'Exportieren …'),
              ),
              const PopupMenuDivider(),
              const PopupMenuItem(
                value: 'settings',
                child: _MenuRow(Icons.settings_outlined, 'Einstellungen'),
              ),
              PopupMenuItem(
                key: const Key('menu-leave'),
                value: 'leave',
                child: _MenuRow(
                  Icons.logout,
                  'Einsatz verlassen',
                  color: theme.colorScheme.error,
                ),
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
                      borderColor: _pal.searchArea,
                      borderStrokeWidth: 2,
                      pattern: StrokePattern.dashed(segments: const [10, 8]),
                    ),
                  ],
                ),
              if (state.rssi.any((r) => !r.isStation))
                _rssiDots(state.rssi.where((r) => !r.isStation).toList()),
              if (estimate != null && filter.showContours)
                PolygonLayer(polygons: _contourPolygons(estimate)),
              if (estimate != null && filter.showRings)
                _stationRings(state, estimate),
              if (estimate != null)
                PolygonLayer(
                  polygons: [
                    Polygon(
                      points: estimate.ellipse2s.ring,
                      color: _pal.estimate.withValues(alpha: 0.08),
                      borderColor: _pal.estimate.withValues(alpha: 0.6),
                      borderStrokeWidth: 1.5,
                    ),
                    Polygon(
                      points: estimate.ellipse1s.ring,
                      color: _pal.estimate.withValues(alpha: 0.18),
                      borderColor: _pal.estimate,
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
                        color: _pal.participant(e.key).withValues(alpha: 0.6),
                      ),
                ],
              ),
              MarkerLayer(
                markers: [
                  for (final (i, sg) in suggestions.indexed)
                    Marker(
                      point: sg.point,
                      width: 40,
                      height: 40,
                      child: GestureDetector(
                        key: Key('suggestion-marker-${i + 1}'),
                        onTap: _openSuggestions,
                        child: CircleAvatar(
                          backgroundColor: _pal.suggestion,
                          foregroundColor: _pal.isNight
                              ? const Color(0xFFFF8A80)
                              : Colors.white,
                          child: Text('${i + 1}'),
                        ),
                      ),
                    ),
                  ..._stationMarkers(state),
                  if (state.mission?.repeater != null)
                    Marker(
                      point: state.mission!.repeater!.point,
                      width: 40,
                      height: 40,
                      child: Icon(
                        Icons.cell_tower,
                        color: _pal.repeater,
                        size: 32,
                        key: Key('repeater-marker'),
                      ),
                    ),
                  if (estimate != null)
                    Marker(
                      point: estimate.point,
                      width: 44,
                      height: 44,
                      child: Icon(
                        Icons.gps_fixed,
                        color: _pal.estimate,
                        size: 40,
                        key: Key('mle-marker'),
                      ),
                    ),
                  for (final e in state.positions.entries)
                    if (e.key != session.participantId)
                      _participantMarker(
                        e.value.point,
                        state.participants[e.key]?.callsign ?? '?',
                        _pal.participant(e.key),
                      ),
                  if (own != null)
                    _participantMarker(
                      own.point,
                      session.callsign,
                      _pal.self,
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
                if (running != null)
                  _TransmissionBanner(
                    startedBy: running.startedBy == session.participantId
                        ? null
                        : state.participants[running.startedBy]?.callsign,
                  ),
                Padding(
                  padding: const EdgeInsets.all(8),
                  child: Row(
                    children: [
                      Expanded(
                        child: FittedBox(
                          fit: BoxFit.scaleDown,
                          alignment: Alignment.centerLeft,
                          child: SegmentedButton<EstimateScope>(
                            showSelectedIcon: false,
                            style: const ButtonStyle(
                              // Same height as the 40 px round buttons on the right;
                              // tight padding so it rarely needs to scale down.
                              minimumSize: WidgetStatePropertyAll(Size(0, 40)),
                              padding: WidgetStatePropertyAll(
                                EdgeInsets.symmetric(horizontal: 12),
                              ),
                              textStyle: WidgetStatePropertyAll(
                                TextStyle(fontSize: 15),
                              ),
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
                        ),
                      ),
                      const SizedBox(width: 8),
                      IconButton.filledTonal(
                        key: const Key('toggle-suggestions'),
                        tooltip: 'Wo als Nächstes peilen?',
                        isSelected: showSuggestions,
                        icon: const Icon(Icons.tips_and_updates_outlined),
                        selectedIcon: const Icon(Icons.tips_and_updates),
                        onPressed: () {
                          ref
                              .read(showSuggestionsProvider.notifier)
                              .set(!showSuggestions);
                          if (!showSuggestions) _openSuggestions();
                        },
                      ),
                      const SizedBox(width: 8),
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
      floatingActionButton: FittedBox(
        fit: BoxFit.scaleDown,
        child: Row(
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
              onPressed: (state.mission?.isActive ?? false) && canToggleTx
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
            color: _pal.labelBackground,
            borderRadius: BorderRadius.circular(4),
          ),
          child: Text(
            callsign,
            style: TextStyle(fontSize: 11, color: _pal.labelText),
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

  /// Fixed omnidirectional stations: the latest S value of each, coloured by level.
  Map<String, RssiSample> _latestStations(MissionState state) {
    final latest = <String, RssiSample>{};
    for (final r in state.rssi) {
      if (r.isStation && !r.isCalibration) latest[r.participantId] = r;
    }
    return latest;
  }

  /// Distance rings: where the fitted path loss model puts the interferer for each station's
  /// level, plus a faint band for the scatter of the fit. The estimate is where they agree.
  Widget _stationRings(MissionState state, Estimate estimate) {
    final fit = estimate.rssi;
    final latest = _latestStations(state);
    if (fit == null || latest.isEmpty) return const SizedBox.shrink();
    final (lo, hi) = levelRange(latest.values.map((r) => r.correctedDbm));
    final circles = <CircleMarker>[];
    for (final r in latest.values) {
      final offset = fit.stationOffsetsDb[r.participantId] ?? 0;
      double dist(double delta) => ringDistanceM(
        levelDbm: r.correctedDbm,
        p0Dbm: fit.p0Dbm,
        exponent: fit.exponent,
        offsetDb: offset,
        deltaDb: delta,
      );
      final color = _pal.signal(r.correctedDbm, min: lo, max: hi);
      CircleMarker ring(double radius, double alpha, double width) =>
          CircleMarker(
            point: r.point,
            radius: radius,
            useRadiusInMeter: true,
            color: Colors.transparent,
            borderColor: color.withValues(alpha: alpha),
            borderStrokeWidth: width,
          );
      circles
        ..add(ring(dist(fit.residualDb), 0.35, 1))
        ..add(ring(dist(-fit.residualDb), 0.35, 1))
        ..add(ring(dist(0), 0.9, 2.5));
    }
    return CircleLayer(key: const Key('station-rings'), circles: circles);
  }

  List<Marker> _stationMarkers(MissionState state) {
    final latest = _latestStations(state);
    final (lo, hi) = levelRange(latest.values.map((r) => r.correctedDbm));
    return [
      for (final r in latest.values)
        Marker(
          point: r.point,
          width: 64,
          height: 44,
          child: Container(
            key: Key('station-marker-${r.participantId}'),
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: _pal.signal(r.correctedDbm, min: lo, max: hi),
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: _pal.outline, width: 1.5),
            ),
            child: Text(
              dbmToSLabel(r.correctedDbm),
              style: TextStyle(
                color: _pal.isNight ? Colors.black : Colors.white,
                fontWeight: FontWeight.bold,
              ),
            ),
          ),
        ),
    ];
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
            color: _pal.signal(r.correctedDbm, min: lo, max: hi),
            borderColor: _pal.outline,
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
          color: _pal.contour.withValues(alpha: entry.$2),
          borderColor: _pal.contour.withValues(alpha: 0.7),
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
            color: _pal
                .participant(b.participantId)
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
        color: _pal
            .participant(b.participantId)
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
    final compact = MediaQuery.sizeOf(context).width < 600;
    return Tooltip(
      message: text,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 4),
        child: Row(
          key: const Key('connection'),
          children: [
            Icon(Icons.circle, size: 12, color: color),
            if (!compact) ...[
              const SizedBox(width: 4),
              Text(text, style: const TextStyle(fontSize: 12)),
            ],
          ],
        ),
      ),
    );
  }
}

class _TransmissionBanner extends StatefulWidget {
  const _TransmissionBanner({this.startedBy});

  /// Callsign of another participant who started it; null for the own one.
  final String? startedBy;

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
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text(
              'STÖRER SENDET',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: Colors.white,
                fontWeight: FontWeight.w900,
                fontSize: 22,
                letterSpacing: 2,
              ),
            ),
            if (widget.startedBy != null)
              Text(
                'gestartet von ${widget.startedBy}',
                key: const Key('tx-started-by'),
                style: const TextStyle(color: Colors.white),
              ),
          ],
        ),
      ),
    );
  }
}

class _MenuRow extends StatelessWidget {
  const _MenuRow(this.icon, this.label, {this.color});

  final IconData icon;
  final String label;
  final Color? color;

  @override
  Widget build(BuildContext context) => Row(
    children: [
      Icon(icon, size: 20, color: color),
      const SizedBox(width: 12),
      Flexible(
        child: Text(label, style: TextStyle(color: color)),
      ),
    ],
  );
}
