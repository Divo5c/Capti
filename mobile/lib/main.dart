/// Capti Mobile – Einstiegspunkt.
///
/// Verdrahtet die App-Session mit den plattformspezifischen
/// Implementierungen:
///   - Datenverzeichnis via path_provider (App-Sandbox; KEINE persönlichen
///     Dateien im Repository/Bündel)
///   - Video-Auswahl via file_picker (Android SAF / iOS DocumentPicker)
///   - Engine-Factories: werfen EngineUnavailableException, solange die
///     Native-Schicht nicht mitgebaut wurde (ehrlicher Zustand im
///     Processing-Screen; siehe docs/MOBILE_ARCHITECTURE.md).

library;
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:path_provider/path_provider.dart';

import 'core/caption_style.dart';
import 'processing/gallery_saver.dart';
import 'processing/native_media.dart';
import 'processing/pipeline.dart';
import 'ui/app.dart';
import 'ui/session.dart';
import 'core/stores.dart';
import 'core/i18n.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Plattformgerechtes Benutzerdatenverzeichnis (App-Sandbox).
  final supportDir = await getApplicationSupportDirectory();
  final settingsFile = File('${supportDir.path}/capti_settings.json');
  final historyFile = File('${supportDir.path}/capti_history.json');

  final settings = SettingsStore(settingsFile);
  CaptiI18n.instance.setLanguage(settings.language);

  // Modellverzeichnis robust sicherstellen (muss DIRECTORY sein).
  // Fix fuer "Not a directory" wenn vorher ein File namens "models" existierte.
  final modelDir = '${settings.file.parent.path}/models';
  final modelsType = FileSystemEntity.typeSync(modelDir, followLinks: false);
  if (modelsType == FileSystemEntityType.file) {
    try { File(modelDir).deleteSync(); } catch (_) {}
  }
  try {
    Directory(modelDir).createSync(recursive: true);
    assert(FileSystemEntity.typeSync(modelDir, followLinks: false) ==
        FileSystemEntityType.directory);
  } catch (_) {
    // Wird spaeter in whisper_model robust behandelt; hier nicht crashen.
  }

  final session = AppSession(
    settings: settings,
    history: HistoryStore(historyFile),
    videoPicker: FilePickerVideoPicker(),
    outputSaver: MediaStoreGallerySaver(),
    // settings.model bestimmt dynamisch welches Modell verwendet wird
    // (tiny/base/small/medium, Default small, multilingual für Auto-Sprache).
    // Der Pfad wird bei JEDEM Engine-Aufruf frisch aus Settings gelesen –
    // ein Wechsel in den Einstellungen wirkt sofort, ohne App-Neustart.
    // Existiert die Datei nicht, versucht WhisperCppEngine sie aus
    // assets/models/<name>.bin zu kopieren; fehlt sie auch dort, wirft
    // sie EngineUnavailableException mit error.model_missing (honest UI).
    engineFactory: () {
      final m = settings.model;
      return WhisperCppEngine(
        modelPath: '$modelDir/$m.bin',
        libPath: 'libwhisper_bridge.so',
      );
    },
    // Echte Medienverarbeitung (FFmpeg + libass, siehe
    // tools/fetch_media.sh + tools/build_media_android.sh). Fehlt die
    // Bibliothek auf dem Gerät, wirft der erste Aufruf eine
    // MediaEngineException -> Processing zeigt den ehrlichen Fehlerzustand.
    mediaFactory: () => NativeMediaProcessor(
          libPath: 'libmedia_bridge.so',
          fontsDir: '/system/fonts',
        ),
    initialStyle: CaptionStyle.load(settings.raw()['caption_style']),
  );

  runApp(CaptiApp(session: session));
}

/// System-Dateipicker (Android SAF / iOS DocumentPicker).
class FilePickerVideoPicker implements VideoPicker {
  static const _channel = MethodChannel('capti/media');

  @override
  Future<String?> pickVideo() async {
    final file = await FilePicker.pickFile(
      type: FileType.video,
    );
    final raw = file?.path;
    if (raw == null) return null;
    // Android-SAF-Absicherung: content://-URIs kann die native FFmpeg-
    // Schicht (POSIX fopen) nicht öffnen. Wir lassen sie uns von der
    // Plattformseite in den App-Cache kopieren und nutzen diesen Pfad.
    if (raw.startsWith('content://')) {
      try {
        final resolved = await _channel
            .invokeMethod<String>('resolveInputPath', {'path': raw});
        return (resolved == null || resolved.isEmpty) ? raw : resolved;
      } catch (_) {
        return raw; // ehrlicher Fallback: Originalpfad -> Bridge meldet Fehler
      }
    }
    return raw;
  }
}

/// Export über den System-Speichern-Dialog (Android/iOS schreiben die
/// Datei selbst; wir übergeben den Inhalt).
class FilePickerOutputSaver implements OutputSaver {
  @override
  Future<bool> saveOutput({
    required String sourcePath,
    required String suggestedName,
  }) async {
    try {
      final bytes = await File(sourcePath).readAsBytes();
      final uri = await FilePicker.saveFile(
        fileName: suggestedName,
        bytes: bytes,
        mimeType: 'video/mp4',
      );
      return uri != null;
    } catch (_) {
      return false;
    }
  }
}
