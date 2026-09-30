/// Zentrale App-Session: hält Stores, Workflow-Zustand und aktuelles
/// Projekt; notifyListeners() treibt die Screens an.
///
/// Alle Abhängigkeiten sind injizierbar -> Widget-Tests laufen ohne
/// Plattform-Kanäle mit Temp-Dateien und Fake-Engines.

library;
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import '../core/caption_style.dart';
import '../core/i18n.dart';
import '../core/project.dart';
import '../core/stores.dart';
import '../core/theme.dart';
import '../processing/gallery_saver.dart';
import '../processing/pipeline.dart';

/// Abstraktion der Video-Auswahl (Android/iOS Dateiberechtigungen).
abstract class VideoPicker {
  /// Liefert einen Dateipfad oder null bei Abbruch.
  Future<String?> pickVideo();
}

/// Abstraktion des Export-Speicherns ("Speichern unter").
/// Die Implementierung schreibt die Datei selbst (mobile Systemdialoge
/// liefern nur ein Ziel-URI, kein beschreibbaren Pfad).
abstract class OutputSaver {
  /// Schreibt die Quelldatei an den vom Benutzer gewählten Ort.
  /// Liefert true bei Erfolg, false bei Abbruch/Fehler.
  Future<bool> saveOutput({
    required String sourcePath,
    required String suggestedName,
  });
}

class AppSession extends ChangeNotifier {
  final SettingsStore settings;
  final HistoryStore history;
  final VideoPicker videoPicker;
  final OutputSaver outputSaver;

  /// Factory für die Transkriptions-Engine (wird erst bei Bedarf gerufen;
  /// wirft EngineUnavailableException, wenn die Native-Schicht fehlt).
  final TranscriptionEngine Function() engineFactory;

  /// Factory für die Medienverarbeitung (FFmpeg/libass-Boundary).
  final MediaProcessor Function() mediaFactory;

  CaptiI18n get i18n => CaptiI18n.instance;

  /// Workflow-Zustandsmaschine (Port aus capti_core.project).
  final ProjectWorkflow workflow = ProjectWorkflow();

  /// Aktives Caption-Style im Style-Screen (Arbeitskopie).
  CaptionStyle styleDraft;

  /// Ergebnis des letzten Laufs (Cache-Pfad, temporär).
  String? lastOutputPath;

  /// Galerie-Speicher: Name/URI des in Movies/Capti gespeicherten Videos.
  String? lastGalleryName;
  String? lastGalleryUri;
  bool gallerySaveFailed = false;

  PipelineRunHandle? _runHandle;

  /// Optionaler Override für Datei-Existenzprüfungen (Widget-Tests
  /// nutzen Fake-Pfade; Produktion bleibt beim echten Dateisystem).
  final bool Function(String path)? existsOverride;

  bool _fileExists(String path) =>
      existsOverride?.call(path) ?? File(path).existsSync();

  AppSession({
    required this.settings,
    required this.history,
    required this.videoPicker,
    required this.outputSaver,
    required this.engineFactory,
    required this.mediaFactory,
    this.existsOverride,
    CaptionStyle? initialStyle,
  }) : styleDraft = initialStyle ?? settings.captionStyle;

  // ---------------- Theme / Sprache (Auto-Save) ----------------

  String get theme => settings.theme;

  void setTheme(String value) {
    if (!isValidTheme(value)) return;
    settings.theme = value;
    notifyListeners();
  }

  String get language => settings.language;

  void setLanguage(String value) {
    i18n.setLanguage(value);
    settings.language = i18n.language;
    notifyListeners();
  }

  String get userName => settings.name;

  void setUserName(String value) {
    settings.name = value.trim();
    notifyListeners();
  }

  void setDefaultModel(String model) {
    if (!validModels.contains(model)) return;
    settings.model = model;
    notifyListeners();
  }

  /// Öffentliche Re-Notify-Methode für Screens, die Projekt-Felder direkt
  /// über die Session ändern.
  void notifyChanged() => notifyListeners();

  void saveCaptionStyle(CaptionStyle style) {
    settings.captionStyle = style;
    styleDraft = style;
    notifyListeners();
  }

  // ---------------- Projekt-Workflow ----------------

  CaptiProject get project => workflow.project;

  bool pickVideoPending = false;

  Future<void> pickVideo() async {
    if (pickVideoPending) return;
    pickVideoPending = true;
    try {
      final path = await videoPicker.pickVideo();
      if (path != null) {
        workflow.project =
            workflow.project.copyWith(videoPath: path);
        notifyListeners();
      }
    } finally {
      pickVideoPending = false;
    }
  }

  List<String> projectValidationErrors() =>
      workflow.project.validationErrors(exists: _fileExists);

  /// Home -> New Project (zustandsmaschinengetriebener Routeneintritt).
  bool enterNewProject() {
    if (workflow.state == WorkflowState.newProject) return true;
    if (!workflow.canTransition(WorkflowState.newProject)) return false;
    workflow.transition(WorkflowState.newProject);
    // Standardmodell aus Settings übernehmen für neue Projekte
    workflow.project = workflow.project.copyWith(model: settings.model);
    notifyListeners();
    return true;
  }

  /// New Project -> Caption Style (nur wenn valide).
  bool continueToCaptionStyle() {
    if (workflow.state != WorkflowState.newProject) return false;
    if (project.validationErrors(exists: _fileExists).isNotEmpty) {
      return false;
    }
    workflow.transition(WorkflowState.captionStyle);
    notifyListeners();
    return true;
  }

  void resetToHome() {
    while (workflow.state != WorkflowState.home) {
      try {
        workflow.transition(WorkflowState.home);
      } catch (_) {
        break;
      }
    }
    workflow.project = CaptiProject(
        language: workflow.project.language,
        model: settings.model); // Standardmodell für neue Projekte
    lastOutputPath = null;
    lastGalleryName = null;
    lastGalleryUri = null;
    gallerySaveFailed = false;
    notifyListeners();
  }

  // ---------------- Verarbeitung ----------------

  PipelineRunHandle? get runHandle => _runHandle;

  bool get isProcessing => _runHandle?.running ?? false;

  String? processingError;

  /// Startet die Verarbeitung (Caption Style -> Processing).
  /// Liefert false, wenn der Start nicht erlaubt ist oder die Engine
  /// nicht verfügbar ist (processingError enthält dann den Grund).
  Future<bool> startProcessing() async {
    if (!workflow.canStartProcessing(exists: _fileExists)) return false;
    if (_runHandle?.running ?? false) return false;

    workflow.transition(WorkflowState.processing);

    TranscriptionEngine engine;
    MediaProcessor media;
    try {
      engine = engineFactory();
      media = mediaFactory();
    } catch (e) {
      // Engine nicht verfügbar -> Zustand zurück zum Style-Schritt
      if (workflow.state == WorkflowState.processing) {
        workflow.transition(WorkflowState.captionStyle);
      }
      processingError = e.toString();
      notifyListeners();
      return false;
    }

    processingError = null;

    final handle = PipelineRunHandle();
    _runHandle = handle;

    unawaited(() async {
      final pipeline = CaptiPipeline(
        tempDir: Directory(
            '${settings.file.parent.path}/processing_tmp'),
        transcriptionEngine: engine,
        mediaProcessor: media,
        onStatus: (key) {
          handle.statusKey = key;
          notifyListeners();
        },
        onProgress: (p) {
          handle.progress = p;
          notifyListeners();
        },
        onLog: (level, msg) {
          handle.logLines.add('[$level] $msg');
          notifyListeners();
        },
      );
      handle.pipeline = pipeline;
      handle.running = true;
      try {
        final result = await pipeline.run(
          videoPath: project.videoPath,
          modelSize: project.model,
          language: project.language,
          captionStyle: settings.captionStyle.toMap(),
        );
        // --- Automatisch in Galerie speichern (Movies/Capti) ---
        // Original wird nicht ueberschrieben: Quelle ist Cache-Kopie (capti_inputs),
        // Ziel ist oeffentlicher MediaStore.
        String displayName;
        {
          final raw = project.videoPath.split('/').last.split('\\').last;
          final dot = raw.lastIndexOf('.');
          final rawStem = dot > 0 ? raw.substring(0, dot) : raw;
          final cleanStem = rawStem.replaceFirst(RegExp(r'^\d+_'), '');
          final base = cleanStem.isEmpty ? 'Video' : cleanStem;
          displayName = 'Capti_$base.mp4';
        }
        String? galleryErrorDetail;
        bool saved = false;
        try {
          saved = await outputSaver.saveOutput(
            sourcePath: result.outputPath,
            suggestedName: displayName,
          );
        } catch (e) {
          galleryErrorDetail = e.toString();
          handle.logLines.add('[ERROR] Galerie-Export Fehler: $e');
          saved = false;
        }
        if (!saved) {
          gallerySaveFailed = true;
          lastGalleryName = null;
          lastGalleryUri = null;
          handle.logLines.add('[ERROR] Galerie-Export fehlgeschlagen');
          // Echte native Ursache an Dart/ UI weitergeben (CAPTI_GALLERY_ERROR)
          final detail = galleryErrorDetail ?? 'Unbekannter Fehler';
          throw Exception(
              'CAPTI_GALLERY_ERROR Galerie-Export fehlgeschlagen – $detail (Movies/Capti/$displayName). Pruefe Speicherplatz/Berechtigung.');
        }
        gallerySaveFailed = false;
        lastGalleryName = displayName;
        lastGalleryUri = 'Movies/Capti/$displayName';
        handle.logLines.add('[SUCCESS] Video in Galerie gespeichert: Movies/Capti/$displayName');
        lastOutputPath = result.outputPath;
        history.addEntry(
          videoPath: project.videoPath,
          outputPath: result.outputPath,
          model: project.model,
          language: project.language ?? '',
        );
        workflow.transition(WorkflowState.result);
      } catch (e) {
        if (e is OperationCancelledException) {
          // Abbruchpfad zurück zum Style-Schritt (Zustandsmaschine)
          if (workflow.state == WorkflowState.processing) {
            workflow.transition(WorkflowState.captionStyle);
          }
        } else {
          processingError = e.toString();
          if (workflow.state == WorkflowState.processing) {
            workflow.transition(WorkflowState.captionStyle);
          }
        }
      } finally {
        handle.running = false;
        _cleanupTempQuietly();
        notifyListeners();
      }
    }());

    notifyListeners();
    return true;
  }

  /// Bricht die laufende Verarbeitung ab, wo technisch sicher möglich.
  void cancelProcessing() {
    _runHandle?.cancelRequested = true;
    _runHandle?.pipeline?.requestCancel();
  }

  void _cleanupTempQuietly() {
    try {
      final dir = Directory(
          '${settings.file.parent.path}/processing_tmp');
      if (dir.existsSync()) dir.deleteSync(recursive: true);
    } catch (_) {
      /* Cleanup darf niemals crashen */
    }
  }

  /// Exportiert das Ergebnis über den OutputSaver ("Speichern unter").
  /// Bei MediaStoreGallerySaver bedeutet dies erneut Galerie-Speichern.
  Future<bool> exportResult() async {
    final src = lastOutputPath;
    if (src == null || !File(src).existsSync()) return false;
    return outputSaver.saveOutput(
        sourcePath: src, suggestedName: src.split('/').last);
  }

  /// Oeffnet die Galerie (letztes Video oder Video-Collection).
  Future<bool> openGallery() async {
    try {
      if (outputSaver is MediaStoreGallerySaver) {
        return await (outputSaver as MediaStoreGallerySaver).openGallery();
      }
      // Fallback: versuche via MethodChannel direkt
      const ch = MethodChannel('capti/media');
      final ok = await ch.invokeMethod<bool>('openGallery');
      return ok ?? false;
    } catch (_) {
      return false;
    }
  }

  // ---------------- Persistenz-Helfer ----------------

  /// Exportiert die Session-Daten als Debug-JSON (nur für Tests genutzt).
  Map<String, Object?> debugSnapshot() =>
      jsonDecode(jsonEncode(settings.raw())) as Map<String, Object?>;
}
