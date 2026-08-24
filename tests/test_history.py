"""
Tests für den HistoryManager (Phase 9).

Die History-Datei wird auf ein temporäres Verzeichnis umgeleitet.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from history import HistoryManager, MAX_ENTRIES


class TestHistoryManager(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.history_path = Path(self.tmp.name) / "history.json"
        self.patcher = patch("history._history_file", return_value=self.history_path)
        self.patcher.start()
        self.hm = HistoryManager()

    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    def _add(self, name="video.mp4", **kwargs):
        return self.hm.add_entry(f"C:/videos/{name}", f"C:/videos/out_{name}",
                                 **kwargs)

    def test_starts_empty_without_file(self):
        self.assertEqual(self.hm.get_entries(), [])

    def test_add_entry(self):
        entry = self._add(model="small", language="de")
        self.assertEqual(entry["model"], "small")
        self.assertEqual(entry["language"], "de")
        self.assertIn("timestamp", entry)
        self.assertIn("T", entry["timestamp"])  # ISO-Format

    def test_entries_persisted_and_reloaded(self):
        self._add()
        hm2 = HistoryManager()
        self.assertEqual(len(hm2.get_entries()), 1)
        self.assertEqual(hm2.get_entries()[0]["video_path"], "C:/videos/video.mp4")

    def test_newest_entry_first(self):
        self._add("a.mp4")
        self._add("b.mp4")
        entries = self.hm.get_entries()
        self.assertEqual(entries[0]["video_path"], "C:/videos/b.mp4")
        self.assertEqual(entries[1]["video_path"], "C:/videos/a.mp4")

    def test_max_entries(self):
        for i in range(MAX_ENTRIES + 5):
            self._add(f"v{i}.mp4")
        self.assertEqual(len(self.hm.get_entries()), MAX_ENTRIES)
        # Neuester bleibt erhalten
        self.assertIn("v14.mp4", self.hm.get_entries()[0]["video_path"])

    def test_broken_json_no_crash(self):
        self.history_path.write_text("{broken json", encoding="utf-8")
        self.assertEqual(self.hm.get_entries(), [])
        self._add()  # Schreiben funktioniert danach wieder
        self.assertEqual(len(self.hm.get_entries()), 1)

    def test_wrong_json_format_no_crash(self):
        self.history_path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
        self.assertEqual(self.hm.get_entries(), [])

    def test_invalid_entries_ignored(self):
        self.history_path.write_text(json.dumps(
            ["string entry", {"no": "fields"}, {"video_path": "ok.mp4"}]),
            encoding="utf-8")
        entries = self.hm.get_entries()
        self.assertEqual(len(entries), 1)  # nur der Dict-Eintrag
        self.assertEqual(entries[0]["video_path"], "ok.mp4")

    def test_missing_optional_fields_safe(self):
        entry = self.hm.add_entry("", "", model=None, language=None,
                                  duration="not-a-number", resolution="")
        self.assertEqual(entry["video_path"], "")
        self.assertNotIn("duration", entry)
        self.assertNotIn("resolution", entry)

    def test_clear(self):
        self._add()
        self.assertTrue(self.hm.clear())
        self.assertEqual(self.hm.get_entries(), [])

    def test_get_recent_limit(self):
        for i in range(6):
            self._add(f"v{i}.mp4")
        recent = self.hm.get_recent(3)
        self.assertEqual(len(recent), 3)
        self.assertIn("v5.mp4", recent[0]["video_path"])

    def test_remove_entry(self):
        self._add("a.mp4")
        self._add("b.mp4")
        self.assertTrue(self.hm.remove_entry(0))
        entries = self.hm.get_entries()
        self.assertEqual(len(entries), 1)
        self.assertIn("a.mp4", entries[0]["video_path"])
        self.assertFalse(self.hm.remove_entry(99))


if __name__ == "__main__":
    unittest.main()