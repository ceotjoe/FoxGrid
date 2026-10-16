import 'dart:async';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/painting.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:latlong2/latlong.dart';
import 'package:path_provider/path_provider.dart';

import '../core/tile_cache.dart';
import 'settings.dart';

const userAgent = 'FoxGrid/0.2 (open-source radio direction finding)';

/// Tiles shown on the map are stored on disk (native only; browsers use their HTTP cache).
final tileCacheProvider = FutureProvider<TileCache?>((ref) async {
  if (kIsWeb) return null;
  final dir = await getApplicationCacheDirectory();
  final dio = Dio();
  final cache = TileCache(
    directory: Directory('${dir.path}/tiles'),
    fetch: (url) async {
      try {
        final r = await dio.get<List<int>>(
          url,
          options: Options(
            responseType: ResponseType.bytes,
            headers: {'User-Agent': userAgent},
          ),
        );
        return r.data == null ? null : Uint8List.fromList(r.data!);
      } on DioException {
        return null;
      }
    },
  );
  unawaited(cache.prune());
  return cache;
});

class CachingTileProvider extends TileProvider {
  CachingTileProvider(this.cache);

  final TileCache cache;

  @override
  ImageProvider getImage(TileCoordinates coordinates, TileLayer options) =>
      CachedTileImage(getTileUrl(coordinates, options), cache);
}

class MapView {
  const MapView(this.sw, this.ne, this.zoom);

  final LatLng sw;
  final LatLng ne;
  final double zoom;
}

/// Last visible map area, used by the offline region download.
class MapViewNotifier extends Notifier<MapView?> {
  @override
  MapView? build() => null;

  // ignore: use_setters_to_change_properties
  void update(MapView v) => state = v;
}

final mapViewProvider = NotifierProvider<MapViewNotifier, MapView?>(
  MapViewNotifier.new,
);

const maxDownloadTiles = 3000;

class RegionDownload {
  const RegionDownload({
    this.running = false,
    this.done = 0,
    this.total = 0,
    this.message,
  });

  final bool running;
  final int done;
  final int total;
  final String? message;
}

class RegionDownloadNotifier extends Notifier<RegionDownload> {
  bool _cancel = false;

  @override
  RegionDownload build() => const RegionDownload();

  /// Number of tiles for the current view with [extraZoom] additional zoom levels.
  int estimate(MapView v, int extraZoom) {
    final minZ = v.zoom.floor();
    final maxZ = (minZ + extraZoom).clamp(minZ, 17);
    return totalTiles(tileRanges(v.sw, v.ne, minZ, maxZ));
  }

  Future<void> start(MapView v, int extraZoom) async {
    final settings = ref.read(settingsProvider);
    final cache = await ref
        .read(tileCacheProvider.future)
        .then<TileCache?>((c) => c)
        .catchError((Object _) => null);
    if (cache == null) {
      state = const RegionDownload(
        message: 'Kachel-Speicher nicht verfügbar (z. B. im Web)',
      );
      return;
    }
    // The OSM tile usage policy forbids bulk downloads from its public servers.
    if (isPublicTileServer(settings.tileUrl)) {
      state = const RegionDownload(
        message:
            'Massen-Download von öffentlichen OSM-Servern ist laut '
            'Nutzungsrichtlinie nicht erlaubt. Trage einen eigenen Tile-Server ein.',
      );
      return;
    }
    final minZ = v.zoom.floor();
    final maxZ = (minZ + extraZoom).clamp(minZ, 17);
    final ranges = tileRanges(v.sw, v.ne, minZ, maxZ);
    final total = totalTiles(ranges);
    if (total > maxDownloadTiles) {
      state = RegionDownload(
        message:
            'Zu viele Kacheln ($total, max. $maxDownloadTiles). '
            'Zoome näher heran oder wähle weniger Zoomstufen.',
      );
      return;
    }
    _cancel = false;
    state = RegionDownload(running: true, total: total);
    final stored = await downloadRegion(
      cache,
      settings.tileUrl,
      ranges,
      isCancelled: () => _cancel,
      onProgress: (done, total) =>
          state = RegionDownload(running: true, done: done, total: total),
    );
    state = RegionDownload(
      done: total,
      total: total,
      message: _cancel ? 'Abgebrochen' : '$stored neue Kacheln gespeichert',
    );
  }

  void cancel() => _cancel = true;
}

final regionDownloadProvider =
    NotifierProvider<RegionDownloadNotifier, RegionDownload>(
      RegionDownloadNotifier.new,
    );
