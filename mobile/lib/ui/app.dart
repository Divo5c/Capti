/// Capti Mobile App-Root: Theme (Dark/Light/Yellow), Sprache live,
/// Navigation über Navigator-Routen. Der Workflow läuft ausschließlich
/// über die ProjectWorkflow-Zustandsmaschine der Session.

library;
import 'package:flutter/material.dart';

import '../core/caption_style.dart';
import '../core/i18n.dart';
import '../core/theme.dart';
import 'session.dart';
import 'screens/caption_style_screen.dart';
import 'screens/home_screen.dart';
import 'screens/new_project_screen.dart';
import 'screens/processing_screen.dart';
import 'screens/result_screen.dart';
import 'screens/settings_screen.dart';

class CaptiApp extends StatelessWidget {
  final AppSession session;

  const CaptiApp({super.key, required this.session});

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: Listenable.merge([session, CaptiI18n.instance]),
      builder: (context, _) {
        final tokens = getTheme(session.theme);
        return MaterialApp(
          title: 'Capti',
          debugShowCheckedModeBanner: false,
          theme: materialTheme(tokens),
          navigatorKey: sessionNavigatorKey,
          routes: {
            '/': (_) => HomeScreen(session: session),
            '/new-project': (_) => NewProjectScreen(session: session),
            '/caption-style': (_) => CaptionStyleScreen(session: session),
            '/processing': (_) => ProcessingScreen(session: session),
            '/result': (_) => ResultScreen(session: session),
            '/settings': (_) => SettingsScreen(session: session),
          },
        );
      },
    );
  }
}

/// Globaler Navigator-Schlüssel (Session-gesteuerte Navigation).
final GlobalKey<NavigatorState> sessionNavigatorKey =
    GlobalKey<NavigatorState>();

/// Navigiert nur, wenn der Workflow den Übergang erlaubt.
void navigateIfAllowed(AppSession session, String route) {
  sessionNavigatorKey.currentState?.pushNamedAndRemoveUntil(
    route,
    (r) => r.settings.name == '/' || route == '/',
  );
}

/// Wiederverwendbare Capti-Hintergrundfarbe für Screens.
Color screenBackground(BuildContext context) =>
    getTheme(currentThemeName(context)).background;

/// Liest den aktiven Theme-Namen aus dem nächsten MaterialApp.
String currentThemeName(BuildContext context) =>
    Theme.of(context).brightness == Brightness.dark ? 'dark' : 'light';

/// Standard-Karten-Dekoration im Capti-Look.
Widget captiCard({
  required BuildContext context,
  String? themeName,
  required Widget child,
  EdgeInsets padding = const EdgeInsets.all(16),
}) {
  final tokens = getTheme(themeName ?? currentThemeName(context));
  return Container(
    padding: padding,
    decoration: BoxDecoration(
      color: tokens.surface,
      border: Border.all(color: tokens.border),
      borderRadius: BorderRadius.circular(14),
    ),
    child: child,
  );
}

/// Großer Touch-Primärbutton (Capti Yellow).
class PrimaryActionButton extends StatelessWidget {
  final String label;
  final VoidCallback? onPressed;

  const PrimaryActionButton(
      {super.key, required this.label, this.onPressed});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      height: 56,
      child: ElevatedButton(
        onPressed: onPressed,
        child: Text(label),
      ),
    );
  }
}

/// Sekundärer Outline-Button.
class SecondaryActionButton extends StatelessWidget {
  final String label;
  final VoidCallback? onPressed;

  const SecondaryActionButton(
      {super.key, required this.label, this.onPressed});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      height: 52,
      child: OutlinedButton(onPressed: onPressed, child: Text(label)),
    );
  }
}

/// Export für Style-Presets in Screens.
const Map<String, Map<String, Object>> uiPresets = captionPresets;
