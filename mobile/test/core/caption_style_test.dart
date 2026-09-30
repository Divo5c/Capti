/// Akzeptanztests für den Dart-Port des Caption-Style-Modells.
/// Spiegelt tests/test_capti_core_caption_style.py (Desktop) – identische
/// Erwartungswerte garantieren Verhaltensparität.

library;
import 'package:flutter_test/flutter_test.dart';
import 'package:capti_mobile/core/caption_style.dart';

void main() {
  group('Defaults (kanonische Form)', () {
    test('1: Defaults entsprechen dem dokumentierten Capti-Look', () {
      expect(defaultCaptionStyle['normal_color'], '#FFFFFF');
      expect(defaultCaptionStyle['highlight_color'], '#FFFF00');
      expect(defaultCaptionStyle['outline_color'], '#101010');
      expect(defaultCaptionStyle['shadow_alpha'], 128);
      expect(defaultCaptionStyle['font_name'], 'Arial Black');
      expect(defaultCaptionStyle['font_size'], 68);
      expect(defaultCaptionStyle['pop_enabled'], true);
      expect(defaultCaptionStyle['pop_scale'], 112);
      expect(defaultCaptionStyle['pop_decay_ms'], 150);
    });

    test('2: ASS-Defaults unverändert (Render-Seite)', () {
      expect(captionStyleAssDefaults['normal_color'], '&H00FFFFFF');
      expect(captionStyleAssDefaults['highlight_color'], '&H0000FFFF');
      expect(captionStyleAssDefaults['outline_color'], '&H00101010');
      expect(captionStyleAssDefaults['shadow_color'], '&H80000000');
    });
  });

  group('resolveCaptionStyle-Kompatibilität', () {
    test('4: null liefert ASS-Defaults', () {
      expect(CaptionStyle.resolve(null), captionStyleAssDefaults);
    });

    test('5: leeres Dict liefert ASS-Defaults', () {
      expect(CaptionStyle.resolve({}), captionStyleAssDefaults);
    });

    test('6: gültige Hex-Farben werden konvertiert (BGR!)', () {
      final result = CaptionStyle.resolve({
        'normal_color': '#FF8800',
        'highlight_color': '#00ff88',
        'outline_color': '#000000',
        'shadow_color': '#202020',
        'shadow_alpha': 200,
      });
      expect(result['normal_color'], '&H000088FF');
      expect(result['highlight_color'], '&H0088FF00');
      expect(result['outline_color'], '&H00000000');
      expect(result['shadow_color'], '&HC8202020');
    });

    test('7: ungültige Werte fallen auf Defaults zurück', () {
      final result = CaptionStyle.resolve({
        'normal_color': 'rot',
        'highlight_color': 12345,
        'font_size': 'riesig',
        'pop_scale': 9999,
        'pop_decay_ms': -5,
      });
      expect(result['normal_color'], captionStyleAssDefaults['normal_color']);
      expect(
          result['highlight_color'], captionStyleAssDefaults['highlight_color']);
      expect(result['font_size'], 68);
      expect(result['pop_scale'], 112);
      expect(result['pop_decay_ms'], 150);
    });

    test('8: font_name wird getrimmt und angewendet', () {
      final result = CaptionStyle.resolve({'font_name': '  Impact  '});
      expect(result['font_name'], 'Impact');
    });

    test('9: shadow_alpha außerhalb 0..255 wird geclampt', () {
      final result = CaptionStyle.resolve({
        'shadow_color': '#000000',
        'shadow_alpha': 999,
      });
      expect(result['shadow_color'], '&HFF000000'); // FF=255
    });

    test('9b: Legacy-Regel – ohne explizite Farbe bleibt Alpha wirkungslos', () {
      expect(CaptionStyle.resolve({'shadow_alpha': 64})['shadow_color'],
          '&H80000000');
      expect(
          CaptionStyle.resolve(
                  {'shadow_color': 'kaputt', 'shadow_alpha': 200})
              ['shadow_color'],
          '&H80000000');
    });

    test('9c: explizites Schwarz (Wert=Default) bekommt Alpha', () {
      expect(
          CaptionStyle.resolve(
                  {'shadow_color': '#000000', 'shadow_alpha': 200})
              ['shadow_color'],
          '&HC8000000');
    });

    test('10: pop_enabled-Koersion wie Python bool()', () {
      expect(CaptionStyle.resolve({'pop_enabled': 'wahr'})['pop_enabled'],
          true); // truthy String -> true
      expect(CaptionStyle.resolve({'pop_enabled': ''})['pop_enabled'],
          false); // leerer String -> false
      expect(CaptionStyle.resolve({'pop_enabled': 0})['pop_enabled'], false);
      expect(CaptionStyle.resolve({'pop_enabled': 1})['pop_enabled'], true);
    });

    test('Zusätzlich: numerische Strings bei font_size werden akzeptiert', () {
      // Python: _int_in_range("80", 68, 20, 200) == 80
      expect(CaptionStyle.resolve({'font_size': '80'})['font_size'], 80);
    });
  });

  group('CaptionStyle-Modell', () {
    test('11: Roundtrip toMap/fromMap', () {
      const style = CaptionStyle(highlightColor: '#FF3B30', popScale: 125);
      final clone = CaptionStyle.fromRaw(style.toMap());
      expect(clone, style);
    });

    test('12: Müll-Eingabe crasht nicht -> Defaults', () {
      expect(CaptionStyle.fromRaw(null).toMap(), CaptionStyle.defaults.toMap());
      expect(
          CaptionStyle.fromRaw('kaputt').toMap(), CaptionStyle.defaults.toMap());
    });

    test('12b: shadow_color_explicit-Semantik', () {
      expect(CaptionStyle.fromRaw({}).shadowColorExplicit, false);
      expect(
          CaptionStyle.fromRaw({'shadow_color': '#101010'}).shadowColorExplicit,
          true);
      expect(const CaptionStyle().shadowColorExplicit, true);
    });

    test('13: unbekannte Keys werden ignoriert', () {
      final style = CaptionStyle.fromRaw({'future_param': 42});
      expect(style.popScale, 112);
      expect(style.toMap().containsKey('future_param'), false);
    });

    test('14: load mit gespeichertem Settings-Wert', () {
      final style =
          CaptionStyle.load({'pop_enabled': false, 'font_size': 90});
      expect(style.popEnabled, false);
      expect(style.fontSize, 90);
    });

    test('15: load mit null/leer -> Defaults', () {
      expect(CaptionStyle.load(null), CaptionStyle.defaults);
      expect(CaptionStyle.load({}), CaptionStyle.defaults);
      expect(CaptionStyle.load(''), CaptionStyle.defaults);
    });

    test('16: mergedWithPreset Strong', () {
      const base = CaptionStyle();
      final merged = base.mergedWithPreset('Strong');
      expect(merged.highlightColor, '#FF3B30');
      expect(merged.popScale, 125);
      expect(merged.popDecayMs, 120);
      expect(merged.shadowAlpha, 180);
      // Basis bleibt unverändert
      expect(base.highlightColor, '#FFFF00');
    });

    test('17: unbekanntes Preset ist No-op', () {
      const base = CaptionStyle(popScale: 130);
      expect(base.mergedWithPreset('Existiert nicht').popScale, 130);
    });

    test('18: Preset "Capti Default" hat leere Overrides', () {
      expect(captionPresets['Capti Default'], isEmpty);
    });

    test('19: toRendererKwargs entspricht resolve', () {
      final raw = <Object?, Object?>{
        'normal_color': '#112233',
        'shadow_alpha': 64,
      };
      final viaModel = CaptionStyle.fromRaw(raw).toRendererKwargs();
      expect(viaModel, CaptionStyle.resolve(raw));
    });

    test('21: Position/max_words sind bewusst KEINE Style-Felder', () {
      expect(defaultCaptionStyle.containsKey('position'), false);
      expect(defaultCaptionStyle.containsKey('max_words_per_line'), false);
    });
  });
}
