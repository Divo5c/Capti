/// Capti Theme-System (Dart-Port von ui/theme.py).
/// Identische Tokens/Farben wie der Desktop – die Capti-Identität
/// bleibt über Plattformen hinweg erkennbar.

library;
import 'package:flutter/material.dart';

const List<String> availableThemes = ['dark', 'light', 'yellow'];
const String defaultTheme = 'dark';

class ThemeTokens {
  final Color background;
  final Color surface;
  final Color surfaceSecondary;
  final Color text;
  final Color textSecondary;
  final Color accent;
  final Color accentHover;
  final Color border;
  final Color success;
  final Color error;

  const ThemeTokens({
    required this.background,
    required this.surface,
    required this.surfaceSecondary,
    required this.text,
    required this.textSecondary,
    required this.accent,
    required this.accentHover,
    required this.border,
    required this.success,
    required this.error,
  });
}

const Map<String, ThemeTokens> captiThemes = {
  'dark': ThemeTokens(
    background: Color(0xFF1A1A1A),
    surface: Color(0xFF242424),
    surfaceSecondary: Color(0xFF2E2E2E),
    text: Color(0xFFFFFFFF),
    textSecondary: Color(0xFF9E9E9E),
    accent: Color(0xFFFFD60A), // Capti Yellow
    accentHover: Color(0xFFE6C200),
    border: Color(0xFF3A3A3A),
    success: Color(0xFF4EC9B0),
    error: Color(0xFFF44747),
  ),
  'light': ThemeTokens(
    background: Color(0xFFFAFAFA),
    surface: Color(0xFFFFFFFF),
    surfaceSecondary: Color(0xFFF0F0F0),
    text: Color(0xFF1A1A1A),
    textSecondary: Color(0xFF6B6B6B),
    accent: Color(0xFFF5C400),
    accentHover: Color(0xFFDDB000),
    border: Color(0xFFDCDCDC),
    success: Color(0xFF2E8B6E),
    error: Color(0xFFD13438),
  ),
  'yellow': ThemeTokens(
    background: Color(0xFF1C1A10),
    surface: Color(0xFF2A2617),
    surfaceSecondary: Color(0xFF38331D),
    text: Color(0xFFFFF8DC),
    textSecondary: Color(0xFFC9BD8A),
    accent: Color(0xFFFFD60A),
    accentHover: Color(0xFFFFE45C),
    border: Color(0xFF4A4325),
    success: Color(0xFF8FD694),
    error: Color(0xFFFF6B6B),
  ),
};

ThemeTokens getTheme(String? name) =>
    captiThemes[name] ?? captiThemes[defaultTheme]!;

bool isValidTheme(String? name) => availableThemes.contains(name);

/// Textfarbe auf dem gelben Accent (alle Themes).
const Color onAccentText = Color(0xFF1A1A1A);

/// Material-Theme aus den Capti-Tokens (Portrait-first, große
/// Touch-Ziele ≥48 dp sind in den Widgets sichergestellt).
/// Die Helligkeit leitet sich aus der Textfarbe ab (Light-Theme hell).
ThemeData materialTheme(ThemeTokens t) {
  final brightness =
      t.text.computeLuminance() > 0.5 ? Brightness.dark : Brightness.light;
  final base = ThemeData(brightness: brightness);
  return base.copyWith(
    scaffoldBackgroundColor: t.background,
    colorScheme: base.colorScheme.copyWith(
      primary: t.accent,
      secondary: t.accent,
      surface: t.surface,
      error: t.error,
      onPrimary: onAccentText,
      onSurface: t.text,
    ),
    appBarTheme: AppBarTheme(
      backgroundColor: t.surface,
      foregroundColor: t.text,
      elevation: 0,
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: t.accent,
        foregroundColor: onAccentText,
        minimumSize: const Size.fromHeight(56), // Touch-Ziel
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: t.text,
        side: BorderSide(color: t.border),
        minimumSize: const Size.fromHeight(52),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: t.surfaceSecondary,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: BorderSide(color: t.border),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: BorderSide(color: t.border),
      ),
      labelStyle: TextStyle(color: t.textSecondary),
    ),
  );
}
