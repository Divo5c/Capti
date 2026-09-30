/// Capti i18n (Dart-Port): Deutsch & Englisch.
///
/// - Zugriff ausschließlich über CaptiI18n.t(key)
/// - Fallback-Kette: aktuelle Sprache -> Deutsch -> Key selbst
/// - Stabile Keys, lokalisierte Labels (nie umgekehrt) – identisch zur
///   Desktop-Konvention; Pipeline-Status-Keys bleiben maschinenstabil.

library;
import 'package:flutter/foundation.dart';

const Map<String, Map<String, String>> captiTranslations = {
  'de': {
    'app.tagline': 'Untertitel. Automatisch. Dein Stil.',
    'nav.home': 'Home',
    'nav.new_project': 'Neues Projekt',
    'nav.caption_style': 'Caption Style',
    'nav.settings': 'Einstellungen',
    'home.greeting_no_name': 'Hallo!',
    'home.greeting': 'Hallo, {name}!',
    'home.cta_new': '+ Neues Projekt',
    'home.cta_hint': 'Video auswählen',
    'home.history_title': 'Zuletzt verarbeitet',
    'history.empty_title': 'Noch keine Videos verarbeitet.',
    'history.empty_hint': 'Starte dein erstes Projekt.',
    'np.title': 'Neues Projekt',
    'np.subtitle': 'Erstelle Untertitel für dein nächstes Video.',
    'np.btn_select': 'Video auswählen',
    'np.selected': 'Ausgewählt:',
    'np.lang.auto': 'Auto',
    'np.lang.auto_desc': 'Automatische Spracherkennung',
    'np.lang_desc': 'Gesprochene Sprache im Video',
    'np.model_title': 'Transkriptionsmodell',
    'common.back': '← Zurück',
    'np.warn_no_video': 'Bitte wähle zuerst ein Video aus.',
    'np.warn_invalid': 'Ungültiges Videoformat.',
    'cs.title': 'Caption Style',
    'cs.subtitle': 'Passe das Aussehen deiner Untertitel an.',
    'cs.preview': 'VORSCHAU',
    'cs.preview_replay': '↻',
    'cs.preset_applied': 'Preset „{name}“ angewendet.',
    'cs.preview_sentence': 'So sehen deine Captions im Video aus',
    'cs.pop_enabled': 'Pop-Effekt aktiv',
    'cs.pop_scale': 'Pop Scale',
    'cs.pop_decay': 'Pop Decay (ms)',
    'cs.color.normal': 'Normalfarbe',
    'cs.color.highlight': 'Highlightfarbe',
    'cs.start_processing': 'Verarbeitung starten →',
    'proc.title': 'Capti arbeitet...',
    'proc.subtitle': 'Dein Video wird gerade verarbeitet.',
    'proc.preparing': 'Video wird vorbereitet...',
    'proc.cancel': 'Abbrechen',
    'proc.engine_missing':
        'Auf diesem Gerät ist noch keine Verarbeitungs-Engine verfügbar. '
            'Die native Schicht (whisper.cpp + FFmpeg) muss mitgebaut werden – '
            'siehe docs/MOBILE_ARCHITECTURE.md.',
    'res.title': 'Fertig!',
    'res.subtitle': 'Dein Video wurde erfolgreich verarbeitet.',
    'res.no_result': 'Kein Ergebnis vorhanden',
    'res.btn_open': 'Video öffnen',
    'res.btn_save_as': 'Speichern unter...',
    'res.btn_new_project': 'Neues Projekt',
    'res.gallery_saved': 'Video gespeichert',
    'res.gallery_saved_desc': 'Dein fertiges Video wurde in der Galerie gespeichert.',
    'res.gallery_path': 'Galerie: Movies/Capti/',
    'res.btn_open_gallery': 'Galerie öffnen',
    'error.gallery_failed': 'Video konnte nicht in Galerie gespeichert werden.',
    'set.title': 'Einstellungen',
    'set.name_title': 'Dein Name',
    'set.theme_title': 'Darstellung',
    'set.lang_title': 'Sprache',
    'set.model_title': 'Standardmodell',
    'set.saved': 'Gespeichert.',
    'set.clear_history': 'Verlauf löschen',
    'np.lang_title': 'Sprache',
    'np.continue': 'Weiter →',
    'error.no_video': 'Kein Video ausgewählt.',
    'error.invalid_format': 'Ungültiges Videoformat.',
    'error.video_missing': 'Videodatei wurde nicht gefunden.',
    'error.invalid_model': 'Ungültiges Modell.',
    'pipeline.download_model': 'Modell wird heruntergeladen...',
    'error.model_missing':
        'Whisper-Modell "{model}" nicht gefunden unter {path}. '
            'Bitte Modell unter assets/models/{model}.bin bündeln oder manuell nach {path} kopieren. '
            'Download: https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{model}.bin',
  },
  'en': {
    'app.tagline': 'Subtitles. Automatic. Your style.',
    'nav.home': 'Home',
    'nav.new_project': 'New Project',
    'nav.caption_style': 'Caption Style',
    'nav.settings': 'Settings',
    'home.greeting_no_name': 'Hello!',
    'home.greeting': 'Hello, {name}!',
    'home.cta_new': '+ New Project',
    'home.cta_hint': 'Choose a video',
    'home.history_title': 'Recently processed',
    'history.empty_title': 'No videos processed yet.',
    'history.empty_hint': 'Start your first project.',
    'np.title': 'New Project',
    'np.subtitle': 'Create subtitles for your next video.',
    'np.btn_select': 'Choose video',
    'np.selected': 'Selected:',
    'np.lang_title': 'Language',
    'np.lang_desc': 'Spoken language in the video',
    'np.lang.auto': 'Auto',
    'np.lang.auto_desc': 'Automatic speech recognition',
    'np.model_title': 'Transcription model',
    'np.continue': 'Next →',
    'common.back': '← Back',
    'np.warn_no_video': 'Please choose a video first.',
    'np.warn_invalid': 'Invalid video format.',
    'cs.title': 'Caption Style',
    'cs.subtitle': 'Customize the look of your subtitles.',
    'cs.preview': 'PREVIEW',
    'cs.preview_replay': '↻',
    'cs.preset_applied': 'Preset "{name}" applied.',
    'cs.preview_sentence': 'This is how your captions will look',
    'cs.pop_enabled': 'Pop effect enabled',
    'cs.pop_scale': 'Pop Scale',
    'cs.pop_decay': 'Pop Decay (ms)',
    'cs.color.normal': 'Normal color',
    'cs.color.highlight': 'Highlight color',
    'cs.start_processing': 'Start processing →',
    'proc.title': 'Capti is working...',
    'proc.subtitle': 'Your video is being processed.',
    'proc.preparing': 'Preparing video...',
    'proc.cancel': 'Cancel',
    'proc.engine_missing':
        'No processing engine available on this device yet. '
            'The native layer (whisper.cpp + FFmpeg) has to be built with the '
            'app – see docs/MOBILE_ARCHITECTURE.md.',
    'res.title': 'Done!',
    'res.subtitle': 'Your video was processed successfully.',
    'res.no_result': 'No result available',
    'res.btn_open': 'Open video',
    'res.btn_save_as': 'Save as...',
    'res.btn_new_project': 'New Project',
    'res.gallery_saved': 'Video saved',
    'res.gallery_saved_desc': 'Your finished video was saved to the gallery.',
    'res.gallery_path': 'Gallery: Movies/Capti/',
    'res.btn_open_gallery': 'Open gallery',
    'error.gallery_failed': 'Could not save video to gallery.',
    'set.title': 'Settings',
    'set.name_title': 'Your name',
    'set.theme_title': 'Appearance',
    'set.lang_title': 'Language',
    'set.model_title': 'Default model',
    'set.saved': 'Saved.',
    'set.clear_history': 'Clear history',
    'error.no_video': 'No video selected.',
    'error.invalid_format': 'Invalid video format.',
    'error.video_missing': 'Video file was not found.',
    'error.invalid_model': 'Invalid model.',
    'pipeline.download_model': 'Downloading model...',
    'error.model_missing':
        'Whisper model "{model}" not found at {path}. '
            'Bundle it as assets/models/{model}.bin or copy manually to {path}. '
            'Download: https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{model}.bin',
  },
};

const List<String> supportedLanguages = ['de', 'en'];
const String defaultLanguage = 'de';

class CaptiI18n extends ChangeNotifier {
  String _language = defaultLanguage;

  static final CaptiI18n instance = CaptiI18n();

  String get language => _language;

  void setLanguage(String language) {
    _language =
        supportedLanguages.contains(language) ? language : defaultLanguage;
    notifyListeners();
  }

  /// Übersetzt einen Key in der aktuellen Sprache.
  /// Fallback: aktuelle Sprache -> Deutsch -> Key selbst.
  String t(String key, [Map<String, Object?> params = const {}]) {
    var text = captiTranslations[_language]?[key];
    text ??= captiTranslations[defaultLanguage]?[key];
    text ??= key;
    if (params.isNotEmpty) {
      params.forEach((k, v) {
        text = text!.replaceAll('{$k}', '$v');
      });
    }
    return text!;
  }
}

/// Bequemer Modulfunktions-Zugriff für Widgets.
String tr(String key, [Map<String, Object?> params = const {}]) =>
    CaptiI18n.instance.t(key, params);
