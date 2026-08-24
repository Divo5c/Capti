"""
Regressionstests Phase 24: zentrale Config-Verwaltung (config.py).
"""

import config as config_mod
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    load_config, save_config, get_config_value, set_config_value,
)


class ConfigTestBase(unittest.TestCase):

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

    def _write_raw(self, content: str):
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            f.write(content)


class TestLoadConfig(ConfigTestBase):

    def test_missing_file_returns_empty_dict(self):  # 1
        self.assertEqual(load_config(), {})

    def test_valid_json_loaded(self):  # 2
        self._write_raw(json.dumps({"name": "Diraj", "theme": "dark"}))
        cfg = load_config()
        self.assertEqual(cfg["name"], "Diraj")
        self.assertEqual(cfg["theme"], "dark")

    def test_broken_json_returns_empty_dict_no_crash(self):  # 3+16
        self._write_raw("{not valid json!!!")
        self.assertEqual(load_config(), {})
        self.assertEqual(get_config_value("theme", "dark"), "dark")

    def test_non_dict_json_returns_empty_dict(self):  # 4
        self._write_raw("[1, 2, 3]")
        self.assertEqual(load_config(), {})
        self._write_raw('"just a string"')
        self.assertEqual(load_config(), {})


class TestGetSetValues(ConfigTestBase):

    def test_get_single_value_with_default(self):  # 5
        self.assertIsNone(get_config_value("missing"))
        self.assertEqual(get_config_value("missing", "fallback"), "fallback")

    def test_set_single_value_creates_file(self):  # 6
        self.assertTrue(set_config_value("theme", "light"))
        self.assertEqual(load_config()["theme"], "light")

    def test_set_preserves_unknown_keys(self):  # 7
        set_config_value("custom_key", {"nested": [1, 2]})
        set_config_value("theme", "yellow")
        cfg = load_config()
        self.assertEqual(cfg["custom_key"], {"nested": [1, 2]})
        self.assertEqual(cfg["theme"], "yellow")


class TestMergeSafety(ConfigTestBase):
    """8-13: Kein Datenverlust bei Teil-Änderungen."""

    FULL_CONFIG = {
        "name": "Diraj",
        "theme": "dark",
        "language": "de",
        "model": "small",
        "caption_style": {"highlight_color": "#FFFF00", "pop_enabled": True},
        "custom_key": "keep-me",
    }

    def setUp(self):
        super().setUp()
        save_config(dict(self.FULL_CONFIG))

    def _assert_full_config_intact(self, **overrides):
        cfg = load_config()
        for key, value in {**self.FULL_CONFIG, **overrides}.items():
            self.assertEqual(cfg[key], value, f"Key verloren/geändert: {key}")

    def test_name_preserved_on_theme_change(self):  # 8+11
        set_config_value("theme", "light")
        self._assert_full_config_intact(theme="light")

    def test_model_preserved_on_language_change(self):  # 9+12
        set_config_value("language", "en")
        self._assert_full_config_intact(language="en")

    def test_caption_style_preserved(self):  # 10
        style = dict(self.FULL_CONFIG["caption_style"])
        style["pop_scale"] = 125
        set_config_value("caption_style", style)
        self._assert_full_config_intact(caption_style=style)
        self.assertEqual(load_config()["caption_style"]["pop_scale"], 125)

    def test_multiple_changes_in_sequence(self):  # 13
        set_config_value("name", "Alex")
        set_config_value("model", "tiny")
        set_config_value("language", "en")
        set_config_value("theme", "yellow")
        self._assert_full_config_intact(name="Alex", model="tiny",
                                        language="en", theme="yellow")

    def test_save_rejects_non_dict(self):
        self.assertFalse(save_config(["not", "a", "dict"]))
        self._assert_full_config_intact()


class TestThemesAndLanguages(ConfigTestBase):
    """14+15: Alle drei Themes und beide Sprachen round-trip."""

    def test_all_three_themes_roundtrip(self):
        for theme in ("dark", "light", "yellow"):
            set_config_value("theme", theme)
            self.assertEqual(get_config_value("theme"), theme)

    def test_de_and_en_roundtrip(self):
        for lang in ("de", "en"):
            set_config_value("language", lang)
            self.assertEqual(get_config_value("language"), lang)


class TestBrokenConfigRecovery(ConfigTestBase):
    """16: Kaputte Config -> sichere Defaults statt Crash."""

    def test_overwrite_after_broken_json(self):
        self._write_raw("{{{broken")
        # Lesen liefert Defaults ...
        self.assertEqual(get_config_value("theme", "dark"), "dark")
        # ... und Schreiben startet mit frischer Basis (keine Crash-Reste)
        self.assertTrue(set_config_value("theme", "light"))
        self.assertEqual(load_config(), {"theme": "light"})

    def test_screens_delegate_to_central_config(self):
        """Smoke: Screen-Wrapper delegieren an config.py (Single Source of Truth)."""
        import ui.screens.settings as settings_mod
        import ui.screens.caption_style as cs_mod
        from unittest.mock import patch
        for mod in (settings_mod, cs_mod):
            with patch.object(mod, "_config_file", return_value=self.cfg_path), \
                 patch.object(mod, "load_config", wraps=config_mod.load_config) as m:
                mod._read_config()
            self.assertTrue(m.called, f"{mod.__name__} nutzt nicht config.load_config")


if __name__ == "__main__":
    unittest.main()