/// Capti Core (Dart-Port): Projektmodell, Workflow-Zustandsmaschine,
/// Validierung. Portiert aus capti_core/project.py – identische Zustände,
/// Übergänge und Fehler-Codes wie die Desktop-Version.
///
/// Workflow: HOME -> NEW_PROJECT -> CAPTION_STYLE -> PROCESSING -> RESULT

library;

import 'dart:io';

import 'package:flutter/foundation.dart';

const Set<String> validVideoExtensions = {
  '.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv', '.m4v',
};

/// Unterstützte Whisper-Modelle (Desktop-Parität).
const List<String> validModels = ['tiny', 'base', 'small', 'medium'];

enum WorkflowState {
  home('home'),
  newProject('new_project'),
  captionStyle('caption_style'),
  processing('processing'),
  result('result');

  final String value;
  const WorkflowState(this.value);
}

/// Erlaubte Übergänge: state -> mögliche Folgezustände.
const Map<WorkflowState, Set<WorkflowState>> workflowTransitions = {
  WorkflowState.home: {WorkflowState.newProject},
  WorkflowState.newProject: {
    WorkflowState.home,
    WorkflowState.captionStyle,
  },
  WorkflowState.captionStyle: {
    WorkflowState.newProject, // Zurück zum Projektschritt
    WorkflowState.processing, // Verarbeitung starten
    WorkflowState.home,
  },
  WorkflowState.processing: {
    WorkflowState.result, // Erfolg
    WorkflowState.captionStyle, // Fehler-/Abbruchpfad
    WorkflowState.home,
  },
  WorkflowState.result: {
    WorkflowState.newProject, // Weiteres Projekt
    WorkflowState.home,
  },
};

class InvalidTransitionError extends Error {
  final WorkflowState from;
  final WorkflowState to;
  InvalidTransitionError(this.from, this.to);

  @override
  String toString() =>
      'InvalidTransitionError: ${from.value} -> ${to.value} nicht erlaubt';
}

/// Datei-Existenz abstrahierbar (Tests injizieren Fakes).
typedef FileExists = bool Function(String path);

bool _defaultExists(String path) => File(path).existsSync();

bool isValidVideoPath(String? path) {
  if (path == null || path.isEmpty) return false;
  final dot = path.lastIndexOf('.');
  if (dot < 0) return false;
  final ext = path.substring(dot).toLowerCase();
  return validVideoExtensions.contains(ext);
}

@immutable
class CaptiProject {
  final String videoPath;
  final String? language; // null = Auto-Erkennung
  final String model;
  final Map<String, Object> captionStyle;

  const CaptiProject({
    this.videoPath = '',
    this.language,
    this.model = 'small',
    this.captionStyle = const {},
  });

  /// Serialisierbare Repräsentation.
  Map<String, Object?> toMap() => {
        'video_path': videoPath,
        'language': language,
        'model': model,
        'caption_style': Map<String, Object>.of(captionStyle),
      };

  /// Robustes Deserialisieren; kaputte Werte -> sichere Defaults.
  factory CaptiProject.fromMap(Object? raw) {
    final map = raw is Map ? raw : const {};
    final lang = map['language'];
    final style = map['caption_style'];
    return CaptiProject(
      videoPath: map['video_path'] is String ? map['video_path'] as String : '',
      language: lang is String ? lang : null,
      model: validModels.contains(map['model']) ? map['model'] as String : 'small',
      captionStyle: style is Map
          ? Map<String, Object>.from(style.cast<Object?, Object?>())
          : {},
    );
  }

  /// Liste stabiler Fehler-Codes; leer = verarbeitungsbereit.
  /// [exists] ist für Tests austauschbar.
  List<String> validationErrors({FileExists exists = _defaultExists}) {
    final errors = <String>[];
    if (videoPath.isEmpty) {
      errors.add('error.no_video');
    } else if (!isValidVideoPath(videoPath)) {
      errors.add('error.invalid_format');
    }
    if (videoPath.isNotEmpty && !exists(videoPath)) {
      errors.add('error.video_missing');
    }
    if (!validModels.contains(model)) {
      errors.add('error.invalid_model');
    }
    return errors;
  }

  CaptiProject copyWith({
    String? videoPath,
    String? language,
    bool clearLanguage = false,
    String? model,
    Map<String, Object>? captionStyle,
  }) =>
      CaptiProject(
        videoPath: videoPath ?? this.videoPath,
        language: clearLanguage ? null : (language ?? this.language),
        model: model ?? this.model,
        captionStyle: captionStyle ?? this.captionStyle,
      );

  @override
  bool operator ==(Object other) =>
      other is CaptiProject &&
      other.videoPath == videoPath &&
      other.language == language &&
      other.model == model;

  @override
  int get hashCode => Object.hash(videoPath, language, model);
}

class ProjectWorkflow {
  CaptiProject project;
  WorkflowState state;

  ProjectWorkflow({
    CaptiProject? project,
    WorkflowState initialState = WorkflowState.home,
  })  : project = project ?? CaptiProject(),
        state = initialState;

  bool canTransition(WorkflowState target) =>
      workflowTransitions[state]!.contains(target);

  WorkflowState transition(WorkflowState target) {
    if (!canTransition(target)) {
      throw InvalidTransitionError(state, target);
    }
    state = target;
    return state;
  }

  /// Verarbeitung nur starten, wenn im Style-Schritt und Projekt valide.
  bool canStartProcessing({FileExists exists = _defaultExists}) =>
      state == WorkflowState.captionStyle &&
      project.validationErrors(exists: exists).isEmpty;
}
