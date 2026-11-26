import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/models.dart';
import 'providers.dart';

/// Which bearings feed the estimate shown on the map.
class BearingFilter {
  const BearingFilter({
    this.transmissionIds = const {},
    this.window,
    this.halfLife,
    this.showContours = true,
    this.showRings = true,
    this.hideOutliers = false,
    this.showExternal = true,
    this.interfererIds = const {},
    this.dimOthers = false,
    this.showStoredSensor = false,
  });

  /// Also draw sensor bearings that do not count (outside a transmission or excluded by hand),
  /// dimmed. Off by default: a vehicle bears every user of the frequency (ADR 0010).
  final bool showStoredSensor;

  /// Interferers to show; empty = all. Their bearings, estimates and readings only.
  final Set<String> interfererIds;

  /// Fade the bearings of the other interferers instead of hiding them.
  final bool dimOthers;

  /// Whether [interfererId] is among the selected interferers (everything is when none is chosen;
  /// bearings from a server without interferers always are).
  bool selects(String? interfererId) =>
      interfererIds.isEmpty ||
      interfererId == null ||
      interfererIds.contains(interfererId);

  final Set<String> transmissionIds;
  final Duration? window;
  final Duration? halfLife;
  final bool showContours;

  /// Distance rings of the fixed stations (from the fitted path loss model).
  final bool showRings;
  final bool hideOutliers;

  /// Rays and markers of external bearing points (display only).
  final bool showExternal;

  /// True when the server's own estimates cannot answer: an ad-hoc query is needed.
  bool get needsQuery =>
      transmissionIds.isNotEmpty || window != null || halfLife != null;

  BearingFilter copyWith({
    Set<String>? transmissionIds,
    Duration? window,
    bool clearWindow = false,
    Duration? halfLife,
    bool clearHalfLife = false,
    bool? showContours,
    bool? showRings,
    bool? hideOutliers,
    bool? showExternal,
    Set<String>? interfererIds,
    bool? dimOthers,
    bool? showStoredSensor,
  }) => BearingFilter(
    transmissionIds: transmissionIds ?? this.transmissionIds,
    window: clearWindow ? null : (window ?? this.window),
    halfLife: clearHalfLife ? null : (halfLife ?? this.halfLife),
    showContours: showContours ?? this.showContours,
    showRings: showRings ?? this.showRings,
    hideOutliers: hideOutliers ?? this.hideOutliers,
    showExternal: showExternal ?? this.showExternal,
    interfererIds: interfererIds ?? this.interfererIds,
    dimOthers: dimOthers ?? this.dimOthers,
    showStoredSensor: showStoredSensor ?? this.showStoredSensor,
  );

  /// Client-side check used for drawing rays.
  bool allows(Bearing b, DateTime now) {
    if (hideOutliers && b.isOutlier) return false;
    if (!showExternal && b.isExternal) return false;
    if (!showStoredSensor && b.sensorId != null && !b.gateCounts) return false;
    if (!dimOthers && !selects(b.interfererId)) return false;
    if (transmissionIds.isNotEmpty &&
        !transmissionIds.contains(b.transmissionId)) {
      return false;
    }
    if (window != null && now.difference(b.measuredAt) > window!) return false;
    return true;
  }
}

class FilterNotifier extends Notifier<BearingFilter> {
  @override
  BearingFilter build() => const BearingFilter();

  void set(BearingFilter f) => state = f;

  void reset() => state = const BearingFilter();
}

final filterProvider = NotifierProvider<FilterNotifier, BearingFilter>(
  FilterNotifier.new,
);

/// Ad-hoc estimate for the active filter; `null` when the live estimate applies.
final filteredEstimateProvider = FutureProvider.autoDispose<Estimate?>((
  ref,
) async {
  final filter = ref.watch(filterProvider);
  if (!filter.needsQuery) return null;
  // Refresh whenever bearings change.
  ref.watch(missionProvider.select((s) => s.bearings.length));
  ref.watch(
    missionProvider.select(
      (s) => s.bearings.values.where((b) => b.isOutlier).length,
    ),
  );
  final window = filter.window;
  return ref
      .read(apiProvider)
      .queryEstimate(
        interfererId: ref.watch(activeInterfererIdProvider),
        transmissions: filter.transmissionIds.toList(),
        since: window == null ? null : DateTime.now().toUtc().subtract(window),
        halfLifeS: filter.halfLife?.inSeconds.toDouble(),
      );
});

/// Ad-hoc estimates for the active filter, one per shown interferer (keyed by interferer id,
/// `null` for a server without interferers); empty when the live estimates apply.
final filteredEstimatesProvider =
    FutureProvider.autoDispose<Map<String?, Estimate>>((ref) async {
      final filter = ref.watch(filterProvider);
      if (!filter.needsQuery) return const {};
      ref.watch(missionProvider.select((s) => s.bearings.length));
      ref.watch(
        missionProvider.select(
          (s) => s.bearings.values.where((b) => b.isOutlier).length,
        ),
      );
      final joined = ref.watch(
        missionProvider.select(
          (s) => [
            for (final i in s.activeInterferers)
              if (filter.selects(i.id)) i.id,
          ].join(','),
        ),
      );
      final ids = joined.isEmpty ? <String?>[null] : joined.split(',');
      final window = filter.window;
      final api = ref.read(apiProvider);
      final out = <String?, Estimate>{};
      for (final id in ids) {
        final e = await api.queryEstimate(
          interfererId: id,
          transmissions: filter.transmissionIds.toList(),
          since: window == null
              ? null
              : DateTime.now().toUtc().subtract(window),
          halfLifeS: filter.halfLife?.inSeconds.toDouble(),
        );
        if (e != null) out[id] = e;
      }
      return out;
    });
