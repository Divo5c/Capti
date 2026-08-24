"""
Tests für den Settings-Screen (Phase 8).

Die Config wird auf eine temporäre Datei umgeleitet (Monkeypatch von
_config_file), damit die echte Benutzer-Konfiguration nicht berührt wird.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Hermetisch: echte Nutzer-Config niemals lesen/schreiben
import tempfile as _tmp
if "CAPTI_CONFIG_FILE" not in os.environ:
    os.environ["APPDATA"] = _tmp.mkdtemp(prefix="capti_test_appdata_")


import customtkinter as ctk

from history import HistoryManager
from ui.app_controller import AppController
from ui import i18n
from ui.screens import settings as settings_mod
from ui.screens.settings import SettingsScreen, DEFAULTS


class TestSettingsScreen(unittest.TestCase):

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
        self.config_path = Path(self.tmp.name) / "config.json"
        # Alle Lese-/Schreibzugriffe auf Temp-Config umleiten
        self.patcher = patch.object(settings_mod, "_config_file",
                                    return_value=self.config_path)
        self.patcher.start()
        self.controller = AppController(self.root)
        self.screen = self.controller.get_screen("settings")

    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    def test_screen_builds(self):
        self.assertIsInstance(self.screen, SettingsScreen)
        for attr in ("name_entry", "theme_segmented", "language_combo",
                     "model_combo"):
            self.assertIsNotNone(getattr(self.screen, attr, None))

    def test_defaults_without_config(self):
        """Fehlende config.json -> sichere Defaults."""
        self.assertEqual(self.screen.name_entry.get(), "")
        self.assertEqual(self.screen.theme_var.get(), i18n.t("set.theme.dark"))
        self.assertEqual(self.screen.language_var.get(), i18n.t("set.lang.de"))
        self.assertEqual(self.screen.model_var.get(), "small")

    def test_load_existing_config(self):
        self.config_path.write_text(json.dumps(
            {"name": "Diraj", "theme": "yellow", "language": "en", "model": "base"}),
            encoding="utf-8")
        self.screen.load_settings()
        self.assertEqual(self.screen.name_entry.get(), "Diraj")
        self.assertEqual(self.screen.theme_var.get(), i18n.t("set.theme.yellow"))
        self.assertEqual(self.screen.language_var.get(), i18n.t("set.lang.en"))
        self.assertEqual(self.screen.model_var.get(), "base")

    def test_invalid_values_fall_back(self):
        """Ungültige Theme/Modell-Werte -> Defaults statt Crash."""
        self.config_path.write_text(json.dumps(
            {"theme": "bogus", "model": "ultra", "language": "xx"}),
            encoding="utf-8")
        self.screen.load_settings()
        self.assertEqual(self.screen.theme_var.get(), i18n.t("set.theme.dark"))
        self.assertEqual(self.screen.language_var.get(), i18n.t("set.lang.de"))
        self.assertEqual(self.screen.model_var.get(), "small")

    def test_broken_config_is_safe(self):
        """Kaputte config.json -> Defaults statt Crash."""
        self.config_path.write_text("{not valid json", encoding="utf-8")
        self.screen.load_settings()
        self.assertEqual(self.screen.name_entry.get(), "")

    def test_save_writes_config_and_preserves_keys(self):
        self.config_path.write_text(json.dumps({"custom_key": 42}), encoding="utf-8")
        self.screen.name_entry.delete(0, "end")
        self.screen.name_entry.insert(0, "Diraj")
        self.screen.theme_var.set("Yellow")  # übersetztes Label (wie in der UI)
        self.screen.language_var.set("English")
        self.screen.model_var.set("medium")
        self.screen.save_settings()

        saved = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["name"], "Diraj")
        self.assertEqual(saved["theme"], "yellow")
        self.assertEqual(saved["language"], "en")
        self.assertEqual(saved["model"], "medium")
        self.assertEqual(saved["custom_key"], 42)  # bestehende Keys bleiben erhalten
        # Phase 31: Auto-Save – keine Erfolgsmeldung mehr nötig

    def test_save_empty_name_is_ok(self):
        self.screen.name_entry.delete(0, "end")
        self.screen.save_settings()
        saved = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["name"], "")

    def test_clear_history(self):
        """Verlauf löschen entfernt alle Einträge und zeigt Erfolgsmeldung."""
        history_path = self.config_path.parent / "history.json"
        with patch("history._history_file", return_value=history_path):
            HistoryManager().add_entry("C:/videos/a.mp4", "C:/videos/out.mp4")
            self.screen._clear_history()
            self.assertEqual(HistoryManager().get_entries(), [])
        self.assertIn("gelöscht", self.screen.history_status_label.cget("text"))

    def test_reset_restores_saved_values(self):
        self.config_path.write_text(json.dumps({"name": "Alt"}), encoding="utf-8")
        self.screen.load_settings()
        self.screen.name_entry.delete(0, "end")
        self.screen.name_entry.insert(0, "Neu")
        self.screen.reset()
        self.assertEqual(self.screen.name_entry.get(), "Alt")


if __name__ == "__main__":
    unittest.main()