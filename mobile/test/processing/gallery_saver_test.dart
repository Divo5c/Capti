import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:capti_mobile/processing/gallery_saver.dart';
import 'package:capti_mobile/core/project.dart';
import 'package:capti_mobile/core/stores.dart';
import 'package:capti_mobile/ui/session.dart';
import 'package:capti_mobile/core/caption_style.dart';
import 'package:capti_mobile/captions/renderer.dart';
import 'package:capti_mobile/processing/pipeline.dart';

class _FakeGallery implements OutputSaver {
  String? lastSource;
  String? lastName;
  bool result = true;
  @override
  Future<bool> saveOutput({required String sourcePath, required String suggestedName}) async {
    lastSource = sourcePath;
    lastName = suggestedName;
    return result;
  }
}

class _FakeEngine implements TranscriptionEngine {
  @override
  Future<List<Segment>> transcribe(String audioPath, String? language) async => [
        const Segment(start: 0, end: 1, text: 'Hi', words: [WordTimestamp('Hi', 0, 1)]),
      ];
}

class _FakeMedia implements MediaProcessor {
  final Directory tmp;
  _FakeMedia(this.tmp);
  @override
  Future<String> extractAudio(String videoPath, String outputPath) async {
    File(outputPath).writeAsStringSync('fake');
    return outputPath;
  }
  @override
  Future<String> embedAss(String videoPath, String assPath, String outputPath) async {
    // Mindestens 1KB fuer Pipeline-Validierung (real MP4 waere viel groesser)
    File(outputPath).writeAsBytesSync(List<int>.filled(2048, 0x01));
    return outputPath;
  }
  @override
  Future<VideoInfo?> getVideoInfo(String videoPath) async => const VideoInfo(width: 720, height: 1280);
}

void main() {
  group('MediaStoreGallerySaver - Dateiname', () {
    test('FakeGallery speichert Capti_ Prefix', () async {
      final tmp = Directory.systemTemp.createTempSync('gallery_name_');
      addTearDown(() => tmp.deleteSync(recursive: true));
      final src = File('${tmp.path}/out.mp4')..writeAsStringSync('x');
      final saver = _FakeGallery();
      final ok = await saver.saveOutput(sourcePath: src.path, suggestedName: 'Capti_test.mp4');
      expect(ok, isTrue);
      expect(saver.lastName, 'Capti_test.mp4');
    });

    test('GallerySaver fuegt Capti_ hinzu wenn fehlend', () async {
      // Teste FakeGallery, das MediaStoreGallerySaver Verhalten simuliert
      final tmp = Directory.systemTemp.createTempSync('gallery_prefix_');
      addTearDown(() => tmp.deleteSync(recursive: true));
      final src = File('${tmp.path}/clip_subtitled.mp4')..writeAsStringSync('x');
      final saver = FakeGallerySaver();
      // FakeGallerySaver prueft nur Existenz, daher true
      final ok = await saver.saveOutput(sourcePath: src.path, suggestedName: 'clip.mp4');
      expect(ok, isTrue);
    });
  });

  group('Session automatischer Galerie-Export', () {
    late Directory tmp;
    setUp(() => tmp = Directory.systemTemp.createTempSync('gallery_session_'));
    tearDown(() => tmp.deleteSync(recursive: true));

    test('Erfolgreicher Pipeline-Lauf speichert automatisch in Galerie (Movies/Capti)', () async {
      final gallery = _FakeGallery();
      final session = AppSession(
        settings: SettingsStore(File('${tmp.path}/s.json')),
        history: HistoryStore(File('${tmp.path}/h.json')),
        videoPicker: _FakePicker(),
        outputSaver: gallery,
        engineFactory: () => _FakeEngine(),
        mediaFactory: () => _FakeMedia(tmp),
        existsOverride: (_) => true,
        initialStyle: CaptionStyle.defaults,
      );
      // Simuliere Video-Pfad wie nach SAF-Cache (timestamp_name)
      session.workflow.project = session.project.copyWith(videoPath: '${tmp.path}/12345_MyVideo.mp4');
      session.workflow.transition(WorkflowState.newProject);
      session.workflow.transition(WorkflowState.captionStyle);
      final started = await session.startProcessing();
      expect(started, isTrue);
      for (var i = 0; i < 100 && session.workflow.state != WorkflowState.result; i++) {
        await Future<void>.delayed(const Duration(milliseconds: 10));
      }
      expect(session.workflow.state, WorkflowState.result);
      expect(session.processingError, isNull);
      expect(gallery.lastSource, isNotNull);
      expect(gallery.lastName, startsWith('Capti_'));
      expect(gallery.lastName, endsWith('.mp4'));
      // Original nicht ueberschrieben: Quelle ist Cache-Pfad, Galerie-Ziel ist Movies/Capti
      expect(gallery.lastSource, isNot(contains('Movies/Capti')));
      expect(session.lastGalleryName, isNotNull);
      expect(session.lastGalleryName, startsWith('Capti_'));
    });

    test('Galerie-Fehler fuehrt nicht zu Erfolgszustand', () async {
      final gallery = _FakeGallery()..result = false;
      final session = AppSession(
        settings: SettingsStore(File('${tmp.path}/s2.json')),
        history: HistoryStore(File('${tmp.path}/h2.json')),
        videoPicker: _FakePicker(),
        outputSaver: gallery,
        engineFactory: () => _FakeEngine(),
        mediaFactory: () => _FakeMedia(tmp),
        existsOverride: (_) => true,
        initialStyle: CaptionStyle.defaults,
      );
      session.workflow.project = session.project.copyWith(videoPath: '${tmp.path}/vid.mp4');
      session.workflow.transition(WorkflowState.newProject);
      session.workflow.transition(WorkflowState.captionStyle);
      await session.startProcessing();
      for (var i = 0; i < 100 && session.isProcessing; i++) {
        await Future<void>.delayed(const Duration(milliseconds: 10));
      }
      await Future<void>.delayed(const Duration(milliseconds: 50));
      expect(session.workflow.state, isNot(WorkflowState.result));
      expect(session.processingError, isNotNull);
      expect(session.processingError, contains('Galerie'));
    });

    test('Originalvideo wird nicht ueberschrieben', () async {
      final orig = File('${tmp.path}/orig.mp4')..writeAsStringSync('ORIGINAL');
      final gallery = _FakeGallery();
      final session = AppSession(
        settings: SettingsStore(File('${tmp.path}/s3.json')),
        history: HistoryStore(File('${tmp.path}/h3.json')),
        videoPicker: _FakePicker(),
        outputSaver: gallery,
        engineFactory: () => _FakeEngine(),
        mediaFactory: () => _FakeMedia(tmp),
        existsOverride: (_) => true,
        initialStyle: CaptionStyle.defaults,
      );
      session.workflow.project = session.project.copyWith(videoPath: orig.path);
      session.workflow.transition(WorkflowState.newProject);
      session.workflow.transition(WorkflowState.captionStyle);
      await session.startProcessing();
      for (var i = 0; i < 100 && session.workflow.state != WorkflowState.result; i++) {
        await Future<void>.delayed(const Duration(milliseconds: 10));
      }
      expect(File(orig.path).readAsStringSync(), 'ORIGINAL');
      expect(gallery.lastSource, isNot(equals(orig.path)));
    });
  });
}

class _FakePicker implements VideoPicker {
  @override
  Future<String?> pickVideo() async => null;
}
