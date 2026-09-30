/// Capti Core (Dart-Port): das EINZIGE Caption-Style-Modell.
///
/// Portiert aus capti_core/caption_style.py mit identischer Semantik.
/// Die Python-Tests (tests/test_capti_core_caption_style.py) sind die
/// Akzeptanzkriterien; test/core/caption_style_test.dart spiegelt sie.
///
/// Kanonisches Speicherformat (settings.json: "caption_style"):
///   - Farben als Hex "#RRGGBB"
///   - shadow_alpha 0..255; wirkt nur bei explizit gesetzter shadow_color
///     (Legacy-Regel: ohne Farbe gilt der klassische Look &H80000000)
///   - font_name / font_size / pop_enabled / pop_scale / pop_decay_ms
///
/// Nur an der Render-Grenze wird in ASS-Farben (&HAABBGGRR) konvertiert.

library;

import 'package:flutter/foundation.dart';

const Map<String, Object> defaultCaptionStyle = {
  'normal_color': '#FFFFFF',
  'highlight_color': '#FFFF00',
  'outline_color': '#101010',
  'shadow_color': '#000000',
  'shadow_alpha': 128,
  'font_name': 'Arial Black',
  'font_size': 68,
  'pop_enabled': true,
  'pop_scale': 112,
  'pop_decay_ms': 150,
};

/// Presets in kanonischer Form ("Capti Default" = exakt die Defaults).
const Map<String, Map<String, Object>> captionPresets = {
  'Capti Default': {},
  'Clean': {
    'normal_color': '#FFFFFF',
    'highlight_color': '#FFFFFF',
    'outline_color': '#000000',
    'shadow_alpha': 96,
    'pop_enabled': false,
  },
  'Strong': {
    'normal_color': '#FFFFFF',
    'highlight_color': '#FF3B30',
    'outline_color': '#000000',
    'shadow_alpha': 180,
    'pop_enabled': true,
    'pop_scale': 125,
    'pop_decay_ms': 120,
  },
};

/// ASS-Defaults (Render-Seite) = aktueller Capti-Look.
const Map<String, Object> captionStyleAssDefaults = {
  'normal_color': '&H00FFFFFF',
  'highlight_color': '&H0000FFFF',
  'outline_color': '&H00101010',
  'shadow_color': '&H80000000',
  'font_name': 'Arial Black',
  'font_size': 68,
  'pop_enabled': true,
  'pop_scale': 112,
  'pop_decay_ms': 150,
};

final RegExp _hexRe = RegExp(r'^#[0-9A-Fa-f]{6}$');

bool isValidHex(Object? value) =>
    value is String && _hexRe.hasMatch(value);

String _bgrFromHex(String hex) {
  // hex ist validiert "#RRGGBB"
  final h = hex.toUpperCase();
  final r = h.substring(1, 3), g = h.substring(3, 5), b = h.substring(5, 7);
  return '$b$g$r';
}

/// Python-int-ähnliche Koersion: num -> trunc toward zero,
/// String -> int-Parse, sonst double-Parse mit Truncation.
int? _pyInt(Object? value) {
  if (value is int) return value;
  if (value is double) return value.truncate();
  if (value is String) {
    final asInt = int.tryParse(value);
    if (asInt != null) return asInt;
    final asDouble = double.tryParse(value);
    if (asDouble != null) return asDouble.truncate();
  }
  return null;
}

/// Python-bool()-ähnliche Koersion.
bool _pyBool(Object? value) {
  if (value is bool) return value;
  if (value is num) return value != 0;
  if (value is String) return value.isNotEmpty;
  if (value == null) return false;
  return true;
}

int _clampInt(int v, int lo, int hi) => v < lo ? lo : (v > hi ? hi : v);

int? _intInRange(Object? value, int lo, int hi) {
  final v = _pyInt(value);
  if (v == null) return null;
  if (v < lo || v > hi) return null;
  return v;
}

@immutable
class CaptionStyle {
  final String normalColor;
  final String highlightColor;
  final String outlineColor;
  final String shadowColor;
  final int shadowAlpha;
  final String fontName;
  final int fontSize;
  final bool popEnabled;
  final int popScale;
  final int popDecayMs;

  /// Legacy-Regel: shadow_alpha wirkt nur bei explizit gültiger
  /// shadow_color. Direkt konstruierte Styles gelten als explizit.
  final bool shadowColorExplicit;

  const CaptionStyle({
    this.normalColor = '#FFFFFF',
    this.highlightColor = '#FFFF00',
    this.outlineColor = '#101010',
    this.shadowColor = '#000000',
    this.shadowAlpha = 128,
    this.fontName = 'Arial Black',
    this.fontSize = 68,
    this.popEnabled = true,
    this.popScale = 112,
    this.popDecayMs = 150,
    this.shadowColorExplicit = true,
  });

  /// Kanonische Defaults.
  static const CaptionStyle defaults = CaptionStyle();

  factory CaptionStyle.fromRaw(Object? raw) {
    final map = raw is Map ? raw : const {};
    String hexOr(String? key, String fallback) {
      final v = map[key];
      return isValidHex(v) ? (v! as String).toUpperCase() : fallback;
    }

    final rawShadow = map['shadow_color'];
    return CaptionStyle(
      normalColor: hexOr('normal_color', '#FFFFFF'),
      highlightColor: hexOr('highlight_color', '#FFFF00'),
      outlineColor: hexOr('outline_color', '#101010'),
      shadowColor: hexOr('shadow_color', '#000000'),
      shadowColorExplicit: isValidHex(rawShadow),
      // Legacy-konform clampen (nicht verwerfen); ungültig -> 128
      shadowAlpha: _shadowAlpha(map['shadow_alpha']),
      fontName: _fontName(map['font_name']),
      fontSize: _intInRange(map['font_size'], 20, 200) ?? 68,
      popEnabled: map.containsKey('pop_enabled')
          ? _pyBool(map['pop_enabled'])
          : true,
      popScale: _intInRange(map['pop_scale'], 100, 200) ?? 112,
      popDecayMs: _intInRange(map['pop_decay_ms'], 0, 1000) ?? 150,
    );
  }

  /// Liest den Style aus einem Settings-Wert (null/leer -> Defaults).
  factory CaptionStyle.load(Object? configValue) {
    if (configValue is Map && configValue.isNotEmpty) {
      return CaptionStyle.fromRaw(configValue);
    }
    return CaptionStyle.defaults;
  }

  static int _shadowAlpha(Object? v) {
    final i = _pyInt(v);
    if (i == null) return 128;
    return _clampInt(i, 0, 255);
  }

  static String _fontName(Object? v) {
    if (v is String && v.trim().isNotEmpty) return v.trim();
    return 'Arial Black';
  }

  /// Kanonisches Dict (für settings.json); interne Flags ausgenommen.
  Map<String, Object> toMap() => {
        'normal_color': normalColor,
        'highlight_color': highlightColor,
        'outline_color': outlineColor,
        'shadow_color': shadowColor,
        'shadow_alpha': shadowAlpha,
        'font_name': fontName,
        'font_size': fontSize,
        'pop_enabled': popEnabled,
        'pop_scale': popScale,
        'pop_decay_ms': popDecayMs,
      };

  /// Wendet ein Preset auf eine Kopie an (unbekanntes Preset -> unverändert).
  CaptionStyle mergedWithPreset(String presetName) {
    final overrides = captionPresets[presetName];
    if (overrides == null) return this;
    final data = toMap();
    data.addAll(overrides);
    return CaptionStyle.fromRaw(data);
  }

  /// Konvertierung in Renderer-kwargs (ASS) – EINZIGE Konvertierungsstelle.
  /// Ausgabe entspricht resolveCaptionStyle() bzw. pipeline.resolve_caption_style.
  static String _assDefault(String key) =>
      captionStyleAssDefaults[key]! as String;

  Map<String, Object> toRendererKwargs() {
    final shadow = shadowColorExplicit
        ? assColor(shadowColor, alpha: shadowAlpha) ?? _assDefault('shadow_color')
        : _assDefault('shadow_color');
    return {
      'normal_color': assColor(normalColor) ?? _assDefault('normal_color'),
      'highlight_color':
          assColor(highlightColor) ?? _assDefault('highlight_color'),
      'outline_color': assColor(outlineColor) ?? _assDefault('outline_color'),
      'shadow_color': shadow,
      'font_name': fontName,
      'font_size': fontSize,
      'pop_enabled': popEnabled,
      'pop_scale': popScale,
      'pop_decay_ms': popDecayMs,
    };
  }

  /// #RRGGBB -> &HAABBGGRR (alpha clamped 0..255); ungültig -> null.
  static String? assColor(String? hex, {int alpha = 0}) {
    if (!isValidHex(hex)) return null;
    final a = _clampInt(alpha, 0, 255);
    final prefix = a.toRadixString(16).padLeft(2, '0').toUpperCase();
    return '&H$prefix${_bgrFromHex(hex!)}';
  }

  /// UI-taugliche Flutter-Color für eine Hex-Farbe (Fallback bei ungültig).
  static int argbFromHex(String? hex, {int alphaByte = 255, int fallback = 0xFFFFFFFF}) {
    if (!isValidHex(hex)) return fallback;
    final h = hex!.substring(1);
    final a = _clampInt(alphaByte, 0, 255);
    final rgb = int.parse(h, radix: 16);
    return (a << 24) | rgb;
  }

  @override
  bool operator ==(Object other) =>
      other is CaptionStyle &&
      other.normalColor == normalColor &&
      other.highlightColor == highlightColor &&
      other.outlineColor == outlineColor &&
      other.shadowColor == shadowColor &&
      other.shadowAlpha == shadowAlpha &&
      other.fontName == fontName &&
      other.fontSize == fontSize &&
      other.popEnabled == popEnabled &&
      other.popScale == popScale &&
      other.popDecayMs == popDecayMs &&
      other.shadowColorExplicit == shadowColorExplicit;

  @override
  int get hashCode => Object.hash(normalColor, highlightColor, outlineColor,
      shadowColor, shadowAlpha, fontName, fontSize, popEnabled, popScale,
      popDecayMs, shadowColorExplicit);

  /// Validiert ein rohes Style-Dict und liefert Renderer-(ASS-)kwargs.
  /// Identische Semantik zu pipeline.resolve_caption_style (Python).
  static Map<String, Object> resolve(Map<Object?, Object?>? style) {
    if (style == null) return Map.of(captionStyleAssDefaults);
    return CaptionStyle.fromRaw(style).toRendererKwargs();
  }
}
