/// Tests für Settings-/History-Persistenz (Port der config.py/history.py-
/// Garantien): Merge-Sicherheit, Robustheit gegen kaputte Dateien,
/// History-Limit.

library;
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:capti_mobile/core/caption_style.dart';
import 'package:capti_mobile/core/stores.dart';

void main() {
  late Directory tmp;

  setUp(() => tmp = Directory.systemTemp.createTempSync('capti_stores_'));
  tearDown(() => tmp.deleteSync(recursive: true));

  group('SettingsStore', () {
    test('fehlende Datei -> leere Defaults', () {
      final store = SettingsStore(File('${tmp.path}/settings.json'));
      expect(store.raw(), isEmpty);
      expect(store.name, '');
      expect(store.theme, 'dark');
      expect(store.language, 'de');
      expect(store.model, 'small');
    });

    test('kaputtes JSON -> Defaults statt Crash', () {
      final file = File('${tmp.path}/broken.json')
        ..writeAsStringSync('{kaputt');
      final store = SettingsStore(file);
      expect(store.raw(), isEmpty);
    });

    test('Merge-Sicherheit: set() erhält unbekannte Keys', () {
      final file = File('${tmp.path}/merge.json')
        ..writeAsStringSync(
            jsonEncode({'custom_key': 42, 'theme': 'light'}));
      SettingsStore(file).set('theme', 'yellow');

      final reloaded = SettingsStore(file);
      expect(reloaded.theme, 'yellow');
      expect(reloaded.raw()['custom_key'], 42); // unbekannter Key bleibt!
    });

    test('CaptionStyle-Roundtrip über die Settings-Datei', () {
      final file = File('${tmp.path}/style.json');
      SettingsStore(file).captionStyle = const CaptionStyle(popScale: 130);

      final reloaded = SettingsStore(file).captionStyle;
      expect(reloaded.popScale, 130);
      expect(reloaded.highlightColor, '#FFFF00');
    });

    test('ungültige Theme-/Sprach-Werte fallen auf Defaults', () {
      final file = File('${tmp.path}/invalid.json')
        ..writeAsStringSync(jsonEncode({'theme': 'neon', 'language': 'fr'}));
      final store = SettingsStore(file);
      // Ungültige Werte -> Defaults (Getter normalisieren)
      expect(store.raw()['theme'], 'neon');
      expect(store.theme, 'dark');
      expect(store.language, 'de');
      expect(store.language, 'de');
    });
  });

  group('HistoryStore', () {
    test('add/recent Reihenfolge neuester zuerst', () {
      final store =
          HistoryStore(File('${tmp.path}/history.json'));
      store.addEntry(videoPath: '/a/first.mp4', outputPath: '/a/out1.mp4');
      store.addEntry(videoPath: '/b/second.mp4', outputPath: '/b/out2.mp4');

      final recent = store.recent();
      expect(recent.length, 2);
      expect(recent.first['video_path'], '/b/second.mp4');
      expect(recent.last['video_path'], '/a/first.mp4');
    });

    test('maxEntries wird eingehalten (10)', () {
      final store = HistoryStore(File('${tmp.path}/h2.json'));
      for (var i = 0; i < 15; i++) {
        store.addEntry(videoPath: '/v/$i.mp4', outputPath: '/o/$i.mp4');
      }
      expect(store.recent().length, 10);
      expect(store.recent(limit: 3).length, 3);
    });

    test('removeAt/clear funktionieren robust', () {
      final store =
          HistoryStore(File('${tmp.path}/h3.json'));
      store.addEntry(videoPath: '/x/a.mp4', outputPath: '/x/o.mp4');
      expect(store.removeAt(5), false); // außerhalb
      expect(store.removeAt(0), true);
      expect(store.recent(), isEmpty);
      expect(store.clear(), true);
    });

    test('kaputte History-Datei -> leere Liste statt Crash', () {
      final file = File('${tmp.path}/bad.json')..writeAsStringSync('[{]');
      final store = HistoryStore(file);
      expect(store.recent(), isEmpty);
    });
  });
}
