"""
Regressionstests Phase 23: Pipeline-Statusmeldungen internationalisieren.

Die Pipeline ist UI-agnostisch und liefert ausschließlich stabile
Status-Keys ("pipeline.*"); die UI übersetzt sie.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Hermetisch: echte Nutzer-Config niemals lesen/schreiben
import tempfile as _tmp
if "CAPTI_CONFIG_FILE" not in os.environ:
    os.environ["APPDATA"] = _tmp.mkdtemp(prefix="capti_test_appdata_")


import pipeline as pipeline_mod
from pipeline import (
    CaptiPipeline, STATUS_STARTED, STATUS_EXTRACT_AUDIO, STATUS_TRANSCRIBE,
    STATUS_EMBED_SUBTITLES, STATUS_COMPLETED,
)
from ui import i18n


class TestPipelineStatusKeys(unittest.TestCase):
    """1+2: Pipeline liefert nur Keys, keine deutschen Texte; Keys stabil."""

    def _run_pipeline(self):
        statuses = []
        p = CaptiPipeline(
            temp_dir=os.path.join(os.environ.get("TEMP", "."), "capti_test"),
            on_status=statuses.append,
        )
        # Alle externen Abhängigkeiten mocken – nur der Status-Fluss zählt
        with patch.object(pipeline_mod, "create_subtitle_engine", return_value=MagicMock()), \
             patch.object(pipeline_mod, "create_video_processor") as mock_vp, \
             patch.object(pipeline_mod, "group_caption_segments", return_value=[]):
            vp = mock_vp.return_value
            vp.extract_audio.return_value = "audio.wav"
            vp.get_video_info.return_value = {"streams": [{"width": 1080, "height": 1920}]}
            try:
                p._run("C:/videos/clip.mp4", "tiny", None)
            except Exception:
                pass  # Mock-Kette kann spät fehlschlagen – Status sind bereits geflogen
        return statuses

    def test_no_german_status_texts(self):
        statuses = self._run_pipeline()
        self.assertTrue(statuses)
        for s in statuses:
            self.assertTrue(s.startswith("pipeline."), f"Kein Key: {s!r}")
            self.assertNotIn("Extrahiere", s)
            self.assertNotIn("Transkribiere", s)
            self.assertNotIn("Bette Untertitel", s)

    def test_expected_key_sequence(self):
        statuses = self._run_pipeline()
        expected_prefixes = [STATUS_STARTED, STATUS_EXTRACT_AUDIO,
                             STATUS_TRANSCRIBE]
        for i, prefix in enumerate(expected_prefixes):
            self.assertEqual(statuses[i], prefix)


class TestI18nPipelineKeys(unittest.TestCase):
    """3+4+5: Beide Sprachen besitzen alle Pipeline-Keys mit korrekten Texten."""

    KEYS = [STATUS_STARTED, STATUS_EXTRACT_AUDIO, STATUS_TRANSCRIBE,
            STATUS_EMBED_SUBTITLES, STATUS_COMPLETED]

    def test_all_keys_in_both_languages(self):
        de = set(i18n.TRANSLATIONS["de"])
        en = set(i18n.TRANSLATIONS["en"])
        for key in self.KEYS:
            self.assertIn(key, de)
            self.assertIn(key, en)

    def test_german_texts_preserve_meaning(self):
        i18n.set_language("de")
        self.assertEqual(i18n.t(STATUS_STARTED), "Verarbeitung gestartet...")
        self.assertEqual(i18n.t(STATUS_EXTRACT_AUDIO), "Extrahiere Audio...")
        self.assertEqual(i18n.t(STATUS_TRANSCRIBE), "Transkribiere Audio...")
        self.assertEqual(i18n.t(STATUS_EMBED_SUBTITLES), "Bette Untertitel ein...")
        self.assertEqual(i18n.t(STATUS_COMPLETED),
                         "Verarbeitung erfolgreich abgeschlossen!")

    def test_english_texts(self):
        i18n.set_language("en")
        self.assertEqual(i18n.t(STATUS_STARTED), "Processing started...")
        self.assertEqual(i18n.t(STATUS_EXTRACT_AUDIO), "Extracting audio...")
        self.assertEqual(i18n.t(STATUS_TRANSCRIBE), "Transcribing audio...")
        self.assertEqual(i18n.t(STATUS_EMBED_SUBTITLES), "Embedding subtitles...")
        self.assertEqual(i18n.t(STATUS_COMPLETED),
                         "Processing completed successfully!")


class TestProcessingScreenStatusTranslation(unittest.TestCase):

    def setUp(self):
        import customtkinter as ctk
        from ui.app_controller import AppController
        ctk.set_appearance_mode("dark")
        self.root = ctk.CTk()
        self.root.withdraw()
        self.controller = AppController(self.root)
        self.screen = self.controller.get_screen("processing")

    def tearDown(self):
        i18n.set_language("de")
        self.root.destroy()

    def test_key_translated_german(self):
        i18n.set_language("de")
        self.screen.update_status(STATUS_EXTRACT_AUDIO)
        self.assertEqual(self.screen.status_label.cget("text"), "Extrahiere Audio...")

    def test_key_translated_english(self):
        i18n.set_language("en")
        self.screen.update_status(STATUS_EMBED_SUBTITLES)
        self.assertEqual(self.screen.status_label.cget("text"), "Embedding subtitles...")

    def test_free_text_passes_through_untranslated(self):
        """7: Fehler-/Exception-Texte werden nicht als Keys behandelt."""
        i18n.set_language("en")
        raw = "ffmpeg failed: No such file 'xyz' (code -1)"
        self.screen.update_status(raw)
        self.assertEqual(self.screen.status_label.cget("text"), raw)

    def test_unknown_pipeline_key_falls_back_to_key(self):
        i18n.set_language("de")
        self.screen.update_status("pipeline.does_not_exist")
        self.assertEqual(self.screen.status_label.cget("text"),
                         "pipeline.does_not_exist")


class TestLegacyTranslationFile(unittest.TestCase):
    """Legacy-UI (translations.json) kennt dieselben Pipeline-Keys."""

    def test_translations_json_has_pipeline_keys(self):
        import json
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "translations.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for lang in ("de", "en"):
            for key in TestI18nPipelineKeys.KEYS:
                self.assertIn(key, data[lang], f"{key} fehlt in {lang}")
        self.assertEqual(data["de"][STATUS_EXTRACT_AUDIO], "Extrahiere Audio...")
        self.assertEqual(data["en"][STATUS_EXTRACT_AUDIO], "Extracting audio...")


if __name__ == "__main__":
    unittest.main()