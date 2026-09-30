"""Fix-Block 27: Undo/Redo im Caption-Editor (Tk-Integration).

- Text/Timing/Split/Merge -> Undo -> Redo
- mehrere Schritte, Verzweigung, Button-Zustände
- Preview/Transcript/Re-Export-Parität nach Restore
- Caption-Wechsel-Isolation, Load-/Projekt-Reset, Shortcuts.
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

VIDEO_A = "C:/vids/clipA.mp4"
VIDEO_B = "C:/vids/clipB.mp4"


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


class TestEditorUndoRedo(unittest.TestCase):

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
        self.controller.pending_project = {"video_path": VIDEO_A,
                                           "model": "tiny", "language": "de"}
        self.controller.last_transcript = {
            "video_path": VIDEO_A, "segments": _segments()}
        self.screen.on_show()

    def tearDown(self):
        i18n.set_language(self._prev_lang)
        self.patcher.stop()
        self.tmp.cleanup()
        import contextlib
        with contextlib.suppress(Exception):
            self.screen.destroy()

    # -- Helfer ----------------------------------------------------

    def _apply_text(self, text):
        self.screen._editor_entry.delete(0, "end")
        self.screen._editor_entry.insert(0, text)
        self.screen._on_editor_apply()

    def _select_word(self, idx):
        labels = list(self.screen._word_option.cget("values"))
        self.screen._word_option.set(labels[idx])
        self.screen._on_word_select(None)

    def _set_timing(self, start, end):
        self.screen._word_start_entry.delete(0, "end")
        self.screen._word_start_entry.insert(0, start)
        self.screen._word_end_entry.delete(0, "end")
        self.screen._word_end_entry.insert(0, end)
        self.screen._on_word_set()

    def _select_caption(self, idx):
        labels = list(self.screen._editor_option.cget("values"))
        self.screen._editor_option.set(labels[idx])
        self.screen._on_editor_select(None)

    def _btn_state(self, name):
        return str(getattr(self.screen, name).cget("state"))

    def _seg_text(self, idx=0):
        return self.screen._transcript_segments[idx]["text"]

    # -- Tests -----------------------------------------------------

    def test_text_undo_redo(self):
        self._apply_text("Hello beautiful world")
        self.assertEqual(self._seg_text(), "Hello beautiful world")
        self.assertEqual(self._btn_state("_undo_btn"), "normal")
        self.screen._on_undo()
        self.assertEqual(self._seg_text(), "Hello world")
        self.assertEqual(self.screen._preview_caption.text, "Hello world")
        self.assertEqual(
            self.controller.last_transcript["segments"][0]["text"],
            "Hello world")
        self.assertEqual(self._btn_state("_redo_btn"), "normal")
        self.screen._on_redo()
        self.assertEqual(self._seg_text(), "Hello beautiful world")
        self.assertEqual(self.screen._preview_caption.text,
                         "Hello beautiful world")

    def test_timing_undo(self):
        self._select_word(1)
        self._set_timing("6.0", "6.9")
        words = self.screen._transcript_segments[0]["words"]
        self.assertEqual((words[1]["start"], words[1]["end"]), (6.0, 6.9))
        self.screen._on_undo()
        words = self.screen._transcript_segments[0]["words"]
        self.assertEqual((words[1]["start"], words[1]["end"]), (5.9, 7.0))
        preview = {w.word: w
                   for w in self.screen._preview_caption.words}
        self.assertEqual((preview["world"].start, preview["world"].end),
                         (5.9, 7.0))

    def test_split_undo_redo(self):
        self._select_word(0)
        self.screen._on_word_split()
        self.assertEqual(
            [w["word"]
             for w in self.screen._transcript_segments[0]["words"]],
            ["He", "llo", "world"])
        self.screen._on_undo()
        self.assertEqual(
            [w["word"]
             for w in self.screen._transcript_segments[0]["words"]],
            ["Hello", "world"])
        self.screen._on_redo()
        self.assertEqual(
            [w["word"]
             for w in self.screen._transcript_segments[0]["words"]],
            ["He", "llo", "world"])

    def test_merge_undo(self):
        self._select_word(0)
        self.screen._on_word_merge()
        self.assertEqual(
            [w["word"]
             for w in self.screen._transcript_segments[0]["words"]],
            ["Hello world"])
        self.screen._on_undo()
        self.assertEqual(
            [w["word"]
             for w in self.screen._transcript_segments[0]["words"]],
            ["Hello", "world"])
        self.assertEqual(
            [w.word for w in self.screen._preview_caption.words],
            ["Hello", "world"])

    def test_multi_undo_redo(self):
        self._apply_text("Hello beautiful world")
        self._select_word(2)
        self._set_timing("6.0", "6.9")
        self.screen._on_undo()  # Timing zurück
        words = self.screen._transcript_segments[0]["words"]
        self.assertEqual(words[2]["word"], "world")
        self.assertEqual((words[2]["start"], words[2]["end"]), (5.9, 7.0))
        self.screen._on_undo()  # Text zurück
        self.assertEqual(self._seg_text(), "Hello world")
        self.assertEqual(self._btn_state("_undo_btn"), "disabled")
        self.screen._on_redo()
        self.screen._on_redo()
        words = self.screen._transcript_segments[0]["words"]
        self.assertEqual(words[0]["word"], "Hello")
        self.assertEqual((words[2]["start"], words[2]["end"]), (6.0, 6.9))

    def test_branch_discards_redo(self):
        self._apply_text("Version B")
        self.screen._on_undo()
        self.assertEqual(self._btn_state("_redo_btn"), "normal")
        self._apply_text("Version C")
        self.assertEqual(self._btn_state("_redo_btn"), "disabled")
        self.screen._on_redo()  # No-Op
        self.assertEqual(self._seg_text(), "Version C")
        self.screen._on_undo()
        self.assertEqual(self._seg_text(), "Hello world")

    def test_failed_op_creates_no_step(self):
        self._select_word(1)
        self.screen._on_word_merge()  # letztes Wort -> Ablehnung
        self.assertEqual(self._btn_state("_undo_btn"), "disabled")
        self.screen._on_undo()  # No-Op, kein Crash
        self.assertEqual(self._seg_text(), "Hello world")

    def test_reexport_uses_restored_state(self):
        import ui.screens.processing as proc_mod
        self._apply_text("Hello beautiful world")
        self.screen._on_undo()
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
                         "Hello world")

    def test_caption_switch_isolates(self):
        self._apply_text("Cap0 edited")
        self._select_caption(1)
        self._apply_text("Cap1 edited")
        # Undo wirkt nur auf Caption 1:
        self.screen._on_undo()
        self.assertEqual(self.screen._transcript_segments[1]["text"],
                         "Second caption here")
        self.assertEqual(self.screen._transcript_segments[0]["text"],
                         "Cap0 edited")
        # Zurück auf Caption 0: eigene History intakt:
        self._select_caption(0)
        self.screen._on_undo()
        self.assertEqual(self.screen._transcript_segments[0]["text"],
                         "Hello world")
        self.screen._on_redo()
        self.assertEqual(self.screen._transcript_segments[0]["text"],
                         "Cap0 edited")

    def test_load_resets_history(self):
        self._apply_text("Hello beautiful world")
        self.assertEqual(self._btn_state("_undo_btn"), "normal")
        self.controller.save_project_state(
            str(Path(self.tmp.name) / "x.capti.json"))
        self.controller.last_transcript = None
        self.controller.pending_project = None
        self.screen.clear_transcript()
        self.controller.load_project_state(
            str(Path(self.tmp.name) / "x.capti.json"))
        self.screen.on_show()
        # Geladen = neuer Ausgangspunkt: kein Undo, kein alter Redo-Zweig.
        self.assertEqual(self._btn_state("_undo_btn"), "disabled")
        self.assertEqual(self._btn_state("_redo_btn"), "disabled")
        self.screen._on_undo()  # No-Op
        self.assertEqual(self._seg_text(), "Hello beautiful world")
        # Neue Änderung danach: Undo bringt zum geladenen Stand zurück.
        self._apply_text("Neu")
        self.screen._on_undo()
        self.assertEqual(self._seg_text(), "Hello beautiful world")

    def test_project_switch_resets_history(self):
        self._apply_text("Hello beautiful world")
        self.controller.pending_project = {"video_path": VIDEO_B,
                                           "model": "tiny", "language": "de"}
        self.screen.on_show()
        self.assertEqual(self._btn_state("_undo_btn"), "disabled")
        self.controller.pending_project = {"video_path": VIDEO_A,
                                           "model": "tiny", "language": "de"}
        self.screen.on_show()
        self.screen._on_undo()  # kein alter Schritt überleben
        self.assertEqual(self._seg_text(), "Hello beautiful world")

    def test_shortcuts(self):
        # Fokus außerhalb -> Guard greift, keine Aktion:
        self.assertIsNone(self.screen._on_undo_key(None))
        self._apply_text("Hello beautiful world")
        # Fokus im Editor -> Ctrl+Z macht Undo:
        with patch.object(type(self.screen), "focus_get",
                          return_value=self.screen._editor_entry):
            self.assertEqual(self.screen._on_undo_key(None), "break")
        self.assertEqual(self._seg_text(), "Hello world")
        # Ctrl+Y macht Redo:
        with patch.object(type(self.screen), "focus_get",
                          return_value=self.screen._editor_entry):
            self.assertEqual(self.screen._on_redo_key(None), "break")
        self.assertEqual(self._seg_text(), "Hello beautiful world")
        # Fokus auf fremdem Widget -> Guard blockt:
        with patch.object(type(self.screen), "focus_get",
                          return_value=self.root):
            self.assertIsNone(self.screen._on_undo_key(None))
        self.assertEqual(self._seg_text(), "Hello beautiful world")
        # Bindings registriert:
        bound = self.root.bind("<Control-z>")
        self.assertTrue(bound)


if __name__ == "__main__":
    unittest.main()
