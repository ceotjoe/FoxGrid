import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:foxgrid/core/tile_cache.dart';
import 'package:latlong2/latlong.dart';

void main() {
  late Directory dir;
  late List<String> fetched;

  setUp(() {
    dir = Directory.systemTemp.createTempSync('fg_tiles');
    fetched = [];
  });

  tearDown(() {
    if (dir.existsSync()) dir.deleteSync(recursive: true);
  });

  TileCache cache({int maxBytes = 1 << 30}) => TileCache(
    directory: dir,
    maxBytes: maxBytes,
    fetch: (url) async {
      fetched.add(url);
      return url.contains('missing')
          ? null
          : Uint8List.fromList(List.filled(100, 7));
    },
  );

  test('tile ranges follow the slippy map scheme', () {
    // The whole world is one tile at zoom 0 and four at zoom 1.
    final r = tileRanges(const LatLng(-80, -170), const LatLng(80, 170), 0, 1);
    expect(r[0].count, 1);
    expect(r[1].count, 4);
    // Munich city centre at zoom 12 is tile 2179/1420 (OSM tile numbering).
    final m = tileRanges(
      const LatLng(48.137, 11.575),
      const LatLng(48.137, 11.575),
      12,
      12,
    );
    expect((m.single.minX, m.single.minY), (2179, 1421));
    expect(
      totalTiles(
        tileRanges(const LatLng(48, 11), const LatLng(48.2, 11.3), 10, 12),
      ),
      greaterThan(3),
    );
  });

  test('url templates are filled', () {
    expect(
      TileCache.urlFor('https://t/{z}/{x}/{y}.png', 3, 4, 5),
      'https://t/3/4/5.png',
    );
  });

  test('a tile is fetched once and then served from disk', () async {
    final c = cache();
    final a = await c.get('https://t/1/1/1.png');
    final b = await c.get('https://t/1/1/1.png');
    expect(a, b);
    expect(fetched, hasLength(1));
    expect(c.has('https://t/1/1/1.png'), isTrue);
    expect(c.has('https://t/9/9/9.png'), isFalse);
  });

  test('failed fetches are not cached', () async {
    final c = cache();
    expect(await c.get('https://t/missing.png'), isNull);
    expect(c.has('https://t/missing.png'), isFalse);
  });

  test('prune removes the least recently used tiles', () async {
    final c = cache(maxBytes: 250);
    for (var i = 0; i < 4; i++) {
      await c.get('https://t/$i.png');
      await Future<void>.delayed(const Duration(milliseconds: 20));
    }
    await c.get('https://t/0.png'); // touch the oldest
    final removed = await c.prune();
    expect(removed, 2);
    expect(c.has('https://t/0.png'), isTrue);
    expect(c.has('https://t/1.png'), isFalse);
  });

  test('clear empties the cache', () async {
    final c = cache();
    await c.get('https://t/1.png');
    await c.clear();
    expect(c.has('https://t/1.png'), isFalse);
  });

  test(
    'region download stores every tile, reports progress and can be cancelled',
    () async {
      final c = cache();
      final ranges = [const TileRange(5, 10, 11, 20, 21)];
      final progress = <int>[];
      final stored = await downloadRegion(
        c,
        'https://t/{z}/{x}/{y}.png',
        ranges,
        onProgress: (done, total) => progress.add(done),
      );
      expect(stored, 4);
      expect(progress.last, 4);
      expect(c.has('https://t/5/10/20.png'), isTrue);

      // second run: everything is cached, nothing new is stored
      expect(await downloadRegion(c, 'https://t/{z}/{x}/{y}.png', ranges), 0);

      var calls = 0;
      final cancelled = await downloadRegion(
        cache(),
        'https://other/{z}/{x}/{y}.png',
        [const TileRange(6, 0, 9, 0, 9)],
        isCancelled: () => ++calls > 6,
        concurrency: 1,
      );
      expect(cancelled, lessThan(100));
    },
  );
}
