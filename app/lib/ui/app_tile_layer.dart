import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../state/settings.dart';
import '../state/tiles.dart';

/// Map tiles according to the settings: chosen source, disk cache and dark/night filter.
class AppTileLayer extends ConsumerWidget {
  const AppTileLayer({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final settings = ref.watch(settingsProvider);
    final cache = ref.watch(tileCacheProvider).value;
    final layer = TileLayer(
      urlTemplate: settings.tileUrl,
      userAgentPackageName: 'com.itwebservice.foxgrid',
      maxZoom: settings.baseMap == BaseMap.topo ? 17 : 19,
      tileProvider: cache == null
          ? NetworkTileProvider()
          : CachingTileProvider(cache),
    );
    if (!settings.nightMode &&
        Theme.of(context).brightness == Brightness.light) {
      return layer;
    }
    return ColorFiltered(
      colorFilter: ColorFilter.matrix(
        settings.nightMode ? _nightMatrix : _darkMatrix,
      ),
      child: layer,
    );
  }
}

/// Dark mode: invert the tiles and rotate the hue by 180 degrees, so land and
/// water turn dark while roads, water and green keep roughly their colours.
const _darkMatrix = <double>[
  0.574 * 1.5, -1.430 * 1.5, -0.144 * 1.5, 0, 390, //
  -0.426 * 1.5, -0.430 * 1.5, -0.144 * 1.5, 0, 390,
  -0.426 * 1.5, -1.430 * 1.5, 0.856 * 1.5, 0, 390,
  0, 0, 0, 1, 0,
];

/// Night mode: inverted luminance on the red channel only, stretched around
/// the light OSM land colour so roads, borders and labels stand out clearly
/// from a near-black background.
const _nightMatrix = <double>[
  -0.299 * 2, -0.587 * 2, -0.114 * 2, 0, 505, //
  0, 0, 0, 0, 0,
  0, 0, 0, 0, 0,
  0, 0, 0, 1, 0,
];
