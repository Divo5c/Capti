/// Regressionstests für die Caption-Preview (Teil B des Samsung-Bugfixes):
///
/// 1. cs.preview_sentence-Fehlerteufel: Der Preview-Satz muss übersetzt
///    gerendert werden – NIEMALS der rohe Translation-Key. Der Text wird
///    über CustomPainter gezeichnet und ist für find.text unsichtbar;
///    daher wird der State direkt geprüft.
/// 2. Kein interner i18n-Key als sichtbarer Text auf dem Screen (de+en).
/// 3. Animation läuft (activeIndex wechselt) und ein schmaler Viewport
///    (360 dp) erzeugt keinen RenderFlex-Overflow mehr.

library;
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:capti_mobile/core/caption_style.dart';
import 'package:capti_mobile/core/i18n.dart';
import 'package:capti_mobile/core/stores.dart';
import 'package:capti_mobile/processing/pipeline.dart';
import 'package:capti_mobile/ui/screens/caption_style_screen.dart';
import 'package:capti_mobile/ui/session.dart';

class _FakePicker implements VideoPicker {
  @override
  Future<String?> pickVideo() async => null;
}

class _FakeSaver implements OutputSaver {
  @override
  Future<bool> saveOutput({
    required String sourcePath,
    required String suggestedName,
  }) async =>
      true;
}

AppSession _session(Directory tmp) => AppSession(
      settings: SettingsStore(File('${tmp.path}/settings.json')),
      history: HistoryStore(File('${tmp.path}/history.json')),
      videoPicker: _FakePicker(),
      outputSaver: _FakeSaver(),
      engineFactory: () =>
          throw EngineUnavailableException('not used in preview tests'),
      mediaFactory: () =>
          throw EngineUnavailableException('not used in preview tests'),
      existsOverride: (_) => true,
      initialStyle: CaptionStyle.defaults,
    );

/// Interne Key-Form wie "np.foo", "cs.preview_sentence" etc.
final _internalKeyPattern = RegExp(
    r'\b(np|set|cs|proc|res|nav|home|history|common|error)\.[a-z_0-9]+');

Future<void> _pumpStyleScreen(WidgetTester tester,
    {String lang = 'de'}) async {
  final tmp = Directory.systemTemp.createTempSync('capti_preview_');
  addTearDown(() {
    if (tmp.existsSync()) tmp.deleteSync(recursive: true);
  });
  CaptiI18n.instance.setLanguage(lang);
  final session = _session(tmp);
  await tester.pumpWidget(MaterialApp(home: CaptionStyleScreen(session: session)));
  // postFrameCallback (_rebuildTimeline) + erste Ticks ausführen
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 50));
}

dynamic _stateOf(WidgetTester tester) =>
    tester.state(find.byType(CaptionStyleScreen));

void main() {
  testWidgets(
      'Preview rendert den ÜBERSETZTEN Satz – kein roher i18n-Key '
      '(Regression: cs.preview_sentence fehlte)', (tester) async {
    await _pumpStyleScreen(tester, lang: 'de');
    final words = List<String>.from(
        (_stateOf(tester).previewWordsForTests as List<dynamic>));

    expect(words, isNotEmpty, reason: 'Timeline darf nicht leer sein');
    for (final w in words) {
      expect(_internalKeyPattern.hasMatch(w), isFalse,
          reason: 'Rohes i18n-Key-Fragment in Preview-Wörtern: "$w"');
    }
    // Exakte Desktop-Parität des Satzes:
    final expected = tr('cs.preview_sentence').split(' ');
    expect(words, expected);

    // EN-Parität ebenfalls sauber übersetzbar:
    CaptiI18n.instance.setLanguage('en');
    expect(tr('cs.preview_sentence'), isNot(equals('cs.preview_sentence')));
    expect(tr('cs.preview_sentence').split(' '),
        'This is how your captions will look'.split(' '));
  });

  testWidgets('Keine internen Translation-Keys als sichtbarer Text '
      'auf dem Caption-Style-Screen (de+en)', (tester) async {
    for (final lang in const ['de', 'en']) {
      await _pumpStyleScreen(tester, lang: lang);
      final texts = <String>{};
      for (final t in find.byType(Text).evaluate()) {
        final data = (t.widget as Text).data;
        if (data != null) texts.add(data);
      }
      for (final s in texts) {
        expect(_internalKeyPattern.hasMatch(s), isFalse,
            reason: 'Sichtbarer interner Key "$s" (lang=$lang)');
      }
      // Ticker sauber beenden, bevor der nächste Durchlauf pumpt
      await tester.pumpWidget(const SizedBox());
      await tester.pump(const Duration(milliseconds: 60));
    }
  });

  testWidgets('Animation läuft und schmaler 360-dp-Viewport '
      'überläuft nicht', (tester) async {
    // Schmales Gerät simulieren (Samsung A-Serie ~360 dp)
    tester.view.physicalSize = const Size(360 * 3, 800 * 3);
    tester.view.devicePixelRatio = 3.0;
    addTearDown(tester.view.reset);

    await _pumpStyleScreen(tester, lang: 'de');

    expect(find.byKey(const ValueKey('cs_preview')), findsOneWidget);

    int? seenActive;
    // Erstes Wort startet bei t=300 ms für 450 ms -> innerhalb von
    // ~1200 ms muss activeIndex mindestens einmal != null gewesen sein.
    for (var i = 0; i < 36; i++) {
      await tester.pump(const Duration(milliseconds: 33));
      final idx = _stateOf(tester).activeIndexForTests as int?;
      if (idx != null) {
        seenActive = idx;
        break;
      }
    }
    expect(seenActive, isNotNull,
        reason: 'Preview-Animation hat nie ein aktives Wort gehabt');
  });

  testWidgets('Diagnosezeile zeigt Größe · Wörter · Anim · Font',
      (tester) async {
    await _pumpStyleScreen(tester, lang: 'de');
    final diag = find.byKey(const ValueKey('cs_preview_diag'));
    expect(diag, findsOneWidget);
    final t = tester.widget<Text>(diag).data ?? '';
    expect(t, contains('×'));        // tatsächliche Canvas-Größe
    expect(t, contains('Wörter'));   // Timeline-Wortanzahl
    expect(t, contains('Anim'));     // Animationsstatus
    expect(t, contains('Font'));     // verwendete Font-Family
    // Ticker sauber beenden
    await tester.pumpWidget(const SizedBox());
    await tester.pump(const Duration(milliseconds: 60));
  });
}
