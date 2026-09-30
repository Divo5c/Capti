/// Akzeptanztests für den Dart-Port der Workflow-Zustandsmaschine.
/// Spiegelt tests/test_capti_core_project.py (Desktop).

library;
import 'package:flutter_test/flutter_test.dart';
import 'package:capti_mobile/core/project.dart';

void main() {
  group('Validierung', () {
    test('1: leeres Projekt meldet nur error.no_video', () {
      final errors = CaptiProject().validationErrors(exists: (_) => false);
      expect(errors, ['error.no_video']);
    });

    test('2: valides Projekt hat keine Fehler', () {
      const project = CaptiProject(
          videoPath: '/x/video.mp4', language: 'de', model: 'small');
      expect(project.validationErrors(exists: (_) => true), isEmpty);
    });

    test('3: ungültige Endung wird abgelehnt', () {
      const project = CaptiProject(videoPath: '/x/not_video.txt');
      expect(project.validationErrors(exists: (_) => true),
          contains('error.invalid_format'));
    });

    test('4: fehlende Datei wird separat gemeldet', () {
      const project = CaptiProject(videoPath: '/x/fehlt.mp4');
      final errors = project.validationErrors(exists: (_) => false);
      expect(errors, contains('error.video_missing'));
      expect(errors, isNot(contains('error.invalid_format')));
    });

    test('5: unbekanntes Modell wird abgelehnt', () {
      const project = CaptiProject(
          videoPath: '/x/v.mp4', model: 'large-v3');
      expect(project.validationErrors(exists: (_) => true),
          contains('error.invalid_model'));
    });

    test('6: Endungs-Prüfung ist case-insensitive', () {
      expect(isValidVideoPath('C:\\x\\Video.MOV'), true);
      expect(isValidVideoPath('C:\\x\\video.gif'), false);
      expect(isValidVideoPath(''), false);
      expect(isValidVideoPath(null), false);
    });
  });

  group('Serialisierung', () {
    test('7: Roundtrip toMap/fromMap', () {
      const project = CaptiProject(
        videoPath: '/x/v.mp4',
        language: 'en',
        model: 'base',
        captionStyle: {'pop_scale': 120},
      );
      final clone = CaptiProject.fromMap(project.toMap());
      expect(clone.videoPath, project.videoPath);
      expect(clone.language, project.language);
      expect(clone.model, project.model);
      expect(clone.captionStyle, project.captionStyle);
    });

    test('8: Müll-Eingabe liefert sichere Defaults', () {
      final project = CaptiProject.fromMap(null);
      expect(project.videoPath, '');
      expect(project.language, isNull);
      expect(project.model, 'small');
      expect(project.captionStyle, isEmpty);

      final broken = CaptiProject.fromMap({'model': 42, 'language': 7});
      expect(broken.model, 'small');
      expect(broken.language, isNull);
    });

    test('9: Style muss ein Dict sein', () {
      final project = CaptiProject.fromMap({
        'caption_style': ['kaputt'],
      });
      expect(project.captionStyle, isEmpty);
    });
  });

  group('Workflow', () {
    ProjectWorkflow workflowWithVideo() => ProjectWorkflow(
          project: const CaptiProject(videoPath: '/x/v.mp4'),
          initialState: WorkflowState.newProject,
        );

    test('10: Happy Path durch den gesamten Workflow', () {
      final wf = workflowWithVideo();
      expect(wf.canTransition(WorkflowState.captionStyle), true);
      wf.transition(WorkflowState.captionStyle);
      wf.transition(WorkflowState.processing);
      wf.transition(WorkflowState.result);
      wf.transition(WorkflowState.home);
      expect(wf.state, WorkflowState.home);
    });

    test('11: Zurück-Navigation new_project -> home', () {
      final wf = workflowWithVideo();
      wf.transition(WorkflowState.home);
      expect(wf.state, WorkflowState.home);
    });

    test('12: Fehlerpfad processing -> caption_style', () {
      final wf = workflowWithVideo();
      wf.transition(WorkflowState.captionStyle);
      wf.transition(WorkflowState.processing);
      wf.transition(WorkflowState.captionStyle);
      expect(wf.state, WorkflowState.captionStyle);
    });

    test('13: unerlaubter Übergang wirft InvalidTransitionError', () {
      final wf = ProjectWorkflow(); // HOME
      expect(() => wf.transition(WorkflowState.processing),
          throwsA(isA<InvalidTransitionError>()));
    });

    test('14: result darf nicht direkt zu processing', () {
      final wf = workflowWithVideo();
      wf.transition(WorkflowState.captionStyle);
      wf.transition(WorkflowState.processing);
      wf.transition(WorkflowState.result);
      expect(wf.canTransition(WorkflowState.processing), false);
    });

    test('15: Verarbeitung nur mit validem Projekt im Style-Schritt', () {
      final wf = ProjectWorkflow(initialState: WorkflowState.captionStyle);
      expect(wf.canStartProcessing(exists: (_) => false), false);

      wf.project =
          wf.project.copyWith(videoPath: '/irgendwas/v.mp4');
      expect(wf.canStartProcessing(exists: (_) => true), true);
    });

    test('16: can_start_processing erfordert Style-Zustand', () {
      final wf = ProjectWorkflow(
          project: const CaptiProject(videoPath: '/x/v.mp4'));
      expect(wf.canStartProcessing(exists: (_) => true), false); // Zustand HOME
    });

    test('Zusätzlich: copyWith/clearLanguage Verhalten', () {
      var p = const CaptiProject(language: 'de');
      p = p.copyWith(language: 'en');
      expect(p.language, 'en');
      p = p.copyWith(clearLanguage: true);
      expect(p.language, isNull);
    });
  });
}
