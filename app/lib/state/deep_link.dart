import 'package:app_links/app_links.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/session.dart';

/// Invite link (`foxgrid://join?...`) opened from outside the app (e.g. a scanned QR code).
/// The join screen takes it over and clears it; it never joins by itself.
class PendingInviteNotifier extends Notifier<String?> {
  @override
  String? build() => null;

  void offer(Uri uri) {
    final text = uri.toString();
    if (parseInvite(text).token.isNotEmpty && text.startsWith('foxgrid://')) {
      state = text;
    }
  }

  void clear() => state = null;
}

final pendingInviteProvider = NotifierProvider<PendingInviteNotifier, String?>(
  PendingInviteNotifier.new,
);

/// Listens for incoming links (cold start and while running). Platforms without the plugin are ignored.
final deepLinkListenerProvider = Provider<void>((ref) {
  final notifier = ref.read(pendingInviteProvider.notifier);
  try {
    final links = AppLinks();
    links.getInitialLink().then((uri) {
      if (uri != null) notifier.offer(uri);
    }, onError: (_) {});
    final sub = links.uriLinkStream.listen(notifier.offer, onError: (_) {});
    ref.onDispose(sub.cancel);
  } catch (_) {}
});
