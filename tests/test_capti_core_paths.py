"""
Tests für capti_core.paths: plattformunabhängige Datenverzeichnisse.

Garantien:
- Windows-Verhalten unverändert (APPDATA -> %APPDATA%/Capti,
  Fallback ~Capti wie bisher Path.home()/"Capti")
- CAPTI_DATA_DIR überschreibt alles (Tests/mobile Sandbox)
- Linux/macOS erhalten plattformkonforme Pfade
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capti_core.paths import user_data_dir


class PathsTestBase(unittest.TestCase):
    """Räumt relevante Umgebungsvariablen weg und stellt sie wieder her."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._saved = {k: os.environ.get(k)
                       for k in ("APPDATA", "CAPTI_DATA_DIR", "XDG_DATA_HOME",
                                 "CAPTI_CONFIG_FILE")}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def _clear_env(self):
        for k in ("APPDATA", "CAPTI_DATA_DIR", "XDG_DATA_HOME",
                  "CAPTI_CONFIG_FILE"):
            os.environ.pop(k, None)


class TestResolutionOrder(PathsTestBase):

    def test_capti_data_dir_wins_over_everything(self):  # 1
        self._clear_env()
        override = os.path.join(self.tmp.name, "sandbox")
        os.environ["CAPTI_DATA_DIR"] = override
        os.environ["APPDATA"] = os.path.join(self.tmp.name, "appdata")
        self.assertEqual(user_data_dir(), Path(override))

    def test_appdata_used_when_no_explicit_override(self):  # 2
        self._clear_env()
        appdata = os.path.join(self.tmp.name, "appdata")
        os.environ["APPDATA"] = appdata
        self.assertEqual(user_data_dir(), Path(appdata) / "Capti")

    def test_linux_xdg_data_home(self):  # 3
        self._clear_env()
        xdg = os.path.join(self.tmp.name, "xdg")
        os.environ["XDG_DATA_HOME"] = xdg
        with patch.object(sys, "platform", "linux"):
            self.assertEqual(user_data_dir(), Path(xdg) / "Capti")

    def test_linux_default_local_share(self):  # 4
        self._clear_env()
        with patch.object(sys, "platform", "linux"):
            expected = Path.home() / ".local" / "share" / "Capti"
            self.assertEqual(user_data_dir(), expected)

    def test_macos_application_support(self):  # 5
        self._clear_env()
        with patch.object(sys, "platform", "darwin"):
            expected = (Path.home() / "Library" / "Application Support" / "Capti")
            self.assertEqual(user_data_dir(), expected)

    def test_windows_without_appdata_falls_back_to_home(self):  # 6
        # Historisches Verhalten: Path.home()/"Capti"
        self._clear_env()
        with patch.object(sys, "platform", "win32"):
            self.assertEqual(user_data_dir(), Path.home() / "Capti")

    def test_does_not_create_directories(self):  # 7
        self._clear_env()
        override = Path(self.tmp.name) / "not_created"
        os.environ["CAPTI_DATA_DIR"] = str(override)
        self.assertFalse(override.exists())
        user_data_dir()
        self.assertFalse(override.exists())


class TestConfigHistoryIntegration(PathsTestBase):
    """config.py und history.py müssen über denselben Pfad laufen."""

    def test_config_file_uses_user_data_dir(self):  # 8
        self._clear_env()
        appdata = os.path.join(self.tmp.name, "appdata")
        os.environ["APPDATA"] = appdata
        import config as config_mod
        self.assertEqual(config_mod.config_file(),
                         Path(appdata) / "Capti" / "config.json")

    def test_history_file_uses_user_data_dir(self):  # 9
        self._clear_env()
        appdata = os.path.join(self.tmp.name, "appdata")
        os.environ["APPDATA"] = appdata
        import history as history_mod
        self.assertEqual(history_mod._history_file(),
                         Path(appdata) / "Capti" / "history.json")

    def test_capti_config_file_still_overrides(self):  # 10
        # Bestehender Test-Mechanismus bleibt erhalten
        self._clear_env()
        custom = Path(self.tmp.name) / "custom.json"
        os.environ["CAPTI_CONFIG_FILE"] = str(custom)
        os.environ["APPDATA"] = os.path.join(self.tmp.name, "appdata")
        import config as config_mod
        self.assertEqual(config_mod.config_file(), custom)


if __name__ == "__main__":
    unittest.main()
