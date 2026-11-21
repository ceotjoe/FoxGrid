import 'package:material_ui/material_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/models.dart';
import '../core/permissions.dart';
import '../state/providers.dart';

/// Letter badge of an interferer (A, B, C ...), also used where colour alone is not enough.
class InterfererBadge extends StatelessWidget {
  const InterfererBadge(this.interferer, {super.key, this.radius = 14});

  final Interferer interferer;
  final double radius;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return CircleAvatar(
      radius: radius,
      backgroundColor: interferer.isActive
          ? scheme.primaryContainer
          : scheme.surfaceContainerHighest,
      child: Text(
        interferer.letter,
        style: TextStyle(
          fontSize: radius * 0.95,
          fontWeight: FontWeight.bold,
          color: scheme.onPrimaryContainer,
        ),
      ),
    );
  }
}

/// Asks for the name of a new interferer and creates it. Returns its id (null if cancelled).
Future<String?> createInterfererDialog(
  BuildContext context,
  WidgetRef ref,
) async {
  final state = ref.read(missionProvider);
  if (state.activeInterferers.length >= maxInterferers) {
    await showDialog<void>(
      context: context,
      builder: (_) => const AlertDialog(
        content: Text(
          'Es sind schon $maxInterferers Störer aktiv. '
          'Deaktiviere zuerst einen anderen.',
        ),
      ),
    );
    return null;
  }
  final name = await showDialog<String>(
    context: context,
    builder: (_) => _NameDialog(
      title: 'Neuer Störer',
      initial: 'Störer ${state.interferers.length + 1}',
      fieldKey: const Key('interferer-name'),
      confirmKey: const Key('interferer-create'),
      confirmLabel: 'Anlegen',
    ),
  );
  if (name == null || name.trim().isEmpty) return null;
  final notifier = ref.read(missionProvider.notifier);
  final id = await notifier.createInterferer(name: name);
  await ref.read(activeInterfererProvider.notifier).select(id);
  return id;
}

/// Asks for a name. Owns its controller so it is disposed only after the dialog is gone.
class _NameDialog extends StatefulWidget {
  const _NameDialog({
    required this.title,
    required this.initial,
    required this.fieldKey,
    required this.confirmKey,
    required this.confirmLabel,
  });

  final String title;
  final String initial;
  final Key fieldKey;
  final Key confirmKey;
  final String confirmLabel;

  @override
  State<_NameDialog> createState() => _NameDialogState();
}

class _NameDialogState extends State<_NameDialog> {
  late final _controller = TextEditingController(text: widget.initial);

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: Text(widget.title),
    content: TextField(
      key: widget.fieldKey,
      controller: _controller,
      autofocus: true,
      maxLength: 60,
      decoration: const InputDecoration(labelText: 'Name'),
      onSubmitted: (v) => Navigator.pop(context, v),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('Abbrechen'),
      ),
      FilledButton(
        key: widget.confirmKey,
        onPressed: () => Navigator.pop(context, _controller.text),
        child: Text(widget.confirmLabel),
      ),
    ],
  );
}

/// The mission's interferers: add, rename, mark as found, deactivate, choose the one captured for.
class InterferersScreen extends ConsumerWidget {
  const InterferersScreen({super.key});

  Future<void> _rename(
    BuildContext context,
    WidgetRef ref,
    Interferer i,
  ) async {
    final name = await showDialog<String>(
      context: context,
      builder: (_) => _NameDialog(
        title: 'Umbenennen',
        initial: i.name,
        fieldKey: const Key('interferer-rename'),
        confirmKey: const Key('interferer-rename-save'),
        confirmLabel: 'Speichern',
      ),
    );
    if (name != null && name.trim().isNotEmpty && name.trim() != i.name) {
      await ref.read(missionProvider.notifier).patchInterferer(i.id, {
        'name': name.trim(),
      });
    }
  }

  /// Picks the interferer to merge [i] into and asks once more: the move cannot be undone.
  Future<void> _merge(BuildContext context, WidgetRef ref, Interferer i) async {
    final others = [
      for (final o in ref.read(missionProvider).activeInterferers)
        if (o.id != i.id) o,
    ];
    final target = await showModalBottomSheet<Interferer>(
      context: context,
      showDragHandle: true,
      builder: (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(title: Text('„${i.name}" zusammenführen mit')),
            for (final o in others)
              ListTile(
                key: Key('merge-into-${o.id}'),
                leading: InterfererBadge(o),
                title: Text(o.name),
                onTap: () => Navigator.pop(ctx, o),
              ),
          ],
        ),
      ),
    );
    if (target == null || !context.mounted) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Zusammenführen?'),
        content: Text(
          'Alle Peilungen und Messwerte von „${i.name}" gehören danach zu '
          '„${target.name}". „${i.name}" wird deaktiviert. Das lässt sich '
          'nur per Hand zurückordnen.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Abbrechen'),
          ),
          FilledButton(
            key: const Key('merge-confirm'),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Zusammenführen'),
          ),
        ],
      ),
    );
    if (ok == true) {
      await ref.read(missionProvider.notifier).mergeInterferer(i.id, target.id);
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(missionProvider);
    final session = ref.watch(sessionProvider);
    final canManage = session?.can(Perm.interfererManage) ?? false;
    final activeId = ref.watch(activeInterfererIdProvider);
    final notifier = ref.read(missionProvider.notifier);
    final list = state.interferers.values.toList()
      ..sort((a, b) {
        if (a.isActive != b.isActive) return a.isActive ? -1 : 1;
        return a.colorSlot.compareTo(b.colorSlot);
      });
    int bearingsOf(Interferer i) =>
        state.bearings.values.where((b) => b.interfererId == i.id).length;

    return Scaffold(
      appBar: AppBar(title: const Text('Störer')),
      floatingActionButton: canManage
          ? FloatingActionButton.extended(
              key: const Key('interferer-add'),
              onPressed: () => createInterfererDialog(context, ref),
              icon: const Icon(Icons.add),
              label: const Text('Störer'),
            )
          : null,
      body: list.isEmpty
          ? const Center(
              child: Padding(
                padding: EdgeInsets.all(24),
                child: Text(
                  'Dieser Server kennt noch keine mehreren Störer.',
                  key: Key('interferers-empty'),
                  textAlign: TextAlign.center,
                ),
              ),
            )
          : ListView(
              padding: const EdgeInsets.only(bottom: 96),
              children: [
                for (final i in list)
                  ListTile(
                    key: Key('interferer-${i.id}'),
                    enabled: i.isActive,
                    leading: InterfererBadge(i),
                    title: Text(i.name),
                    subtitle: Text(
                      '${bearingsOf(i)} Peilungen'
                      '${i.isResolved ? ' · gefunden' : ''}'
                      '${i.isActive ? '' : ' · deaktiviert'}'
                      '${i.id == activeId ? ' · aktiv für neue Peilungen' : ''}',
                    ),
                    selected: i.id == activeId,
                    onTap: i.isActive
                        ? () => ref
                              .read(activeInterfererProvider.notifier)
                              .select(i.id)
                        : null,
                    trailing: canManage
                        ? PopupMenuButton<String>(
                            key: Key('interferer-menu-${i.id}'),
                            onSelected: (v) {
                              switch (v) {
                                case 'rename':
                                  _rename(context, ref, i);
                                case 'resolve':
                                  notifier.patchInterferer(i.id, {
                                    'status': i.isResolved
                                        ? 'active'
                                        : 'resolved',
                                  });
                                case 'merge':
                                  _merge(context, ref, i);
                                case 'toggle':
                                  notifier.patchInterferer(i.id, {
                                    'is_active': !i.isActive,
                                  });
                              }
                            },
                            itemBuilder: (_) => [
                              if (i.isActive)
                                const PopupMenuItem(
                                  value: 'rename',
                                  child: Text('Umbenennen'),
                                ),
                              if (i.isActive)
                                PopupMenuItem(
                                  key: Key('interferer-resolve-${i.id}'),
                                  value: 'resolve',
                                  child: Text(
                                    i.isResolved
                                        ? 'Wieder als aktiv markieren'
                                        : 'Als gefunden markieren',
                                  ),
                                ),
                              if (i.isActive &&
                                  list.where((o) => o.isActive).length > 1)
                                PopupMenuItem(
                                  key: Key('interferer-merge-${i.id}'),
                                  value: 'merge',
                                  child: const Text(
                                    'Mit anderem zusammenführen …',
                                  ),
                                ),
                              PopupMenuItem(
                                key: Key('interferer-toggle-${i.id}'),
                                value: 'toggle',
                                child: Text(
                                  i.isActive ? 'Deaktivieren' : 'Aktivieren',
                                ),
                              ),
                            ],
                          )
                        : null,
                  ),
              ],
            ),
    );
  }
}
