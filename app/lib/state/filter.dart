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
    this.hideOutliers = false,
  });

  final Set<String> transmissionIds;
  final Duration? window;
  final Duration? halfLife;
  final bool showContours;
  final bool hideOutliers;

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
    bool? hideOutliers,
  }) => BearingFilter(
    transmissionIds: transmissionIds ?? this.transmissionIds,
    window: clearWindow ? null : (window ?? this.window),
    halfLife: clearHalfLife ? null : (halfLife ?? this.halfLife),
    showContours: showContours ?? this.showContours,
    hideOutliers: hideOutliers ?? this.hideOutliers,
  );

  /// Client-side check used for drawing rays.
  bool allows(Bearing b, DateTime now) {
    if (hideOutliers && b.isOutlier) return false;
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
        transmissions: filter.transmissionIds.toList(),
        since: window == null ? null : DateTime.now().toUtc().subtract(window),
        halfLifeS: filter.halfLife?.inSeconds.toDouble(),
      );
});
