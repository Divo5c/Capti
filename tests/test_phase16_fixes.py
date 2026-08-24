"""
Regressionstests Phase 16: Config-Merge (Legacy), Thread-Safety (Legacy),
Temp-Cleanup (neue UI).
"""

import json
import os
import queue
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestLegacyConfigMerge(unittest.TestCase):
    """Problem 1: TranslationManager.save_config darf keine Keys löschen."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config_file = Path(self.tmp.name) / "config.json"
        self._patcher = patch("main.CONFIG_FILE", self.config_file)
        self._patcher.start()

        import main
        self.tm = main.TranslationManager.__new__(main.TranslationManager)
        self.tm.translations = {"de": {}, "en": {}}
        self.tm.current_language = "en"

    def tearDown(self):
        self._patcher.stop()
        self.tmp.cleanup()

    def _write(self, data):
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def _read(self):
        with open(self.config_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_unknown_keys_preserved(self):
        self._write({"name": "Diraj", "model": "small",
                     "caption_style": {"pop_enabled": False},
                     "theme": "dark", "language": "de"})
        self.tm.save_config()
        cfg = self._read()
        self.assertEqual(cfg["name"], "Diraj")
        self.assertEqual(cfg["model"], "small")
        self.assertEqual(cfg["caption_style"], {"pop_enabled": False})
        self.assertEqual(cfg["language"], "en")  # aktualisiert

    def test_theme_language_updated(self):
        self._write({"theme": "dark", "language": "de"})
        self.tm.save_config()
        cfg = self._read()
        self.assertEqual(cfg["language"], "en")
        self.assertIn("theme", cfg)

    def test_broken_config_no_crash(self):
        with open(self.config_file, "w", encoding="utf-8") as f:
            f.write("{invalid json")
        self.tm.save_config()  # darf nicht crashen
        cfg = self._read()
        self.assertEqual(cfg["language"], "en")

    def test_missing_config_creates_defaults(self):
        if self.config_file.exists():
            self.config_file.unlink()
        self.tm.save_config()
        self.assertEqual(self._read()["language"], "en")


class TestLegacyThreadSafety(unittest.TestCase):
    """Problem 2: Legacy-Callbacks dürfen kein Tkinter aus dem Worker nutzen."""

    def _make_app(self):
        import main
        app = main.CaptiApp.__new__(main.CaptiApp)
        app._ui_queue = queue.Queue()
        return app

    def test_callbacks_only_enqueue_from_worker_thread(self):
        app = self._make_app()
        errors = []

        def worker():
            try:
                app._update_status("Status")
                app._update_progress(50)
                app._log("INFO", "Log")
            except Exception as e:  # kein Tkinter-Zugriff erlaubt
                errors.append(e)

        t = threading.Thread(target=worker)
        t.start()
        t.join(2)

        self.assertEqual(errors, [])
        kinds = [app._ui_queue.get_nowait()[0] for _ in range(3)]
        self.assertEqual(kinds, ["status", "progress", "log"])

    def test_poller_processes_events_in_main_thread(self):
        app = self._make_app()
        app.status_var = MagicMock()
        app.progress_var = MagicMock()
        app.log_text = MagicMock()
        done_calls, error_calls = [], []
        app._on_pipeline_done = lambda p: done_calls.append(p)
        app._processing_error = lambda e: error_calls.append(e)
        app.root = MagicMock()  # after() abfangen (Reschedule im Test egal)

        app._ui_queue.put(("status", "s"))
        app._ui_queue.put(("progress", 40))
        app._ui_queue.put(("log", ("INFO", "m")))
        app._ui_queue.put(("done", "out.mp4"))
        app._poll_ui_queue()

        app.status_var.set.assert_called_with("s")
        app.progress_var.set.assert_called_with(0.4)
        app.log_text.configure.assert_called()
        self.assertEqual(done_calls, ["out.mp4"])
        self.assertEqual(error_calls, [])


class TestNewUiTempCleanup(unittest.TestCase):
    """Problem 3: _temp wird bei Erfolg und Fehler bereinigt."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.temp_dir = Path(self.tmp.name) / "_temp"
        self.temp_dir.mkdir()
        (self.temp_dir / "x.wav").write_bytes(b"a")
        self.patcher = patch("ui.screens.processing.ProcessingScreen._temp_dir",
                             return_value=self.temp_dir)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    def test_cleanup_removes_temp(self):
        from ui.screens.processing import ProcessingScreen
        ProcessingScreen._cleanup_temp()
        self.assertFalse(self.temp_dir.exists())

    def test_cleanup_missing_temp_no_crash(self):
        from ui.screens.processing import ProcessingScreen
        import shutil
        shutil.rmtree(self.temp_dir)
        ProcessingScreen._cleanup_temp()  # kein Crash

    def test_cleanup_keeps_output_elsewhere(self):
        from ui.screens.processing import ProcessingScreen
        output = Path(self.tmp.name) / "out.mp4"
        output.write_bytes(b"v")
        ProcessingScreen._cleanup_temp()
        self.assertTrue(output.exists())  # Output unberührt


if __name__ == "__main__":
    unittest.main()