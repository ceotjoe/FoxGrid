import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api.dart';
import '../state/providers.dart';

/// Shown after joining until the lead lets the participant in.
class PendingScreen extends ConsumerStatefulWidget {
  const PendingScreen({
    super.key,
    this.pollInterval = const Duration(seconds: 4),
  });

  final Duration pollInterval;

  @override
  ConsumerState<PendingScreen> createState() => _PendingScreenState();
}

class _PendingScreenState extends ConsumerState<PendingScreen> {
  Timer? _timer;
  bool _rejected = false;
  String? _code;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(widget.pollInterval, (_) => _poll());
    WidgetsBinding.instance.addPostFrameCallback((_) => _poll());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _poll() async {
    final session = ref.read(sessionProvider);
    if (session == null || _rejected) return;
    try {
      final me = await ref.read(apiProvider).me();
      if (!mounted) return;
      if (me.joinCode != _code) setState(() => _code = me.joinCode);
      if (me.status == 'active') {
        await ref
            .read(sessionProvider.notifier)
            .set(session.copyWith(status: 'active', role: me.role));
      } else if (me.status == 'rejected') {
        _timer?.cancel();
        setState(() => _rejected = true);
      }
    } on ApiException catch (e) {
      // Removed or unknown: this login is dead.
      if (e.statusCode == 401 || e.statusCode == 403) {
        await ref.read(sessionProvider.notifier).leave();
      }
    }
    // Offline: just try again at the next tick.
  }

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(sessionProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('FoxGrid')),
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                _rejected ? Icons.block : Icons.hourglass_top,
                size: 48,
                color: Theme.of(context).colorScheme.primary,
              ),
              const SizedBox(height: 16),
              Text(
                _rejected
                    ? 'Die Einsatzleitung hat die Anfrage abgelehnt.'
                    : 'Warte auf Freigabe durch die Einsatzleitung …',
                key: const Key('pending-text'),
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.titleMedium,
              ),
              if (_code != null && !_rejected) ...[
                const SizedBox(height: 16),
                Text(
                  _code!,
                  key: const Key('join-code'),
                  style: Theme.of(context).textTheme.displayMedium
                      ?.copyWith(letterSpacing: 8),
                ),
                const Text(
                  'Dein Code. Nenne ihn der Einsatzleitung per Funk, '
                  'damit sie weiß, dass du es bist.',
                  textAlign: TextAlign.center,
                ),
              ],
              if (session != null && !_rejected) ...[
                const SizedBox(height: 8),
                Text(
                  'Rufzeichen ${session.callsign}. Sag der Leitung kurz per Funk Bescheid.',
                  textAlign: TextAlign.center,
                ),
              ],
              const SizedBox(height: 24),
              OutlinedButton(
                key: const Key('pending-leave'),
                onPressed: () => ref.read(sessionProvider.notifier).leave(),
                child: Text(_rejected ? 'Zurück' : 'Abbrechen'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
