import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api.dart';
import '../core/device_secret.dart';
import '../core/session.dart';
import '../state/deep_link.dart';
import '../state/providers.dart';

/// Release builds talk to servers over HTTPS only; plain HTTP stays available
/// in debug builds for the local dev stack.
String? serverUrlError(String url, {bool releaseMode = kReleaseMode}) {
  final uri = Uri.tryParse(url);
  if (uri == null || !uri.hasAuthority || uri.host.isEmpty) {
    return 'Bitte eine gültige Server-Adresse eingeben.';
  }
  if (uri.scheme == 'https') return null;
  if (uri.scheme == 'http' && !releaseMode) return null;
  return 'Der Server muss per HTTPS erreichbar sein (https://…).';
}

/// Parses a frequency typed in MHz; accepts a decimal comma. `null` if it is not a number.
double? parseFrequencyMhz(String text) =>
    double.tryParse(text.trim().replaceAll(',', '.'));

/// Why a mission frequency is rejected (same bounds as the API), or `null` if it is fine.
String? frequencyError(double? mhz) {
  if (mhz == null || mhz <= 0 || mhz >= 10000) {
    return 'Bitte eine Frequenz in MHz eingeben, z. B. 145.500 oder 433.500.';
  }
  return null;
}

/// Hint below 30 MHz: FoxGrid assumes line-of-sight VHF/UHF propagation and the VHF S-meter scale.
String? frequencyHint(double? mhz) {
  if (mhz == null || mhz <= 0 || mhz >= 30) return null;
  return 'Unter 30 MHz sind Peilungen per Bodenwelle unsicher und S9 liegt bei '
      '−73 dBm; FoxGrid rechnet mit der VHF/UHF-Skala (S9 = −93 dBm).';
}

String defaultServerUrl() {
  if (kReleaseMode) return '';
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

const lastServerKey = 'foxgrid.last_server';
const lastCallsignKey = 'foxgrid.last_callsign';

class _JoinScreenState extends ConsumerState<JoinScreen>
    with SingleTickerProviderStateMixin {
  late final _tabs = TabController(length: 2, vsync: this);
  late final _server = TextEditingController(
    text:
        ref.read(sharedPrefsProvider).getString(lastServerKey) ??
        defaultServerUrl(),
  );
  late final _callsign = TextEditingController(
    text: ref.read(sharedPrefsProvider).getString(lastCallsignKey) ?? '',
  );
  final _invite = TextEditingController();
  final _name = TextEditingController();
  final _frequency = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    // Cold start: the link may have arrived before this screen existed.
    WidgetsBinding.instance.addPostFrameCallback(
      (_) => _takeInvite(ref.read(pendingInviteProvider)),
    );
  }

  void _takeInvite(String? link) {
    if (link == null || !mounted) return;
    final parsed = parseInvite(link);
    setState(() {
      _invite.text = link;
      if (parsed.server != null) _server.text = parsed.server!;
      _error = null;
    });
    ref.read(pendingInviteProvider.notifier).clear();
    _tabs.animateTo(0);
  }

  @override
  void dispose() {
    _tabs.dispose();
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
      final session = await action(ref.read(apiProvider));
      final prefs = ref.read(sharedPrefsProvider);
      await prefs.setString(lastServerKey, session.baseUrl);
      await prefs.setString(lastCallsignKey, _callsign.text.trim());
      await ref.read(sessionProvider.notifier).set(session);
    } on ApiException catch (e) {
      setState(
        () => _error = e.message.contains('bound to another device')
            ? 'Dieses Rufzeichen ist an ein anderes Gerät gebunden. '
                  'Die Einsatzleitung muss das Gerät freigeben.'
            : e.message,
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  String get _base => _server.text.trim().replaceAll(RegExp(r'/+$'), '');

  bool _serverOk(String server) {
    final error = serverUrlError(server);
    if (error != null) setState(() => _error = error);
    return error == null;
  }

  void _join() {
    final parsed = parseInvite(_invite.text);
    final server = parsed.server ?? _base;
    if (!_serverOk(server)) return;
    _run(
      (api) => api.join(
        baseUrl: server,
        inviteToken: parsed.token,
        callsign: _callsign.text.trim(),
        deviceSecret: deviceSecret(ref.read(sharedPrefsProvider)),
      ),
    );
  }

  void _create() {
    if (!_serverOk(_base)) return;
    final mhz = parseFrequencyMhz(_frequency.text);
    final error = frequencyError(mhz);
    if (error != null) {
      setState(() => _error = error);
      return;
    }
    _run(
      (api) => api.createMission(
        baseUrl: _base,
        name: _name.text.trim(),
        frequencyMhz: mhz!,
        callsign: _callsign.text.trim(),
        deviceSecret: deviceSecret(ref.read(sharedPrefsProvider)),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    ref.listen(pendingInviteProvider, (_, link) => _takeInvite(link));
    return Scaffold(
      appBar: AppBar(
        title: const Text('FoxGrid'),
        bottom: TabBar(
          controller: _tabs,
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
                    hintText: 'https://foxgrid.example.org',
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
                    controller: _tabs,
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
                            key: const Key('frequency'),
                            controller: _frequency,
                            onChanged: (_) => setState(() {}),
                            keyboardType: const TextInputType.numberWithOptions(
                              decimal: true,
                            ),
                            decoration: InputDecoration(
                              labelText: 'Frequenz in MHz',
                              hintText: 'z. B. 145.500 oder 433.500',
                              helperText: frequencyHint(
                                parseFrequencyMhz(_frequency.text),
                              ),
                              helperMaxLines: 3,
                              border: const OutlineInputBorder(),
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
    );
  }
}
