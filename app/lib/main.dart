import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'core/push.dart';
import 'state/providers.dart';
import 'state/push.dart';
import 'ui/join_screen.dart';
import 'ui/map_screen.dart';
import 'ui/pending_screen.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final prefs = await SharedPreferences.getInstance();
  final push = await FirebasePushMessaging.tryInit();
  runApp(
    ProviderScope(
      overrides: [
        sharedPrefsProvider.overrideWithValue(prefs),
        if (push != null) pushMessagingProvider.overrideWithValue(push),
      ],
      child: const FoxGridApp(),
    ),
  );
}

class FoxGridApp extends ConsumerWidget {
  const FoxGridApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final session = ref.watch(sessionProvider);
    ref.watch(pushRegistrarProvider);
    final night = ref.watch(settingsProvider.select((s) => s.nightMode));
    final themeMode = ref.watch(settingsProvider.select((s) => s.themeMode));
    return MaterialApp(
      title: 'FoxGrid',
      debugShowCheckedModeBanner: false,
      theme: night ? _redTheme : _dayTheme,
      darkTheme: night ? _redTheme : _darkTheme,
      themeMode: night ? ThemeMode.dark : themeMode,
      home: session == null
          ? const JoinScreen()
          : session.isPending
          ? const PendingScreen()
          : const MapScreen(),
    );
  }
}

final _dayTheme = ThemeData(
  colorSchemeSeed: Colors.deepOrange,
  useMaterial3: true,
);

/// Regular dark scheme (same seed as the day theme).
final _darkTheme = ThemeData(
  colorSchemeSeed: Colors.deepOrange,
  brightness: Brightness.dark,
  useMaterial3: true,
);

/// Black background with red accents only: keeps night vision intact in the field.
final _redTheme = ThemeData(
  useMaterial3: true,
  brightness: Brightness.dark,
  scaffoldBackgroundColor: Colors.black,
  colorScheme: const ColorScheme.dark(
    primary: Color(0xFFFF3B30),
    onPrimary: Colors.black,
    secondary: Color(0xFFB71C1C),
    onSecondary: Colors.white,
    primaryContainer: Color(0xFF4A0000),
    onPrimaryContainer: Color(0xFFFF8A80),
    secondaryContainer: Color(0xFF330000),
    onSecondaryContainer: Color(0xFFFF8A80),
    surface: Colors.black,
    onSurface: Color(0xFFFF6B60),
    surfaceContainerHighest: Color(0xFF220000),
    error: Color(0xFFFF8A80),
  ),
  appBarTheme: const AppBarTheme(
    backgroundColor: Colors.black,
    foregroundColor: Color(0xFFFF6B60),
  ),
);
