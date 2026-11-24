import 'package:material_ui/material_ui.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:latlong2/latlong.dart';

import '../state/providers.dart';
import 'app_tile_layer.dart';

/// Full-screen map to choose one position by tapping. Pops with the chosen [LatLng].
class PositionPickerScreen extends ConsumerStatefulWidget {
  const PositionPickerScreen({super.key, this.initial});

  final LatLng? initial;

  @override
  ConsumerState<PositionPickerScreen> createState() =>
      _PositionPickerScreenState();
}

class _PositionPickerScreenState extends ConsumerState<PositionPickerScreen> {
  LatLng? _picked;

  @override
  void initState() {
    super.initState();
    _picked = widget.initial;
  }

  LatLng get _center =>
      widget.initial ??
      ref.read(ownPositionProvider)?.point ??
      ref.read(missionProvider).mission?.searchArea?.first ??
      const LatLng(51.0, 10.0);

  @override
  Widget build(BuildContext context) {
    final p = _picked;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Standort wählen'),
        actions: [
          TextButton(
            key: const Key('picker-done'),
            onPressed: p == null ? null : () => Navigator.pop(context, p),
            child: const Text('Übernehmen'),
          ),
        ],
      ),
      body: FlutterMap(
        options: MapOptions(
          initialCenter: _center,
          initialZoom: widget.initial != null ? 15 : 12,
          interactionOptions: const InteractionOptions(
            flags: InteractiveFlag.all & ~InteractiveFlag.rotate,
          ),
          onTap: (_, point) => setState(() => _picked = point),
        ),
        children: [
          const AppTileLayer(),
          if (p != null)
            MarkerLayer(
              markers: [
                Marker(
                  point: p,
                  width: 44,
                  height: 44,
                  alignment: Alignment.topCenter,
                  child: Icon(
                    Icons.location_on,
                    key: const Key('picker-marker'),
                    size: 44,
                    color: Theme.of(context).colorScheme.error,
                  ),
                ),
              ],
            ),
        ],
      ),
    );
  }
}
