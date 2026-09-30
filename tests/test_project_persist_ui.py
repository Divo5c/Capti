"""Fix-Block 24: Projekt-Persistenz im Controller + UI.

14. loaded state -> Preview
15. loaded state -> Editor
16. loaded state -> Re-Export override
17. edit -> save -> load -> re-export uses edited text
18. save after second edit stores second edit
+ Controller collect/save/load, Home-Open, Style-Save-Button.
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

from capti_core.project_state import load_project
from ui import i18n
from ui.app_controller import AppController
from ui.screens import caption_style as cs_mod

VIDEO_A = "C:/vids/clipA.mp4"


def _segments():
    return [
        {"start": 5.0, "end": 7.0, "text": "Hello world",
         "words": [{"word": "Hello", "start": 5.0, "end": 5.8},
                   {"word": "world", "start": 5.9, "end": 7.0}]},
        {"start": 8.0, "end": 10.0, "text": "Grüße aus München",
         "words": [{"word": "Grüße", "start": 8.0, "end": 8.6},
                   {"word": "aus", "start": 8.7, "end": 9.0},
                   {"word": "München", "start": 9.1, "end": 10.0}]},
    ]


class TestProjectPersistUI(unittest.TestCase):

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
        self.proj_path = str(Path(self.tmp.name) / "clipA.capti.json")

    def tearDown(self):
        i18n.set_language(self._prev_lang)
        self.patcher.stop()
        self.tmp.cleanup()
        import contextlib
        for name in ("caption_style",):
            with contextlib.suppress(Exception):
                screen = self.controller._screens.get(name)
                if screen is not None:
                    screen.destroy()

    def _seed_transcript(self, segments=None):
        self.controller.pending_project = {"video_path": VIDEO_A,
                                           "model": "tiny", "language": "de"}
        self.controller.last_transcript = {
            "video_path": VIDEO_A,
            "segments": segments if segments is not None else _segments(),
            "model": "tiny", "language": "de"}

    def _clear_session(self):
        self.controller.last_transcript = None
        self.controller.pending_project = None
        screen = self.controller.get_screen("caption_style")
        screen.clear_transcript()

    def test_collect_save_load_roundtrip(self):
        self._seed_transcript()
        saved = self.controller.save_project_state(self.proj_path)
        self.assertEqual(saved, self.proj_path)
        loaded = load_project(self.proj_path)
        self.assertEqual(loaded.video_path, VIDEO_A)
        self.assertEqual(loaded.segments, _segments())
        self.assertIn("pop_scale", loaded.caption_style)
        self.assertIsNotNone(self.controller.current_project_state)

    def test_loaded_state_drives_preview(self):
        """14) Load -> Transcript-Preview mit gespeicherten Wörtern."""
        self._seed_transcript()
        self.controller.save_project_state(self.proj_path)
        self._clear_session()
        self.controller.load_project_state(self.proj_path)
        screen = self.controller.get_screen("caption_style")
        screen.on_show()
        self.assertEqual(screen._preview_mode, "transcript")
        self.assertEqual([w.word for w in screen._preview_caption.words],
                         ["Hello", "world"])

    def test_loaded_state_drives_editor(self):
        """15) Load -> Editor zeigt gespeicherten Text + Timings."""
        self._seed_transcript()
        self.controller.save_project_state(self.proj_path)
        self._clear_session()
        self.controller.load_project_state(self.proj_path)
        screen = self.controller.get_screen("caption_style")
        screen.on_show()
        self.assertEqual(screen._editor_entry.get(), "Hello world")
        self.assertIn("5.00", screen._editor_time_label.cget("text"))

    def test_loaded_state_drives_reexport(self):
        """16) Load -> Override für Re-Export aus geladenem State."""
        import ui.screens.processing as proc_mod
        self._seed_transcript()
        self.controller.save_project_state(self.proj_path)
        self._clear_session()
        self.controller.load_project_state(self.proj_path)
        processing = self.controller.get_screen("processing")
        processing.video_path = VIDEO_A
        processing.model = "tiny"
        processing.language = "de"
        with patch.object(proc_mod, "CaptiPipeline") as mk_pipe, \
             patch.object(type(processing), "_cleanup_temp",
                          lambda self: None):
            processing._start_pipeline()
        _a, kwargs = mk_pipe.return_value.run_async.call_args
        self.assertEqual(kwargs["override_segments"], _segments())

    def test_edit_save_load_reexport(self):
        """17) Edit -> Save -> Load -> Re-Export nutzt Edit."""
        import ui.screens.processing as proc_mod
        self._seed_transcript()
        screen = self.controller.get_screen("caption_style")
        screen.on_show()
        screen._editor_entry.delete(0, "end")
        screen._editor_entry.insert(0, "Hello beautiful world")
        screen._on_editor_apply()
        self.controller.save_project_state(self.proj_path)
        self._clear_session()
        self.controller.load_project_state(self.proj_path)
        processing = self.controller.get_screen("processing")
        processing.video_path = VIDEO_A
        processing.model = "tiny"
        processing.language = "de"
        with patch.object(proc_mod, "CaptiPipeline") as mk_pipe, \
             patch.object(type(processing), "_cleanup_temp",
                          lambda self: None):
            processing._start_pipeline()
        _a, kwargs = mk_pipe.return_value.run_async.call_args
        self.assertEqual(kwargs["override_segments"][0]["text"],
                         "Hello beautiful world")

    def test_second_edit_wins(self):
        """18) EDIT 1 -> speichern, EDIT 2 -> speichern, LOAD -> EDIT 2."""
        self._seed_transcript()
        screen = self.controller.get_screen("caption_style")
        screen.on_show()
        screen._editor_entry.delete(0, "end")
        screen._editor_entry.insert(0, "EDIT 1")
        screen._on_editor_apply()
        self.controller.save_project_state(self.proj_path)
        screen._editor_entry.delete(0, "end")
        screen._editor_entry.insert(0, "EDIT 2")
        screen._on_editor_apply()
        self.controller.save_project_state(self.proj_path)
        self._clear_session()
        state = self.controller.load_project_state(self.proj_path)
        self.assertEqual(state.segments[0]["text"], "EDIT 2")

    def test_home_open_navigates(self):
        self._seed_transcript()
        self.controller.save_project_state(self.proj_path)
        self._clear_session()
        home = self.controller.get_screen("home")
        home.open_project_file(path=self.proj_path)
        self.assertEqual(self.controller.current_screen, "caption_style")
        self.assertEqual(
            self.controller.get_screen("caption_style")._preview_mode,
            "transcript")

    def test_home_open_invalid_shows_status(self):
        home = self.controller.get_screen("home")
        bad = str(Path(self.tmp.name) / "nonsense.json")
        Path(bad).write_text("{kaputt", encoding="utf-8")
        home.open_project_file(path=bad)
        self.assertTrue(home.open_status_label.cget("text"))
        self.assertIsNone(self.controller.last_transcript)

    def test_style_save_button(self):
        self._seed_transcript()
        screen = self.controller.get_screen("caption_style")
        screen.on_show()
        with patch.object(cs_mod.filedialog, "asksaveasfilename",
                          return_value=self.proj_path):
            screen.save_project_file()
        self.assertTrue(Path(self.proj_path).exists())
        self.assertIn("clipA.capti.json",
                      screen.success_label.cget("text"))


if __name__ == "__main__":
    unittest.main()
