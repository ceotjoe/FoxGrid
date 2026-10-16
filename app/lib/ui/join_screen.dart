import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api.dart';
import '../core/session.dart';
import '../state/providers.dart';

String defaultServerUrl() {
  if (kIsWeb) return 'http://localhost:8000';
  return defaultTargetPlatform == TargetPlatform.android
      ? 'http://10.0.2.2:8000' // host machine as seen from the Android emulator
      : 'http://localhost:8000';
}

class JoinScreen extends ConsumerStatefulWidget {
  const JoinScreen({super.key});

  @override
  ConsumerState<JoinScreen> createState() => _JoinScreenState();
}

class _JoinScreenState extends ConsumerState<JoinScreen> {
  final _server = TextEditingController(text: defaultServerUrl());
  final _callsign = TextEditingController();
  final _invite = TextEditingController();
  final _name = TextEditingController();
  final _frequency = TextEditingController(text: '433.500');
  String _role = 'mobile';
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    for (final c in [_server, _callsign, _invite, _name, _frequency]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _run(Future<Session> Function(FoxGridApi api) action) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final session = await action(DioFoxGridApi());
      await ref.read(sessionProvider.notifier).set(session);
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  String get _base => _server.text.trim().replaceAll(RegExp(r'/+$'), '');

  void _join() {
    final parsed = parseInvite(_invite.text);
    final server = parsed.server ?? _base;
    _run(
      (api) => api.join(
        baseUrl: server,
        inviteToken: parsed.token,
        callsign: _callsign.text.trim(),
        role: _role,
      ),
    );
  }

  void _create() {
    _run(
      (api) => api.createMission(
        baseUrl: _base,
        name: _name.text.trim(),
        frequencyMhz:
            double.tryParse(_frequency.text.trim().replaceAll(',', '.')) ?? 0,
        callsign: _callsign.text.trim(),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('FoxGrid'),
          bottom: const TabBar(
            tabs: [
              Tab(text: 'Beitreten'),
              Tab(text: 'Einsatz anlegen'),
            ],
          ),
        ),
        body: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 520),
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                children: [
                  TextField(
                    key: const Key('server'),
                    controller: _server,
                    keyboardType: TextInputType.url,
                    decoration: const InputDecoration(
                      labelText: 'Server',
                      border: OutlineInputBorder(),
                    ),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    key: const Key('callsign'),
                    controller: _callsign,
                    textCapitalization: TextCapitalization.characters,
                    decoration: const InputDecoration(
                      labelText: 'Rufzeichen',
                      border: OutlineInputBorder(),
                    ),
                  ),
                  const SizedBox(height: 12),
                  Expanded(
                    child: TabBarView(
                      children: [
                        ListView(
                          children: [
                            TextField(
                              key: const Key('invite'),
                              controller: _invite,
                              decoration: const InputDecoration(
                                labelText: 'Einladung (Token oder Link)',
                                border: OutlineInputBorder(),
                              ),
                            ),
                            const SizedBox(height: 12),
                            SegmentedButton<String>(
                              segments: const [
                                ButtonSegment(
                                  value: 'mobile',
                                  label: Text('Mobil'),
                                ),
                                ButtonSegment(
                                  value: 'fixed',
                                  label: Text('Fest'),
                                ),
                              ],
                              selected: {_role},
                              onSelectionChanged: (s) =>
                                  setState(() => _role = s.first),
                            ),
                            const SizedBox(height: 16),
                            FilledButton(
                              key: const Key('join'),
                              onPressed: _busy ? null : _join,
                              child: const Text('Beitreten'),
                            ),
                          ],
                        ),
                        ListView(
                          children: [
                            TextField(
                              key: const Key('mission-name'),
                              controller: _name,
                              decoration: const InputDecoration(
                                labelText: 'Name des Einsatzes',
                                border: OutlineInputBorder(),
                              ),
                            ),
                            const SizedBox(height: 12),
                            TextField(
                              controller: _frequency,
                              keyboardType:
                                  const TextInputType.numberWithOptions(
                                    decimal: true,
                                  ),
                              decoration: const InputDecoration(
                                labelText: 'Frequenz in MHz',
                                border: OutlineInputBorder(),
                              ),
                            ),
                            const SizedBox(height: 16),
                            FilledButton(
                              key: const Key('create'),
                              onPressed: _busy ? null : _create,
                              child: const Text('Einsatz anlegen'),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                  if (_error != null)
                    Text(
                      _error!,
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.error,
                      ),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
