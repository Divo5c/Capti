"""
Tests für den Result-Screen (Phase 7).
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Hermetisch: echte Nutzer-Config niemals lesen/schreiben (Phase 30)
import tempfile as _tmp
if "CAPTI_CONFIG_FILE" not in os.environ:
    os.environ["APPDATA"] = _tmp.mkdtemp(prefix="capti_test_appdata_")

import customtkinter as ctk

from ui.app_controller import AppController
from ui.screens.result import ResultScreen


class TestResultScreen(unittest.TestCase):

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
        self.controller = AppController(self.root)
        self.screen = self.controller.get_screen("result")

    def test_screen_builds(self):
        self.assertIsInstance(self.screen, ResultScreen)
        for attr in ("result_card", "filename_label", "meta_label", "error_label"):
            self.assertIsNotNone(getattr(self.screen, attr, None))

    def test_set_result_takes_output_path_and_filename(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            path = f.name
        try:
            self.screen.set_result(path)
            self.assertEqual(self.screen.output_path, path)
            self.assertEqual(self.screen.filename_label.cget("text"),
                             os.path.basename(path))
            self.assertEqual(self.screen.error_label.cget("text"), "")
        finally:
            os.unlink(path)

    def test_model_language_displayed(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            path = f.name
        try:
            self.screen.set_result(path, model="small", language="Deutsch")
            meta = self.screen.meta_label.cget("text")
            self.assertIn("small", meta)
            self.assertIn("Deutsch", meta)
        finally:
            os.unlink(path)

    def test_missing_optional_info_is_safe(self):
        """Fehlende optionale Metadaten verursachen keinen Fehler."""
        self.screen.set_result("", filename="video.mp4")
        self.assertEqual(self.screen.filename_label.cget("text"), "video.mp4")
        self.assertIn("Kein Ausgabevideo", self.screen.error_label.cget("text"))

    def test_nonexistent_path_no_crash(self):
        """Ungültiger/nicht vorhandener Pfad -> Fehlerhinweis statt Crash."""
        self.screen.set_result("Z:/does/not/exist.mp4")
        self.assertIn("nicht gefunden", self.screen.error_label.cget("text"))
        # open_video darf nicht abstürzen
        self.screen.open_video()

    def test_reset_clears_state(self):
        self.screen.set_result("C:/videos/out.mp4", model="tiny")
        self.screen.reset()
        self.assertEqual(self.screen.output_path, "")
        self.assertEqual(self.screen.filename_label.cget("text"), "Kein Ergebnis vorhanden")
        self.assertEqual(self.screen.meta_label.cget("text"), "")
        self.assertEqual(self.screen.error_label.cget("text"), "")

    def test_navigation_new_project(self):
        self.controller.show_screen("result")
        self.screen.navigate("new_project")
        self.assertEqual(self.controller.current_screen, "new_project")

    def test_navigation_home(self):
        self.controller.show_screen("result")
        self.screen.navigate("home")
        self.assertEqual(self.controller.current_screen, "home")


if __name__ == "__main__":
    unittest.main()

