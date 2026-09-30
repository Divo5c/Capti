/// Caption-Preview-Painter: zeichnet die animierte 9:16-Vorschau exakt
/// mit der Renderer-Port-Mathematik (computeLayout + currentPopState).
///
/// Öffentliche Klasse, damit Pixel-Render-Tests denselben Codepfad nutzen
/// wie das Gerät (siehe test/ui/preview_render_test.dart).

library;
import 'package:flutter/material.dart';

import '../../captions/renderer.dart';
import '../../core/caption_style.dart';

class CaptionPreviewPainter extends CustomPainter {
  final List<String> words;
  final int? activeIndex;
  final double activeScale;
  final CaptionStyle style;
  final CaptionLayout layout;

  /// Garantiert sichtbarer statischer Fallback, falls Timeline/Animation
  /// versagen: wird statt einer leeren Fläche groß auf das Canvas gemalt.
  final String staticFallbackText;

  CaptionPreviewPainter({
    required this.words,
    required this.activeIndex,
    required this.activeScale,
    required this.style,
    required this.layout,
    this.staticFallbackText = 'CAPTI PREVIEW',
  });

  String? get _safeFont {
    final n = style.fontName.trim();
    if (n.isEmpty || n.toLowerCase() == 'default') return null;
    return n;
  }

  @override
  void paint(Canvas canvas, Size size) {
    // Geraete-Diagnose: IMMER loggen (auch Release), damit adb logcat die Preview verfolgt.
    // Throttle: nur bei Groessenwechsel oder erstem Paint wird voll geloggt – hier immer, da paint selten genug.
    debugPrint(
        'PREVIEW_PAINT words=${words.length} active=$activeIndex scale=${activeScale.toStringAsFixed(1)} size=${size.width.toStringAsFixed(1)}x${size.height.toStringAsFixed(1)} fallback="$staticFallbackText" font=${style.fontName}');
    if (size.isEmpty) {
      debugPrint('PREVIEW_PAINT_EMPTY size.isEmpty');
      return;
    }
    // STUFE 1 – "CAPTI"-Label immer sichtbar: Wenn dieses auf dem Gerät
    // erscheint, ist CustomPaint/Canvas/TextPaint grundsätzlich funktions-
    // fähig; fehlt es, liegt das Problem im Layout/Clip – nicht in der
    // Timeline. Statisch, ohne Animation, ohne Font-Abhängigkeit.
    _drawCaptiBadge(canvas, size);
    if (words.isEmpty) {
      // STATISCHER FALLBACK: Die Preview darf niemals eine leere Fläche
      // sein. Großer, weißer, zentrierter Caption-Text + kleine Diagnose.
      _drawStaticFallback(canvas, size);
      return;
    }

    final scaleH = size.height / layout.playResY;
    final fontSizePx =
        (layout.fontSize * scaleH).clamp(10.0, 60.0).toDouble();

    // Zwei Zeilen wie im Renderer aufbauen
    final perLine = layout.maxWordsPerLine < 1 ? 1 : layout.maxWordsPerLine;
    final lines = <List<int>>[];
    for (var i = 0; i < words.length && lines.length < 2; i += perLine) {
      lines.add([
        for (var j = i; j < words.length && j < i + perLine; j++) j
      ]);
    }

    final safeAreaBottom =
        (size.height - layout.marginV * scaleH).clamp(0.0, size.height);
    final lineHeight = fontSizePx * 1.3;
    var firstY = safeAreaBottom - lineHeight * (lines.length - 1);
    if (firstY < 0) firstY = 0;

    for (var li = 0; li < lines.length; li++) {
      final indices = lines[li];
      final textSpans = <TextSpan>[];
      for (final idx in indices) {
        final isActive = idx == activeIndex;
        textSpans.add(TextSpan(
          text: words[idx] + (idx == indices.last ? '' : ' '),
          style: TextStyle(
            // Android-Wirklichkeit: Desktop-Fonts (z.B. 'Arial Black')
            // existieren dort nicht -> explizite Fallback-Kette, damit der
            // Text IMMEr gerendert wird statt unsichtbar zu scheitern.
            fontFamily: _safeFont,
            fontFamilyFallback: const ['Roboto', 'sans-serif'],
            color: Color(CaptionStyle.argbFromHex(
                isActive ? style.highlightColor : style.normalColor)),
            fontWeight: FontWeight.w900,
            fontSize:
                fontSizePx * (isActive ? activeScale / 100.0 : 1.0),
          ),
        ));
      }
      final tp = TextPainter(
        text: TextSpan(children: textSpans),
        textAlign: TextAlign.center,
        textDirection: TextDirection.ltr,
      )..layout(maxWidth: size.width <= 0 ? 10 : size.width);

      tp.paint(canvas, Offset((size.width - tp.width) / 2, firstY));
      firstY += lineHeight;
    }
  }

  /// Großer statischer Fallback-Text (immer deutlich sichtbar) plus
  /// dezente Diagnosezeile darunter.
  void _drawStaticFallback(Canvas canvas, Size size) {
    final main = staticFallbackText.isNotEmpty
        ? staticFallbackText
        : 'CAPTI PREVIEW';
    final fs = (size.height * 0.05).clamp(16.0, 28.0);
    final tp = TextPainter(
      text: TextSpan(
        text: main,
        style: TextStyle(
          color: const Color(0xFFFFFFFF),
          fontWeight: FontWeight.w900,
          fontSize: fs,
          fontFamily: _safeFont,
          fontFamilyFallback: const ['Roboto', 'sans-serif'],
        ),
      ),
      textAlign: TextAlign.center,
      textDirection: TextDirection.ltr,
    )..layout(maxWidth: (size.width - 16).clamp(10.0, size.width));
    tp.paint(
      canvas,
      Offset((size.width - tp.width) / 2, size.height / 2 - tp.height / 2),
    );

    final diag = TextPainter(
      text: const TextSpan(
        text: 'Timeline leer – statische Vorschau',
        style: TextStyle(color: Color(0xFFFF6B6B), fontSize: 11),
      ),
      textDirection: TextDirection.ltr,
    )..layout(maxWidth: (size.width - 16).clamp(10.0, size.width));
    diag.paint(
      canvas,
      Offset(
          (size.width - diag.width) / 2,
          size.height / 2 +
              tp.height / 2 +
              8),
    );
  }

  /// Stufe-1-Diagnose: kleines weißes CAPTI oben links.
  void _drawCaptiBadge(Canvas canvas, Size size) {
    final tp = TextPainter(
      text: const TextSpan(
        text: 'CAPTI',
        style: TextStyle(
          color: Color(0xCCFFFFFF),
          fontSize: 11,
          fontWeight: FontWeight.w700,
          letterSpacing: 1.5,
        ),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    final top = 6.0.clamp(0.0, (size.height - tp.height).clamp(0.0, 1e9));
    tp.paint(canvas, Offset(6, top));
  }

  @override
  bool shouldRepaint(covariant CaptionPreviewPainter old) =>
      old.activeIndex != activeIndex ||
      old.activeScale != activeScale ||
      old.words != words ||
      old.style != style;
}
