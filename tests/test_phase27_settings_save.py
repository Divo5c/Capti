"""
Regressionstests Phase 27: Settings-Save-Korrektheit & UX-Reparatur.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import customtkinter as ctk

from config import load_config, save_config, set_config_value
from ui import i18n
from ui.screens.settings import _theme_label, _language_label


class Phase27Base(unittest.TestCase):
    """Temp-Config + gemeinsames (verstecktes) CTk-Root."""

    @classmethod
    def setUpClass(cls):
        ctk.set_appearance_mode("dark")
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg_path = os.path.join(self.tmp.name, "config.json")
        self._old_cfg_env = os.environ.get("CAPTI_CONFIG_FILE")
        os.environ["CAPTI_CONFIG_FILE"] = self.cfg_path
        i18n.set_language("de")

    def tearDown(self):
        if self._old_cfg_env is None:
            os.environ.pop("CAPTI_CONFIG_FILE", None)
        else:
            os.environ["CAPTI_CONFIG_FILE"] = self._old_cfg_env
        i18n.set_language("de")
        self.tmp.cleanup()

    def _controller(self):
        from ui.app_controller import AppController
        return AppController(self.root)

    def _settings_screen(self, theme=None, language=None):
        if theme is not None:
            set_config_value("theme", theme)
        if language is not None:
            set_config_value("language", language)
        controller = self._controller()
        screen = controller.get_screen("settings")
        self.root.update()
        return controller, screen


class TestSettingsSaveWithoutChange(Phase27Base):
    """Speichern ohne Änderung darf nichts zurücksetzen."""

    def test_no_change_preserves_values(self):  # alle 6 Kombinationen
        for theme in ("dark", "light", "yellow"):
            for language in ("de", "en"):
                with self.subTest(theme=theme, language=language):
                    _, screen = self._settings_screen(theme, language)
                    screen.save_settings()
                    cfg = load_config()
                    self.assertEqual(cfg["theme"], theme)
                    self.assertEqual(cfg["language"], language)

    def test_labels_are_never_raw_keys(self):
        """Sichtbare Werte enthalten keine rohen set.*-Keys."""
        for lang_ui in ("de", "en"):
            i18n.set_language(lang_ui)
            _, screen = self._settings_screen("yellow", "en")
            self.assertNotIn("set.", screen.theme_var.get())
            self.assertNotIn("set.", screen.language_var.get())
            for value in screen.theme_segmented.cget("values"):
                self.assertFalse(str(value).startswith("set."),
                                 f"Roh-Key sichtbar: {value}")
            for value in screen.language_combo.cget("values"):
                self.assertFalse(str(value).startswith("set."),
                                 f"Roh-Key sichtbar: {value}")

    def test_theme_change_persists(self):
        _, screen = self._settings_screen("dark", "de")
        screen.theme_var.set(_theme_label("yellow"))
        screen.save_settings()
        self.assertEqual(load_config()["theme"], "yellow")

    def test_language_change_persists(self):
        _, screen = self._settings_screen("dark", "de")
        screen.language_var.set(_language_label("en"))
        screen.save_settings()
        self.assertEqual(load_config()["language"], "en")

    def test_theme_and_language_changed_together(self):
        _, screen = self._settings_screen("dark", "de")
        screen.theme_var.set(_theme_label("light"))
        screen.language_var.set(_language_label("en"))
        screen.save_settings()
        cfg = load_config()
        self.assertEqual(cfg["theme"], "light")
        self.assertEqual(cfg["language"], "en")

    def test_yellow_survives_save_in_english_ui(self):
        i18n.set_language("en")
        _, screen = self._settings_screen("yellow", "en")
        screen.name_entry.insert(0, "Tester")  # einzige Änderung: Name
        screen.save_settings()
        cfg = load_config()
        self.assertEqual(cfg["theme"], "yellow")
        self.assertEqual(cfg["language"], "en")
        self.assertEqual(cfg["name"], "Tester")


class TestLiveLanguageSwitchKeepsCodes(Phase27Base):

    def test_labels_update_codes_stay(self):
        controller, screen = self._settings_screen("yellow", "de")
        # Live-Sprachwechsel über den Controller (baut Screens neu auf)
        controller.set_language("en")
        screen2 = controller.get_screen("settings")
        self.root.update()
        # Label entspricht der EN-Übersetzung, kein Roh-Key
        self.assertEqual(screen2.theme_var.get(),
                         i18n.TRANSLATIONS["en"]["set.theme.yellow"])
        self.assertEqual(screen2.language_var.get(),
                         i18n.TRANSLATIONS["en"]["set.lang.en"])
        self.assertNotIn("set.", screen2.theme_var.get())
        screen2.save_settings()
        cfg = load_config()
        self.assertEqual(cfg["theme"], "yellow")
        self.assertEqual(cfg["language"], "en")


class TestResultSaveAs(unittest.TestCase):
    """save_as(): Erfolg funktioniert weiter, Fehler wird sichtbar."""

    @classmethod
    def setUpClass(cls):
        ctk.set_appearance_mode("dark")
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg_path = os.path.join(self.tmp.name, "config.json")
        self._old = os.environ.get("CAPTI_CONFIG_FILE")
        os.environ["CAPTI_CONFIG_FILE"] = self.cfg_path

    def tearDown(self):
        if self._old is None:
            os.environ.pop("CAPTI_CONFIG_FILE", None)
        else:
            os.environ["CAPTI_CONFIG_FILE"] = self._old
        self.tmp.cleanup()

    def _screen_with_output(self):
        from ui.app_controller import AppController
        controller = AppController(self.root)
        screen = controller.get_screen("result")
        src = os.path.join(self.tmp.name, "out.mp4")
        with open(src, "w", encoding="utf-8") as f:
            f.write("x")
        screen.set_result(src)
        return screen, src

    def test_successful_save_clears_error(self):
        screen, src = self._screen_with_output()
        dest = os.path.join(self.tmp.name, "copy.mp4")
        with patch("ui.screens.result.filedialog.asksaveasfilename",
                   return_value=dest):
            screen.save_as()
        self.assertTrue(os.path.exists(dest))
        self.assertEqual(screen.error_label.cget("text"), "")

    def test_failed_save_shows_visible_error(self):
        i18n.set_language("de")
        screen, src = self._screen_with_output()
        # Ziel in nicht existierendes Verzeichnis -> shutil.copy2 schlägt fehl
        dest = os.path.join(self.tmp.name, "nope", "x.mp4")
        with patch("ui.screens.result.filedialog.asksaveasfilename",
                   return_value=dest):
            screen.save_as()
        text = screen.error_label.cget("text")
        prefix = i18n.TRANSLATIONS["de"]["res.save_failed"].split(":")[0]
        self.assertTrue(text.startswith(prefix),
                        f"Keine sichtbare Fehlermeldung: {text!r}")
        self.assertNotIn("res.save_failed", text)  # Key nie roh sichtbar


class TestStartupTempCleanup(unittest.TestCase):
    """Vorverarbeitungs-Cleanup: entfernt _temp-Reste, sonst nichts."""

    def test_cleanup_removes_temp_and_keeps_output(self):
        from ui.screens.processing import ProcessingScreen
        tmp = tempfile.TemporaryDirectory()
        try:
            base = Path(tmp.name)
            temp_dir = base / "_temp"
            temp_dir.mkdir()
            (temp_dir / "clip_audio.wav").write_text("x", encoding="utf-8")
            output = base / "clip_subtitled.mp4"
            output.write_text("video", encoding="utf-8")

            with patch.object(ProcessingScreen, "_temp_dir",
                              return_value=temp_dir):
                ProcessingScreen._cleanup_temp()

            self.assertFalse(temp_dir.exists())      # _temp entfernt
            self.assertTrue(output.exists())          # Output unberührt
            # Zweiter Aufruf ohne _temp: kein Fehler
            with patch.object(ProcessingScreen, "_temp_dir",
                              return_value=temp_dir):
                ProcessingScreen._cleanup_temp()
        finally:
            tmp.cleanup()


class TestCentralizedConfigReaders(Phase27Base):

    def test_home_and_new_project_use_central_config(self):
        import ui.screens.home as home_mod
        import ui.screens.new_project as np_mod
        save_config({"name": "Diraj", "model": "medium"})
        self.assertEqual(home_mod._load_user_name(), "Diraj")
        self.assertEqual(np_mod._load_default_model(), "medium")
        # Kaputte Config -> sichere Defaults, kein Crash
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            f.write("{broken")
        self.assertEqual(home_mod._load_user_name(), "")
        self.assertEqual(np_mod._load_default_model(), "small")


if __name__ == "__main__":
    unittest.main()



