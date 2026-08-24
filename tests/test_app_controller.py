"""
Tests für AppController und Screens (Phase 3 Architektur-Gerüst).

Erzeugt ein echtes (zurückgezogenes) Tk-Fenster – auf Windows-CI/Desktop ok.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Hermetisch: echte Nutzer-Config niemals lesen/schreiben
import tempfile as _tmp
if "CAPTI_CONFIG_FILE" not in os.environ:
    os.environ["APPDATA"] = _tmp.mkdtemp(prefix="capti_test_appdata_")


import customtkinter as ctk

from ui.app_controller import AppController, SCREEN_REGISTRY


class AppControllerTestBase(unittest.TestCase):
    """Gemeinsames Root-Fenster für alle Controller-Tests."""

    @classmethod
    def setUpClass(cls):
        ctk.set_appearance_mode("dark")
        cls.root = ctk.CTk()
        cls.root.withdraw()  # Fenster nicht anzeigen

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except Exception:
            pass


class TestAppController(AppControllerTestBase):

    def test_controller_created(self):
        controller = AppController(self.root)
        self.assertIsNotNone(controller)
        self.assertEqual(controller.current_screen, "home")
        self.assertEqual(set(controller.screen_names),
                         {"home", "new_project", "caption_style",
                          "processing", "result", "settings"})

    def test_all_screens_can_be_created(self):
        """Alle sechs Screens lassen sich instanziieren."""
        controller = AppController(self.root)
        for name in SCREEN_REGISTRY:
            screen = controller.get_screen(name)
            self.assertIsNotNone(screen, f"Screen '{name}' konnte nicht erstellt werden")

    def test_show_screen_home(self):
        controller = AppController(self.root)
        controller.show_screen("home")
        self.assertEqual(controller.current_screen, "home")

    def test_navigation_between_screens(self):
        """Navigation zwischen mindestens zwei Screens funktioniert zentral."""
        controller = AppController(self.root)
        controller.show_screen("new_project")
        self.assertEqual(controller.current_screen, "new_project")
        controller.show_screen("settings")
        self.assertEqual(controller.current_screen, "settings")
        # Zurück zu Home über Screen-eigene navigate()-Hilfe
        controller.get_screen("settings").navigate("home")
        self.assertEqual(controller.current_screen, "home")

    def test_invalid_screen_name_falls_back_to_home(self):
        controller = AppController(self.root)
        controller.show_screen("does_not_exist")
        self.assertEqual(controller.current_screen, "home")


if __name__ == "__main__":
    unittest.main()