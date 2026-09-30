/// Whisper-Modellbereitstellung auf Android.
///
/// Wo erwartet WhisperCppEngine das Modell?
///   `${supportDir.path}/models/<settings.model>.bin`
///   - supportDir = getApplicationSupportDirectory() (App-Sandbox)
///   - settings.model in ['tiny','base','small','medium'], Default 'small'
///   - multilingual (kein .en-Suffix) – erforderlich für Auto-Sprache
///
/// Woher soll `model`.bin kommen?
///   Priorität:
///     1) Bereits im Sandbox-Verzeichnis vorhanden (persistiert)
///     2) Aus Flutter-Assets `assets/models/model.bin` kopieren (falls gebündelt)
///     3) Erst-Download von HuggingFace `ggml-model.bin` nach Sandbox
///     4) Ehrlicher Fehler – UI zeigt `error.model_missing` lokalisiert
///
/// Dateinamen sind whisper.cpp-korrekt:
///   Asset:   `assets/models/tiny.bin`  (Kurzname, wird als tiny.bin gesichert)
///   Remote:  `https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin`
///   Sandbox: `.../files/models/tiny.bin`  (identisch zu Asset-Kurzname)
///   Nie `*.en.bin` – Auto-Sprache benötigt multilingual.
///

library;
import 'dart:io';

import 'package:flutter/services.dart' show AssetBundle, rootBundle;
import 'package:http/http.dart' as http;

import '../core/project.dart' show validModels;

const String _assetPrefix = 'assets/models';

/// HuggingFace ggml-URL für whisper.cpp (multilingual, nicht .en).
String whisperDownloadUrl(String model) =>
    'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-$model.bin';

/// Kanonischer Pfad im Sandbox-Verzeichnis.
String whisperModelPath(String baseDir, String modelName) {
  final m = validModels.contains(modelName) ? modelName : 'small';
  return '$baseDir/models/$m.bin';
}

/// Stabile Modell-Bezeichnung validiert auf `validModels`.
String validatedModelName(String? raw) =>
    validModels.contains(raw) ? raw! : 'small';

String modelNameFromPath(String p) {
  final base = p.split('/').last.split('\\').last;
  final dot = base.lastIndexOf('.');
  final name = dot > 0 ? base.substring(0, dot) : base;
  return validModels.contains(name) ? name : 'small';
}

String? baseDirFromModelPath(String p) {
  final idx = p.lastIndexOf('/models/');
  if (idx < 0) return null;
  return p.substring(0, idx);
}

bool whisperModelExists(String path) {
  try {
    final f = File(path);
    return f.existsSync() && f.lengthSync() > 1024;
  } catch (_) {
    return false;
  }
}

/// Stellt sicher, dass `$baseDir/models` ein VERZEICHNIS ist.
/// - Erzeugt es mit `recursive: true`, falls fehlend.
/// - Falls dort eine DATEI namens `models` existiert, wird sie geloescht
///   und danach das Verzeichnis erzeugt – statt spaeter `Not a directory`.
/// - Prueft abschliessend, dass der Pfad wirklich ein Directory ist.
/// Liefert true bei Erfolg, false bei Fehler (mit onLog).
Future<bool> _ensureModelsDir(String baseDir,
    {void Function(String level, String msg)? onLog}) async {
  final dirPath = '$baseDir/models';
  final type = FileSystemEntity.typeSync(dirPath, followLinks: false);
  if (type == FileSystemEntityType.file) {
    onLog?.call('WARNING', 'Pfad $dirPath ist Datei statt Verzeichnis – loesche Datei');
    try {
      File(dirPath).deleteSync();
    } catch (e) {
      onLog?.call('ERROR', 'Konnte Datei $dirPath nicht loeschen: $e');
      return false;
    }
  }
  try {
    final dir = Directory(dirPath);
    if (!dir.existsSync()) {
      dir.createSync(recursive: true);
    }
    final after = FileSystemEntity.typeSync(dirPath, followLinks: false);
    if (after != FileSystemEntityType.directory) {
      onLog?.call('ERROR', 'Pfad $dirPath ist kein Verzeichnis nach create (type=$after)');
      return false;
    }
    return true;
  } catch (e) {
    onLog?.call('ERROR', 'Konnte Verzeichnis $dirPath nicht erstellen: $e');
    return false;
  }
}

bool _ensureModelsDirSync(String baseDir,
    {void Function(String level, String msg)? onLog}) {
  final dirPath = '$baseDir/models';
  final type = FileSystemEntity.typeSync(dirPath, followLinks: false);
  if (type == FileSystemEntityType.file) {
    onLog?.call('WARNING', 'Pfad $dirPath ist Datei statt Verzeichnis – loesche Datei');
    try {
      File(dirPath).deleteSync();
    } catch (e) {
      onLog?.call('ERROR', 'Konnte Datei $dirPath nicht loeschen: $e');
      return false;
    }
  }
  try {
    final dir = Directory(dirPath);
    if (!dir.existsSync()) dir.createSync(recursive: true);
    return FileSystemEntity.typeSync(dirPath, followLinks: false) ==
        FileSystemEntityType.directory;
  } catch (e) {
    onLog?.call('ERROR', 'Konnte Verzeichnis $dirPath nicht erstellen: $e');
    return false;
  }
}

/// Versucht, ein fehlendes Modell aus Flutter-Assets zu kopieren.
/// BEVORZUGT Asset vor Download – tiny.bin ist gebuendelt.
/// Liefert true, wenn danach eine brauchbare Datei am Ziel liegt.
Future<bool> ensureWhisperModelFromAssets(
  String baseDir,
  String modelName, {
  AssetBundle? bundle,
}) async {
  final target = whisperModelPath(baseDir, modelName);
  if (whisperModelExists(target)) return true;
  // Verzeichnis robust sicherstellen (Not a directory-Fix)
  if (!await _ensureModelsDir(baseDir)) return false;
  final b = bundle ?? rootBundle;
  final assetKey = '$_assetPrefix/$modelName.bin';
  try {
    final data = await b.load(assetKey);
    final bytes = data.buffer.asUint8List();
    if (bytes.length < 1024) return false;
    // Atomar ueber .part schreiben, validieren, dann verschieben
    final tmp = File('$target.part');
    if (tmp.existsSync()) {
      try { tmp.deleteSync(); } catch (_) {}
    }
    await tmp.writeAsBytes(bytes, flush: true);
    if (!tmp.existsSync() || tmp.lengthSync() < 1024) {
      try { tmp.deleteSync(); } catch (_) {}
      return false;
    }
    final dest = File(target);
    if (dest.existsSync()) {
      try { dest.deleteSync(); } catch (_) {}
    }
    await tmp.rename(target);
    return whisperModelExists(target);
  } catch (_) {
    return whisperModelExists(target);
  }
}

/// Lädt `ggml-model.bin` von HuggingFace nach `baseDir/models/model.bin`.
/// Schreibt atomar über `.part`-Datei, meldet Fortschritt 0..1, wirft bei
/// HTTP-Fehler/zu kleiner Datei. `client` ist für Tests injizierbar.
Future<bool> downloadWhisperModel(
  String baseDir,
  String modelName, {
  http.Client? client,
  void Function(double progress)? onProgress,
  void Function(String level, String msg)? onLog,
}) async {
  final target = whisperModelPath(baseDir, modelName);
  if (whisperModelExists(target)) return true;
  final url = whisperDownloadUrl(modelName);
  final c = client ?? http.Client();
  final shouldClose = client == null;
  try {
    onLog?.call('INFO', 'Lade Whisper-Modell $modelName von HuggingFace…');
    final req = http.Request('GET', Uri.parse(url));
    final resp = await c.send(req);
    if (resp.statusCode != 200) {
      onLog?.call('ERROR', 'Download $modelName fehlgeschlagen: HTTP ${resp.statusCode}');
      return false;
    }
    final total = resp.contentLength ?? -1;
    if (!await _ensureModelsDir(baseDir, onLog: onLog)) return false;
    final tmp = File('$target.part');
    if (tmp.existsSync()) {
      try { tmp.deleteSync(); } catch (_) {}
    }
    final sink = tmp.openWrite();
    var received = 0;
    await for (final chunk in resp.stream) {
      sink.add(chunk);
      received += chunk.length;
      if (total > 0 && onProgress != null) {
        onProgress((received / total).clamp(0.0, 1.0));
      }
    }
    await sink.close();
    if (!tmp.existsSync() || tmp.lengthSync() < 1024 * 1024) {
      // Zu klein -> kein echtes Modell (Fehler/HTML)
      try { tmp.deleteSync(); } catch (_) {}
      onLog?.call('ERROR', 'Download $modelName unvollständig/zu klein');
      return false;
    }
    // Atomar ersetzen
    final dest = File(target);
    if (dest.existsSync()) dest.deleteSync();
    await tmp.rename(target);
    onLog?.call('SUCCESS', 'Whisper-Modell $modelName bereit (${(dest.lengthSync()/1e6).toStringAsFixed(1)} MB)');
    return whisperModelExists(target);
  } catch (e) {
    onLog?.call('ERROR', 'Download $modelName Fehler: $e');
    return false;
  } finally {
    if (shouldClose) c.close();
  }
}

/// Vereinheitlichte Bereitstellung: Sandbox → Asset → Download.
/// Wird vor `capti_whisper_create` aufgerufen. Liefert true, wenn danach
/// eine brauchbare Datei existiert.
Future<bool> ensureWhisperModelAvailable(
  String baseDir,
  String modelName, {
  AssetBundle? bundle,
  http.Client? client,
  void Function(String level, String msg)? onLog,
  void Function(double progress)? onProgress,
}) async {
  final target = whisperModelPath(baseDir, modelName);
  if (whisperModelExists(target)) return true;
  if (await ensureWhisperModelFromAssets(baseDir, modelName, bundle: bundle)) {
    onLog?.call('INFO', 'Whisper-Modell $modelName aus Assets bereitgestellt');
    return true;
  }
  // Netzwerk-Fallback – benötigt INTERNET permission
  return downloadWhisperModel(baseDir, modelName,
      client: client, onProgress: onProgress, onLog: onLog);
}

/// Synchrone Variante für Tests (AssetBundle injizierbar über Fake).
bool ensureWhisperModelSyncForTest(
  String baseDir,
  String modelName, {
  bool Function(String assetKey)? assetExists,
  List<int> Function(String assetKey)? assetBytes,
}) {
  final target = whisperModelPath(baseDir, modelName);
  if (whisperModelExists(target)) return true;
  if (assetExists == null || assetBytes == null) return false;
  final key = '$_assetPrefix/$modelName.bin';
  if (!assetExists(key)) return false;
  final bytes = assetBytes(key);
  if (bytes.length < 1024) return false;
  try {
    if (!_ensureModelsDirSync(baseDir)) return false;
    final tmp = File('$target.part');
    if (tmp.existsSync()) {
      try { tmp.deleteSync(); } catch (_) {}
    }
    tmp.writeAsBytesSync(bytes, flush: true);
    if (!tmp.existsSync() || tmp.lengthSync() < 1024) {
      try { tmp.deleteSync(); } catch (_) {}
      return false;
    }
    final dest = File(target);
    if (dest.existsSync()) {
      try { dest.deleteSync(); } catch (_) {}
    }
    tmp.renameSync(target);
    return whisperModelExists(target);
  } catch (_) {
    return false;
  }
}
