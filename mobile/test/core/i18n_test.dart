/// i18n-Tests: Fallback-Kette, Parameter, Live-Sprachwechsel.
/// Stabile Keys bleiben maschinenlesbar; niemals rohe Keys sichtbar
/// für definierte Texte.

library;
import 'package:flutter_test/flutter_test.dart';
import 'package:capti_mobile/core/i18n.dart';

void main() {
  setUp(() => CaptiI18n.instance.setLanguage('de'));
  tearDown(() => CaptiI18n.instance.setLanguage('de'));

  test('deutsche Standardtexte vorhanden', () {
    expect(tr('home.cta_new'), '+ Neues Projekt');
    expect(tr('np.continue'), 'Weiter →');
  });

  test('englische Texte nach Sprachwechsel', () {
    CaptiI18n.instance.setLanguage('en');
    expect(tr('home.cta_new'), '+ New Project');
    expect(tr('np.continue'), 'Next →');
  });

  test('unbekannte Sprache -> Fallback Deutsch', () {
    CaptiI18n.instance.setLanguage('fr');
    expect(CaptiI18n.instance.language, 'de');
    expect(tr('np.continue'), 'Weiter →');
  });

  test('unbekannter Key liefert Key selbst (kein Crash)', () {
    expect(tr('does.not.exist'), 'does.not.exist');
  });

  test('Parameter werden eingesetzt', () {
    expect(
      tr('home.greeting', {'name': 'Diraj'}),
      'Hallo, Diraj!',
    );
    CaptiI18n.instance.setLanguage('en');
    expect(
      tr('home.greeting', {'name': 'Diraj'}),
      'Hello, Diraj!',
    );
  });

  test('setLanguage benachrichtigt Listener (Live-Wechsel)', () {
    var notified = 0;
    CaptiI18n.instance.addListener(() => notified++);
    CaptiI18n.instance.setLanguage('en');
    expect(notified, 1);
  });
}
