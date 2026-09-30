/// Session-Logik-Tests: Workflow-Gates, Fehlerpfad, Export, History-Eintrag
/// bei erfolgreichem (Fake-)Pipeline-Lauf.

library;
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:capti_mobile/core/caption_style.dart';
import 'package:capti_mobile/core/i18n.dart';
import 'package:capti_mobile/core/project.dart';
import 'package:capti_mobile/core/stores.dart';
import 'package:capti_mobile/captions/renderer.dart';
import 'package:capti_mobile/processing/pipeline.dart';
import 'package:capti_mobile/ui/session.dart';

class FakeVideoPicker implements VideoPicker {
  String? nextPath;
  @override
  Future<String?> pickVideo() async => nextPath;
}

class FakeOutputSaver implements OutputSaver {
  bool succeed = true;
  @override
  Future<bool> saveOutput(
      {required String sourcePath, required String suggestedName}) async =>
      succeed;
}

/// Deterministische Fake-Engine: liefert zwei Segmente mit Word-Timestamps.
class FakeEngine implements TranscriptionEngine {
  @override
  Future<List<Segment>> transcribe(String audioPath, String? language) async {
    return [
      const Segment(
        start: 0,
        end: 1.6,
        text: 'Hallo Welt',
        words: [
          WordTimestamp('Hallo', 0.0, 0.7),
          WordTimestamp('Welt', 0.8, 1.5),
        ],
      ),
    ];
  }
}

/// Fake-MediaProcessor: schreibt echte kleine Dateien, damit die Pipeline
/// real durchläuft (ohne echtes ffmpeg).
class FakeMediaProcessor implements MediaProcessor {
  final Directory tmp;
  FakeMediaProcessor(this.tmp);

  @override
  Future<String> extractAudio(String videoPath, String outputPath) async {
    File(outputPath).writeAsStringSync('RIFFfake');
    return outputPath;
  }

  @override
  Future<String> embedAss(
      String videoPath, String assPath, String outputPath) async {
    // ASS-Inhalt übernehmen -> beweist, dass die Pipeline die Datei erzeugt hat
    // Mindestens 1KB fuer neue Validierung (real MP4 waere MB)
    final marker =
        'VIDEO+${File(assPath).readAsStringSync().contains(r'{\k') ? "KARAOKE" : "PLAIN"}';
    final filler = List<int>.filled(2048 - marker.length, 0x41);
    File(outputPath).writeAsBytesSync([...marker.codeUnits, ...filler]);
    return outputPath;
  }

  @override
  Future<VideoInfo?> getVideoInfo(String videoPath) async =>
      const VideoInfo(width: 1080, height: 1920);
}

AppSession buildSession(Directory tmp,
    {required TranscriptionEngine Function() engineFactory}) {
  CaptiI18n.instance.setLanguage('de');
  final session = AppSession(
    settings: SettingsStore(File('${tmp.path}/settings.json')),
    history: HistoryStore(File('${tmp.path}/history.json')),
    videoPicker: FakeVideoPicker(),
    outputSaver: FakeOutputSaver(),
    engineFactory: engineFactory,
    mediaFactory: () => FakeMediaProcessor(tmp),
    existsOverride: (_) => true,
    initialStyle: CaptionStyle.defaults,
  );
  // Video im real existierenden Temp-Verzeichnis -> Pipeline-Output
  // (liegt neben dem Quellvideo, Desktop-Parität) ist schreibbar.
  session.workflow.project =
      session.project.copyWith(videoPath: '${tmp.path}/clip.mp4');
  return session;
}

void main() {
  late Directory tmp;
  setUp(() => tmp = Directory.systemTemp.createTempSync('capti_session_'));
  tearDown(() => tmp.deleteSync(recursive: true));

  test('startProcessing verweigert ohne Video', () async {
    final session = buildSession(tmp, engineFactory: () => throw EngineUnavailableException('x'));
    expect(session.startProcessing(), completion(false));
  });

  test('Erfolgsfall: Pipeline läuft, ASS enthält Karaoke, Result-Zustand '
      'und History-Eintrag entstehen', () async {
    final session = buildSession(tmp, engineFactory: () => FakeEngine());
    session.workflow.transition(WorkflowState.newProject);
    session.workflow.transition(WorkflowState.captionStyle);
    expect(
        session.workflow.canStartProcessing(exists: (_) => true), true);

    final started = await session.startProcessing();
    expect(started, true);

    // Auf Abschluss warten (Fake ist sofort fertig)
    for (var i = 0; i < 100 && !session.workflow.state.isResult; i++) {
      await Future<void>.delayed(const Duration(milliseconds: 10));
    }
    expect(session.processingError, isNull,
        reason: 'Pipeline darf keinen Fehler werfen');
    expect(session.workflow.state, WorkflowState.result);
    expect(session.lastOutputPath, isNotNull);

    final out = File(session.lastOutputPath!).readAsStringSync();
    expect(out.contains('KARAOKE'), true,
        reason: 'Burn-in-Ersatz muss Karaoke-ASS sehen');

    final history = session.history.recent();
    expect(history, hasLength(1));
    expect(history.first['output_path'], session.lastOutputPath);
  });

  test('Fehlerpfad führt zurück zu caption_style und setzt processingError',
      () async {
    final session = buildSession(
        tmp,
        engineFactory: () => throw EngineUnavailableException('fehlt'));
    session.workflow.transition(WorkflowState.newProject);
    session.workflow.transition(WorkflowState.captionStyle);

    await session.startProcessing();
    await Future<void>.delayed(const Duration(milliseconds: 20));

    expect(session.workflow.state, WorkflowState.captionStyle);
    expect(session.processingError, isNotNull);
  });

  test('resetToHome setzt Projekt zurück, behält Modell/Sprache', () async {
    final session = buildSession(tmp, engineFactory: () => FakeEngine());
    session.setDefaultModel('base');
    session.workflow.transition(WorkflowState.newProject);
    session.resetToHome();

    expect(session.workflow.state, WorkflowState.home);
    expect(session.project.videoPath, '');
    expect(session.project.model, 'base');
  });
}

extension on WorkflowState {
  bool get isResult => this == WorkflowState.result;
}
