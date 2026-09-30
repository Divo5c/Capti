"""Fix-Block 3 (B1): ConfigManager.save_config muss merge-sicher sein.

Regression: save_config schrieb nur {"theme": ...} und loeschte dabei
name, model, caption_style sowie unbekannte Keys. Identisches Verhalten
wie TranslationManager.save_config wird erwartet.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main
from main import ConfigManager


def _point_config(testcase, tmp: Path) -> Path:
    """Lenkt main.CONFIG_FILE auf eine Temp-Datei um (wird restauriert)."""
    path = tmp / "config.json"
    old = main.CONFIG_FILE
    main.CONFIG_FILE = path
    testcase.addCleanup(setattr, main, "CONFIG_FILE", old)
    return path


def _read_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class TestConfigManagerMerge(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="capti_cfgmgr_"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        _point_config(self, self.tmp)

    def test_existing_keys_survive(self):
        path = main.CONFIG_FILE
        path.write_text(json.dumps({
            "name": "Diraj",
            "model": "medium",
            "caption_style": {"font_size": 80},
            "custom_key": "bleibt",
            "theme": "dark",
        }), encoding="utf-8")
        cm = ConfigManager()
        cm.current_theme = "light"
        cm.save_config()
        cfg = _read_json(path)
        self.assertEqual(cfg["theme"], "light")
        self.assertEqual(cfg["name"], "Diraj")
        self.assertEqual(cfg["model"], "medium")
        self.assertEqual(cfg["caption_style"], {"font_size": 80})
        self.assertEqual(cfg["custom_key"], "bleibt")

    def test_theme_updated(self):
        cm = ConfigManager()
        cm.current_theme = "dark"
        cm.save_config()
        self.assertEqual(_read_json(main.CONFIG_FILE)["theme"], "dark")
        cm.current_theme = "light"
        cm.save_config()
        self.assertEqual(_read_json(main.CONFIG_FILE)["theme"], "light")

    def test_missing_config_file(self):
        self.assertFalse(main.CONFIG_FILE.exists())
        cm = ConfigManager()
        cm.current_theme = "dark"
        cm.save_config()  # kein Crash, Datei wird angelegt
        self.assertTrue(main.CONFIG_FILE.exists())
        self.assertEqual(_read_json(main.CONFIG_FILE)["theme"], "dark")

    def test_corrupt_config_no_crash(self):
        main.CONFIG_FILE.write_text("{kaputt json,,,", encoding="utf-8")
        cm = ConfigManager()
        cm.current_theme = "light"
        cm.save_config()  # kein Crash
        cfg = _read_json(main.CONFIG_FILE)
        self.assertEqual(cfg["theme"], "light")

    def test_non_dict_config_no_crash(self):
        main.CONFIG_FILE.write_text("[1, 2, 3]", encoding="utf-8")
        cm = ConfigManager()
        cm.current_theme = "dark"
        cm.save_config()
        self.assertEqual(_read_json(main.CONFIG_FILE)["theme"], "dark")

    def test_roundtrip_load_save(self):
        cm = ConfigManager()
        cm.current_theme = "light"
        cm.save_config()
        cm2 = ConfigManager()
        cm2.load_config()
        self.assertEqual(cm2.current_theme, "light")


if __name__ == "__main__":
    unittest.main()
