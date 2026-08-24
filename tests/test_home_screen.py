"""
Tests für den professionellen Home-Screen (Phase 4).
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Hermetisch: echte Nutzer-Config niemals lesen/schreiben (Phase 30)
import tempfile as _tmp
if "CAPTI_CONFIG_FILE" not in os.environ:
    os.environ["APPDATA"] = _tmp.mkdtemp(prefix="capti_test_appdata_")

import customtkinter as ctk

from history import HistoryManager
from ui.app_controller import AppController
from ui import i18n
from ui.screens.home import HomeScreen, ATMOSPHERE_KEYS, _load_user_name


class TestHomeScreen(unittest.TestCase):

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
        # History auf temporäre Datei umleiten (echte Benutzer-History unberührt)
        self.tmp = tempfile.TemporaryDirectory()
        self.history_path = Path(self.tmp.name) / "history.json"
        self.history_patcher = patch("history._history_file",
                                     return_value=self.history_path)
        self.history_patcher.start()

    def tearDown(self):
        self.history_patcher.stop()
        self.tmp.cleanup()

    def test_home_builds(self):
        controller = AppController(self.root)
        home = controller.get_screen("home")
        self.assertIsInstance(home, HomeScreen)
        self.assertIsNotNone(getattr(home, "cta_card", None))

    def test_atmosphere_texts_exist(self):
        """Mindestens die geforderten Atmosphäre-Texte sind vorhanden."""
        for key in ("home.atmosphere.1", "home.atmosphere.3"):
            self.assertIn(key, ATMOSPHERE_KEYS)
        i18n.set_language("de")
        self.assertEqual(i18n.t("home.atmosphere.1"), "Heute ein Short oder ein Video?")
        self.assertEqual(i18n.t("home.atmosphere.3"), "Bereit für dein nächstes Projekt?")

    def test_user_name_fallback_safe(self):
        """_load_user_name gibt immer einen String zurück (auch ohne Config)."""
        name = _load_user_name()
        self.assertIsInstance(name, str)

    def test_empty_history_shows_placeholder(self):
        """Leere History -> Empty State mit Hinweistexten."""
        controller = AppController(self.root)
        home = controller.get_screen("home")
        texts = [w.cget("text") for w in home._history_frame.winfo_children()[0].winfo_children()]
        self.assertIn("Noch keine Videos verarbeitet.", texts)
        self.assertIn("Starte dein erstes Projekt.", texts)

    def test_real_history_entries_displayed(self):
        """Echte History-Einträge werden als Cards angezeigt."""
        HistoryManager().add_entry("C:/videos/Mein Video.mp4", "C:/videos/out.mp4",
                                   model="small", language="de")
        controller = AppController(self.root)
        home = controller.get_screen("home")
        cards = [c for c in home._history_frame.winfo_children()
                 if isinstance(c, ctk.CTkFrame)]
        self.assertEqual(len(cards), 1)
        labels = [w.cget("text") for w in cards[0].winfo_children()]
        self.assertIn("Mein Video.mp4", labels)

    def test_history_entry_click_opens_result(self):
        """Klick auf einen Eintrag öffnet Result mit Output + Metadaten."""
        HistoryManager().add_entry("C:/videos/clip.mp4", "C:/videos/out_clip.mp4",
                                   model="tiny", language="de")
        controller = AppController(self.root)
        home = controller.get_screen("home")
        entry = HistoryManager().get_entries()[0]
        home._open_history_entry(entry)
        self.assertEqual(controller.current_screen, "result")
        result = controller.get_screen("result")
        self.assertEqual(result.output_path, "C:/videos/out_clip.mp4")
        self.assertEqual(result.filename_label.cget("text"), "clip.mp4")

    def test_on_show_rebuilds_history(self):
        """on_show() aktualisiert die Verlaufsanzeige."""
        controller = AppController(self.root)
        home = controller.get_screen("home")
        self.assertTrue(home._history_frame.winfo_children())  # Empty State vorhanden
        HistoryManager().add_entry("C:/videos/neu.mp4", "C:/videos/out_neu.mp4")
        home.on_show()
        cards = [c for c in home._history_frame.winfo_children()
                 if isinstance(c, ctk.CTkFrame)]
        self.assertEqual(len(cards), 1)


if __name__ == "__main__":
    unittest.main()

