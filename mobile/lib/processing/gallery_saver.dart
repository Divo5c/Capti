/// MediaStore-Galerie-Export für Android.
///
/// Schreibt das fertige Video automatisch nach Movies/Capti/ via
/// MainActivity.saveToGallery (MediaStore RELATIVE_PATH, IS_PENDING).
/// Kein "Speichern unter"-Dialog, kein manuelles Kopieren, Original bleibt
/// unverändert (Quelle ist Cache-Kopie).
library;
import 'dart:io';

import 'package:flutter/services.dart';

import '../ui/session.dart' show OutputSaver;

class MediaStoreGallerySaver implements OutputSaver {
  static const _channel = MethodChannel('capti/media');

  /// Offener Gallery-Intent (letztes gespeichertes Video oder Video-Collection).
  Future<bool> openGallery() async {
    try {
      final ok = await _channel.invokeMethod<bool>('openGallery');
      return ok ?? true;
    } catch (_) {
      return false;
    }
  }

  /// Test-Export unabhaengig von Whisper: erzeugt Dummy und exportiert via MediaStore
  Future<String?> testGalleryExport() async {
    try {
      final res = await _channel.invokeMethod<String>('testGalleryExport');
      return res;
    } on PlatformException catch (e) {
      throw Exception('CAPTI_GALLERY_ERROR testGalleryExport ${e.code}: ${e.message} ${e.details ?? ''}');
    }
  }

  @override
  Future<bool> saveOutput({
    required String sourcePath,
    required String suggestedName,
  }) async {
    final src = File(sourcePath);
    if (!src.existsSync()) {
      throw Exception('CAPTI_GALLERY_ERROR Quelle nicht gefunden: $sourcePath');
    }
    if (src.lengthSync() < 1024) {
      throw Exception('CAPTI_GALLERY_ERROR Quelle zu klein (${src.lengthSync()} Bytes): $sourcePath');
    }
    // Sicherer Display-Name: Capti_<Original>.mp4, keine Pfade, .mp4 erzwungen
    var name = suggestedName.trim();
    if (name.isEmpty) name = 'Capti_${DateTime.now().millisecondsSinceEpoch}.mp4';
    name = name.replaceAll(RegExp(r'[/\\]'), '_');
    if (!name.toLowerCase().endsWith('.mp4')) name = '$name.mp4';
    if (!name.startsWith('Capti_')) name = 'Capti_$name';
    final base = name.substring(0, name.length - 4);
    final safeBase = base.replaceAll(RegExp(r'[^A-Za-z0-9._-]'), '_');
    name = '$safeBase.mp4';
    try {
      final res = await _channel.invokeMethod<String>('saveToGallery', {
        'sourcePath': sourcePath,
        'displayName': name,
      });
      if (res == null || res.isEmpty) {
        throw Exception('CAPTI_GALLERY_ERROR saveToGallery lieferte leere Antwort');
      }
      return true;
    } on PlatformException catch (e) {
      // Echte native Ursache weitergeben (Klasse + Message + Details)
      throw Exception(
          'CAPTI_GALLERY_ERROR ${e.code}: ${e.message} ${e.details ?? ''}'.trim());
    } catch (e) {
      throw Exception('CAPTI_GALLERY_ERROR ${e.runtimeType}: $e');
    }
  }
}

/// Fallback für Tests/Desktop: schreibt Bytes nicht in MediaStore, sondern liefert true/false
/// basierend auf Datei-Existenz (kein Dialog).
class FakeGallerySaver implements OutputSaver {
  bool Function(String sourcePath, String suggestedName)? handler;
  FakeGallerySaver({this.handler});
  @override
  Future<bool> saveOutput({required String sourcePath, required String suggestedName}) async {
    if (handler != null) return handler!(sourcePath, suggestedName);
    return File(sourcePath).existsSync();
  }
}
