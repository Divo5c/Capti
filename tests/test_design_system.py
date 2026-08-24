"""
Tests für Theme- und Font-System (Phase 2 Design-System).
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui.theme import get_theme, is_valid_theme, AVAILABLE_THEMES, TOKEN_KEYS
from ui.fonts import FontManager, FONT_ROLES


class TestThemeSystem(unittest.TestCase):

    def test_all_themes_have_all_tokens(self):
        """Alle drei Themes definieren alle verpflichtenden Token-Keys."""
        for name in AVAILABLE_THEMES:
            theme = get_theme(name)
            for key in TOKEN_KEYS:
                self.assertIn(key, theme, f"{name} fehlt Token '{key}'")
                self.assertTrue(theme[key].startswith("#"), f"{name}/{key} keine Hex-Farbe")

    def test_dark_theme_values(self):
        """Dark-Theme behält bekannte Basiswerte."""
        t = get_theme("dark")
        self.assertEqual(t["background"], "#1a1a1a")
        self.assertEqual(t["accent"], "#ffd60a")

    def test_light_theme(self):
        t = get_theme("light")
        self.assertEqual(t["background"], "#fafafa")
        self.assertNotEqual(t["text"], t["background"])

    def test_yellow_theme(self):
        t = get_theme("yellow")
        self.assertEqual(t["accent"], "#ffd60a")
        self.assertIn("yellow", AVAILABLE_THEMES)

    def test_invalid_theme_falls_back_to_dark(self):
        t = get_theme("does_not_exist")
        self.assertEqual(t, get_theme("dark"))
        self.assertFalse(is_valid_theme("does_not_exist"))
        self.assertTrue(is_valid_theme("yellow"))

    def test_get_theme_returns_copy(self):
        """Manipulationen am Rückgabewert ändern das Original nicht."""
        t = get_theme("dark")
        t["accent"] = "#000000"
        self.assertEqual(get_theme("dark")["accent"], "#ffd60a")


class TestFontSystem(unittest.TestCase):

    def setUp(self):
        FontManager.reset()

    def tearDown(self):
        FontManager.reset()

    def test_font_files_exist(self):
        """Alle deklarierten Font-Dateien existieren unter assets/fonts/."""
        fonts_dir = Path(__file__).parent.parent / "assets" / "fonts"
        for role, info in FONT_ROLES.items():
            path = fonts_dir / info["file"]
            self.assertTrue(path.exists(), f"Fehlende Font-Datei: {path}")

    def test_initialize_registers_fonts(self):
        """Private Registrierung über AddFontResourceEx funktioniert (Windows)."""
        ok = FontManager.initialize()
        self.assertTrue(ok)
        for role, info in FONT_ROLES.items():
            family = FontManager.get_family(role)
            self.assertTrue(family)
            # Entweder Marken-Font oder dokumentierter Fallback
            self.assertIn(family, {info["family"], info["fallback"]})

    def test_all_roles_resolved(self):
        """Alle vier Rollen liefern nach Initialisierung einen Familiennamen."""
        FontManager.initialize()
        for role in ("display", "technical", "body", "signature"):
            self.assertIn(role, FontManager._loaded_families)

    def test_missing_assets_use_fallback(self):
        """Fehlender Asset-Ordner -> saubere Fallbacks statt Crash."""
        ok = FontManager.initialize(assets_dir=Path("Z:/nonexistent/fonts"))
        self.assertTrue(ok)  # Fallbacks zählen als funktional
        self.assertEqual(FontManager.get_family("display"), "Segoe UI")
        self.assertEqual(FontManager.get_family("technical"), "Consolas")


if __name__ == "__main__":
    unittest.main()