"""
Integrationstests: Neue UI <-> CaptiPipeline (Phase 10).

Die Pipeline wird gemockt (keine echte Whisper-/FFmpeg-Verarbeitung,
keine Model-Downloads). History wird auf eine Temp-Datei umgeleitet.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Hermetisch: echte Nutzer-Config niemals lesen/schreiben
import tempfile as _tmp
if "CAPTI_CONFIG_FILE" not in os.environ:
    os.environ["APPDATA"] = _tmp.mkdtemp(prefix="capti_test_appdata_")


import customtkinter as ctk

from history import HistoryManager
from ui.app_controller import AppController


class PipelineIntegrationTestBase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        ctk.set_appearance_mode("dark")
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except Exception:
            pass

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.history_path = Path(self.tmp.name) / "history.json"
        self.history_patcher = patch("history._history_file",
                                     return_value=self.history_path)
        self.history_patcher.start()
        self.controller = AppController(self.root)
        self.processing = self.controller.get_screen("processing")

    def tearDown(self):
        self.history_patcher.stop()
        self.tmp.cleanup()

    def _make_pipeline_mock(self, done_path=None, error=None):
        """Erzeugt einen CaptiPipeline-Mock, der run_async synchron simuliert."""
        instance = MagicMock()
        captured = {}

        def fake_init(**kwargs):
            captured.update(kwargs)
            return instance  # Konstruktor gibt die Instanz zurück

        # run_async tut nichts – Tests lösen on_done/on_error explizit aus
        instance.run_async.side_effect = lambda v, **k: None
        return MagicMock(side_effect=fake_init), instance, captured


class TestPipelineIntegration(PipelineIntegrationTestBase):

    @patch("ui.screens.processing.CaptiPipeline")
    def test_set_project_starts_pipeline(self, mock_pipeline):
        """set_project startet die Pipeline mit Video/Modell/Sprache."""
        self.processing.set_project("C:/videos/clip.mp4", model="tiny", language="de")
        instance = mock_pipeline.return_value
        instance.run_async.assert_called_once_with(
            "C:/videos/clip.mp4", model_size="tiny", language="de",
            caption_style=unittest.mock.ANY)
        # Nav-Lock aktiv während Verarbeitung
        self.assertTrue(self.processing._nav_locked)

    def test_callbacks_update_processing(self):
        """Pipeline-Callbacks aktualisieren Status/Progress/Log thread-safe."""
        mock_cls, instance, captured = self._make_pipeline_mock()
        with patch("ui.screens.processing.CaptiPipeline", mock_cls):
            self.processing.set_project("C:/videos/clip.mp4")

        captured["on_status"]("Transkribiere Audio...")
        captured["on_progress"](50)
        captured["on_log"]("INFO", "Audio extrahiert")
        self.processing._drain_ui_queue()  # Queue im Main-Thread verarbeiten

        self.assertEqual(self.processing.status_label.cget("text"), "Transkribiere Audio...")
        self.assertEqual(self.processing.percent_label.cget("text"), "50 %")
        self.assertIn("[INFO] Audio extrahiert", self.processing.log_box.get("1.0", "end"))

    def test_success_navigates_to_result_and_saves_history(self):
        """on_done -> Result-Screen + History-Eintrag + Navigation frei."""
        mock_cls, instance, captured = self._make_pipeline_mock(done_path="C:/videos/out.mp4")
        with patch("ui.screens.processing.CaptiPipeline", mock_cls):
            self.processing.set_project("C:/videos/clip.mp4", model="small", language="de")
        captured["on_done"]("C:/videos/out.mp4")
        self.processing._drain_ui_queue()  # done-Event verarbeiten

        self.assertEqual(self.controller.current_screen, "result")
        result = self.controller.get_screen("result")
        self.assertEqual(result.output_path, "C:/videos/out.mp4")
        self.assertEqual(result.filename_label.cget("text"), "clip.mp4")
        # History gespeichert (nur bei Erfolg)
        entries = HistoryManager().get_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["video_path"], "C:/videos/clip.mp4")
        self.assertEqual(entries[0]["output_path"], "C:/videos/out.mp4")
        self.assertEqual(entries[0]["model"], "small")
        # Navigation wieder frei
        self.assertFalse(self.processing._nav_locked)

    def test_error_shows_error_no_history(self):
        """on_error -> Fehlerzustand, Navigation frei, KEIN History-Eintrag."""
        mock_cls, instance, captured = self._make_pipeline_mock(error="boom")
        with patch("ui.screens.processing.CaptiPipeline", mock_cls):
            self.processing.set_project("C:/videos/clip.mp4")
        captured["on_error"]("boom")
        self.processing._drain_ui_queue()  # error-Event verarbeiten

        self.assertIn("boom", self.processing.error_label.cget("text"))
        self.assertFalse(self.processing._nav_locked)
        self.assertEqual(self.controller.current_screen, "processing")
        self.assertEqual(HistoryManager().get_entries(), [])

    def test_ui_updates_thread_safe_via_queue(self):
        """Callbacks landen thread-safe in einer Queue (kein direkter Widget-Zugriff)."""
        mock_cls, instance, captured = self._make_pipeline_mock()
        with patch("ui.screens.processing.CaptiPipeline", mock_cls):
            self.processing.set_project("C:/videos/clip.mp4")
        # Callbacks schreiben nur in die Queue; Poller wendet sie im Main-Thread an
        captured["on_status"]("x")
        self.processing._drain_ui_queue()
        self.assertEqual(self.processing.status_label.cget("text"), "x")


if __name__ == "__main__":
    unittest.main()