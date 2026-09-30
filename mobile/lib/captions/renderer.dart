/// Capti Caption-Renderer (Dart-Port).
///
/// 1:1-Port der Desktop-Algorithmik aus caption_renderer.py:
///   - computeLayout (Portrait/Landscape, Safe Area, Zeichengrenzen)
///   - formatAssTime / normalizeWordTimestamps
///   - groupCaptionSegments (Pause-/Zeichen-/Wortgrenzen)
///   - generateAss (Karaoke-Tags \k + Pop \t(\fscx\fscy))
///
/// KEINE zweite Caption-Engine: mobile erzeugt exakt dieselben
/// ASS-Dateien wie der Desktop; das Einbrennen übernimmt FFmpeg+libass.

library;

import 'dart:io';
import 'dart:math' as math;

import 'package:flutter/foundation.dart';

// ---------------------------------------------------------------------
// Layout-Grenzen (identisch zur Desktop-Version)
// ---------------------------------------------------------------------
const int minFontSize = 12;
const double maxFontRatio = 0.08;
const int maxCharsPerLine = 60;

const double minWordDuration = 0.2;
const double minDialogueDuration = 0.01;

const Map<String, Object> groupingDefaults = {
  'pause_threshold': 0.4,
  'max_words_portrait': 8,
  'max_words_landscape': 10,
};

double? _asDouble(Object? v) {
  if (v is num) return v.toDouble();
  if (v is String) return double.tryParse(v);
  return null;
}

bool _validTimeRange(double start, Object? end) {
  final e = _asDouble(end);
  return e != null && e > start;
}

@immutable
class WordTimestamp {
  final String word;
  final double start;
  final double end;
  const WordTimestamp(this.word, this.start, this.end);

  Map<String, Object> toMap() => {'word': word, 'start': start, 'end': end};
}

@immutable
class Segment {
  final double start;
  final double end;
  final String text;
  final List<WordTimestamp> words;
  const Segment({
    required this.start,
    required this.end,
    required this.text,
    this.words = const [],
  });

  Map<String, Object> toMap() => {
        'start': start,
        'end': end,
        'text': text,
        'words': words.map((w) => w.toMap()).toList(),
      };
}

@immutable
class CaptionLayout {
  final String format; // "portrait" | "landscape"
  final int playResX;
  final int playResY;
  final int fontSize;
  final int maxWordsPerLine;
  final int marginV;
  final int charsPerLine;
  const CaptionLayout({
    required this.format,
    required this.playResX,
    required this.playResY,
    required this.fontSize,
    required this.maxWordsPerLine,
    required this.marginV,
    required this.charsPerLine,
  });
}

CaptionLayout computeLayout(int videoWidth, int videoHeight) {
  final aspect = videoHeight != 0 ? videoWidth / videoHeight : 1.0;
  int fontSize;
  int marginV;
  int maxWordsPerLine;
  if (aspect < 1.0) {
    // Portrait / Shorts (z.B. 1080x1920, 720x1280):
    // Font relativ zur KURZEN Seite (Python: min(w,h) * 0.062).
    fontSize = (math.min(videoWidth, videoHeight) * 0.062).round();
    fontSize = math.max(36, fontSize);
    marginV = (videoHeight * 0.20).round();
    maxWordsPerLine = 4;
  } else {
    // Landscape – bisheriger Look (proportional zu PlayResY=1280).
    fontSize = math.max(24, (videoHeight * 68 / 1280).round());
    marginV = (videoHeight * 280 / 1280).round();
    maxWordsPerLine = 5;
  }

  // Grenzfälle: sehr kleine Videos -> Font relativ zur Höhe begrenzen.
  fontSize = math.max(minFontSize, math.min(fontSize, (videoHeight * maxFontRatio).floor()));

  // Geschätzte Zeichen pro Zeile; hartes Maximum gegen Ultra-Wide.
  final usableWidth = videoWidth * 0.88;
  final avgCharWidth = fontSize * 0.58;
  final charsPerLine =
      math.max(10, math.min(maxCharsPerLine, (usableWidth / avgCharWidth).truncate()));

  return CaptionLayout(
    format: aspect < 1.0 ? 'portrait' : 'landscape',
    playResX: videoWidth,
    playResY: videoHeight,
    fontSize: fontSize,
    maxWordsPerLine: maxWordsPerLine,
    marginV: marginV,
    charsPerLine: charsPerLine,
  );
}

String formatAssTime(double seconds) {
  if (seconds < 0) seconds = 0;
  final hours = seconds ~/ 3600;
  final minutes = ((seconds % 3600) ~/ 60).toInt();
  final secs = (seconds % 60).toInt();
  var centis = ((seconds - seconds.truncateToDouble()) * 100).round();
  if (centis >= 100) centis = 99; // Rundungsüberlauf abfangen
  return '$hours:${minutes.toString().padLeft(2, '0')}:'
      '${secs.toString().padLeft(2, '0')}.${centis.toString().padLeft(2, '0')}';
}

/// Füllt fehlende/ungültige Word-End-Timestamps robust auf
/// (identische Prioritäten wie die Desktop-Version). Kopiert die Eingabe.
List<WordTimestamp> normalizeWordTimestamps(
  List<WordTimestamp> words, {
  double? fallbackEnd,
}) {
  final normalized = <WordTimestamp>[];
  final n = words.length;
  for (var i = 0; i < n; i++) {
    final w = words[i];
    if (_validTimeRange(w.start, w.end)) {
      normalized.add(w);
      continue;
    }
    double? resolved;
    // 1) Ende aus dem nächsten Word-Start ableiten
    if (i + 1 < n && words[i + 1].start > w.start) {
      resolved = words[i + 1].start;
    }
    // 2) Übergeordnetes Segment-Ende
    if (resolved == null && _validTimeRange(w.start, fallbackEnd)) {
      resolved = fallbackEnd;
    }
    // 3) Sicherer Fallback
    resolved ??= w.start + minWordDuration;
    normalized.add(WordTimestamp(w.word, w.start, resolved));
  }
  return normalized;
}

/// Teilt lange Segmente in kurze, natürlich wirkende Gruppen
/// (Break-Priorität: Zeichenbudget -> Sprechpause -> Wortlimit).
List<Segment> groupCaptionSegments(
  List<Segment> segments, {
  CaptionLayout? layout,
  double? pauseThreshold,
  int? maxWordsPerGroup,
  int? maxCharsPerGroup,
}) {
  pauseThreshold ??= groupingDefaults['pause_threshold']! as double;
  if (layout != null) {
    maxWordsPerGroup ??= layout.format == 'portrait'
        ? groupingDefaults['max_words_portrait']! as int
        : groupingDefaults['max_words_landscape']! as int;
    maxCharsPerGroup ??= layout.charsPerLine * 2;
  }

  final grouped = <Segment>[];
  for (final segment in segments) {
    if (segment.words.length <= 1) {
      grouped.add(segment); // nichts zu gruppieren
      continue;
    }
    final words =
        normalizeWordTimestamps(segment.words, fallbackEnd: segment.end);

    var current = <WordTimestamp>[words.first];
    var currentChars = words.first.word.length;

    void flush() {
      grouped.add(Segment(
        start: current.first.start,
        end: current.last.end,
        text: current.map((w) => w.word).join(' '),
        words: List.of(current),
      ));
    }

    for (var i = 0; i < words.length - 1; i++) {
      final prev = words[i];
      final nxt = words[i + 1];
      final gap = nxt.start - prev.end;
      final wouldExceedChars = maxCharsPerGroup != null &&
          currentChars + 1 + nxt.word.length > maxCharsPerGroup;
      final reachedWordLimit =
          maxWordsPerGroup != null && current.length >= maxWordsPerGroup;

      if (gap >= pauseThreshold || wouldExceedChars || reachedWordLimit) {
        flush();
        current = [nxt];
        currentChars = nxt.word.length;
      } else {
        current.add(nxt);
        currentChars += 1 + nxt.word.length;
      }
    }
    flush();
  }
  return grouped;
}

/// Pop-Zeitfenster eines Worts relativ zum Dialogue-Start (ms).
@immutable
class PopSlot {
  final double startMs;
  final double endMs;
  final double decayEndMs;
  const PopSlot(this.startMs, this.endMs, this.decayEndMs);
}

/// Pop-Zustand eines Worts zum Zeitpunkt tMs (ASS-\t-Semantik):
/// während des Worts auf popScale hochskalieren, danach linear zurück.
/// Identische Mathematik zum Desktop-Preview (_current_pop_state).
({int? active, double scale}) currentPopState({
  required bool popEnabled,
  required int popScalePct,
  required List<PopSlot> timeline,
  required double tMs,
}) {
  int? active;
  var scale = 100.0;
  if (!popEnabled) {
    for (var i = 0; i < timeline.length; i++) {
      final slot = timeline[i];
      if (tMs >= slot.startMs && tMs < slot.endMs) {
        active = i;
        break;
      }
    }
    return (active: active, scale: scale);
  }
  final target = popScalePct < 100 ? 100 : popScalePct;
  for (var i = 0; i < timeline.length; i++) {
    final slot = timeline[i];
    if (tMs >= slot.startMs && tMs < slot.decayEndMs) {
      active = i;
      if (tMs < slot.endMs) {
        final denom = math.max(1.0, slot.endMs - slot.startMs);
        final frac = ((tMs - slot.startMs) / denom) * 1.6;
        scale =
            100 + (target - 100) * math.min(1.0, math.max(0.0, frac));
      } else {
        final denom = math.max(1.0, slot.decayEndMs - slot.endMs);
        final frac = math.min(1.0, (tMs - slot.endMs) / denom);
        scale = target - (target - 100) * frac;
      }
      break;
    }
  }
  if (scale < 100.0) scale = 100.0;
  return (active: active, scale: scale);
}

/// Verteilt Karaoke-Wörter auf maximal 2 Zeilen
/// (max_words_per_line + geschätzte Zeichenbreite).
String applyLineBreaks(List<String> parts, List<int>? wordLengths,
    {int? maxPerLineOverride, int? charsLimit}) {
  final n = parts.length;
  final lengths = wordLengths ?? List.filled(n, 0);
  final maxPerLine = math.max(1, maxPerLineOverride ?? 5);

  var cut = n;
  var wordCount = 0;
  var charAcc = 0;
  for (var i = 0; i < n; i++) {
    final addChars = lengths[i] + (i > 0 ? 1 : 0);
    if (wordCount >= maxPerLine) {
      cut = i;
      break;
    }
    if (charsLimit != null && i > 0 && charAcc + addChars > charsLimit) {
      cut = i;
      break;
    }
    wordCount++;
    charAcc += addChars;
  }

  if (cut >= n) return parts.join(' ');
  return '${parts.take(cut).join(' ')}\\N${parts.skip(cut).join(' ')}';
}

class CaptionRenderer {
  String normalColor; // ASS &H...
  String highlightColor;
  String outlineColor;
  String shadowColor;
  String fontName;
  int fontSize;
  int marginV;
  int maxWordsPerLine;
  int popScale;
  int popDecayMs;
  bool popEnabled;
  int? charsPerLine;

  CaptionRenderer({
    this.normalColor = '&H00FFFFFF',
    this.highlightColor = '&H0000FFFF',
    this.outlineColor = '&H00101010',
    this.shadowColor = '&H80000000',
    this.fontName = 'Arial Black',
    this.fontSize = 68,
    this.marginV = 280,
    this.maxWordsPerLine = 5,
    this.popScale = 112,
    this.popDecayMs = 150,
    this.popEnabled = true,
    this.charsPerLine,
  });

  /// Baut einen Renderer aus den validierten Style-Kwargs
  /// (CaptionStyle.toRendererKwargs()).
  factory CaptionRenderer.fromStyleKwargs(Map<String, Object> kwargs) =>
      CaptionRenderer(
        normalColor: kwargs['normal_color']! as String,
        highlightColor: kwargs['highlight_color']! as String,
        outlineColor: kwargs['outline_color']! as String,
        shadowColor: kwargs['shadow_color']! as String,
        fontName: kwargs['font_name']! as String,
        fontSize: kwargs['font_size']! as int,
        popEnabled: kwargs['pop_enabled']! as bool,
        popScale: kwargs['pop_scale']! as int,
        popDecayMs: kwargs['pop_decay_ms']! as int,
      );

  String _buildKaraokeText(Segment segment) {
    if (segment.words.isEmpty) return segment.text;

    final segStart = segment.start;
    final parts = <String>[];
    final wordLengths = <int>[];
    final n = segment.words.length;
    for (var i = 0; i < n; i++) {
      final w = segment.words[i];
      double nextStart;
      if (i + 1 < n) {
        nextStart = segment.words[i + 1].start;
      } else {
        nextStart = _validTimeRange(w.start, segment.end)
            ? segment.end
            : w.end;
      }
      // Karaoke-Dauer immer positiv halten (min. 1 Zentisekunde).
      final span = math.max(nextStart, w.end) - w.start;
      final durationCs = math.max(1, (span * 100).round());

      // Pop/Scale-Effekt: \t-Zeiten in ms relativ zum Dialogue-Start.
      final tUp = math.max(0, ((w.start - segStart) * 1000).round());
      final tDown = math.max(tUp + 1, ((w.end - segStart) * 1000).round());
      final tBack = tDown + popDecayMs;
      final popTag = popEnabled
          ? '{\\t($tUp,$tDown,\\fscx$popScale\\fscy$popScale)'
              '\\t($tDown,$tBack,\\fscx100\\fscy100)}'
          : '';
      parts.add('{\\k$durationCs}$popTag${w.word}');
      wordLengths.add(w.word.length);
    }

    return applyLineBreaks(parts, wordLengths,
        maxPerLineOverride: maxWordsPerLine, charsLimit: charsPerLine);
  }

  /// Generiert eine ASS-Datei mit Word-by-Word-Highlighting.
  /// [videoWidth]/[videoHeight] aktivieren das adaptive Layout
  /// (Fallback: feste PlayRes 720x1280 mit Konstruktor-Werten).
  String generateAss(
    List<Segment> segments,
    String outputPath, {
    int? videoWidth,
    int? videoHeight,
  }) {
    int playResX;
    int playResY;
    int effectiveFontSize;
    int effectiveMarginV;
    if (videoWidth != null && videoHeight != null) {
      final layout = computeLayout(videoWidth, videoHeight);
      playResX = layout.playResX;
      playResY = layout.playResY;
      effectiveFontSize = layout.fontSize;
      effectiveMarginV = layout.marginV;
      maxWordsPerLine = layout.maxWordsPerLine;
      charsPerLine = layout.charsPerLine;
    } else {
      playResX = 720;
      playResY = 1280;
      effectiveFontSize = fontSize;
      effectiveMarginV = marginV;
      charsPerLine = null;
    }

    // Android libass: Arial Black existiert nicht in /system/fonts -> Fallback Roboto
    // Preview hat fontFamilyFallback, ASS benoetigt echten vorhandenen Font.
    String effectiveFontName = fontName;
    if (Platform.isAndroid && fontName.toLowerCase() == 'arial black') {
      effectiveFontName = 'Roboto';
    }
    // Noch sicherer: falls Roboto nicht gefunden, libass faellt auf Default zurueck
    // (fontsdir=/system/fonts enthaelt Roboto-Regular.ttf)
    final header = '''[Script Info]
Title: Capti Captions
ScriptType: v4.00+
WrapStyle: 2
PlayResX: $playResX
PlayResY: $playResY
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,$effectiveFontName,$effectiveFontSize,$highlightColor,$normalColor,$outlineColor,$shadowColor,1,0,0,0,100,100,0,0,1,4,1,2,40,40,$effectiveMarginV,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
''';

    final lines = <String>[header];
    for (final segment in segments) {
      final text = _buildKaraokeText(segment);
      if (text.isEmpty) continue;
      var segEnd = segment.end;
      // Garantie: Dialogue-Ende immer echt nach dem Start.
      if (segEnd <= segment.start) {
        segEnd = segment.start + minDialogueDuration;
      }
      lines.add('Dialogue: 0,${formatAssTime(segment.start)},'
          '${formatAssTime(segEnd)},Caption,,0,0,0,,$text');
    }

    File(outputPath).writeAsStringSync(lines.join('\n'), mode: FileMode.write);
    return outputPath;
  }
}
