/// Native Media-Engine (FFmpeg + libass) via dart:ffi.
///
/// Bindet die aus native/media_bridge.c gebaute Bibliothek
/// `libmedia_bridge.so` an die MediaProcessor-Abstraktion der Pipeline:
///
///   extractAudio -> capti_media_extract_audio (16 kHz Mono WAV für Whisper)
///   embedAss     -> capti_media_burn_ass      (H.264/AAC-MP4 + ASS-Burn-in)
///   getVideoInfo -> capti_media_probe
///
/// Die Ausführung läuft komplett im Worker-Isolate (UI bleibt flüssig);
/// über die Isolate-Grenze gehen ausschließlich sendbare Werte (Strings,
/// Ints). Fortschritt kommt aus der nativen Dekodierung (pts/duration) und
/// wird über einen NativeCallable.listener an das Haupt-Isolate geliefert –
/// kein simulierter Fortschritt.
///
/// Fehler werden als MediaEngineException mit stabilen Codes geworfen; die
/// UI übersetzt sie lokalisiert.

library;
import 'dart:ffi' as ffi;
import 'dart:io';
import 'dart:isolate';

import 'package:ffi/ffi.dart' as pd;

import 'pipeline.dart';

/// Stabile Rückgabecodes aus media_bridge.c (Pflicht-Kopplung).
enum MediaError {
  ok(0),
  openInput(1),
  streamInfo(2),
  noStreams(3),
  extractAudio(4),
  ass(5),
  filterGraph(6),
  openOutput(7),
  encode(8),
  cancelled(9),
  internal(10);

  final int code;
  const MediaError(this.code);

  static MediaError fromCode(int code) =>
      MediaError.values.firstWhere((e) => e.code == code,
          orElse: () => MediaError.internal);
}

class MediaEngineException implements Exception {
  final MediaError code;

  /// Technischer Kontexttext aus der Bridge.
  final String detail;
  MediaEngineException(this.code, this.detail);
  @override
  String toString() => 'MediaEngineException(${code.name}): $detail';
}

// ---------------------------------------------------------------------
// FFI-Bindings
// ---------------------------------------------------------------------

// Native-Seite (FFI-C-Signaturen)
typedef _ProbeC = ffi.Int32 Function(
    ffi.Pointer<ffi.Char>, ffi.Pointer<ffi.Int32>, ffi.Pointer<ffi.Int32>,
    ffi.Pointer<ffi.Int64>);
typedef _ExtractC = ffi.Int32 Function(
    ffi.Pointer<ffi.Char>, ffi.Pointer<ffi.Char>, ffi.Pointer<ffi.Uint8>,
    ffi.Int32);
typedef _BurnC = ffi.Int32 Function(
    ffi.Pointer<ffi.Char>,
    ffi.Pointer<ffi.Char>,
    ffi.Pointer<ffi.Char>,
    ffi.Pointer<ffi.Char>,
    ffi.Pointer<ffi.NativeFunction<_ProgressC>>,
    ffi.Pointer<ffi.Uint8>,
    ffi.Int32);
typedef _ProgressC = ffi.Void Function(ffi.Double);
typedef _CancelC = ffi.Void Function();

// Dart-Seite (Aufrufsignaturen)
typedef _ProbeDart = int Function(ffi.Pointer<ffi.Char>, ffi.Pointer<ffi.Int32>,
    ffi.Pointer<ffi.Int32>, ffi.Pointer<ffi.Int64>);
typedef _ExtractDart = int Function(ffi.Pointer<ffi.Char>,
    ffi.Pointer<ffi.Char>, ffi.Pointer<ffi.Uint8>, int);
typedef _BurnDart = int Function(
    ffi.Pointer<ffi.Char>,
    ffi.Pointer<ffi.Char>,
    ffi.Pointer<ffi.Char>,
    ffi.Pointer<ffi.Char>,
    ffi.Pointer<ffi.NativeFunction<_ProgressC>>,
    ffi.Pointer<ffi.Uint8>,
    int);
typedef _CancelDart = void Function();

class _Bindings {
  final ffi.DynamicLibrary lib;
  late final probe =
      lib.lookupFunction<_ProbeC, _ProbeDart>('capti_media_probe');
  late final extractAudio =
      lib.lookupFunction<_ExtractC, _ExtractDart>('capti_media_extract_audio');
  late final burnAss =
      lib.lookupFunction<_BurnC, _BurnDart>('capti_media_burn_ass');
  late final requestCancel =
      lib.lookupFunction<_CancelC, _CancelDart>('capti_media_request_cancel');
  _Bindings(this.lib);
}

ffi.Pointer<ffi.Char> _toChar(String s) =>
    s.isEmpty ? ffi.nullptr : s.toNativeUtf8().cast<ffi.Char>();

void _freeChar(ffi.Pointer<ffi.Char> p) {
  if (p != ffi.nullptr) pd.calloc.free(p.cast<pd.Utf8>());
}

/// Liest den Fehlertext aus dem vom Aufrufer allokierten Puffer.
/// OWNERSHIP: Der Aufrufer behält die Freigabe (genau EIN free im finally).
/// Ein Free hier wäre ein Double-Free -> SIGABRT auf Android (bionic),
/// exakt der im Feld beobachtete Crash nach EXIT rc=0.
String _readErr(ffi.Pointer<ffi.Uint8> buf) {
  return buf.cast<pd.Utf8>().toDartString();
}

// ---------------------------------------------------------------------
// Processor
// ---------------------------------------------------------------------

/// Defensive Vorprüfung auf Dart-Seite (testbar ohne Native-Lib):
/// Pfad nicht leer, Datei existiert, lesbar, Größe > 0.
/// Wirft MediaEngineException(openInput) – derselbe Vertrag wie nativ.
void validateInputFile(String path) {
  if (path.isEmpty) {
    throw MediaEngineException(
        MediaError.openInput, 'Eingabepfad ist leer');
  }
  final f = File(path);
  if (!f.existsSync()) {
    throw MediaEngineException(
        MediaError.openInput, 'Eingabedatei fehlt: $path');
  }
  try {
    if (f.lengthSync() <= 0) {
      throw MediaEngineException(
          MediaError.openInput, 'Eingabedatei ist leer: $path');
    }
  } on FileSystemException catch (e) {
    throw MediaEngineException(
        MediaError.openInput, 'Eingabedatei unlesbar: ${e.message}');
  }
}

class NativeMediaProcessor implements MediaProcessor {
  final String? libPath;

  /// Verzeichnis mit TTF/OTF-Dateien für libass (fontconfig-frei).
  /// Auf Android z. B. '/system/fonts'.
  final String? fontsDir;

  /// Optionaler Fortschritt (0..1) für den Burn-in-Schritt.
  final void Function(double fraction)? onProgress;

  NativeMediaProcessor({this.libPath, this.fontsDir, this.onProgress});

  static String defaultLibName() {
    if (Platform.isWindows) return 'media_bridge.dll';
    if (Platform.isMacOS) return 'libmedia_bridge.dylib';
    return 'libmedia_bridge.so';
  }

  @override
  Future<String> extractAudio(String videoPath, String outputPath) async {
    validateInputFile(videoPath);
    final lib = libPath ?? defaultLibName();
    return Isolate.run(() {
      final b = _Bindings(ffi.DynamicLibrary.open(lib));
      final v = _toChar(videoPath);
      final o = outputPath.toNativeUtf8().cast<ffi.Char>();
      final errBuf = pd.calloc<ffi.Uint8>(1024);
      try {
        final rc = b.extractAudio(v, o, errBuf, 1024);
        final detail = _readErr(errBuf);
        if (rc != MediaError.ok.code) throw _toEx(rc, detail);
        return outputPath;
      } finally {
        _freeChar(v);
        pd.calloc.free(o);
        pd.calloc.free(errBuf);
      }
    });
  }

  @override
  Future<String> embedAss(
      String videoPath, String assPath, String outputPath) async {
    validateInputFile(videoPath);
    // ASS-Datei muss existieren und plausibel sein
    final assFile = File(assPath);
    if (!assFile.existsSync() || assFile.lengthSync() < 10) {
      throw MediaEngineException(
          MediaError.ass, 'ASS-Datei fehlt oder zu klein: $assPath');
    }
    final lib = libPath ?? defaultLibName();
    final fonts = fontsDir ?? '';
    final progressCb = onProgress == null
        ? null
        : ffi.NativeCallable<_ProgressC>.listener((double p) => onProgress!(p));
    try {
      final outputPathRes = await Isolate.run(() {
        final b = _Bindings(ffi.DynamicLibrary.open(lib));
        final v = _toChar(videoPath);
        final a = _toChar(assPath);
        final o = outputPath.toNativeUtf8().cast<ffi.Char>();
        final f = _toChar(fonts);
        final errBuf = pd.calloc<ffi.Uint8>(2048);
        final progressPtr = progressCb?.nativeFunction ?? ffi.nullptr;
        try {
          final rc = b.burnAss(v, a, o, f, progressPtr, errBuf, 2048);
          final detail = _readErr(errBuf);
          if (rc != MediaError.ok.code) throw _toEx(rc, detail);
          return outputPath;
        } finally {
          _freeChar(v); _freeChar(a); _freeChar(f);
          pd.calloc.free(o);
          pd.calloc.free(errBuf);
        }
      });
      // Post-FFmpeg Validierung – 859-Byte-Fehler abfangen
      final out = File(outputPathRes);
      if (!out.existsSync()) {
        throw MediaEngineException(MediaError.encode,
            'Burn-in Output fehlt: $outputPathRes (FFmpeg rc=0 aber Datei nicht geschrieben)');
      }
      final sz = out.lengthSync();
      if (sz < 1024) {
        // Versuche FFmpeg stderr Detail zu erhalten, aber hier nur Groesse
        try { out.deleteSync(); } catch (_) {}
        throw MediaEngineException(MediaError.encode,
            'Burn-in erzeugte ungueltige MP4 (size=$sz Bytes, path=$outputPathRes) – FFmpeg schrieb nur Header, kein Video-Paket. Pruefe Input/ASS/Codec.');
      }
      return outputPathRes;
    } finally {
      progressCb?.close();
    }
  }

  @override
  Future<VideoInfo?> getVideoInfo(String videoPath) async {
    validateInputFile(videoPath);
    final lib = libPath ?? defaultLibName();
    return Isolate.run(() {
      final b = _Bindings(ffi.DynamicLibrary.open(lib));
      final v = _toChar(videoPath);
      final w = pd.calloc<ffi.Int32>();
      final h = pd.calloc<ffi.Int32>();
      final dur = pd.calloc<ffi.Int64>();
      try {
        final rc = b.probe(v, w, h, dur);
        if (rc != MediaError.ok.code || w.value <= 0 || h.value <= 0) {
          return null;
        }
        return VideoInfo(width: w.value, height: h.value);
      } finally {
        _freeChar(v);
        pd.calloc.free(w); pd.calloc.free(h); pd.calloc.free(dur);
      }
    });
  }

  /// Fordert Abbruch des LAUFENDEN nativen Laufs an (globales Flag in der
  /// Bridge; wirkt beim nächsten Fortschritts-/Loop-Tick).
  void requestCancel() {
    final b = _Bindings(
        ffi.DynamicLibrary.open(libPath ?? defaultLibName()));
    b.requestCancel();
  }

  static MediaEngineException _toEx(int rc, String detail) {
    final code = MediaError.fromCode(rc);
    if (code == MediaError.cancelled) {
      return MediaEngineException(code, 'abgebrochen');
    }
    return MediaEngineException(code, detail);
  }
}
