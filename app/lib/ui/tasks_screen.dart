import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/models.dart';
import '../state/providers.dart';

const _statusLabels = {
  'open': 'offen',
  'in_progress': 'in Arbeit',
  'done': 'erledigt',
  'cancelled': 'abgebrochen',
};

class TasksScreen extends ConsumerWidget {
  const TasksScreen({super.key});

  String _assignee(MissionState s, TaskItem t) {
    if (t.assigneeParticipantId != null) {
      return s.participants[t.assigneeParticipantId]?.callsign ?? '?';
    }
    if (t.assigneeTeamId != null) {
      final team = s.teams.where((x) => x.id == t.assigneeTeamId).firstOrNull;
      return 'Team ${team?.name ?? '?'}';
    }
    return 'niemand';
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(missionProvider);
    final tasks = state.tasks.values.toList()
      ..sort((a, b) {
        final done = (a.status == 'done' || a.status == 'cancelled' ? 1 : 0)
            .compareTo(b.status == 'done' || b.status == 'cancelled' ? 1 : 0);
        return done != 0 ? done : a.title.compareTo(b.title);
      });

    return Scaffold(
      appBar: AppBar(title: const Text('Aufgaben')),
      body: tasks.isEmpty
          ? const Center(child: Text('Keine Aufgaben.'))
          : ListView.builder(
              itemCount: tasks.length,
              itemBuilder: (_, i) {
                final t = tasks[i];
                final closed = t.status == 'done' || t.status == 'cancelled';
                return ListTile(
                  key: Key('task-${t.id}'),
                  title: Text(
                    t.title,
                    style: closed
                        ? const TextStyle(
                            decoration: TextDecoration.lineThrough,
                          )
                        : null,
                  ),
                  subtitle: Text(
                    '${_statusLabels[t.status]} · ${_assignee(state, t)}'
                    '${t.pending ? ' · wird gesendet' : ''}',
                  ),
                  trailing: PopupMenuButton<String>(
                    onSelected: (v) => ref
                        .read(missionProvider.notifier)
                        .patchTask(t.id, {'status': v}),
                    itemBuilder: (_) => [
                      for (final e in _statusLabels.entries)
                        PopupMenuItem(value: e.key, child: Text(e.value)),
                    ],
                  ),
                  onTap: () => _assignDialog(context, ref, state, t),
                );
              },
            ),
      floatingActionButton: FloatingActionButton.extended(
        key: const Key('new-task'),
        onPressed: () => _createDialog(context, ref, state),
        icon: const Icon(Icons.add_task),
        label: const Text('Aufgabe'),
      ),
    );
  }

  Future<void> _createDialog(
    BuildContext context,
    WidgetRef ref,
    MissionState state,
  ) => showDialog<void>(
    context: context,
    builder: (ctx) => _NewTaskDialog(
      state: state,
      onCreate: ({required title, participantId, teamId}) => ref
          .read(missionProvider.notifier)
          .createTask(
            title: title,
            participantId: participantId,
            teamId: teamId,
          ),
    ),
  );

  Future<void> _assignDialog(
    BuildContext context,
    WidgetRef ref,
    MissionState state,
    TaskItem task,
  ) {
    return showDialog<void>(
      context: context,
      builder: (ctx) => SimpleDialog(
        title: Text('„${task.title}“ zuweisen'),
        children: [
          for (final t in state.teams)
            SimpleDialogOption(
              onPressed: () {
                ref.read(missionProvider.notifier).patchTask(task.id, {
                  'assignee_team_id': t.id,
                });
                Navigator.pop(ctx);
              },
              child: Text('Team ${t.name}'),
            ),
          for (final p in state.participants.values)
            SimpleDialogOption(
              onPressed: () {
                ref.read(missionProvider.notifier).patchTask(task.id, {
                  'assignee_participant_id': p.id,
                });
                Navigator.pop(ctx);
              },
              child: Text(p.callsign),
            ),
        ],
      ),
    );
  }
}

/// Owns its controller so it is disposed together with the dialog, after the close animation.
class _NewTaskDialog extends StatefulWidget {
  const _NewTaskDialog({required this.state, required this.onCreate});

  final MissionState state;
  final void Function({
    required String title,
    String? participantId,
    String? teamId,
  })
  onCreate;

  @override
  State<_NewTaskDialog> createState() => _NewTaskDialogState();
}

class _NewTaskDialogState extends State<_NewTaskDialog> {
  final _title = TextEditingController();
  String? _assignee; // "p:<id>" or "t:<id>"

  @override
  void dispose() {
    _title.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = widget.state;
    return AlertDialog(
      title: const Text('Neue Aufgabe'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          TextField(
            key: const Key('task-title'),
            controller: _title,
            autofocus: true,
            decoration: const InputDecoration(labelText: 'Titel'),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String?>(
            initialValue: _assignee,
            decoration: const InputDecoration(labelText: 'Zuweisen an'),
            items: [
              const DropdownMenuItem(value: null, child: Text('niemand')),
              for (final t in state.teams)
                DropdownMenuItem(
                  value: 't:${t.id}',
                  child: Text('Team ${t.name}'),
                ),
              for (final p in state.participants.values)
                DropdownMenuItem(value: 'p:${p.id}', child: Text(p.callsign)),
            ],
            onChanged: (v) => setState(() => _assignee = v),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Abbrechen'),
        ),
        FilledButton(
          key: const Key('task-save'),
          onPressed: () {
            if (_title.text.trim().isEmpty) return;
            final a = _assignee;
            widget.onCreate(
              title: _title.text.trim(),
              participantId: a != null && a.startsWith('p:')
                  ? a.substring(2)
                  : null,
              teamId: a != null && a.startsWith('t:') ? a.substring(2) : null,
            );
            Navigator.pop(context);
          },
          child: const Text('Anlegen'),
        ),
      ],
    );
  }
}
