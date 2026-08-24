"""
Tests für den New-Project-Screen (Phase 5).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Hermetisch: echte Nutzer-Config niemals lesen/schreiben (Phase 30)
import tempfile as _tmp
if "CAPTI_CONFIG_FILE" not in os.environ:
    os.environ["APPDATA"] = _tmp.mkdtemp(prefix="capti_test_appdata_")

import customtkinter as ctk
from unittest.mock import MagicMock, patch

from ui.app_controller import AppController
from ui import i18n
from ui.screens.new_project import (
    NewProjectScreen, LANGUAGE_KEYS, MODEL_OPTIONS, _load_default_model,
)


class TestNewProjectScreen(unittest.TestCase):

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
        self.screen = self.controller.get_screen("new_project")

    def test_screen_builds(self):
        self.assertIsInstance(self.screen, NewProjectScreen)
        self.assertIsNotNone(getattr(self.screen, "drop_card", None))
        self.assertIsNotNone(getattr(self.screen, "model_combo", None))

    def test_video_selection_updates_filename(self):
        """set_video übernimmt Dateiname und leert den Warnhinweis."""
        self.screen.set_video("C:/videos/Mein Video.mp4")
        self.assertEqual(self.screen.video_path, "C:/videos/Mein Video.mp4")
        self.assertEqual(self.screen.file_label.cget("text"), "Mein Video.mp4")
        self.assertEqual(self.screen.warning_label.cget("text"), "")

    def test_continue_without_video_shows_warning(self):
        """Weiter ohne Video -> Warnung, keine Navigation."""
        self.controller.show_screen("new_project")
        self.screen._on_continue()
        self.assertIn("Video", self.screen.warning_label.cget("text"))
        self.assertEqual(self.controller.current_screen, "new_project")

    def test_continue_passes_project_data_to_workflow(self):
        """Weiter speichert das Projekt und navigiert zum Caption-Style-Schritt.

        Phase 31: Kein Pipeline-Start mehr hier – erst nach der Style-Auswahl.
        """
        self.controller.show_screen("new_project")
        self.screen.set_video("C:/videos/clip.mp4")
        self.screen.lang_var.set("np.lang.de")
        self.screen.model_var.set("tiny")
        self.screen._on_continue()

        # Projekt zwischengespeichert, Navigation zum Style-Schritt
        self.assertEqual(self.controller.current_screen, "caption_style")
        project = self.controller.pending_project
        self.assertEqual(project["video_path"], "C:/videos/clip.mp4")
        self.assertEqual(project["model"], "tiny")
        self.assertEqual(project["language"], "de")

    def test_continue_invalid_extension_warns(self):
        self.controller.show_screen("new_project")
        self.screen.set_video("C:/videos/datei.txt")
        self.screen._on_continue()
        self.assertIn("Ungültig", self.screen.warning_label.cget("text"))
        self.assertEqual(self.controller.current_screen, "new_project")

    def test_language_options_no_fake_translation(self):
        """Nur Auto/Deutsch/English – keine funktionierende Ãœbersetzung vorgetäuscht."""
        self.assertEqual(LANGUAGE_KEYS, ["np.lang.auto", "np.lang.de", "np.lang.en"])
        i18n.set_language("de")
        self.assertEqual(i18n.t("np.lang.auto"), "Auto")
        self.assertEqual(i18n.t("np.lang.de"), "Deutsch")
        self.assertEqual(i18n.t("np.lang.en"), "English")

    def test_model_default_from_config_or_small(self):
        """Default-Modell ist gültig (Config-Wert oder Fallback 'small')."""
        self.assertIn(_load_default_model(), MODEL_OPTIONS)
        self.assertIn(self.screen.model_var.get(), MODEL_OPTIONS)

    def test_back_navigation_to_home(self):
        self.controller.show_screen("new_project")
        self.screen.navigate("home")
        self.assertEqual(self.controller.current_screen, "home")


if __name__ == "__main__":
    unittest.main()

