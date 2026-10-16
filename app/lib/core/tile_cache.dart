import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';

import 'dart:ui';

import 'package:flutter/painting.dart';
import 'package:latlong2/latlong.dart';

typedef TileFetcher = Future<Uint8List?> Function(String url);

class TileRange {
  const TileRange(this.zoom, this.minX, this.maxX, this.minY, this.maxY);

  final int zoom;
  final int minX;
  final int maxX;
  final int minY;
  final int maxY;

  int get count => (maxX - minX + 1) * (maxY - minY + 1);
}

/// File based tile cache: tiles that were viewed or downloaded stay available offline.
class TileCache {
  TileCache({
    required this.directory,
    required this.fetch,
    this.maxBytes = 300 * 1024 * 1024,
  });

  final Directory directory;
  final TileFetcher fetch;
  final int maxBytes;

  File _file(String url) {
    final name = sha1.convert(url.codeUnits).toString();
    return File('${directory.path}/${name.substring(0, 2)}/$name.tile');
  }

  /// Cached bytes if present, otherwise fetch (and store) them.
  Future<Uint8List?> get(String url) async {
    final f = _file(url);
    if (f.existsSync()) {
      f.setLastAccessedSync(DateTime.now());
      return f.readAsBytes();
    }
    final bytes = await fetch(url);
    if (bytes != null && bytes.isNotEmpty) {
      await f.parent.create(recursive: true);
      await f.writeAsBytes(bytes, flush: true);
    }
    return bytes;
  }

  bool has(String url) => _file(url).existsSync();

  /// Removes the least recently used tiles until the cache fits [maxBytes].
  Future<int> prune() async {
    if (!directory.existsSync()) return 0;
    final files = directory
        .listSync(recursive: true)
        .whereType<File>()
        .where((f) => f.path.endsWith('.tile'))
        .toList();
    var total = files.fold<int>(0, (sum, f) => sum + f.lengthSync());
    files.sort((a, b) => a.lastAccessedSync().compareTo(b.lastAccessedSync()));
    var removed = 0;
    for (final f in files) {
      if (total <= maxBytes) break;
      total -= f.lengthSync();
      f.deleteSync();
      removed++;
    }
    return removed;
  }

  Future<void> clear() async {
    if (directory.existsSync()) await directory.delete(recursive: true);
  }

  static String urlFor(String template, int z, int x, int y) => template
      .replaceAll('{z}', '$z')
      .replaceAll('{x}', '$x')
      .replaceAll('{y}', '$y');
}

/// Slippy-map tile ranges covering [sw]..[ne] for zooms [minZoom]..[maxZoom].
List<TileRange> tileRanges(LatLng sw, LatLng ne, int minZoom, int maxZoom) {
  int tx(double lon, int z) =>
      ((lon + 180) / 360 * (1 << z)).floor().clamp(0, (1 << z) - 1);
  int ty(double lat, int z) {
    final r = lat * pi / 180;
    return ((1 - log(tan(r) + 1 / cos(r)) / pi) / 2 * (1 << z)).floor().clamp(
      0,
      (1 << z) - 1,
    );
  }

  return [
    for (var z = minZoom; z <= maxZoom; z++)
      TileRange(
        z,
        tx(sw.longitude, z),
        tx(ne.longitude, z),
        ty(ne.latitude, z),
        ty(sw.latitude, z),
      ),
  ];
}

int totalTiles(List<TileRange> ranges) =>
    ranges.fold(0, (sum, r) => sum + r.count);

/// Downloads all tiles of [ranges]; returns how many were stored.
Future<int> downloadRegion(
  TileCache cache,
  String template,
  List<TileRange> ranges, {
  void Function(int done, int total)? onProgress,
  bool Function()? isCancelled,
  int concurrency = 2,
}) async {
  final urls = [
    for (final r in ranges)
      for (var x = r.minX; x <= r.maxX; x++)
        for (var y = r.minY; y <= r.maxY; y++)
          TileCache.urlFor(template, r.zoom, x, y),
  ];
  var next = 0;
  var done = 0;
  var stored = 0;
  Future<void> worker() async {
    while (next < urls.length && !(isCancelled?.call() ?? false)) {
      final url = urls[next++];
      try {
        if (!cache.has(url) && await cache.get(url) != null) stored++;
      } on Object {
        // a missing tile must not abort the whole download
      }
      onProgress?.call(++done, urls.length);
    }
  }

  await Future.wait([for (var i = 0; i < concurrency; i++) worker()]);
  return stored;
}

/// Image provider that reads tiles through [TileCache].
class CachedTileImage extends ImageProvider<CachedTileImage> {
  const CachedTileImage(this.url, this.cache);

  final String url;
  final TileCache cache;

  @override
  Future<CachedTileImage> obtainKey(ImageConfiguration configuration) =>
      Future.value(this);

  @override
  ImageStreamCompleter loadImage(
    CachedTileImage key,
    ImageDecoderCallback decode,
  ) => OneFrameImageStreamCompleter(_load(decode));

  Future<ImageInfo> _load(ImageDecoderCallback decode) async {
    final bytes = await cache.get(url);
    if (bytes == null) throw StateError('tile unavailable: $url');
    final codec = await decode(await ImmutableBuffer.fromUint8List(bytes));
    final frame = await codec.getNextFrame();
    return ImageInfo(image: frame.image);
  }

  @override
  bool operator ==(Object other) =>
      other is CachedTileImage && other.url == url;

  @override
  int get hashCode => url.hashCode;
}
