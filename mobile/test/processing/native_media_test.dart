/// Unit-Tests für die Dart-Seite der Media-Bridge:
/// stabiler Fehlercode -> MediaError -> verständliche Exception.
/// (Die native Seite selbst wird auf dem Gerät verifiziert.)

library;
import 'package:flutter_test/flutter_test.dart';

import 'package:capti_mobile/processing/native_media.dart';

void main() {
  test('Alle Brücken-Codes 0..10 sind im Enum vorhanden', () {
    for (var i = 0; i <= 10; i++) {
      expect(MediaError.fromCode(i).code, i);
    }
    // Unbekannter Code -> internal statt Crash
    expect(MediaError.fromCode(99), MediaError.internal);
  });

  test('MediaEngineException trägt Code und Detail', () {
    final ex = MediaEngineException(MediaError.ass, 'ass load failed');
    expect(ex.code, MediaError.ass);
    expect(ex.detail, contains('ass'));
    expect(ex.toString(), contains('ass'));
  });

  test('defaultLibName liefert plattformgerechten Dateinamen', () {
    // Auf dem Testhost (Linux) erwartet die App die Android-/POSIX-Form.
    expect(NativeMediaProcessor.defaultLibName(), endsWith('.so'));
  });
}
