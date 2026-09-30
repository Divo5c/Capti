"""Fix-Block 21: Editor-UI auf der Caption-Style-Seite (Tk).

J) Preview bekommt die bearbeitete Caption
- Apply aktualisiert Segment + Preview + Controller-Sync
- Sample-Modus: Editor deaktiviert
- Captions bleiben unabhängig voneinander
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tempfile as _tmp

if "CAPTI_CONFIG_FILE" not in os.environ:
    os.environ["APPDATA"] = _tmp.mkdtemp(prefix="capti_test_appdata_")

import customtkinter as ctk

from ui import i18n
from ui.app_controller import AppController
from ui.screens import caption_style as cs_mod


def _segments():
    return [
        {"start": 5.0, "end": 7.0, "text": "Hello world",
         "words": [{"word": "Hello", "start": 5.0, "end": 5.8},
                   {"word": "world", "start": 5.9, "end": 7.0}]},
        {"start": 8.0, "end": 10.0, "text": "Second caption here",
         "words": [{"word": "Second", "start": 8.0, "end": 8.5},
                   {"word": "caption", "start": 8.6, "end": 9.2},
                   {"word": "here", "start": 9.3, "end": 10.0}]},
    ]


class TestCaptionEditorUI(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        ctk.set_appearance_mode("dark")
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        import contextlib
        with contextlib.suppress(Exception):
            cls.root.destroy()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config_path = Path(self.tmp.name) / "config.json"
        self.patcher = patch.object(cs_mod, "_config_file",
                                    return_value=self.config_path)
        self.patcher.start()
        self._prev_lang = i18n.get_language()
        i18n.set_language("de")
        self.controller = AppController(self.root)
        self.screen = self.controller.get_screen("caption_style")
        self.controller.pending_project = {"video_path": "C:/vids/clip.mp4",
                                           "model": "tiny", "language": "de"}
        self.controller.last_transcript = {
            "video_path": "C:/vids/clip.mp4", "segments": _segments()}
        self.screen.on_show()

    def tearDown(self):
        i18n.set_language(self._prev_lang)
        self.patcher.stop()
        self.tmp.cleanup()
        import contextlib
        with contextlib.suppress(Exception):
            self.screen.destroy()

    def test_editor_active_in_transcript_mode(self):
        self.assertEqual(self.screen._preview_mode, "transcript")
        self.assertEqual(self.screen._editor_index, 0)
        self.assertEqual(self.screen._editor_entry.get(), "Hello world")
        self.assertIn("5.00", self.screen._editor_time_label.cget("text"))
        self.assertIn("7.00", self.screen._editor_time_label.cget("text"))

    def test_apply_updates_preview(self):
        """J) Preview bekommt die bearbeitete Caption."""
        self.screen._editor_entry.delete(0, "end")
        self.screen._editor_entry.insert(0, "Hello beautiful world")
        self.screen._on_editor_apply()
        # Segment aktualisiert (start/end unverändert, Timings übertragen)
        seg = self.screen._transcript_segments[0]
        self.assertEqual(seg["text"], "Hello beautiful world")
        self.assertEqual((seg["start"], seg["end"]), (5.0, 7.0))
        by_word = {w["word"]: w for w in seg["words"]}
        self.assertEqual(by_word["Hello"]["start"], 5.0)
        self.assertEqual(by_word["world"]["end"], 7.0)
        # Preview zeigt die geänderte Caption sofort
        self.assertEqual(self.screen._preview_caption.text,
                         "Hello beautiful world")
        self.assertEqual([w.word for w in self.screen._preview_caption.words],
                         ["Hello", "beautiful", "world"])
        # Controller-Kopie synchron (überlebt on_show-Vergleich)
        synced = self.controller.last_transcript["segments"][0]
        self.assertEqual(synced["text"], "Hello beautiful world")
        # Hinweismeldung gesetzt
        self.assertIn("1", self.screen._editor_hint.cget("text"))

    def test_captions_stay_independent(self):
        self.screen._editor_entry.delete(0, "end")
        self.screen._editor_entry.insert(0, "Hello beautiful world")
        self.screen._on_editor_apply()
        seg2 = self.screen._transcript_segments[1]
        self.assertEqual(seg2["text"], "Second caption here")
        self.assertEqual([w["word"] for w in seg2["words"]],
                         ["Second", "caption", "here"])
        # Zweite Caption anwählbar und unverändert im Editor
        self.screen._editor_option.set(
            self.screen._editor_option.cget("values")[1])
        self.screen._on_editor_select(None)
        self.assertEqual(self.screen._editor_index, 1)
        self.assertEqual(self.screen._editor_entry.get(),
                         "Second caption here")

    def test_sample_mode_disables_editor(self):
        self.controller.last_transcript = None
        self.controller.pending_project = {"video_path": "C:/vids/neu.mp4",
                                           "model": "tiny", "language": "de"}
        self.screen.on_show()
        self.assertEqual(self.screen._preview_mode, "sample")
        self.assertIsNone(self.screen._editor_index)
        self.assertEqual(
            str(self.screen._editor_apply.cget("state")), "disabled")
        self.assertTrue(self.screen._editor_hint.cget("text"))

    def test_empty_text_apply(self):
        self.screen._editor_entry.delete(0, "end")
        self.screen._editor_entry.insert(0, "   ")
        self.screen._on_editor_apply()
        seg = self.screen._transcript_segments[0]
        self.assertEqual(seg["words"], [])
        self.assertEqual((seg["start"], seg["end"]), (5.0, 7.0))


if __name__ == "__main__":
    unittest.main()
