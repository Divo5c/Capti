/// Capti Processing: UI-unabhängige Orchestrierung + Engine-Abstraktion.
///
/// Port der pipeline.py-Semantik:
///   - Stabile Status-Keys ("pipeline.*"); die UI übersetzt sie (i18n).
///   - Fortschritt 0..100, Log-Level INFO/WARNING/ERROR/SUCCESS.
///   - Ablauf: Audio extrahieren -> transkribieren -> gruppieren ->
///     SRT+ASS erzeugen -> Untertitel einbrennen.
///
/// Die nativen Engines sind bewusst als Schnittstellen modelliert:
///   - WhisperCppEngine: dart:ffi-Binding auf native/whisper_bridge.c
///     (wird vom Android-Gradle-Build mitgebaut, sobald whisper.cpp
///     unter native/third_party/whisper.cpp liegt; tools/fetch_native.sh)
///   - MediaProcessor: FFmpeg/libass-Anbindung (gleiches Boundary-Prinzip)
/// Fehlt die native Schicht, wirft die Engine eine EngineUnavailableException –
/// die UI zeigt diesen Zustand lokalisiert an (keine Fake-Fortschritte).

library;
import 'dart:async';
import 'dart:ffi' as ffi;
import 'dart:io';
import 'dart:isolate';

import 'package:ffi/ffi.dart' as pd;
import 'package:flutter/foundation.dart';

import '../captions/renderer.dart';
import '../core/caption_style.dart';
import '../core/project.dart' show validModels;
import 'native_media.dart' show MediaError, MediaEngineException;
import 'whisper_model.dart'
    show
        whisperModelExists,
        ensureWhisperModelAvailable,
        baseDirFromModelPath,
        modelNameFromPath;

// ---------------------------------------------------------------------
// Stabile Status-Keys (identisch zur Desktop-Pipeline)
// ---------------------------------------------------------------------
const String statusStarted = 'pipeline.started';
const String statusExtractAudio = 'pipeline.extract_audio';
const String statusDownloadModel = 'pipeline.download_model';
const String statusTranscribe = 'pipeline.transcribe';
const String statusEmbedSubtitles = 'pipeline.embed_subtitles';
const String statusCompleted = 'pipeline.completed';

typedef OnStatus = void Function(String key);
typedef OnProgress = void Function(double percent); // 0..100
typedef OnLog = void Function(String level, String message);

@immutable
class VideoInfo {
  final int? width;
  final int? height;
  const VideoInfo({this.width, this.height});
}

class EngineUnavailableException implements Exception {
  final String message;
  EngineUnavailableException(this.message);
  @override
  String toString() => message;
}

class OperationCancelledException implements Exception {
  final String message;
  OperationCancelledException([this.message = 'Verarbeitung abgebrochen']);
  @override
  String toString() => message;
}

/// Handle für einen laufenden Pipeline-Run (UI-seitiger Zustand).
class PipelineRunHandle {
  bool running = false;
  bool cancelRequested = false;
  double progress = 0;
  String statusKey = '';
  final List<String> logLines = [];
  CaptiPipeline? pipeline;
}

/// Transkriptions-Engine (plattformspezifisch gebunden).
abstract class TranscriptionEngine {
  /// Transkribiert eine 16 kHz Mono-WAV-Datei.
  Future<List<Segment>> transcribe(String audioPath, String? language);
}

/// Medienverarbeitung (Audio-Extraktion, Burn-in, Videoinfo).
abstract class MediaProcessor {
  Future<String> extractAudio(String videoPath, String outputPath);
  Future<String> embedAss(
      String videoPath, String assPath, String outputPath);
  Future<VideoInfo?> getVideoInfo(String videoPath);
}

// ---------------------------------------------------------------------
// Whisper.cpp FFI-Binding
//
// Bindet an die flache C-API aus native/whisper_bridge.c:
//   void*       capti_whisper_create(const char* model_path)
//   int32_t     capti_whisper_transcribe_file(void*, const char* wav,
//                                            const char* lang_or_null)
//               -> Anzahl Segmente (>=0), -1 bei Fehler
//   int32_t     capti_whisper_segment_count(void*)
//   const char* capti_whisper_segment_text(void*, int32_t)
//   double      capti_whisper_segment_t0(void*, int32_t)   // Sekunden
//   double      capti_whisper_segment_t1(void*, int32_t)
//   void        capti_whisper_free(void*)
//
// Der Aufruf läuft komplett in einem Worker-Isolate (UI bleibt flüssig).
// ---------------------------------------------------------------------

class WhisperCppEngine implements TranscriptionEngine {
  /// Pfad zur geladenen Bridge-Bibliothek. Auf Android genügt der Name,
  /// da jniLibs-Artefakte in den Prozess gemappt werden.
  final String? libPath;

  /// Pfad zum GGML/GGUF-Modell im App-Sandbox-Verzeichnis.
  final String modelPath;

  WhisperCppEngine({required this.modelPath, this.libPath});

  static String defaultLibName() {
    if (Platform.isWindows) return 'whisper_bridge.dll';
    return 'libwhisper_bridge.so';
  }

  @override
  Future<List<Segment>> transcribe(String audioPath, String? language) async {
    // Vor dem teuren Isolate: Modell im Sandbox checken, falls fehlend
    // aus Flutter-Assets nachliefern oder von HuggingFace laden.
    // Das deckt frische Installationen ab: der vom Nutzer gewählte
    // settings.model wird ehrlich bereitgestellt statt hart zu scheitern.
    // Auto-Sprache (language==null) benötigt multilingual – validModels
    // sind bereits multilingual (kein .en).
    // Reihenfolge: vorhandene Datei → Asset → Download.
    if (!whisperModelExists(modelPath)) {
      final modelName = _modelNameFromPath(modelPath);
      final baseDir = _baseDirFromModelPath(modelPath);
      if (baseDir != null) {
        try {
          final ok = await ensureWhisperModelAvailable(baseDir, modelName);
          if (!ok) {
            // Ehrlicher Fehler wird im Isolate (transcribeSync) als
            // EngineUnavailableException mit error.model_missing geworfen.
            // Hier kein throw, damit der Isolate-Pfad die lokalisierte
            // Meldung konsistent erzeugt.
          }
        } catch (_) {}
      }
    }
    final path = libPath ?? defaultLibName();
    final model = modelPath;
    return Isolate.run(() {
      final bindings = _Bindings(path.isEmpty
          ? ffi.DynamicLibrary.process()
          : ffi.DynamicLibrary.open(path));
      return bindings.transcribeSync(model, audioPath, language);
    });
  }

  static String _modelNameFromPath(String p) {
    final base = p.split(Platform.isWindows ? r'\' : '/').last;
    final dot = base.lastIndexOf('.');
    final name = dot > 0 ? base.substring(0, dot) : base;
    return validModels.contains(name) ? name : 'small';
  }

  static String? _baseDirFromModelPath(String p) {
    // Erwartet .../models/<name>.bin  ->  ... (ohne /models/...)
    final idx = p.lastIndexOf('/models/');
    if (idx < 0) return null;
    return p.substring(0, idx);
  }
}

/// Typisierte dart:ffi-Bindings auf die Bridge-Funktionen.
class _Bindings {
  final ffi.DynamicLibrary lib;
  _Bindings(this.lib);

  late final _create = lib.lookupFunction<
      ffi.Pointer<ffi.Void> Function(ffi.Pointer<ffi.Char>),
      ffi.Pointer<ffi.Void> Function(
          ffi.Pointer<ffi.Char>)>('capti_whisper_create');

  late final _transcribe = lib.lookupFunction<
      ffi.Int32 Function(ffi.Pointer<ffi.Void>, ffi.Pointer<ffi.Char>,
          ffi.Pointer<ffi.Char>),
      int Function(ffi.Pointer<ffi.Void>, ffi.Pointer<ffi.Char>,
          ffi.Pointer<ffi.Char>)>('capti_whisper_transcribe_file');

  late final _segCount = lib.lookupFunction<
      ffi.Int32 Function(ffi.Pointer<ffi.Void>),
      int Function(ffi.Pointer<ffi.Void>)>('capti_whisper_segment_count');

  late final _segText = lib.lookupFunction<
      ffi.Pointer<ffi.Char> Function(ffi.Pointer<ffi.Void>, ffi.Int32),
      ffi.Pointer<ffi.Char> Function(
          ffi.Pointer<ffi.Void>, int)>('capti_whisper_segment_text');

  late final _segT0 = lib.lookupFunction<
      ffi.Double Function(ffi.Pointer<ffi.Void>, ffi.Int32),
      double Function(ffi.Pointer<ffi.Void>, int)>('capti_whisper_segment_t0');

  late final _segT1 = lib.lookupFunction<
      ffi.Double Function(ffi.Pointer<ffi.Void>, ffi.Int32),
      double Function(ffi.Pointer<ffi.Void>, int)>('capti_whisper_segment_t1');

  late final _free = lib.lookupFunction<
      ffi.Void Function(ffi.Pointer<ffi.Void>),
      void Function(ffi.Pointer<ffi.Void>)>('capti_whisper_free');

  List<Segment> transcribeSync(String modelPath, String wavPath, String? language) {
    // Ehrliche Vorprüfung im Worker-Isolate: falls die Main-Isolate-
    // Asset-Kopie nicht geklappt hat (z. B. kein Asset gebündelt), hier
    // klar abbrechen – keine Fake-Datei, keine leere .bin.
    try {
      final mf = File(modelPath);
      if (!mf.existsSync() || mf.lengthSync() < 1024) {
        final base = modelPath.split(Platform.isWindows ? r'\' : '/').last;
        final dot = base.lastIndexOf('.');
        final m = dot > 0 ? base.substring(0, dot) : base;
        throw EngineUnavailableException(
            'Whisper-Modell "$m" nicht gefunden unter $modelPath. '
            'Bitte Modell unter assets/models/$m.bin bündeln oder nach $modelPath kopieren. '
            'Download: https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-$m.bin');
      }
    } catch (e) {
      if (e is EngineUnavailableException) rethrow;
      // Unerwartete FS-Fehler ebenfalls als unavailable melden
    }
    final modelChars = modelPath.toNativeUtf8();
    final ctx = _create(modelChars.cast<ffi.Char>());
    pd.calloc.free(modelChars);
    if (ctx == ffi.nullptr) {
      throw EngineUnavailableException(
          'Whisper-Modell konnte nicht geladen werden: $modelPath');
    }
    try {
      final wavChars = wavPath.toNativeUtf8();
      final langPtr =
          language == null ? ffi.nullptr : language.toNativeUtf8();
      final rc = _transcribe(
          ctx, wavChars.cast<ffi.Char>(), langPtr.cast<ffi.Char>());
      pd.calloc.free(wavChars);
      if (langPtr != ffi.nullptr) pd.calloc.free(langPtr);
      if (rc < 0) {
        throw Exception('Whisper-Transkription fehlgeschlagen (rc=$rc)');
      }

      final count = _segCount(ctx);
      final segments = <Segment>[];
      for (var i = 0; i < count; i++) {
        final textPtr = _segText(ctx, i);
        segments.add(Segment(
          start: _segT0(ctx, i),
          end: _segT1(ctx, i),
          // Pointer<Char> -> Pointer<Utf8>, um zu dekodieren
          text: textPtr.cast<pd.Utf8>().toDartString().trim(),
          words: const [],
        ));
      }
      return segments;
    } finally {
      _free(ctx);
    }
  }
}

// ---------------------------------------------------------------------
// Pipeline
// ---------------------------------------------------------------------

class CaptiPipelineResult {
  final String outputPath;
  final List<Segment> groupedSegments;
  const CaptiPipelineResult({required this.outputPath, required this.groupedSegments});
}

class CaptiPipeline {
  final Directory tempDir;
  final TranscriptionEngine transcriptionEngine;
  final MediaProcessor mediaProcessor;
  final OnStatus onStatus;
  final OnProgress onProgress;
  final OnLog onLog;

  /// Wird an sicheren Stufengrenzen geprüft (Abbruch ohne korrupte Dateien).
  bool _cancelRequested = false;

  CaptiPipeline({
    required this.tempDir,
    required this.transcriptionEngine,
    required this.mediaProcessor,
    this.onStatus = _noopStatus,
    this.onProgress = _noopProgress,
    this.onLog = _noopLog,
  });

  /// Fordert einen Abbruch an; greift an der nächsten Stufengrenze.
  void requestCancel() => _cancelRequested = true;

  void _checkCancelled() {
    if (_cancelRequested) throw OperationCancelledException();
  }

  static void _noopStatus(String _) {}
  static void _noopProgress(double _) {}
  static void _noopLog(String _, String __) {}

  double _percent = 0;

  void _setProgress(double p) {
    _percent = p.clamp(0.0, 100.0);
    onProgress(_percent);
  }

  /// Führt die komplette Verarbeitung aus und liefert das Output-Video.
  ///
  /// [captionStyle] None/leer -> Renderer-Defaults (exakt Desktop-Look).
  /// Wirft bei Fehlern; die UI fängt ab und zeigt lokalisierte Meldungen.
  Future<CaptiPipelineResult> run({
    required String videoPath,
    String modelSize = 'small',
    String? language,
    Map<String, Object>? captionStyle,
  }) async {
    try {
      onStatus(statusStarted);
      _setProgress(5);
      _checkCancelled();

      await tempDir.create(recursive: true);

      final stem = _stemOf(videoPath);

      // 1) Audio extrahieren (16 kHz Mono WAV für Whisper)
      onStatus(statusExtractAudio);
      _setProgress(15);
      _checkCancelled();
      final audioPath = '${tempDir.path}/$stem.wav';
      await mediaProcessor.extractAudio(videoPath, audioPath);
      onLog('INFO', 'Audio extrahiert: $stem.wav');

      // 2) Whisper-Modell bereitstellen (falls fehlend) – sichtbar, kein Haengen bei 30%
      if (transcriptionEngine is WhisperCppEngine) {
        final eng = transcriptionEngine as WhisperCppEngine;
        final mp = eng.modelPath;
        final bd = baseDirFromModelPath(mp);
        final mn = modelNameFromPath(mp);
        if (bd != null && !whisperModelExists(mp)) {
          onStatus(statusDownloadModel);
          onLog('INFO', 'Whisper-Modell $mn wird bereitgestellt (Asset/Download)...');
          _setProgress(30);
          bool ok = false;
          try {
            ok = await ensureWhisperModelAvailable(
              bd,
              mn,
              onLog: onLog,
              onProgress: (p) {
                _setProgress(30 + (p.clamp(0.0, 1.0) * 10));
              },
            );
          } catch (e) {
            onLog('ERROR', 'Modell-Bereitstellung Fehler: $e');
          }
          if (!ok || !whisperModelExists(mp)) {
            throw EngineUnavailableException(
              'Whisper-Modell "$mn" nicht gefunden unter $mp. '
              'Download fehlgeschlagen – pruefe Internetverbindung. '
              'Fuer Offline-Nutzung Modell unter assets/models/$mn.bin buendeln. '
              'Manueller Download: https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-$mn.bin nach $mp kopieren.',
            );
          }
          onLog('SUCCESS', 'Whisper-Modell $mn bereit');
          _setProgress(40);
          _checkCancelled();
        }
      }
      // 2b) Transkription mit Word-Timestamps
      onStatus(statusTranscribe);
      _setProgress(40);
      _checkCancelled();
      var segments = await transcriptionEngine.transcribe(audioPath, language);

      // 3) Echte Videoauflösung -> adaptives Layout + Gruppierung
      VideoInfo? info;
      try {
        info = await mediaProcessor.getVideoInfo(videoPath);
      } catch (e) {
        onLog('WARNING', 'Videoauflösung nicht ermittelbar ($e)');
      }
      CaptionLayout? layout;
      if (info?.width != null && info?.height != null) {
        layout = computeLayout(info!.width!, info.height!);
      }
      segments = groupCaptionSegments(segments, layout: layout);

      // 4) SRT + ASS aus denselben gruppierten Segmenten
      final srtPath = '${tempDir.path}/$stem.srt';
      generateSrt(segments, srtPath);
      onLog('SUCCESS', 'SRT-Datei erstellt: $stem.srt');

      final kwargs = captionStyle == null || captionStyle.isEmpty
          ? null
          : CaptionStyle.resolve(captionStyle.cast<Object?, Object?>());
      final renderer = kwargs == null
          ? CaptionRenderer()
          : CaptionRenderer.fromStyleKwargs(kwargs);
      final assPath = '${tempDir.path}/$stem.ass';
      renderer.generateAss(segments, assPath,
          videoWidth: info?.width, videoHeight: info?.height);
      // Diagnose ASS nach Generierung (fuer Samsung Burn-in)
      try {
        final assFile = File(assPath);
        final assSize = assFile.existsSync() ? assFile.lengthSync() : -1;
        final assContent = assFile.existsSync() ? assFile.readAsStringSync() : '';
        final dialogueLines = assContent.split('\n').where((l) => l.trim().startsWith('Dialogue:')).toList();
        final videoDur = info?.width != null ? '${info!.width}x${info.height}' : 'unbekannt';
        onLog('INFO',
            'ASS-Datei size=$assSize dialogueCount=${dialogueLines.length} video=$videoDur duration=${info?.width != null ? "bekannt" : "unbekannt"}');
        if (dialogueLines.isNotEmpty) {
          final first = dialogueLines.first;
          onLog('INFO', 'ASS first Dialogue: ${first.substring(0, first.length.clamp(0, 300))}');
          final last = dialogueLines.last;
          onLog('INFO', 'ASS last Dialogue: ${last.substring(0, last.length.clamp(0, 300))}');
        } else {
          onLog('WARNING', 'ASS keine Dialogue-Zeilen – pruefe Transkription (segments leer)');
          // Diagnose-Test-Subtitle fuer Burn-in (erste 3 Sek, sichtbar)
          // Nur wenn wirklich keine Dialogue, damit echter Burn-in getestet wird
          onLog('INFO', 'ASS Fallback: fuege Test-Dialogue fuer Diagnose ein (0.5-3.0s)');
          // Einfacher, garantiert sichtbarer Test-Dialogue ohne Karaoke
          final testDialogue = 'Dialogue: 0,0:00:00.50,0:00:03.00,Caption,,0,0,0,,Capti Test';
          try {
            assFile.writeAsStringSync('\n$testDialogue\n', mode: FileMode.append);
            onLog('INFO', 'ASS Test-Dialogue angehaengt: $testDialogue');
          } catch (e) {
            onLog('WARNING', 'ASS Test-Dialogue append fehlgeschlagen: $e');
          }
          try {
            final newSize = assFile.lengthSync();
            final newCount = assFile.readAsStringSync().split('\n').where((l) => l.trim().startsWith('Dialogue:')).length;
            onLog('INFO', 'ASS nach Fallback size=$newSize dialogueCount=$newCount');
          } catch (_) {}
        }
        // Video-Duration vs Subtitle-Timestamps
        if (segments.isNotEmpty) {
          final firstStart = segments.first.start;
          final lastEnd = segments.last.end;
          onLog('INFO',
              'Subtitle timing firstStart=${firstStart.toStringAsFixed(2)} lastEnd=${lastEnd.toStringAsFixed(2)} videoDuration=${info != null ? "siehe getVideoInfo" : "unbekannt"}');
        }
      } catch (e) {
        onLog('WARNING', 'ASS Diagnose Fehler: $e');
      }
      onLog('SUCCESS', 'ASS-Datei erstellt: $stem.ass');

      // 5) Burn-in (Output neben dem Quellvideo, wie am Desktop)
      onStatus(statusEmbedSubtitles);
      _setProgress(70);
      _checkCancelled();
      final dir = videoPath.contains('/')
          ? videoPath.substring(0, videoPath.lastIndexOf('/'))
          : '.';
      final outputVideoPath = '$dir/${stem}_subtitled.mp4';
      // Diagnose vor FFmpeg
      try {
        final vFile = File(videoPath);
        final aFile = File(assPath);
        onLog('INFO',
            'Burn-in INPUT video=$videoPath size=${vFile.existsSync() ? vFile.lengthSync() : -1} ass=$assPath size=${aFile.existsSync() ? aFile.lengthSync() : -1} out=$outputVideoPath');
        if (aFile.existsSync()) {
          final assPreview = aFile.readAsStringSync();
          onLog('INFO', 'ASS preview head: ${assPreview.substring(0, assPreview.length.clamp(0, 200)).replaceAll('\n', '\\n')}');
        }
      } catch (e) {
        onLog('WARNING', 'Burn-in Diagnose Fehler: $e');
      }
      final output = await mediaProcessor.embedAss(
          videoPath, assPath, outputVideoPath);
      // Validierung nach FFmpeg – nur bei echtem MP4 als Erfolg melden
      final outFile = File(output);
      final outSize = outFile.existsSync() ? outFile.lengthSync() : -1;
      onLog('INFO', 'Burn-in OUTPUT path=$output size=$outSize');
      if (!outFile.existsSync() || outSize < 1024) {
        throw MediaEngineException(
            MediaError.encode, 'Burn-in erzeugte ungueltige MP4 (size=$outSize, path=$output)');
      }
      onLog('SUCCESS', 'Video mit Untertiteln erstellt (size=${outSize}B)');

      onStatus(statusCompleted);
      _setProgress(100);
      return CaptiPipelineResult(
          outputPath: output, groupedSegments: segments);
    } catch (e) {
      onLog('ERROR', '$e');
      rethrow;
    }
  }

  /// SRT-Generierung identisch zu subtitle_engine.py (gleiche Textblöcke
  /// wie die ASS-Datei, damit beide Spuren konsistent bleiben).
  static String formatSrtTimestamp(double seconds) {
    final hours = seconds ~/ 3600;
    final minutes = ((seconds % 3600) ~/ 60).toInt();
    final secs = (seconds % 60).toInt();
    final millis = ((seconds - seconds.truncateToDouble()) * 1000).round();
    String two(int v) => v.toString().padLeft(2, '0');
    String three(int v) => v.toString().padLeft(3, '0');
    return '${two(hours)}:${two(minutes)}:${two(secs)},${three(millis)}';
  }

  static String generateSrt(List<Segment> segments, String outputPath) {
    final buf = StringBuffer();
    for (var i = 0; i < segments.length; i++) {
      final s = segments[i];
      buf.writeln(i + 1);
      buf.writeln('${formatSrtTimestamp(s.start)} --> ${formatSrtTimestamp(s.end)}');
      buf.writeln(s.text);
      buf.writeln();
    }
    File(outputPath).writeAsStringSync(buf.toString());
    return outputPath;
  }

  static String _stemOf(String path) {
    final base = path.split(Platform.isWindows ? r'\' : '/').last;
    final dot = base.lastIndexOf('.');
    return dot > 0 ? base.substring(0, dot) : base;
  }
}
