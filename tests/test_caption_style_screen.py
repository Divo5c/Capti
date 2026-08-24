"""
Tests für den Caption-Style-Screen (Phase 11).

Die Config wird auf eine temporäre Datei umgeleitet.
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

from ui.app_controller import AppController
from ui.screens import caption_style as cs_mod
from ui.screens.caption_style import CaptionStyleScreen, DEFAULT_STYLE, PRESETS


class TestCaptionStyleScreen(unittest.TestCase):

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
        self.patcher = patch.object(cs_mod, "_config_file",
                                    return_value=self.config_path)
        self.patcher.start()
        self.controller = AppController(self.root)
        self.screen = self.controller.get_screen("caption_style")

    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    def test_screen_builds(self):
        self.assertIsInstance(self.screen, CaptionStyleScreen)
        for attr in ("_preview_card", "_color_vars", "pop_scale_slider",
                     "pop_decay_slider", "success_label"):
            self.assertIsNotNone(getattr(self.screen, attr, None))

    def test_defaults_loaded(self):
        """Ohne Config -> exakte Capti-Defaults."""
        self.assertEqual(self.screen.style["normal_color"], "#FFFFFF")
        self.assertEqual(self.screen.style["highlight_color"], "#FFFF00")
        self.assertEqual(self.screen.style["outline_color"], "#101010")
        self.assertEqual(self.screen.style["shadow_alpha"], 128)
        self.assertEqual(self.screen.style["font_name"], "Arial Black")
        self.assertEqual(self.screen.style["pop_scale"], 112)
        self.assertEqual(self.screen.style["pop_decay_ms"], 150)
        self.assertTrue(self.screen.style["pop_enabled"])

    def test_config_values_loaded(self):
        self.config_path.write_text(json.dumps(
            {"caption_style": {"highlight_color": "#FF3B30", "pop_scale": 120}}),
            encoding="utf-8")
        self.screen.load_style()
        self.assertEqual(self.screen.style["highlight_color"], "#FF3B30")
        self.assertEqual(self.screen.style["pop_scale"], 120)
        # Nicht gespeicherte Keys behalten Defaults
        self.assertEqual(self.screen.style["normal_color"], "#FFFFFF")

    def test_color_change_updates_style_and_preview(self):
        self.screen._color_vars["highlight_color"].set("#FF3B30")
        self.screen._on_color_change("highlight_color")
        self.assertEqual(self.screen.style["highlight_color"], "#FF3B30")
        # Phase 32: Vorschau ist ein Canvas – Highlight-Farbe muss in
        # den gezeichneten Text-Items sichtbar sein.
        fills = {self.screen.preview_canvas.itemcget(item, "fill")
                 for item in self.screen.preview_canvas.find_all()
                 if self.screen.preview_canvas.type(item) == "text"}
        # Rahmen während des ersten Worts: Highlight muss sichtbar sein
        slot = self.screen._preview_timeline[0]
        self.screen._draw_preview_frame(slot["start"] + 200)
        fills = {self.screen.preview_canvas.itemcget(item, "fill")
                 for item in self.screen.preview_canvas.find_all()
                 if self.screen.preview_canvas.type(item) == "text"}
        self.assertIn("#FF3B30", fills)

    def test_invalid_color_ignored(self):
        self.screen._color_vars["normal_color"].set("not-a-color")
        self.screen._on_color_change("normal_color")
        self.assertEqual(self.screen.style["normal_color"], "#FFFFFF")

    def test_pop_settings_saved(self):
        self.screen.pop_switch_var.set(False)
        self.screen.pop_scale_slider.set(125)
        self.screen.pop_decay_slider.set(200)
        self.screen.save_style()
        saved = json.loads(self.config_path.read_text(encoding="utf-8"))
        cs = saved["caption_style"]
        self.assertFalse(cs["pop_enabled"])
        self.assertEqual(cs["pop_scale"], 125)
        self.assertEqual(cs["pop_decay_ms"], 200)

    def test_presets(self):
        self.screen.apply_preset("Clean")
        self.assertFalse(self.screen.style["pop_enabled"])
        self.assertEqual(self.screen.style["highlight_color"], "#FFFFFF")
        self.screen.apply_preset("Strong")
        self.assertEqual(self.screen.style["pop_scale"], 125)
        self.screen.apply_preset("Capti Default")
        self.assertEqual(self.screen.style, {**DEFAULT_STYLE})  # exakt aktueller Look

    def test_save_preserves_other_config_keys(self):
        self.config_path.write_text(json.dumps({"theme": "yellow", "name": "Diraj"}),
                                    encoding="utf-8")
        self.screen.save_style()
        saved = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["theme"], "yellow")
        self.assertEqual(saved["name"], "Diraj")
        self.assertIn("caption_style", saved)

    def test_broken_config_is_safe(self):
        self.config_path.write_text("{broken", encoding="utf-8")
        self.screen.load_style()
        self.assertEqual(self.screen.style, {**DEFAULT_STYLE})

    def test_reset(self):
        self.screen.apply_preset("Strong")
        self.screen.reset()
        self.assertEqual(self.screen.style, {**DEFAULT_STYLE})
        self.assertEqual(self.screen.success_label.cget("text"), "")

    def test_back_navigation_to_home(self):
        self.controller.show_screen("caption_style")
        self.screen.navigate("home")
        self.assertEqual(self.controller.current_screen, "home")

    def test_all_themes_valid(self):
        """Screen baut mit allen drei Themes ohne Fehler."""
        for theme in ("dark", "light", "yellow"):
            controller = AppController(self.root, theme_name=theme)
            screen = controller.get_screen("caption_style")
            self.assertIsInstance(screen, CaptionStyleScreen)


if __name__ == "__main__":
    unittest.main()