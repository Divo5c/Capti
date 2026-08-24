"""
Regressionstests Phase 25: i18n-Bereinigungen.

1. Result-Screen Home-Button nutzt i18n.t("nav.home") (de/en)
2. New-Project DnD-Fallback "Ungültige Datei." ist i18n-fähig (np.invalid_file)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Hermetisch: echte Nutzer-Config niemals lesen/schreiben
import tempfile as _tmp
if "CAPTI_CONFIG_FILE" not in os.environ:
    os.environ["APPDATA"] = _tmp.mkdtemp(prefix="capti_test_appdata_")


from ui import i18n


def _all_texts(widget):
    """Sammelt rekursiv alle Texte von Labels/Buttons/Switches."""
    import customtkinter as ctk
    texts = []
    if isinstance(widget, (ctk.CTkLabel, ctk.CTkButton)):
        try:
            texts.append(widget.cget("text"))
        except Exception:
            pass
    for child in widget.winfo_children():
        texts.extend(_all_texts(child))
    return texts


class TestResultHomeButtonI18n(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import customtkinter as ctk
        ctk.set_appearance_mode("dark")
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()
        i18n.set_language("de")

    def _home_button_text(self):
        from ui.app_controller import AppController
        controller = AppController(self.root)
        screen = controller.get_screen("result")
        self.root.update()
        texts = _all_texts(screen)
        controller.root = None  # Screens nicht zerstören (Root bleibt)
        return texts

    def test_home_button_german(self):  # 1a
        i18n.set_language("de")
        texts = self._home_button_text()
        self.assertIn(i18n.TRANSLATIONS["de"]["nav.home"], texts)

    def test_home_button_english(self):  # 1b
        i18n.set_language("en")
        texts = self._home_button_text()
        # nav.home ist in beiden Sprachen "Home" – Key muss verwendet werden,
        # daher prüfen wir den übersetzten Wert aus dem en-Wörterbuch.
        self.assertIn(i18n.TRANSLATIONS["en"]["nav.home"], texts)


class TestNewProjectInvalidFileI18n(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import customtkinter as ctk
        ctk.set_appearance_mode("dark")
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()
        i18n.set_language("de")

    def _screen(self):
        from ui.app_controller import AppController
        controller = AppController(self.root)
        return controller.get_screen("new_project")

    def test_invalid_file_key_exists_both_languages(self):  # 2
        self.assertIn("np.invalid_file", i18n.TRANSLATIONS["de"])
        self.assertIn("np.invalid_file", i18n.TRANSLATIONS["en"])
        self.assertEqual(i18n.TRANSLATIONS["de"]["np.invalid_file"],
                         "Ungültige Datei.")
        self.assertEqual(i18n.TRANSLATIONS["en"]["np.invalid_file"],
                         "Invalid file.")

    def test_drop_fallback_uses_i18n(self):
        """DnD-Fallback (error leer) zeigt den übersetzten np.invalid_file."""
        from unittest.mock import patch
        import ui.screens.new_project as np_mod
        # Erst Screen bauen (Controller-Init setzt Sprache aus der Config),
        # danach die Testsprache setzen.
        screen = self._screen()
        i18n.set_language("en")
        class FakeEvent:
            data = "{C:/videos/clip.mp4}"
        with patch.object(np_mod, "pick_first_video", return_value=(None, "")):
            screen._on_drop(FakeEvent())
        self.root.update()
        self.assertEqual(screen.warning_label.cget("text"),
                         i18n.TRANSLATIONS["en"]["np.invalid_file"])
        i18n.set_language("de")
        screen2 = self._screen()
        i18n.set_language("de")
        with patch.object(np_mod, "pick_first_video", return_value=(None, "")):
            screen2._on_drop(FakeEvent())
        self.root.update()
        self.assertEqual(screen2.warning_label.cget("text"),
                         i18n.TRANSLATIONS["de"]["np.invalid_file"])


if __name__ == "__main__":
    unittest.main()