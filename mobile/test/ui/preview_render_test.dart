/// Echter Render-Test für die Caption-Preview:
/// Der CustomPainter wird auf eine echte Bitmap gemalt und pixelbasiert
/// geprüft – nicht nur, dass das Widget existiert. Das ist die Testform,
/// die der Samsung-Realität am nächsten kommt (CustomPaint → Skia).

library;
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:capti_mobile/captions/renderer.dart';
import 'package:capti_mobile/core/caption_style.dart';
import 'package:capti_mobile/ui/screens/caption_preview_painter.dart';

Future<ui.Image> _paintToImage(CustomPainter painter, Size size) async {
  final recorder = ui.PictureRecorder();
  final canvas = ui.Canvas(recorder, Offset.zero & size);
  // Hintergrund schwarz wie im Widget (Container color)
  canvas.drawRect(
      Offset.zero & size, Paint()..color = const Color(0xFF000000));
  painter.paint(canvas, size);
  final picture = recorder.endRecording();
  return picture.toImage(size.width.round(), size.height.round());
}


void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('Painter zeichnet TATSÄCHLICH sichtbare Pixel (Regression BUG 1)',
      () async {
    const size = Size(324, 576);
    final layout = computeLayout(1080, 1920);
    const words = ['So', 'sehen', 'deine', 'Captions', 'im', 'Video', 'aus'];

    final painter = CaptionPreviewPainter(
      words: words,
      activeIndex: null,
      activeScale: 100,
      style: CaptionStyle.defaults,
      layout: layout,
    );

    final img = await _paintToImage(painter, size);
    final bytes = (await img.toByteData(
            format: ui.ImageByteFormat.rawStraightRgba))!
        .buffer
        .asUint8List();
    var lit = 0;
    for (var i = 0; i < bytes.length; i += 4) {
      if (bytes[i] > 24 || bytes[i + 1] > 24 || bytes[i + 2] > 24) lit++;
    }
    expect(lit, greaterThan(500),
        reason: 'Preview muss Textpixel enthalten – gefunden: $lit');
  });

  test('Aktives Wort wird hervorgehoben (Bild verändert sich messbar)',
      () async {
    const size = Size(324, 576);
    final layout = computeLayout(1080, 1920);
    const words = ['So', 'sehen'];

    Future<List<int>> render(int? activeIdx, double scale) async {
      final img = await _paintToImage(
          CaptionPreviewPainter(
              words: words,
              activeIndex: activeIdx,
              activeScale: scale,
              style: CaptionStyle.defaults,
              layout: layout),
          size);
      return (await img.toByteData(
              format: ui.ImageByteFormat.rawStraightRgba))!
          .buffer
          .asUint8List();
    }

    final b = await render(null, 100);
    final a = await render(0, 130);
    var diff = 0;
    for (var i = 0; i < b.length; i += 4) {
      if (b[i] != a[i] || b[i + 2] != a[i + 2]) diff++;
    }
    expect(diff, greaterThan(50),
        reason: 'Pop/Highlight muss das Bild messbar verändern');
  });

  test('Leere Timeline zeichnet sichtbaren Platzhalter statt Schwarz',
      () async {
    const size = Size(324, 576);
    final layout = computeLayout(1080, 1920);
    final img = await _paintToImage(
        CaptionPreviewPainter(
            words: const [],
            activeIndex: null,
            activeScale: 100,
            style: CaptionStyle.defaults,
            layout: layout),
        size);
    final bytes = (await img.toByteData(
            format: ui.ImageByteFormat.rawStraightRgba))!
        .buffer
        .asUint8List();
    var lit = 0;
    for (var i = 0; i < bytes.length; i += 4) {
      if (bytes[i] > 24 || bytes[i + 1] > 24 || bytes[i + 2] > 24) lit++;
    }
    expect(lit, greaterThan(20));
  });
  test('STATISCHER FALLBACK: leere Timeline zeigt großen sichtbaren Satz',
      () async {
    const size = Size(292, 519); // Android-artig: 360dp Gerät, adaptive Breite
    final layout = computeLayout(1080, 1920);
    final img = await _paintToImage(
        CaptionPreviewPainter(
            words: const [],
            activeIndex: null,
            activeScale: 100,
            style: CaptionStyle.defaults,
            layout: layout,
            staticFallbackText: 'So sehen deine Captions im Video aus'),
        size);
    final bytes = (await img.toByteData(
            format: ui.ImageByteFormat.rawStraightRgba))!
        .buffer
        .asUint8List();
    var white = 0;
    for (var i = 0; i < bytes.length; i += 4) {
      if (bytes[i] > 200 && bytes[i + 1] > 200 && bytes[i + 2] > 200) white++;
    }
    expect(white, greaterThan(300),
        reason: 'Statischer Fallback muss groß und weiß sichtbar sein '
            '(gefunden: $white weiße Pixel)');
  });

  test('Defekter/fehlender Font: Text bleibt dank Fallback-Kette sichtbar',
      () async {
    const size = Size(324, 576);
    final layout = computeLayout(1080, 1920);
    // fontName bewusst auf einen auf Android nicht existierenden Desktop-
    // Font setzen – die fontFamilyFallback muss das abfangen.
    final d = CaptionStyle.defaults;
    final styled = CaptionStyle(
      normalColor: d.normalColor,
      highlightColor: d.highlightColor,
      outlineColor: d.outlineColor,
      shadowColor: d.shadowColor,
      shadowAlpha: d.shadowAlpha,
      shadowColorExplicit: d.shadowColorExplicit,
      fontName: 'NichtExistierenderDesktopFont',
      fontSize: d.fontSize,
      popEnabled: true,
      popScale: d.popScale,
      popDecayMs: d.popDecayMs,
    );
    final img = await _paintToImage(
        CaptionPreviewPainter(
            words: const ['So', 'sehen', 'deine'],
            activeIndex: null,
            activeScale: 100,
            style: styled,
            layout: layout),
        size);
    final bytes = (await img.toByteData(
            format: ui.ImageByteFormat.rawStraightRgba))!
        .buffer
        .asUint8List();
    var lit = 0;
    for (var i = 0; i < bytes.length; i += 4) {
      if (bytes[i] > 24 || bytes[i + 1] > 24 || bytes[i + 2] > 24) lit++;
    }
    expect(lit, greaterThan(500),
        reason: 'Auch mit nicht vorhandenem FontName müssen Textpixel '
            'gerendert werden (Fallback-Kette) – gefunden: $lit');
  });

  test('Ungültige Größe (Size.zero) wirft nicht und zeichnet nichts',
      () async {
    final layout = computeLayout(1080, 1920);
    final painter = CaptionPreviewPainter(
        words: const ['A'],
        activeIndex: null,
        activeScale: 100,
        style: CaptionStyle.defaults,
        layout: layout);
    final recorder = ui.PictureRecorder();
    final canvas = ui.Canvas(recorder);
    expect(() => painter.paint(canvas, ui.Size.zero), returnsNormally);
    recorder.endRecording();
  });


  test('CAPTI-Badge ist IMMER gezeichnet – auch bei leerer Timeline',
      () async {
    const size = Size(292, 519);
    final layout = computeLayout(1080, 1920);
    final img = await _paintToImage(
        CaptionPreviewPainter(
            words: const [],
            activeIndex: null,
            activeScale: 100,
            style: CaptionStyle.defaults,
            layout: layout,
            staticFallbackText: 'So sehen deine Captions'),
        size);
    final bytes = (await img.toByteData(
            format: ui.ImageByteFormat.rawStraightRgba))!
        .buffer
        .asUint8List();
    // Obere linke Ecke (Badge-Region) muss helle Pixel enthalten:
    const regionW = 80 * 4; // px*bytesPerPx grob
    var litTopLeft = 0;
    for (var y = 0; y < 30; y++) {
      for (var x = 0; x < regionW; x += 4) {
        final i = (y * size.width.round() * 4) + x;
        if (i + 2 < bytes.length &&
            (bytes[i] > 100 || bytes[i + 1] > 100 || bytes[i + 2] > 100)) {
          litTopLeft++;
        }
      }
    }
    expect(litTopLeft, greaterThan(5),
        reason: 'Stufe-1-Diagnose CAPTI oben links fehlt '
            '($litTopLeft Pixel)');
  });
}
