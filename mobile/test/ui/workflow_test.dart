/// Widget-Integrationstests für den mobilen Workflow:
/// Home -> New Project -> Caption Style -> Processing.
/// Alle Abhängigkeiten sind injiziert (Temp-Stores, Fake-Picker,
/// Fake-Engines) – kein Plattform-Kanal nötig.

library;
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:capti_mobile/core/caption_style.dart';
import 'package:capti_mobile/core/i18n.dart';
import 'package:capti_mobile/core/project.dart';
import 'package:capti_mobile/core/stores.dart';
import 'package:capti_mobile/processing/pipeline.dart';
import 'package:capti_mobile/ui/app.dart';
import 'package:capti_mobile/ui/session.dart';

class FakeVideoPicker implements VideoPicker {
  String? nextPath;
  @override
  Future<String?> pickVideo() async => nextPath;
}

class FakeOutputSaver implements OutputSaver {
  @override
  Future<bool> saveOutput({
    required String sourcePath,
    required String suggestedName,
  }) async =>
      true;
}

TranscriptionEngine engineUnavailableFactory() =>
    throw EngineUnavailableException('no native layer in test');

MediaProcessor mediaUnavailableFactory() =>
    throw EngineUnavailableException('no native media layer in test');

AppSession buildSession(Directory tmp, {required FakeVideoPicker picker}) {
  CaptiI18n.instance.setLanguage('de');
  return AppSession(
    settings: SettingsStore(File('${tmp.path}/settings.json')),
    history: HistoryStore(File('${tmp.path}/history.json')),
    videoPicker: picker,
    outputSaver: FakeOutputSaver(),
    engineFactory: engineUnavailableFactory,
    mediaFactory: mediaUnavailableFactory,
    existsOverride: (_) => true,
    initialStyle: CaptionStyle.defaults,
  );
}

Future<void> tapVisible(WidgetTester tester, Key key) async {
  await tester.ensureVisible(find.byKey(key));
  await tester.pump();
  await tester.tap(find.byKey(key), warnIfMissed: true);
  await tester.pump();
}

void main() {
  late Directory tmp;
  setUp(() => tmp = Directory.systemTemp.createTempSync('capti_ui_'));
  tearDown(() => tmp.deleteSync(recursive: true));

  testWidgets('New Project: Validierung blockt, gültiges Video führt '
      'zum Style-Schritt', (tester) async {
    CaptiI18n.instance.setLanguage('de');
    final picker = FakeVideoPicker();
    final session = buildSession(tmp, picker: picker);

    await tester.pumpWidget(CaptiApp(session: session));
    await tester.pump();

    // Home sichtbar
    expect(find.byKey(const ValueKey('home_cta')), findsOneWidget);
    expect(session.workflow.state, WorkflowState.home);

    // -> New Project
    await tester.tap(find.byKey(const ValueKey('home_cta')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('np_pick_video')), findsOneWidget);

    // Ohne Video: Weiter blockt mit Warnung
    await tapVisible(tester, const ValueKey('np_continue'));
    expect(find.byKey(const ValueKey('np_warning')), findsOneWidget);
    expect(session.workflow.state, WorkflowState.newProject);

    // Ungültige Endung -> Warnung bleibt
    picker.nextPath = '/movies/notavideo.txt';
    await tapVisible(tester, const ValueKey('np_pick_video'));
    await tapVisible(tester, const ValueKey('np_continue'));
    expect(find.byKey(const ValueKey('np_warning')), findsOneWidget);
    expect(session.workflow.state, WorkflowState.newProject);

    // Gültiges Video -> weiter
    picker.nextPath = '/movies/clip.mp4';
    await tapVisible(tester, const ValueKey('np_pick_video'));
    await tapVisible(tester, const ValueKey('np_continue'));
    // CaptionStyleScreen hat einen periodischen Animation-Timer ->
    // bewusst pump() statt pumpAndSettle()
    await tester.pump(const Duration(milliseconds: 100));
    expect(session.workflow.state, WorkflowState.captionStyle);
    expect(find.byKey(const ValueKey('cs_preview')), findsOneWidget);

    // Animation-Ticker sauber beenden (kein "pending timer")
    await tester.pumpWidget(const SizedBox());
    await tester.pump(const Duration(milliseconds: 100));
  });

  testWidgets('Processing zeigt ehrlichen "Engine nicht verfügbar"-Zustand',
      (tester) async {
    CaptiI18n.instance.setLanguage('de');
    final session = buildSession(tmp, picker: FakeVideoPicker());
    session.workflow.project =
        session.project.copyWith(videoPath: '/movies/clip.mp4');
    session.workflow.transition(WorkflowState.newProject);
    session.workflow.transition(WorkflowState.captionStyle);

    await tester.pumpWidget(CaptiApp(session: session));
    await tester.pump();

    final started = await session.startProcessing();
    expect(started, false);
    expect(session.processingError, isNotNull);
    expect(session.workflow.state, WorkflowState.captionStyle);
  });

  testWidgets('Settings: Theme-Auto-Save in Datei', (tester) async {
    CaptiI18n.instance.setLanguage('de');
    final session = buildSession(tmp, picker: FakeVideoPicker());

    await tester.pumpWidget(CaptiApp(session: session));
    await tester.pump();

    await tester.tap(find.byKey(const ValueKey('home_settings')));
    await tester.pumpAndSettle();

    // Theme-Segment "yellow" antippen -> sofort persistiert
    await tester.ensureVisible(
        find.byKey(const ValueKey('set_theme')));
    await tester.tap(find.text('yellow'));
    await tester.pump();

    expect(session.theme, 'yellow');
    final reloaded = SettingsStore(File('${tmp.path}/settings.json'));
    expect(reloaded.theme, 'yellow');
  });

  testWidgets('Sprachwechsel ändert sichtbare Labels live',
      (tester) async {
    CaptiI18n.instance.setLanguage('de');
    final session = buildSession(tmp, picker: FakeVideoPicker());

    await tester.pumpWidget(CaptiApp(session: session));
    await tester.pump();
    expect(find.text('+ Neues Projekt'), findsOneWidget);

    CaptiI18n.instance.setLanguage('en');
    await tester.pump();
    expect(find.text('+ New Project'), findsOneWidget);
    expect(find.text('+ Neues Projekt'), findsNothing);
  });
}
