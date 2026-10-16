import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../state/settings.dart';
import '../state/tiles.dart';

/// Map tiles according to the settings: chosen source, disk cache and night tint.
class AppTileLayer extends ConsumerWidget {
  const AppTileLayer({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final settings = ref.watch(settingsProvider);
    final cache = ref.watch(tileCacheProvider).value;
    final layer = TileLayer(
      urlTemplate: settings.tileUrl,
      userAgentPackageName: 'de.foxgrid.foxgrid',
      maxZoom: settings.baseMap == BaseMap.topo ? 17 : 19,
      tileProvider: cache == null
          ? NetworkTileProvider()
          : CachingTileProvider(cache),
    );
    if (!settings.nightMode) return layer;
    // Night mode: dim the map and tint it red to protect night vision.
    return ColorFiltered(
      colorFilter: const ColorFilter.matrix(<double>[
        0.45, 0.45, 0.45, 0, 0, //
        0, 0, 0, 0, 0,
        0, 0, 0, 0, 0,
        0, 0, 0, 1, 0,
      ]),
      child: layer,
    );
  }
}
