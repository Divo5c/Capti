/// Renderer-Port-Tests: Schlüsselverhalten aus tests/test_caption_renderer.py
/// (Desktop) als Paritäts-Nachweis für die mobile ASS-Erzeugung.

library;
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:capti_mobile/captions/renderer.dart';
import 'package:capti_mobile/core/caption_style.dart';

List<WordTimestamp> makeWords(List<(String, double, double?)> defs) => [
      for (final (word, start, end) in defs)
        WordTimestamp(word, start, end ?? start + 0.3),
    ];

void main() {
  group('computeLayout', () {
    test('Portrait und Landscape unterscheiden sich', () {
      final p = computeLayout(1080, 1920);
      final l = computeLayout(1920, 1080);
      expect(p.fontSize, isNot(l.fontSize));
      expect(p.maxWordsPerLine, isNot(l.maxWordsPerLine));
      expect(p.format, 'portrait');
      expect(l.format, 'landscape');
    });

    test('Portrait-Werte entsprechen Desktop-Berechnung (1080x1920)', () {
      // Python: font = max(36, round(min(1080,1920)*0.062)) = round(66.96)=67
      final p = computeLayout(1080, 1920);
      expect(p.playResX, 1080);
      expect(p.playResY, 1920);
      expect(p.fontSize, 67);
      expect(p.marginV, 384); // 1920*0.20
      expect(p.maxWordsPerLine, 4);
    });

    test('Landscape-Werte entsprechen Desktop-Berechnung (1920x1080)', () {
      final l = computeLayout(1920, 1080);
      expect(l.fontSize, 57); // round(1080*68/1280)=round(57.375)=57
      expect(l.marginV, 236); // round(1080*280/1280)=236
      expect(l.maxWordsPerLine, 5);
    });
  });

  group('formatAssTime', () {
    test('Format H:MM:SS.cc mit Rundungsüberlauf-Schutz', () {
      expect(formatAssTime(0), '0:00:00.00');
      expect(formatAssTime(61.5), '0:01:01.50');
      expect(formatAssTime(1.999), startsWith('0:00:01.'));
    });
  });

  group('normalizeWordTimestamps', () {
    test('gültige Ends bleiben exakt unverändert', () {
      final words =
          makeWords([('Hallo', 1.0, 1.5)]);
      final out = normalizeWordTimestamps(words);
      expect(out.single.end, 1.5);
    });

    test('fehlendes End -> nächster Wortstart', () {
      final words = [
        const WordTimestamp('eins', 1.0, 1.0),
        const WordTimestamp('zwei', 1.7, 2.0),
      ];
      final out = normalizeWordTimestamps(words);
      expect(out[0].end, 1.7);
      expect(out[1].end, 2.0);
    });

    test('gar nichts -> Fallback start+0.2', () {
      final out = normalizeWordTimestamps(
          [const WordTimestamp('solo', 5.0, 5.0)]);
      expect(out.single.end, closeTo(5.2, 1e-9));
    });
  });

  group('groupCaptionSegments', () {
    test('Pause >= 0.4 s beendet die Gruppe', () {
      final seg = Segment(
        start: 0,
        end: 3.0,
        text: '',
        words: makeWords([
          ('a', 0.0, 0.3),
          ('b', 0.4, 0.6),
          ('c', 1.2, 1.4), // Pause von 0.6 s davor
          ('d', 1.5, 1.8),
        ]),
      );
      final groups = groupCaptionSegments([seg]);
      expect(groups.length, 2);
      expect(groups[0].words.map((w) => w.word), ['a', 'b']);
      expect(groups[1].words.map((w) => w.word), ['c', 'd']);
    });

    test('Wortlimit pro Gruppe wird respektiert', () {
      final seg = Segment(
        start: 0,
        end: 2.0,
        text: '',
        words: makeWords([
          ('w1', 0.0, 0.2),
          ('w2', 0.3, 0.5),
          ('w3', 0.6, 0.8),
          ('w4', 0.9, 1.1),
          ('w5', 1.2, 1.4),
        ]),
      );
      final groups = groupCaptionSegments([seg],
          pauseThreshold: 10, maxWordsPerGroup: 3);
      expect(groups.map((g) => g.words.length).toList(), [3, 2]);
    });
  });

  group('generateAss', () {
    late Directory tmp;
    setUp(() => tmp = Directory.systemTemp.createTempSync('capti_renderer_'));
    tearDown(() => tmp.deleteSync(recursive: true));

    List<String> dialogueLines(String content) => content
        .split('\n')
        .where((l) => l.startsWith('Dialogue:'))
        .toList();

    test('PlayRes entspricht echter Videoauflösung + Karaoke/Pop vorhanden',
        () {
      final renderer = CaptionRenderer();
      final path =
          '${tmp.path}/test.ass';
      renderer.generateAss(
        [
          Segment(
            start: 0,
            end: 2,
            text: 'Hallo Welt du da',
            words: makeWords([
              ('Hallo', 0.0, 0.4),
              ('Welt', 0.5, 0.9),
              ('du', 1.0, 1.2),
              ('da', 1.3, 1.8),
            ]),
          ),
        ],
        path,
        videoWidth: 1080,
        videoHeight: 1920,
      );
      final content = File(path).readAsStringSync();
      expect(content.contains('PlayResX: 1080'), true);
      expect(content.contains('PlayResY: 1920'), true);
      expect(content.contains(r'{\k'), true);
      expect(content.contains(r'\fscx112\fscy112'), true);
    });

    test('Style-Zeile enthält die Style-Kwargs-Farben', () {
      final kwargs = CaptionStyle.fromRaw({
        'normal_color': '#FF0000',
        'highlight_color': '#00FF00',
      }).toRendererKwargs();
      final renderer = CaptionRenderer.fromStyleKwargs(kwargs);
      final path = '${tmp.path}/style.ass';
      renderer.generateAss([
        Segment(start: 0, end: 1, text: 'x',
            words: [const WordTimestamp('x', 0.0, 0.8)]),
      ], path);
      final content = File(path).readAsStringSync();
      expect(content.contains('&H000000FF'), true); // #FF0000 -> BGR FF0000
      expect(content.contains('&H0000FF00'), true); // #00FF00 -> BGR 00FF00
    });

    test('Segment ohne Worte nutzt Segmenttext ohne Karaoke-Tags', () {
      final renderer = CaptionRenderer();
      final path = '${tmp.path}/plain.ass';
      renderer.generateAss(
          [const Segment(start: 0, end: 1, text: 'nur Text')], path);
      final lines = dialogueLines(File(path).readAsStringSync());
      expect(lines.single.contains('{\\k'), false);
      expect(lines.single.contains('nur Text'), true);
    });

    test('Dialogue-Ende ist garantiert nach dem Start', () {
      final renderer = CaptionRenderer();
      final path = '${tmp.path}/clamp.ass';
      renderer.generateAss(
          [const Segment(start: 5, end: 5, text: 'x')], path);
      final line = dialogueLines(File(path).readAsStringSync()).single;
      expect(line.contains('0:00:05.00,0:00:05.01'), true);
    });
  });

  group('currentPopState (Preview-Mathematik)', () {
    final timeline = <PopSlot>[
      for (var i = 0; i < 4; i++)
        PopSlot(300.0 + i * 510, 750.0 + i * 510, 900.0 + i * 510),
    ];

    test('vor erstem Wort: kein aktives Wort, Scale 100', () {
      final r = currentPopState(popEnabled: true, popScalePct: 112,
          timeline: timeline, tMs: 100);
      expect(r.active, isNull);
      expect(r.scale, 100.0);
    });

    test('Mitte des Worts: Skala steigt Richtung popScale', () {
      final r = currentPopState(popEnabled: true, popScalePct: 112,
          timeline: timeline, tMs: 525);
      expect(r.active, 0);
      // frac=(225/450)*1.6=0.8 -> 100+12*0.8=109.6
      expect(r.scale, closeTo(109.6, 0.01));
    });

    test('nach Wortende: linearer Rückweg auf 100', () {
      final r = currentPopState(popEnabled: true, popScalePct: 112,
          timeline: timeline, tMs: 750 + 75); // Mitte Decay
      expect(r.active, 0);
      expect(r.scale, closeTo(106.0, 0.01)); // 112-(12*0.5)
    });

    test('popEnabled=false: nur Highlight, Scale bleibt 100', () {
      final r = currentPopState(popEnabled: false, popScalePct: 112,
          timeline: timeline, tMs: 500);
      expect(r.active, 0);
      expect(r.scale, 100.0);
    });
  });
}
