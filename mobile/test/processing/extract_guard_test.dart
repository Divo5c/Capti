/// Regressionstests für die defensive Vorprüfung der Media-Bridge
/// (extract_audio-Fehlerpfade, die ohne Gerätetestbar sind):
///
///   fehlende Datei / leere Datei / ungültiger Pfad →
///   MediaEngineException(openInput) – NIEMALS ein Prozess-Crash.
///
/// Die nativen FFmpeg-Pfade selbst werden auf dem Gerät über die
/// CaptiMedia-logcat-Instrumentierung verifiziert.

library;
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:capti_mobile/processing/native_media.dart';
import 'package:capti_mobile/processing/pipeline.dart';

void main() {
  late Directory tmp;
  setUp(() => tmp = Directory.systemTemp.createTempSync('capti_media_'));
  tearDown(() {
    if (tmp.existsSync()) tmp.deleteSync(recursive: true);
  });

  test('Fehlende Datei -> MediaEngineException(openInput), kein Crash',
      () {
    expect(
      () => validateInputFile('${tmp.path}/gibtsnicht.mp4'),
      throwsA(isA<MediaEngineException>()
          .having((e) => e.code, 'code', MediaError.openInput)),
    );
  });

  test('Leere Datei (0 Byte, z.B. fehlgeschlagene SAF-Kopie) -> openInput',
      () {
    final f = File('${tmp.path}/leer.mp4')..writeAsBytesSync(const []);
    expect(
      () => validateInputFile(f.path),
      throwsA(isA<MediaEngineException>()
          .having((e) => e.code, 'code', MediaError.openInput)
          .having((e) => e.detail, 'detail', contains('leer'))),
    );
  });

  test('Ungültiger Pfad (content://-Rest o.ä.) wird abgefangen', () {
    expect(
      () => validateInputFile(''),
      throwsA(isA<MediaEngineException>()),
    );
  });

  test('Gültige, nicht-leere Datei passiert die Vorprüfung', () {
    final f = File('${tmp.path}/ok.mp4')
      ..writeAsBytesSync(List.filled(64, 1));
    expect(() => validateInputFile(f.path), returnsNormally);
  });

  test('MediaError-Mapping deckt alle Brücken-Codes ab', () {
    for (var i = 0; i <= 10; i++) {
      expect(MediaError.fromCode(i).code, i);
    }
    expect(MediaError.fromCode(-1), MediaError.internal);
    expect(MediaError.fromCode(9999), MediaError.internal);
  });

  test('EngineUnavailableException bleibt unverändert verfügbar '
      '(Pipeline-Vertrag)', () {
    expect(
        () => throw EngineUnavailableException('x'), throwsException);
  });
}
