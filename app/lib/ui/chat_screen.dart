import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../state/providers.dart';

/// Mission chat with an optional private team channel.
class ChatScreen extends ConsumerStatefulWidget {
  const ChatScreen({super.key});

  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends ConsumerState<ChatScreen> {
  final _text = TextEditingController();
  String? _teamId; // null = whole mission

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final body = _text.text.trim();
    if (body.isEmpty) return;
    _text.clear();
    await ref.read(missionProvider.notifier).sendMessage(body, teamId: _teamId);
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(missionProvider);
    final session = ref.watch(sessionProvider)!;
    final me = state.participants[session.participantId];
    final myTeam = me == null
        ? null
        : state.teams.where((t) => t.name == me.team).firstOrNull;
    final messages = state.messages.where((m) => m.teamId == _teamId).toList();
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(title: const Text('Chat')),
      body: Column(
        children: [
          if (myTeam != null)
            Padding(
              padding: const EdgeInsets.all(8),
              child: SegmentedButton<String?>(
                segments: [
                  const ButtonSegment(value: null, label: Text('Alle')),
                  ButtonSegment(
                    value: myTeam.id,
                    label: Text('Team ${myTeam.name}'),
                  ),
                ],
                selected: {_teamId},
                onSelectionChanged: (s) => setState(() => _teamId = s.first),
              ),
            ),
          Expanded(
            child: messages.isEmpty
                ? const Center(child: Text('Noch keine Nachrichten.'))
                : ListView.builder(
                    reverse: true,
                    padding: const EdgeInsets.all(8),
                    itemCount: messages.length,
                    itemBuilder: (_, i) {
                      final m = messages[messages.length - 1 - i];
                      final mine = m.authorId == session.participantId;
                      final t = m.sentAt.toLocal();
                      return Align(
                        alignment: mine
                            ? Alignment.centerRight
                            : Alignment.centerLeft,
                        child: Card(
                          color: mine
                              ? theme.colorScheme.primaryContainer
                              : theme.colorScheme.surfaceContainerHighest,
                          child: Padding(
                            padding: const EdgeInsets.all(10),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  '${m.authorCallsign} · '
                                  '${t.hour.toString().padLeft(2, '0')}:'
                                  '${t.minute.toString().padLeft(2, '0')}'
                                  '${m.pending ? ' · wird gesendet' : ''}',
                                  style: theme.textTheme.labelSmall,
                                ),
                                Text(m.body),
                              ],
                            ),
                          ),
                        ),
                      );
                    },
                  ),
          ),
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.all(8),
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      key: const Key('chat-input'),
                      controller: _text,
                      textInputAction: TextInputAction.send,
                      onSubmitted: (_) => _send(),
                      decoration: const InputDecoration(
                        hintText: 'Nachricht',
                        border: OutlineInputBorder(),
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  IconButton.filled(
                    key: const Key('chat-send'),
                    onPressed: _send,
                    icon: const Icon(Icons.send),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
