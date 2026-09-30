/// Capti Settings-Persistenz (Dart-Port der config.py-Garantien).
///
/// - Fehlende Datei -> sichere Defaults (leeres Map)
/// - Kaputtes JSON / kein Map -> leeres Map statt Crash
/// - Merge-Sicherheit: set() erhält ALLE bestehenden Keys,
///   auch unbekannte
/// - Der Dateipfad wird injiziert: auf Android/iOS liefert main.dart das
///   Verzeichnis via path_provider (App-Sandbox); Tests nutzen Temp-Files.
/// - Keine persönlichen Daten im Repository – die App schreibt ausschließlich
///   in ihr plattformspezifisches Benutzerdatenverzeichnis.

library;
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';

import 'caption_style.dart';
import 'i18n.dart' show defaultLanguage, supportedLanguages;
import 'project.dart' show validModels;
import 'theme.dart' show defaultTheme, isValidTheme;

class SettingsStore {
  final File file;
  Map<String, Object?> _cache;

  SettingsStore(this.file) : _cache = _readFile(file);

  static Map<String, Object?> _readFile(File file) {
    try {
      if (file.existsSync()) {
        final data = jsonDecode(file.readAsStringSync());
        if (data is Map) {
          return Map<String, Object?>.from(data.cast<Object?, Object?>());
        }
      }
    } catch (_) {
      // niemals crashen – Defaults verwenden
    }
    return <String, Object?>{};
  }

  /// Rohes Config-Map (alle Keys inklusive unbekannter).
  Map<String, Object?> raw() => Map<String, Object?>.of(_cache);

  /// Setzt einen einzelnen Wert merge-sicher (alle anderen Keys bleiben).
  bool set(String key, Object? value) {
    try {
      _cache[key] = value;
      file.parent.createSync(recursive: true);
      file.writeAsStringSync(jsonEncode(_cache));
      return true;
    } catch (_) {
      return false;
    }
  }

  // ---------------- Bequeme typisierte Zugriffe ----------------

  String get name => (_cache['name'] as String?) ?? '';

  set name(String v) => set('name', v);

  String get theme {
    final t = _cache['theme'] as String?;
    return isValidTheme(t) ? t! : defaultTheme;
  }

  set theme(String v) => set('theme', v);

  String get language {
    final l = _cache['language'] as String?;
    return supportedLanguages.contains(l) ? l! : defaultLanguage;
  }

  set language(String v) => set('language', v);

  String get model {
    final m = _cache['model'] as String?;
    return validModels.contains(m) ? m! : 'small';
  }

  set model(String v) => set('model', v);

  CaptionStyle get captionStyle => CaptionStyle.load(_cache['caption_style']);

  set captionStyle(CaptionStyle style) =>
      set('caption_style', style.toMap());

  @visibleForTesting
  void reloadForTests() {
    _cache = _readFile(file);
  }
}

class HistoryStore {
  final File file;
  final int maxEntries;

  HistoryStore(this.file, {this.maxEntries = 10});

  List<Map<String, Object?>> _readAll() {
    try {
      if (file.existsSync()) {
        final data = jsonDecode(file.readAsStringSync());
        if (data is List) {
          return [
            for (final e in data)
              if (e is Map &&
                  ['video_path', 'output_path', 'timestamp']
                      .any(e.containsKey))
                Map<String, Object?>.from(e.cast<Object?, Object?>()),
          ];
        }
      }
    } catch (_) {
      // Robust gegen kaputte Dateien – App stürzt nie wegen History.
    }
    return [];
  }

  bool _writeAll(List<Map<String, Object?>> entries) {
    try {
      file.parent.createSync(recursive: true);
      file.writeAsStringSync(jsonEncode(entries));
      return true;
    } catch (_) {
      return false;
    }
  }

  /// Fügt einen Eintrag hinzu (neuester zuerst) und speichert.
  Map<String, Object?> addEntry({
    required String videoPath,
    required String outputPath,
    String model = '',
    String language = '',
  }) {
    final entry = <String, Object?>{
      'video_path': videoPath,
      'output_path': outputPath,
      'timestamp': DateTime.now().toUtc().toIso8601String(),
      'model': model,
      'language': language,
    };
    final entries = [entry, ..._readAll()];
    _writeAll(entries.take(maxEntries).toList());
    return entry;
  }

  /// Letzte [limit] Einträge (neuester zuerst).
  List<Map<String, Object?>> recent({int limit = 10}) =>
      _readAll().take(limit.clamp(0, maxEntries)).toList();

  bool removeAt(int index) {
    final entries = _readAll();
    if (index < 0 || index >= entries.length) return false;
    entries.removeAt(index);
    return _writeAll(entries);
  }

  bool clear() => _writeAll([]);
}
