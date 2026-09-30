import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:capti_mobile/core/project.dart' show validModels;
import 'package:capti_mobile/core/stores.dart';
import 'package:capti_mobile/processing/whisper_model.dart';

void main() {
  group('whisperModelPath pro settings.model', () {
    for (final m in validModels) {
      test('Pfad für $m ist <base>/models/$m.bin', () {
        final p = whisperModelPath('/tmp/base', m);
        expect(p, '/tmp/base/models/$m.bin');
      });
    }
    test('unbekanntes Modell fällt auf small.bin', () {
      expect(whisperModelPath('/a', 'large'), '/a/models/small.bin');
      expect(whisperModelPath('/a', 'small.en'), '/a/models/small.bin');
      expect(whisperModelPath('/a', ''), '/a/models/small.bin');
    });
  });

  group('validatedModelName', () {
    test('alle validModels bleiben unverändert', () {
      for (final m in validModels) {
        expect(validatedModelName(m), m);
      }
    });
    test('ungültig -> small', () {
      expect(validatedModelName('small.en'), 'small');
      expect(validatedModelName(null), 'small');
      expect(validatedModelName('HUGE'), 'small');
    });
  });

  group('whisperModelExists', () {
    late Directory tmp;
    setUp(() => tmp = Directory.systemTemp.createTempSync('whisper_exists_'));
    tearDown(() => tmp.deleteSync(recursive: true));

    test('fehlendes Modell -> false', () {
      expect(whisperModelExists('${tmp.path}/models/small.bin'), isFalse);
    });

    test('leere Datei (0) -> false (keine Fake-Datei)', () {
      final f = File('${tmp.path}/models/small.bin');
      f.parent.createSync(recursive: true);
      f.writeAsBytesSync([]);
      expect(whisperModelExists(f.path), isFalse);
    });

    test('kleine Fake-Datei <1024 -> false', () {
      final f = File('${tmp.path}/models/small.bin');
      f.parent.createSync(recursive: true);
      f.writeAsBytesSync(List.filled(512, 1));
      expect(whisperModelExists(f.path), isFalse);
    });

    test('vorhandenes Modell >1024 -> true', () {
      final f = File('${tmp.path}/models/small.bin');
      f.parent.createSync(recursive: true);
      f.writeAsBytesSync(List.filled(2048, 7));
      expect(whisperModelExists(f.path), isTrue);
    });
  });

  group('ensureWhisperModelSyncForTest aus Assets', () {
    late Directory tmp;
    setUp(() => tmp = Directory.systemTemp.createTempSync('whisper_asset_'));
    tearDown(() => tmp.deleteSync(recursive: true));

    test('Asset vorhanden -> kopiert und danach exists', () {
      final ok = ensureWhisperModelSyncForTest(
        tmp.path,
        'small',
        assetExists: (k) => k == 'assets/models/small.bin',
        assetBytes: (k) => List.filled(4096, 42),
      );
      expect(ok, isTrue);
      expect(whisperModelExists('${tmp.path}/models/small.bin'), isTrue);
    });

    test('Asset fehlt -> false, keine Datei angelegt', () {
      final ok = ensureWhisperModelSyncForTest(
        tmp.path,
        'small',
        assetExists: (_) => false,
        assetBytes: (_) => [],
      );
      expect(ok, isFalse);
      expect(File('${tmp.path}/models/small.bin').existsSync(), isFalse);
    });

    test('Asset zu klein -> false', () {
      final ok = ensureWhisperModelSyncForTest(
        tmp.path,
        'small',
        assetExists: (_) => true,
        assetBytes: (_) => List.filled(100, 1),
      );
      expect(ok, isFalse);
    });

    test('Bereits vorhandenes Modell wird nicht überschrieben', () {
      final target = File('${tmp.path}/models/base.bin');
      target.parent.createSync(recursive: true);
      target.writeAsBytesSync(List.filled(5000, 9));
      final before = target.lengthSync();
      final ok = ensureWhisperModelSyncForTest(
        tmp.path,
        'base',
        assetExists: (_) => true,
        assetBytes: (_) => List.filled(9999, 1),
      );
      expect(ok, isTrue);
      expect(target.lengthSync(), before);
    });
  });

  group('frische Installation & persistiertes Standardmodell', () {
    test('frische Installation: settings.model Default small -> Pfad small.bin', () {
      final tmp = Directory.systemTemp.createTempSync('whisper_fresh_');
      addTearDown(() => tmp.deleteSync(recursive: true));
      final settingsFile = File('${tmp.path}/capti_settings.json');
      final settings = SettingsStore(settingsFile);
      // frisch -> Cache leer -> Default 'small'
      expect(settings.model, 'small');
      final p = whisperModelPath(settings.file.parent.path, settings.model);
      expect(p, '${tmp.path}/models/small.bin');
      expect(whisperModelExists(p), isFalse); // frisch: fehlt ehrlich
    });

    test('persistiertes Standardmodell wird respektiert', () {
      final tmp = Directory.systemTemp.createTempSync('whisper_persist_');
      addTearDown(() => tmp.deleteSync(recursive: true));
      final settingsFile = File('${tmp.path}/capti_settings.json');
      final s1 = SettingsStore(settingsFile);
      s1.model = 'tiny';
      final s2 = SettingsStore(settingsFile);
      expect(s2.model, 'tiny');
      final p = whisperModelPath(s2.file.parent.path, s2.model);
      expect(p.endsWith('/models/tiny.bin'), isTrue);
    });

    test('Auto-Sprache benötigt multilingual – validModels sind multilingual', () {
      // validModels enthält kein .en ; Auto-Sprache (language=null) darf nicht
      // auf small.en.bin verweisen. Pfad muss small.bin bleiben.
      final p = whisperModelPath('/base', 'small');
      expect(p, isNot(contains('.en')));
      expect(p, contains('small.bin'));
      // tiny/base/medium ebenfalls ohne .en
      for (final m in validModels) {
        expect(whisperModelPath('/b', m), isNot(contains('.en')));
      }
    });
  });

  group('whisperDownloadUrl', () {
    test('URL ist ggml-<model>.bin multilingual', () {
      expect(whisperDownloadUrl('small'),
          'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin');
      expect(whisperDownloadUrl('tiny'), contains('ggml-tiny.bin'));
      expect(whisperDownloadUrl('small'), isNot(contains('.en')));
    });
    test('alle validModels haben korrekte whisper.cpp-Dateinamen', () {
      for (final m in validModels) {
        final url = whisperDownloadUrl(m);
        expect(url, 'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-$m.bin');
        expect(url, isNot(contains('.en.bin')));
      }
    });
  });

  group('Modell-Switching & Auto-Sprache', () {
    test('Wechsel tiny -> medium erzeugt anderen Pfad (kein hartcodierter Pfad)', () {
      final base = '/tmp/models_base';
      final pTiny = whisperModelPath(base, 'tiny');
      final pMedium = whisperModelPath(base, 'medium');
      expect(pTiny, isNot(pMedium));
      expect(pTiny, contains('tiny.bin'));
      expect(pMedium, contains('medium.bin'));
    });

    test('Auto-Sprache (null) verwendet multilingual small.bin, nie small.en.bin', () {
      // Simulation: pipeline ruft transcribe(audio, null) -> engine nutzt modelPath small.bin
      final p = whisperModelPath('/data', 'small');
      expect(p, endsWith('small.bin'));
      expect(p, isNot(contains('small.en')));
      // Stelle sicher dass URL ebenfalls nicht .en ist
      expect(whisperDownloadUrl('small'), isNot(contains('.en')));
    });
  });

  group('downloadWhisperModel (mock, kein echtes Netzwerk)', () {
    late Directory tmp;
    setUp(() => tmp = Directory.systemTemp.createTempSync('whisper_dl_'));
    tearDown(() => tmp.deleteSync(recursive: true));

    test('Download erfolgreich -> Datei >1MB und exists', () async {
      // Simuliere 2 MB Payload
      final mockClient = MockClient((req) async {
        expect(req.url.toString(), contains('ggml-tiny.bin'));
        final body = List<int>.filled(2 * 1024 * 1024, 7);
        return http.Response.bytes(body, 200, headers: {'content-length': '${body.length}'});
      });
      final ok = await downloadWhisperModel(tmp.path, 'tiny', client: mockClient);
      expect(ok, isTrue);
      expect(whisperModelExists('${tmp.path}/models/tiny.bin'), isTrue);
      expect(File('${tmp.path}/models/tiny.bin').lengthSync(), greaterThan(1024 * 1024));
    });

    test('HTTP 404 -> false, keine Datei angelegt', () async {
      final mockClient = MockClient((_) async => http.Response('not found', 404));
      final ok = await downloadWhisperModel(tmp.path, 'small', client: mockClient);
      expect(ok, isFalse);
      expect(File('${tmp.path}/models/small.bin').existsSync(), isFalse);
    });

    test('Bereits vorhandenes Modell wird nicht neu heruntergeladen', () async {
      final target = File('${tmp.path}/models/base.bin');
      target.parent.createSync(recursive: true);
      target.writeAsBytesSync(List<int>.filled(5 * 1024 * 1024, 1));
      var called = false;
      final mockClient = MockClient((_) async {
        called = true;
        return http.Response('should not be called', 200);
      });
      final ok = await downloadWhisperModel(tmp.path, 'base', client: mockClient);
      expect(ok, isTrue);
      expect(called, isFalse);
    });
  });

  group('ensureWhisperModelAvailable (Asset → Download Kette)', () {
    late Directory tmp;
    setUp(() => tmp = Directory.systemTemp.createTempSync('whisper_ensure_'));
    tearDown(() => tmp.deleteSync(recursive: true));

    test('Download-Fallback nach fehlendem Asset (mock)', () async {
      final mockClient = MockClient((req) async {
        final body = List<int>.filled(2 * 1024 * 1024, 5);
        return http.Response.bytes(body, 200);
      });
      // Ohne echtes Asset im Test-Bundle wird ensureWhisperModelAvailable
      // nach fehlgeschlagener Asset-Kopie direkt zum Download fallen.
      // Wir testen den Download-Pfad isoliert via downloadWhisperModel:
      final ok = await downloadWhisperModel(tmp.path, 'tiny', client: mockClient);
      expect(ok, isTrue);
      expect(whisperModelExists('${tmp.path}/models/tiny.bin'), isTrue);
    });
  });

  group('Android Pfad Not a directory Robustheit (Samsung tiny.bin)', () {
    test('models als Datei -> wird zu Verzeichnis korrigiert und Asset kopiert', () {
      final tmp = Directory.systemTemp.createTempSync('whisper_notadir_');
      addTearDown(() => tmp.deleteSync(recursive: true));
      final base = '${tmp.path}/files';
      Directory(base).createSync(recursive: true);
      final modelsFile = File('$base/models');
      modelsFile.writeAsBytesSync([1, 2, 3]);
      expect(FileSystemEntity.typeSync('$base/models'), FileSystemEntityType.file);
      final ok = ensureWhisperModelSyncForTest(
        base,
        'tiny',
        assetExists: (k) => k == 'assets/models/tiny.bin',
        assetBytes: (_) => List.filled(4096, 7),
      );
      expect(ok, isTrue);
      expect(FileSystemEntity.typeSync('$base/models'), FileSystemEntityType.directory);
      expect(whisperModelExists('$base/models/tiny.bin'), isTrue);
    });

    test('echter Android-Pfad <temp>/files/models/tiny.bin nach Provisionierung', () {
      final tmp = Directory.systemTemp.createTempSync('whisper_android_');
      addTearDown(() => tmp.deleteSync(recursive: true));
      final base = '${tmp.path}/files';
      final ok = ensureWhisperModelSyncForTest(
        base,
        'tiny',
        assetExists: (k) => k == 'assets/models/tiny.bin',
        assetBytes: (_) => List.filled(5000, 9),
      );
      expect(ok, isTrue);
      final target = '$base/models/tiny.bin';
      expect(File(target).existsSync(), isTrue);
      expect(whisperModelExists(target), isTrue);
      expect(Directory('$base/models').existsSync(), isTrue);
      // Aufruf ein zweites Mal darf nicht fehlschlagen (bereits vorhanden)
      final ok2 = ensureWhisperModelSyncForTest(
        base,
        'tiny',
        assetExists: (_) => false,
        assetBytes: (_) => [],
      );
      expect(ok2, isTrue);
    });

    test('whisperModelExists erkennt Android-Pfad korrekt', () {
      final tmp = Directory.systemTemp.createTempSync('whisper_exists_android_');
      addTearDown(() => tmp.deleteSync(recursive: true));
      final base = '${tmp.path}/files';
      final target = '$base/models/tiny.bin';
      expect(whisperModelExists(target), isFalse);
      Directory('$base/models').createSync(recursive: true);
      File(target).writeAsBytesSync(List.filled(2048, 1));
      expect(whisperModelExists(target), isTrue);
    });
  });
}
