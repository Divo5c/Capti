"""Fix-Block 28: manuelle Wort-Ops in der Editor-UI + Integration.

- UI manual split / insert / delete
- genau ein Undo-Schritt pro Operation
- Undo/Redo, Verzweigung
- Preview-/Controller-Parität
- Caption-Wechsel, Save/Load, Re-Export.
"""

import copy
import os
import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tempfile as _tmp

if "CAPTI_CONFIG_FILE" not in os.environ:
    os.environ["APPDATA"] = _tmp.mkdtemp(prefix="capti_test_appdata_")

import customtkinter as ctk

from ui import i18n
from ui.app_controller import AppController
from ui.screens import caption_style as cs_mod
from ui.screens.caption_style import (
    _snap_candidates,
    _snap_time,
    _timeline_t,
    _timeline_x,
)

VIDEO_A = "C:/vids/clipA.mp4"


def _segments():
    return [
        {"start": 0.0, "end": 2.0, "text": "Hallo Welt",
         "words": [{"word": "Hallo", "start": 0.0, "end": 0.5},
                   {"word": "Welt", "start": 1.0, "end": 2.0}]},
        {"start": 5.0, "end": 7.0, "text": "Second here",
         "words": [{"word": "Second", "start": 5.0, "end": 5.8},
                   {"word": "here", "start": 5.9, "end": 7.0}]},
    ]


class TestWordOpsUI(unittest.TestCase):

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

    def _select_word(self, idx):
        labels = list(self.screen._word_option.cget("values"))
        self.screen._word_option.set(labels[idx])
        self.screen._on_word_select(None)

    def _words(self, idx=0):
        return [w["word"]
                for w in self.screen._transcript_segments[idx]["words"]]

    def _history(self, idx=0):
        return self.screen._undo_histories.get(idx)

    # -- Tests -----------------------------------------------------

    def test_ui_manual_split(self):
        self._select_word(0)
        self.screen._split_index_entry.delete(0, "end")
        self.screen._split_index_entry.insert(0, "2")
        self.screen._on_word_split_at()
        self.assertEqual(self._words(), ["Ha", "llo", "Welt"])
        preview = [w.word for w in self.screen._preview_caption.words]
        self.assertEqual(preview, ["Ha", "llo", "Welt"])

    def test_ui_split_invalid(self):
        before = copy.deepcopy(self.screen._transcript_segments[0])
        self._select_word(0)
        self.screen._split_index_entry.delete(0, "end")
        self.screen._split_index_entry.insert(0, "0")
        self.screen._on_word_split_at()
        self.assertTrue(self.screen._editor_hint.cget("text"))
        self.assertEqual(self.screen._transcript_segments[0], before)
        self.assertEqual(
            str(self.screen._undo_btn.cget("state")), "disabled")

    def test_ui_insert_before_after(self):
        self._select_word(1)
        self.screen._insert_word_entry.delete(0, "end")
        self.screen._insert_word_entry.insert(0, "schöne")
        self.screen._on_word_insert_before()
        self.assertEqual(self._words(), ["Hallo", "schöne", "Welt"])
        seg = self.screen._transcript_segments[0]["words"][1]
        self.assertEqual((seg["start"], seg["end"]), (0.5, 1.0))
        # Danach einfügen (hinter "schöne"):
        self._select_word(1)
        self.screen._insert_word_entry.delete(0, "end")
        self.screen._insert_word_entry.insert(0, "X")
        # Lücke belegt -> Ablehnung, kein Crash:
        self.screen._on_word_insert_after()
        self.assertTrue(self.screen._editor_hint.cget("text"))

    def test_ui_insert_invalid(self):
        before = copy.deepcopy(self.screen._transcript_segments[0])
        self._select_word(0)
        self.screen._insert_word_entry.delete(0, "end")
        self.screen._insert_word_entry.insert(0, "   ")
        self.screen._on_word_insert_after()
        self.assertTrue(self.screen._editor_hint.cget("text"))
        self.assertEqual(self.screen._transcript_segments[0], before)

    def test_ui_delete(self):
        self._select_word(1)
        self.screen._on_word_delete()
        self.assertEqual(self._words(), ["Hallo"])
        preview = [w.word for w in self.screen._preview_caption.words]
        self.assertEqual(preview, ["Hallo"])
        # Controller synchron:
        self.assertEqual(
            [w["word"] for w in
             self.controller.last_transcript["segments"][0]["words"]],
            ["Hallo"])

    def test_one_undo_step_per_op(self):
        self._select_word(0)
        self.screen._split_index_entry.delete(0, "end")
        self.screen._split_index_entry.insert(0, "2")
        self.screen._on_word_split_at()
        hist = self._history(0)
        self.assertEqual(hist.depth, 2)  # Basis + 1 Schritt
        self.screen._on_undo()
        self.assertEqual(self._words(), ["Hallo", "Welt"])
        # Insert nach Undo = genau ein Schritt (Redo-Zweig verworfen):
        self._select_word(1)
        self.screen._insert_word_entry.delete(0, "end")
        self.screen._insert_word_entry.insert(0, "schöne")
        self.screen._on_word_insert_before()
        self.assertEqual(hist.depth, 2)  # Basis + Insert (Split weg)
        self.assertEqual(
            str(self.screen._redo_btn.cget("state")), "disabled")
        self.screen._on_undo()
        self.assertEqual(self._words(), ["Hallo", "Welt"])

    def test_undo_redo_branch(self):
        self._select_word(1)
        self.screen._on_word_delete()
        self.screen._on_undo()
        self.assertEqual(self._words(), ["Hallo", "Welt"])
        self.screen._on_redo()
        self.assertEqual(self._words(), ["Hallo"])
        # Neue Änderung nach Undo verwirft Redo:
        self.screen._on_undo()
        self._select_word(0)
        self.screen._split_index_entry.delete(0, "end")
        self.screen._split_index_entry.insert(0, "2")
        self.screen._on_word_split_at()
        self.assertEqual(
            str(self.screen._redo_btn.cget("state")), "disabled")
        self.screen._on_redo()  # No-Op
        self.assertEqual(self._words(), ["Ha", "llo", "Welt"])

    def test_caption_switch_isolation(self):
        self._select_word(0)
        self.screen._split_index_entry.delete(0, "end")
        self.screen._split_index_entry.insert(0, "2")
        self.screen._on_word_split_at()
        labels = list(self.screen._editor_option.cget("values"))
        self.screen._editor_option.set(labels[1])
        self.screen._on_editor_select(None)
        self._select_word(0)
        self.screen._on_word_delete()
        self.assertEqual(self._words(1), ["here"])
        # Undo betrifft nur Caption 1:
        self.screen._on_undo()
        self.assertEqual(self._words(1), ["Second", "here"])
        self.assertEqual(self._words(0), ["Ha", "llo", "Welt"])

    def test_save_load_after_ops(self):
        self._select_word(0)
        self.screen._split_index_entry.delete(0, "end")
        self.screen._split_index_entry.insert(0, "2")
        self.screen._on_word_split_at()
        proj = str(Path(self.tmp.name) / "w.capti.json")
        self.controller.save_project_state(proj)
        self.controller.last_transcript = None
        self.controller.pending_project = None
        self.screen.clear_transcript()
        self.controller.load_project_state(proj)
        words = self.controller.last_transcript["segments"][0]["words"]
        self.assertEqual([w["word"] for w in words],
                         ["Ha", "llo", "Welt"])
        self.assertAlmostEqual(words[0]["start"], 0.0)
        self.assertAlmostEqual(words[1]["end"], 0.5)

    def test_reexport_uses_edited_words(self):
        import ui.screens.processing as proc_mod
        self._select_word(1)
        self.screen._on_word_delete()
        processing = self.controller.get_screen("processing")
        processing.video_path = VIDEO_A
        processing.model = "tiny"
        processing.language = "de"
        with patch.object(proc_mod, "CaptiPipeline") as mk_pipe, \
             patch.object(type(processing), "_cleanup_temp",
                          lambda self: None):
            processing._start_pipeline()
        _a, kwargs = mk_pipe.return_value.run_async.call_args
        self.assertEqual(
            [w["word"] for w in kwargs["override_segments"][0]["words"]],
            ["Hallo"])


class TestTimingEditor(unittest.TestCase):
    """Block 29: Timing-Editor (Start/Ende, i18n-Input, History, absolut)."""

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

    def _select_word(self, idx):
        labels = list(self.screen._word_option.cget("values"))
        self.screen._word_option.set(labels[idx])
        self.screen._on_word_select(None)

    def _select_caption(self, idx):
        labels = list(self.screen._editor_option.cget("values"))
        self.screen._editor_option.set(labels[idx])
        self.screen._on_editor_select(None)

    def _set_entries(self, start, end):
        self.screen._word_start_entry.delete(0, "end")
        self.screen._word_start_entry.insert(0, start)
        self.screen._word_end_entry.delete(0, "end")
        self.screen._word_end_entry.insert(0, end)
        self.screen._on_word_set()

    def _times(self, idx=0):
        return [(w["start"], w["end"]) for w in
                self.screen._transcript_segments[idx]["words"]]

    def _history(self, idx=0):
        return self.screen._undo_histories.get(idx)

    # -- Tests -----------------------------------------------------

    def test_start_only(self):
        """1) Nur Start ändern (Ende bleibt)."""
        self._select_word(1)
        self._set_entries("1.2", "2.0")
        self.assertEqual(self._times(), [(0.0, 0.5), (1.2, 2.0)])

    def test_end_only(self):
        """2) Nur Ende ändern (Start bleibt)."""
        self._select_word(0)
        self._set_entries("0.0", "0.4")
        self.assertEqual(self._times(), [(0.0, 0.4), (1.0, 2.0)])

    def test_comma_decimal(self):
        """5) Komma-Dezimalzahl wird übernommen."""
        self._select_word(1)
        self._set_entries("1,2", "2,0")
        self.assertEqual(self._times(), [(0.0, 0.5), (1.2, 2.0)])

    def test_neighbor_overlap_rejected(self):
        """10/11/12) Overlap -> Hinweis, Draft + History unberührt."""
        before = copy.deepcopy(self.screen._transcript_segments[0])
        self._select_word(0)
        self._set_entries("0.0", "1.5")  # überlappt "Welt" (1.0)
        self.assertTrue(self.screen._editor_hint.cget("text"))
        self.assertEqual(self.screen._transcript_segments[0], before)
        self.assertEqual(
            str(self.screen._undo_btn.cget("state")), "disabled")
        self._select_word(1)
        self._set_entries("0.4", "2.0")  # überlappt "Hallo" (Ende 0.5)
        self.assertEqual(self.screen._transcript_segments[0], before)

    def test_success_is_exactly_one_step(self):
        """13/14/15) Ein Step; Undo/Redo stellen exakt wieder her."""
        self._select_word(1)
        self._set_entries("1.2", "1.9")
        hist = self._history(0)
        self.assertEqual(hist.depth, 2)
        self.screen._on_undo()
        self.assertEqual(self._times(), [(0.0, 0.5), (1.0, 2.0)])
        self.screen._on_redo()
        self.assertEqual(self._times(), [(0.0, 0.5), (1.2, 1.9)])

    def test_branch_after_undo(self):
        """16) Neue Änderung nach Undo verwirft Redo."""
        self._select_word(1)
        self._set_entries("1.2", "1.9")
        self.screen._on_undo()
        self._select_word(1)  # Auswahl wird nach Undo zurückgesetzt
        self._set_entries("1.3", "1.8")
        self.assertEqual(
            str(self.screen._redo_btn.cget("state")), "disabled")
        self.assertEqual(self._times(), [(0.0, 0.5), (1.3, 1.8)])

    def test_absolute_timings_at_5s(self):
        """17) Caption ab 5.0 s bleibt absolut (kein 0-Relativieren)."""
        self._select_caption(1)
        self._select_word(1)
        self._set_entries("6.2", "6.8")
        seg = self.screen._transcript_segments[1]["words"][1]
        self.assertEqual((seg["start"], seg["end"]), (6.2, 6.8))
        preview = {w.word: w
                   for w in self.screen._preview_caption.words}
        self.assertEqual((preview["here"].start, preview["here"].end),
                         (6.2, 6.8))
        ctrl = self.controller.last_transcript["segments"][1]["words"][1]
        self.assertEqual((ctrl["start"], ctrl["end"]), (6.2, 6.8))

    def test_controller_updated(self):
        """19) Controller-State enthält neue Zeiten."""
        self._select_word(0)
        self._set_entries("0.1", "0.4")
        ctrl = self.controller.last_transcript["segments"][0]["words"][0]
        self.assertEqual((ctrl["start"], ctrl["end"]), (0.1, 0.4))

    def test_selection_kept(self):
        """20) Caption/Wort/Auswahl bleibt nach Apply erhalten."""
        self._select_caption(1)
        self._select_word(0)
        self._set_entries("5.0", "5.5")
        self.assertEqual(self.screen._editor_index, 1)
        self.assertEqual(self.screen._word_index, 0)
        self.assertEqual(self.screen._word_start_entry.get(), "5.000")
        self.assertEqual(self.screen._word_end_entry.get(), "5.500")
        self.assertIn("Second",
                      self.screen._word_option.get())


class TestTimelineMapping(unittest.TestCase):
    """Block 30: reine Zeit<->Pixel-Abbildung (Tk-frei)."""

    def test_endpoints(self):
        self.assertAlmostEqual(_timeline_x(5.0, 420, 5.0, 7.0), 10.0)
        self.assertAlmostEqual(_timeline_x(7.0, 420, 5.0, 7.0), 410.0)
        self.assertAlmostEqual(_timeline_x(6.0, 420, 5.0, 7.0), 210.0)

    def test_clamp(self):
        self.assertAlmostEqual(_timeline_x(4.0, 420, 5.0, 7.0), 10.0)
        self.assertAlmostEqual(_timeline_x(9.0, 420, 5.0, 7.0), 410.0)
        self.assertAlmostEqual(_timeline_t(-50, 420, 5.0, 7.0), 5.0)
        self.assertAlmostEqual(_timeline_t(999, 420, 5.0, 7.0), 7.0)

    def test_roundtrip(self):
        for t in (5.0, 5.4, 6.2, 7.0):
            self.assertAlmostEqual(
                _timeline_t(_timeline_x(t, 420, 5.0, 7.0), 420, 5.0, 7.0),
                t, places=9)

    def test_degenerate(self):
        self.assertAlmostEqual(_timeline_x(5.0, 420, 5.0, 5.0), 10.0)
        self.assertAlmostEqual(_timeline_t(200, 420, 5.0, 5.0), 5.0)
        self.assertAlmostEqual(_timeline_x(1.0, 10, 0.0, 2.0), 10.0)


class TestTimelineDrag(unittest.TestCase):
    """Block 30: Timing-Leiste (Auswahl, Drag, History, Sync)."""

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

    def _select_word(self, idx):
        labels = list(self.screen._word_option.cget("values"))
        self.screen._word_option.set(labels[idx])
        self.screen._on_word_select(None)

    def _select_caption(self, idx):
        labels = list(self.screen._editor_option.cget("values"))
        self.screen._editor_option.set(labels[idx])
        self.screen._on_editor_select(None)

    def _drag(self, from_x, to_x):
        screen = self.screen
        screen._on_timeline_press(SimpleNamespace(x=from_x))
        screen._on_timeline_move(SimpleNamespace(x=to_x))
        screen._on_timeline_release(SimpleNamespace(x=to_x))

    def _times(self, idx=0):
        return [(w["start"], w["end"]) for w in
                self.screen._transcript_segments[idx]["words"]]

    # -- Tests -----------------------------------------------------

    def test_bar_exists(self):
        self.assertIsInstance(self.screen._timeline, tk.Canvas)
        self.assertEqual(self.screen._timeline_w, 420)
        # Nach on_show ist Wort 0 gewählt -> Marker synchron:
        handles = self.screen._timeline_handles()
        self.assertIsNotNone(handles)
        self.assertAlmostEqual(handles[0], _timeline_x(0.0, 420, 0.0, 2.0))
        self.assertAlmostEqual(handles[1], _timeline_x(0.5, 420, 0.0, 2.0))
        self.assertTrue(self.screen._timeline.find_all())

    def test_selection_sync(self):
        self._select_word(1)  # "Welt" 1.0-2.0 auf Spanne 0.0-2.0
        handles = self.screen._timeline_handles()
        self.assertIsNotNone(handles)
        self.assertAlmostEqual(handles[0], _timeline_x(1.0, 420, 0.0, 2.0))
        self.assertAlmostEqual(handles[1], _timeline_x(2.0, 420, 0.0, 2.0))
        self._select_word(0)
        handles = self.screen._timeline_handles()
        self.assertAlmostEqual(handles[0], _timeline_x(0.0, 420, 0.0, 2.0))

    def test_valid_drag(self):
        self._select_word(1)
        x0, _x1 = self.screen._timeline_handles()
        self._drag(x0 + 2, _timeline_x(1.2, 420, 0.0, 2.0))
        self.assertEqual(self._times(), [(0.0, 0.5), (1.2, 2.0)])
        # Entries + Controller + Preview synchron:
        self.assertEqual(self.screen._word_start_entry.get(), "1.200")
        ctrl = self.controller.last_transcript["segments"][0]["words"][1]
        self.assertEqual((ctrl["start"], ctrl["end"]), (1.2, 2.0))
        preview = {w.word: w
                   for w in self.screen._preview_caption.words}
        self.assertEqual((preview["Welt"].start, preview["Welt"].end),
                         (1.2, 2.0))

    def test_invalid_drag_overlap(self):
        before = copy.deepcopy(self.screen._transcript_segments[0])
        self._select_word(1)
        x0, _x1 = self.screen._timeline_handles()
        self._drag(x0 + 2, _timeline_x(0.3, 420, 0.0, 2.0))  # in "Hallo"
        self.assertEqual(self.screen._transcript_segments[0], before)
        self.assertTrue(self.screen._editor_hint.cget("text"))
        self.assertEqual(
            str(self.screen._undo_btn.cget("state")), "disabled")

    def test_invalid_drag_cross(self):
        before = copy.deepcopy(self.screen._transcript_segments[0])
        self._select_word(1)
        x0, _x1 = self.screen._timeline_handles()
        self._drag(x0 + 2, _timeline_x(2.5, 420, 0.0, 2.0))  # hinter Ende
        self.assertEqual(self.screen._transcript_segments[0], before)
        self.assertTrue(self.screen._editor_hint.cget("text"))

    def test_press_miss_no_drag(self):
        before = copy.deepcopy(self.screen._transcript_segments[0])
        self._select_word(1)
        x0, x1 = self.screen._timeline_handles()
        self._drag((x0 + x1) / 2, (x0 + x1) / 2 + 20)  # kein Marker
        self.assertEqual(self.screen._transcript_segments[0], before)
        self.assertEqual(
            str(self.screen._undo_btn.cget("state")), "disabled")

    def test_multi_move_one_step(self):
        self._select_word(1)
        screen = self.screen
        x0, _x1 = screen._timeline_handles()
        screen._on_timeline_press(SimpleNamespace(x=x0 + 2))
        screen._on_timeline_move(
            SimpleNamespace(x=_timeline_x(1.1, 420, 0.0, 2.0)))
        screen._on_timeline_move(
            SimpleNamespace(x=_timeline_x(1.2, 420, 0.0, 2.0)))
        screen._on_timeline_release(SimpleNamespace(x=0))
        self.assertEqual(self._times(), [(0.0, 0.5), (1.2, 2.0)])
        hist = screen._undo_histories.get(0)
        self.assertEqual(hist.depth, 2)
        screen._on_undo()
        self.assertEqual(self._times(), [(0.0, 0.5), (1.0, 2.0)])
        screen._on_redo()
        self.assertEqual(self._times(), [(0.0, 0.5), (1.2, 2.0)])

    def test_undo_redo_drag(self):
        self._select_word(0)
        _ax0, ax1 = self.screen._timeline_handles()
        self._drag(ax1 - 2, _timeline_x(0.4, 420, 0.0, 2.0))
        self.assertEqual(self._times()[0], (0.0, 0.4))
        self.screen._on_undo()
        self.assertEqual(self._times()[0], (0.0, 0.5))
        self.screen._on_redo()
        self.assertEqual(self._times()[0], (0.0, 0.4))

    def test_caption_switch_redraws(self):
        self._select_caption(1)  # "Second here" 5.0-7.0 (absolut)
        handles = self.screen._timeline_handles()
        self.assertIsNotNone(handles)
        self.assertAlmostEqual(handles[0], _timeline_x(5.0, 420, 5.0, 7.0))
        self.assertAlmostEqual(handles[1], _timeline_x(5.8, 420, 5.0, 7.0))

    def test_ops_refresh_bar(self):
        self._select_word(0)
        self.screen._split_index_entry.delete(0, "end")
        self.screen._split_index_entry.insert(0, "2")
        self.screen._on_word_split_at()  # "Ha"+"llo"
        handles = self.screen._timeline_handles()
        self.assertAlmostEqual(handles[0], _timeline_x(0.0, 420, 0.0, 2.0))
        self._select_word(2)  # "Welt"
        self.screen._on_word_delete()
        self.assertEqual(
            [w["word"]
             for w in self.screen._transcript_segments[0]["words"]],
            ["Ha", "llo"])
        self.assertIsNotNone(self.screen._timeline_handles())

    def test_project_switch_clears(self):
        self._select_word(1)
        self.assertIsNotNone(self.screen._timeline_handles())
        self.controller.pending_project = {"video_path": "C:/vids/ANDERS.mp4",
                                           "model": "tiny", "language": "de"}
        self.screen.on_show()
        self.assertIsNone(self.screen._timeline_handles())
        self.assertEqual(self.screen._timeline.find_all(), ())


class TestNudgeButtons(unittest.TestCase):
    """Block 31: ±0,05s-Feinjustierung (ein Step pro Klick)."""

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

    def _select_word(self, idx):
        labels = list(self.screen._word_option.cget("values"))
        self.screen._word_option.set(labels[idx])
        self.screen._on_word_select(None)

    def _select_caption(self, idx):
        labels = list(self.screen._editor_option.cget("values"))
        self.screen._editor_option.set(labels[idx])
        self.screen._on_editor_select(None)

    def _times(self, idx=0):
        return [(w["start"], w["end"]) for w in
                self.screen._transcript_segments[idx]["words"]]

    # -- Tests -----------------------------------------------------

    def test_buttons_exist(self):
        screen = self.screen
        self.assertEqual(screen._start_minus_btn.cget("text"), "-0.05")
        self.assertEqual(screen._start_plus_btn.cget("text"), "+0.05")
        self.assertEqual(screen._end_minus_btn.cget("text"), "-0.05")
        self.assertEqual(screen._end_plus_btn.cget("text"), "+0.05")

    def test_start_minus_plus(self):
        self._select_word(1)
        self.screen._on_nudge("start", -0.05)
        self.assertAlmostEqual(self._times()[1][0], 0.95)
        self.assertEqual(self.screen._word_start_entry.get(), "0.950")
        self.screen._on_nudge("start", 0.05)
        self.assertAlmostEqual(self._times()[1][0], 1.0)

    def test_end_minus(self):
        self._select_word(1)
        self.screen._on_nudge("end", -0.05)
        self.assertAlmostEqual(self._times()[1][1], 1.95)

    def test_end_plus_beyond_caption_rejected(self):
        before = copy.deepcopy(self.screen._transcript_segments[0])
        self._select_word(1)
        self.screen._on_nudge("end", 0.05)
        self.assertEqual(self.screen._transcript_segments[0], before)
        self.assertTrue(self.screen._editor_hint.cget("text"))
        self.assertEqual(
            str(self.screen._undo_btn.cget("state")), "disabled")

    def test_start_before_zero_rejected(self):
        before = copy.deepcopy(self.screen._transcript_segments[0])
        self._select_word(0)
        self.screen._on_nudge("start", -0.05)
        self.assertEqual(self.screen._transcript_segments[0], before)
        self.assertTrue(self.screen._editor_hint.cget("text"))

    def test_overlap_walk_ends_at_touch(self):
        self._select_word(1)
        for _ in range(12):
            self.screen._on_nudge("start", -0.05)
        start = self.screen._transcript_segments[0]["words"][1]["start"]
        self.assertAlmostEqual(start, 0.5)
        self.assertTrue(self.screen._editor_hint.cget("text"))

    def test_one_step_per_click(self):
        self._select_word(1)
        self.screen._on_nudge("start", -0.05)
        self.screen._on_nudge("start", -0.05)
        hist = self.screen._undo_histories.get(0)
        self.assertEqual(hist.depth, 3)
        self.screen._on_undo()
        self.assertAlmostEqual(self._times()[1][0], 0.95)
        self.screen._on_undo()
        self.assertAlmostEqual(self._times()[1][0], 1.0)
        self.screen._on_redo()
        self.assertAlmostEqual(self._times()[1][0], 0.95)

    def test_branch_after_undo(self):
        self._select_word(1)
        self.screen._on_nudge("start", -0.05)
        self.screen._on_undo()
        self.screen._on_nudge("end", -0.05)
        self.assertEqual(
            str(self.screen._redo_btn.cget("state")), "disabled")
        self.assertAlmostEqual(self._times()[1][1], 1.95)

    def test_preview_and_timeline_updated(self):
        self._select_word(1)
        self.screen._on_nudge("start", -0.05)
        preview = {w.word: w
                   for w in self.screen._preview_caption.words}
        self.assertAlmostEqual(preview["Welt"].start, 0.95)
        handles = self.screen._timeline_handles()
        self.assertAlmostEqual(
            handles[0], _timeline_x(0.95, 420, 0.0, 2.0), places=6)
        ctrl = self.controller.last_transcript["segments"][0]["words"][1]
        self.assertAlmostEqual(ctrl["start"], 0.95)

    def test_selection_kept(self):
        self._select_word(1)
        self.screen._on_nudge("end", -0.05)
        self.assertEqual(self.screen._editor_index, 0)
        self.assertEqual(self.screen._word_index, 1)
        self.assertEqual(self.screen._word_end_entry.get(), "1.950")

    def test_absolute_timings_at_5s(self):
        self._select_caption(1)
        self._select_word(1)
        self.screen._on_nudge("end", -0.05)
        seg = self.screen._transcript_segments[1]["words"][1]
        self.assertAlmostEqual(seg["end"], 6.95)
        self.assertAlmostEqual(seg["start"], 5.9)
        preview = {w.word: w
                   for w in self.screen._preview_caption.words}
        self.assertAlmostEqual(preview["here"].end, 6.95)
        ctrl = self.controller.last_transcript["segments"][1]["words"][1]
        self.assertAlmostEqual(ctrl["end"], 6.95)


class TestKeyboardNudge(unittest.TestCase):
    """Block 32: Pfeiltasten-Nudge (Mapping, Guard, ein Pfad)."""

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

    def _select_word(self, idx):
        labels = list(self.screen._word_option.cget("values"))
        self.screen._word_option.set(labels[idx])
        self.screen._on_word_select(None)

    def _key(self, keysym, state=0, focus=None):
        if focus is None:
            focus = self.screen._timeline
        with patch.object(type(self.screen), "focus_get",
                          return_value=focus):
            return self.screen._on_nudge_key(
                SimpleNamespace(keysym=keysym, state=state))

    def _times(self, idx=0):
        return [(w["start"], w["end"]) for w in
                self.screen._transcript_segments[idx]["words"]]

    # -- Tests -----------------------------------------------------

    def test_left_right_start(self):
        self._select_word(1)
        self.assertEqual(self._key("Left"), "break")
        self.assertAlmostEqual(self._times()[1][0], 0.95)
        self.assertEqual(self._key("Right"), "break")
        self.assertAlmostEqual(self._times()[1][0], 1.0)

    def test_shift_left_right_end(self):
        self._select_word(1)
        self.assertEqual(self._key("Left", state=1), "break")
        self.assertAlmostEqual(self._times()[1][1], 1.95)
        self.assertEqual(self._key("Right", state=1), "break")
        self.assertAlmostEqual(self._times()[1][1], 2.0)

    def test_other_keys_ignored(self):
        before = copy.deepcopy(self.screen._transcript_segments[0])
        self._select_word(1)
        self.assertIsNone(self._key("Up"))
        self.assertIsNone(self._key("a"))
        self.assertIsNone(self._key("Left", state=4))  # Ctrl
        self.assertIsNone(self._key("Right", state=8))  # Alt
        self.assertEqual(self.screen._transcript_segments[0], before)

    def test_entry_focus_blocks(self):
        before = copy.deepcopy(self.screen._transcript_segments[0])
        self._select_word(1)
        for widget in (self.screen._editor_entry,
                       self.screen._word_start_entry,
                       self.screen._word_end_entry,
                       self.screen._word_option):
            self.assertIsNone(self._key("Left", focus=widget))
            self.assertIsNone(self._key("Right", state=1, focus=widget))
        self.assertEqual(self.screen._transcript_segments[0], before)

    def test_outside_focus_blocks(self):
        before = copy.deepcopy(self.screen._transcript_segments[0])
        self._select_word(1)
        self.assertIsNone(self._key("Left", focus=self.root))
        self.assertEqual(self.screen._transcript_segments[0], before)

    def test_invalid_key_no_step(self):
        self._select_word(0)
        self.assertEqual(
            self._key("Left", focus=self.screen._timeline), "break")
        self.assertTrue(self.screen._editor_hint.cget("text"))
        self.assertEqual(
            str(self.screen._undo_btn.cget("state")), "disabled")

    def test_one_step_per_keypress(self):
        self._select_word(1)
        self._key("Left")
        self._key("Left")
        hist = self.screen._undo_histories.get(0)
        self.assertEqual(hist.depth, 3)
        self.screen._on_undo()
        self.assertAlmostEqual(self._times()[1][0], 0.95)
        self.screen._on_redo()
        self.assertAlmostEqual(self._times()[1][0], 0.9)

    def test_branch_after_undo(self):
        self._select_word(1)
        self._key("Left")
        self.screen._on_undo()
        self._key("Left", state=1)
        self.assertEqual(
            str(self.screen._redo_btn.cget("state")), "disabled")
        self.assertAlmostEqual(self._times()[1][1], 1.95)

    def test_preview_timeline_selection_kept(self):
        self._select_word(1)
        self._key("Left")
        preview = {w.word: w
                   for w in self.screen._preview_caption.words}
        self.assertAlmostEqual(preview["Welt"].start, 0.95)
        handles = self.screen._timeline_handles()
        self.assertAlmostEqual(
            handles[0], _timeline_x(0.95, 420, 0.0, 2.0), places=6)
        self.assertEqual(self.screen._editor_index, 0)
        self.assertEqual(self.screen._word_index, 1)
        self.assertEqual(self.screen._word_start_entry.get(), "0.950")

    def test_absolute_timings_at_5s(self):
        labels = list(self.screen._editor_option.cget("values"))
        self.screen._editor_option.set(labels[1])
        self.screen._on_editor_select(None)
        words = list(self.screen._word_option.cget("values"))
        self.screen._word_option.set(words[1])
        self.screen._on_word_select(None)
        with patch.object(type(self.screen), "focus_get",
                          return_value=self.screen._timeline):
            self.screen._on_nudge_key(SimpleNamespace(keysym="Right",
                                                      state=0))
            self.screen._on_nudge_key(SimpleNamespace(keysym="Left",
                                                      state=1))
        seg = self.screen._transcript_segments[1]["words"][1]
        self.assertAlmostEqual(seg["start"], 5.95)
        self.assertAlmostEqual(seg["end"], 6.95)

    def test_bindings_registered_no_bind_all(self):
        self.assertTrue(self.root.bind("<Left>"))
        self.assertTrue(self.root.bind("<Right>"))
        with open(cs_mod.__file__, encoding="utf-8") as handle:
            self.assertNotIn(".bind_all(", handle.read())


class TestNudgeHint(unittest.TestCase):
    """Block 33: Shortcut-Hinweis + Single-Source-Schrittweite."""

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

    # -- Tests -----------------------------------------------------

    def test_hint_exists_de(self):
        text = self.screen._nudge_hint_label.cget("text")
        self.assertIn("Shift", text)
        self.assertIn("0,05", text)
        self.assertIn("Schritt", text)

    def test_hint_english(self):
        i18n.set_language("en")
        self.screen._refresh_nudge_hint()
        text = self.screen._nudge_hint_label.cget("text")
        self.assertIn("Step", text)
        self.assertIn("0.05", text)
        self.assertNotIn("0,05", text)

    def test_hint_matches_constant(self):
        from ui.screens import settings as settings_mod
        from ui.screens.caption_style import _format_nudge_step, get_nudge_step
        self.assertEqual(get_nudge_step(), settings_mod.NUDGE_STEP_DEFAULT)
        self.assertIn(_format_nudge_step(),
                      self.screen._nudge_hint_label.cget("text"))
        self.assertEqual(
            _format_nudge_step(),
            f"{settings_mod.NUDGE_STEP_DEFAULT:.2f}".replace(".", ","))

    def test_single_source_step(self):
        """Config-Wert: Buttons + Keyboard + Hint nutzen ihn."""
        from config import set_config_value
        from ui.screens import settings as settings_mod
        from ui.screens.caption_style import _format_nudge_step
        old_env = os.environ.get("CAPTI_CONFIG_FILE")
        os.environ["CAPTI_CONFIG_FILE"] = str(self.config_path)
        try:
            self.assertTrue(
                set_config_value(settings_mod.NUDGE_STEP_KEY, 0.10))
            self.assertEqual(_format_nudge_step(), "0,10")
            self.screen._refresh_nudge_hint()
            self.assertIn(
                "0,10", self.screen._nudge_hint_label.cget("text"))
            labels = list(self.screen._word_option.cget("values"))
            self.screen._word_option.set(labels[1])
            self.screen._on_word_select(None)
            before = self.screen._transcript_segments[0]["words"][1][
                "start"]
            self.screen._start_minus_btn.invoke()
            after = self.screen._transcript_segments[0]["words"][1][
                "start"]
            self.assertAlmostEqual(after, before - 0.10)
            with patch.object(type(self.screen), "focus_get",
                              return_value=self.screen._timeline):
                self.screen._on_nudge_key(
                    SimpleNamespace(keysym="Right", state=0))
            moved = self.screen._transcript_segments[0]["words"][1][
                "start"]
            self.assertAlmostEqual(moved, after + 0.10)
        finally:
            if old_env is None:
                os.environ.pop("CAPTI_CONFIG_FILE", None)
            else:
                os.environ["CAPTI_CONFIG_FILE"] = old_env

    def test_hint_hidden_without_transcript(self):
        self.controller.last_transcript = None
        self.controller.pending_project = None
        self.screen.on_show()
        self.assertEqual(
            self.screen._nudge_hint_label.grid_info(), {})

    def test_preset_change_live_no_history(self):
        """Preset-Klick: Editor nutzt Wert sofort, kein History-Step."""
        from ui.screens.caption_style import get_nudge_step
        old_env = os.environ.get("CAPTI_CONFIG_FILE")
        os.environ["CAPTI_CONFIG_FILE"] = str(self.config_path)
        try:
            labels = list(self.screen._word_option.cget("values"))
            self.screen._word_option.set(labels[1])
            self.screen._on_word_select(None)
            self.screen._on_nudge("start", -0.05)
            hist = self.screen._undo_histories.get(0)
            self.assertEqual(hist.depth, 2)
            settings_screen = self.controller.get_screen("settings")
            settings_screen._on_preset_selected(0.50)
            self.assertEqual(hist.depth, 2)  # kein Caption-Step
            self.assertEqual(get_nudge_step(), 0.50)
            self.screen._refresh_nudge_hint()
            self.assertIn(
                "0,50", self.screen._nudge_hint_label.cget("text"))
            # Gleicher Editor nutzt 0,50 sofort (1.45 < Ende 2.0):
            self.screen._start_plus_btn.invoke()
            self.assertAlmostEqual(
                self.screen._transcript_segments[0]["words"][1]["start"],
                1.45)
            self.screen._on_undo()
            self.assertAlmostEqual(
                self.screen._transcript_segments[0]["words"][1]["start"],
                0.95)
            self.screen._on_redo()
            self.assertAlmostEqual(
                self.screen._transcript_segments[0]["words"][1]["start"],
                1.45)
        finally:
            if old_env is None:
                os.environ.pop("CAPTI_CONFIG_FILE", None)
            else:
                os.environ["CAPTI_CONFIG_FILE"] = old_env

    def test_setting_change_no_history_step(self):
        """K.8: Settings-Änderung berührt Caption-History nicht."""
        from config import set_config_value
        from ui.screens import settings as settings_mod
        labels = list(self.screen._word_option.cget("values"))
        self.screen._word_option.set(labels[1])
        self.screen._on_word_select(None)
        self.screen._on_nudge("start", -0.05)
        hist = self.screen._undo_histories.get(0)
        self.assertEqual(hist.depth, 2)
        old_env = os.environ.get("CAPTI_CONFIG_FILE")
        os.environ["CAPTI_CONFIG_FILE"] = str(self.config_path)
        try:
            self.assertTrue(
                set_config_value(settings_mod.NUDGE_STEP_KEY, 0.10))
            self.assertEqual(hist.depth, 2)
            self.screen._on_undo()
            self.assertAlmostEqual(
                self.screen._transcript_segments[0]["words"][1]["start"],
                1.0)
        finally:
            if old_env is None:
                os.environ.pop("CAPTI_CONFIG_FILE", None)
            else:
                os.environ["CAPTI_CONFIG_FILE"] = old_env

    def test_hint_english_configured(self):
        """K.10: EN-Hint mit konfiguriertem Wert (Punkt-Format)."""
        from config import set_config_value
        from ui.screens import settings as settings_mod
        old_env = os.environ.get("CAPTI_CONFIG_FILE")
        os.environ["CAPTI_CONFIG_FILE"] = str(self.config_path)
        try:
            self.assertTrue(
                set_config_value(settings_mod.NUDGE_STEP_KEY, 0.10))
            i18n.set_language("en")
            self.screen._refresh_nudge_hint()
            text = self.screen._nudge_hint_label.cget("text")
            self.assertIn("0.10", text)
            self.assertNotIn("0,10", text)
        finally:
            if old_env is None:
                os.environ.pop("CAPTI_CONFIG_FILE", None)
            else:
                os.environ["CAPTI_CONFIG_FILE"] = old_env


class TestCaptionNudgeUI(unittest.TestCase):
    """Block 36: Caption-Grenzen-Nudge (Tk)."""

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

    def _select_caption(self, idx):
        labels = list(self.screen._editor_option.cget("values"))
        self.screen._editor_option.set(labels[idx])
        self.screen._on_editor_select(None)

    def _span(self, idx=0):
        seg = self.screen._transcript_segments[idx]
        return (seg["start"], seg["end"])

    def _history(self, idx=0):
        return self.screen._undo_histories.get(idx)

    # -- Tests -----------------------------------------------------

    def test_card_grid_no_overlap(self):
        """Editor-Card: keine zwei direkten Kinder teilen (row, col)."""
        seen = {}
        for child in self.screen._editor_card.winfo_children():
            info = child.grid_info()
            if not info:
                continue
            key = (int(info["row"]), int(info["column"]))
            self.assertNotIn(key, seen,
                             msg=f"Row-Kollision bei {key}: {seen.get(key)}")
            seen[key] = str(child)

    def test_buttons_exist_de_en(self):
        screen = self.screen
        self.assertEqual(screen._cap_start_minus_btn.cget("text"), "-0.05")
        self.assertEqual(screen._cap_end_plus_btn.cget("text"), "+0.05")
        labels = [w.cget("text") for w in
                  screen._editor_card.winfo_children()
                  if "Label" in type(w).__name__]
        self.assertTrue(any("Caption-Start" in t for t in labels))
        i18n.set_language("en")
        self.assertEqual(i18n.t("cs.caption_nudge_start"), "Caption start:")
        self.assertEqual(i18n.t("cs.caption_nudge_end"), "Caption end:")

    def test_end_plus_valid(self):
        self.screen._cap_end_plus_btn.invoke()
        self.assertAlmostEqual(self._span()[1], 2.05)
        self.assertIn("2.05", self.screen._editor_time_label.cget("text"))
        preview = self.screen._preview_caption
        self.assertAlmostEqual(preview.end, 2.05)
        ctrl = self.controller.last_transcript["segments"][0]
        self.assertAlmostEqual(ctrl["end"], 2.05)
        self.assertEqual(self._history(0).depth, 2)

    def test_start_plus_invalid(self):
        before = (self.screen._transcript_segments[0]["start"],
                  self.screen._transcript_segments[0]["end"])
        self.screen._cap_start_plus_btn.invoke()
        self.assertEqual(
            (self.screen._transcript_segments[0]["start"],
             self.screen._transcript_segments[0]["end"]), before)
        self.assertTrue(self.screen._editor_hint.cget("text"))
        self.assertIsNone(self._history(0))

    def test_start_minus_invalid_at_zero(self):
        self.screen._cap_start_minus_btn.invoke()
        self.assertEqual(self._span(), (0.0, 2.0))
        self.assertTrue(self.screen._editor_hint.cget("text"))

    def test_end_minus_invalid_over_word(self):
        self.screen._cap_end_minus_btn.invoke()
        self.assertEqual(self._span(), (0.0, 2.0))
        self.assertIsNone(self._history(0))

    def test_start_walk_after_delete(self):
        self._select_caption(0)
        first = next(iter(self.screen._word_option.cget("values")))
        self.screen._word_option.set(first)
        self.screen._on_word_select(None)
        self.screen._on_word_delete()
        for _ in range(20):
            self.screen._cap_start_plus_btn.invoke()
        self.assertAlmostEqual(self._span()[0], 1.0)
        self.screen._cap_start_plus_btn.invoke()
        self.assertAlmostEqual(self._span()[0], 1.0)

    def test_absolute_caption(self):
        self._select_caption(1)
        self.screen._cap_end_plus_btn.invoke()
        self.assertEqual(self._span(1), (5.0, 7.05))
        preview = self.screen._preview_caption
        self.assertAlmostEqual(preview.start, 5.0)
        self.assertAlmostEqual(preview.end, 7.05)
        ctrl = self.controller.last_transcript["segments"][1]
        self.assertEqual((ctrl["start"], ctrl["end"]), (5.0, 7.05))

    def test_undo_redo_branch(self):
        self.screen._cap_end_plus_btn.invoke()
        self.screen._cap_end_plus_btn.invoke()
        self.assertAlmostEqual(self._span()[1], 2.10)
        self.screen._on_undo()
        self.assertAlmostEqual(self._span()[1], 2.05)
        self.screen._on_redo()
        self.assertAlmostEqual(self._span()[1], 2.10)
        self.screen._on_undo()
        self.screen._on_undo()
        self.assertAlmostEqual(self._span()[1], 2.0)
        self.screen._cap_start_minus_btn.invoke()  # invalid: kein Step
        self.assertAlmostEqual(self._span()[1], 2.0)
        self.screen._on_redo()  # Redo-Zweig intakt (2.05), dann 2.10
        self.assertAlmostEqual(self._span()[1], 2.05)
        self.screen._on_redo()
        self.assertAlmostEqual(self._span()[1], 2.10)

    def test_caption_switch_isolates(self):
        self.screen._cap_end_plus_btn.invoke()
        self._select_caption(1)
        self.screen._on_undo()  # keine History für Caption 1
        self.assertEqual(self._span(1), (5.0, 7.0))
        self.assertAlmostEqual(self._span(0)[1], 2.05)
        self._select_caption(0)
        self.screen._on_undo()
        self.assertAlmostEqual(self._span(0)[1], 2.0)

    def test_project_switch_clears(self):
        self.screen._cap_end_plus_btn.invoke()
        self.controller.pending_project = {"video_path": "C:/vids/ANDERS.mp4",
                                           "model": "tiny", "language": "de"}
        self.screen.on_show()
        self.assertEqual(
            str(self.screen._undo_btn.cget("state")), "disabled")

    def test_preset_step_applies(self):
        from config import set_config_value
        from ui.screens import settings as settings_mod
        old_env = os.environ.get("CAPTI_CONFIG_FILE")
        os.environ["CAPTI_CONFIG_FILE"] = str(self.config_path)
        try:
            self.assertTrue(
                set_config_value(settings_mod.NUDGE_STEP_KEY, 0.10))
            self.screen._cap_end_plus_btn.invoke()
            self.assertAlmostEqual(self._span()[1], 2.10)
        finally:
            if old_env is None:
                os.environ.pop("CAPTI_CONFIG_FILE", None)
            else:
                os.environ["CAPTI_CONFIG_FILE"] = old_env

    def test_free_value_applies(self):
        from config import set_config_value
        from ui.screens import settings as settings_mod
        old_env = os.environ.get("CAPTI_CONFIG_FILE")
        os.environ["CAPTI_CONFIG_FILE"] = str(self.config_path)
        try:
            self.assertTrue(
                set_config_value(settings_mod.NUDGE_STEP_KEY, 0.15))
            self.screen._cap_end_plus_btn.invoke()
            self.assertAlmostEqual(self._span()[1], 2.15)
        finally:
            if old_env is None:
                os.environ.pop("CAPTI_CONFIG_FILE", None)
            else:
                os.environ["CAPTI_CONFIG_FILE"] = old_env


class TestCaptionTimelineDrag(unittest.TestCase):
    """Block 37: Caption-Grenzen-Drag (Handles, Vorschau, Commit, Sync)."""

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
            "video_path": VIDEO_A, "segments": _cap_segments()}
        self.screen.on_show()

    def tearDown(self):
        i18n.set_language(self._prev_lang)
        self.patcher.stop()
        self.tmp.cleanup()
        import contextlib
        with contextlib.suppress(Exception):
            self.screen.destroy()

    # -- Helfer ----------------------------------------------------

    def _select_caption(self, idx):
        labels = list(self.screen._editor_option.cget("values"))
        self.screen._editor_option.set(labels[idx])
        self.screen._on_editor_select(None)

    def _span(self, idx=0):
        seg = self.screen._transcript_segments[idx]
        return (seg["start"], seg["end"])

    def _history(self, idx=0):
        return self.screen._undo_histories.get(idx)

    def _cap_drag(self, which, to_t):
        """Caption-Drag simulieren: Press am Handle, Move, Release.

        Move-X wird aus der eingefrorenen Drag-Domain UNGEKLEMMT
        berechnet, damit auch Erweiterung über die alte Grenze hinaus
        testbar ist (echte Maus bleibt im Canvas).
        """
        screen = self.screen
        handles = screen._timeline_caption_handles()
        self.assertIsNotNone(handles)
        x0 = handles[0] if which == "start" else handles[1]
        screen._on_timeline_press(SimpleNamespace(x=x0))
        self.assertEqual(screen._timeline_drag["kind"], "caption")
        drag = screen._timeline_drag
        width = screen._timeline_w
        span = drag["map_end"] - drag["map_start"]
        move_x = 10 + (to_t - drag["map_start"]) / span * (width - 20)
        screen._on_timeline_move(SimpleNamespace(x=move_x))
        screen._on_timeline_release(SimpleNamespace(x=0))

    # -- Tests -----------------------------------------------------

    def test_press_left_handle(self):
        """J) Press linker Caption-Handle -> kind caption."""
        self._select_caption(0)
        x0, _x1 = self.screen._timeline_caption_handles()
        self.screen._on_timeline_press(SimpleNamespace(x=x0))
        drag = self.screen._timeline_drag
        self.assertEqual(drag["kind"], "caption")
        self.assertEqual(drag["which"], "start")
        self.screen._on_timeline_release(SimpleNamespace(x=0))

    def test_press_right_handle(self):
        """K) Press rechter Caption-Handle -> kind caption."""
        self._select_caption(0)
        _x0, x1 = self.screen._timeline_caption_handles()
        self.screen._on_timeline_press(SimpleNamespace(x=x1))
        drag = self.screen._timeline_drag
        self.assertEqual(drag["kind"], "caption")
        self.assertEqual(drag["which"], "end")
        self.screen._on_timeline_release(SimpleNamespace(x=0))

    def test_word_priority(self):
        """Wort-Handle gewinnt bei Überlappung (Word-Drag intakt)."""
        self._select_caption(1)  # Wörter berühren Caption-Bounds
        x0, _x1 = self.screen._timeline_caption_handles()
        word_labels = list(self.screen._word_option.cget("values"))
        self.screen._word_option.set(word_labels[0])
        self.screen._on_word_select(None)
        self.screen._on_timeline_press(SimpleNamespace(x=x0))
        self.assertEqual(self.screen._timeline_drag["kind"], "word")
        self.screen._on_timeline_release(SimpleNamespace(x=0))

    def test_move_only_temp(self):
        """L/M) Move: Vorschau ja, Model/History nein."""
        self._select_caption(0)
        x0, _x1 = self.screen._timeline_caption_handles()
        self.screen._on_timeline_press(SimpleNamespace(x=x0))
        self.screen._on_timeline_move(SimpleNamespace(x=x0 + 40))
        self.assertEqual(self._span(), (5.0, 8.0))
        self.assertIsNone(self._history(0))
        self.assertIn("5.", self.screen._editor_time_label.cget("text"))
        self.screen._on_timeline_release(SimpleNamespace(x=0))

    def test_valid_release_one_step(self):
        """N) Gültiger Release: genau ein Step, Segment synchron."""
        self._select_caption(0)
        before = self._span()
        self._cap_drag("start", 5.2)
        self.assertAlmostEqual(self._span()[0], 5.2)
        self.assertAlmostEqual(self._span()[1], before[1])
        self.assertEqual(self._history(0).depth, 2)
        ctrl = self.controller.last_transcript["segments"][0]
        self.assertAlmostEqual(ctrl["start"], 5.2)

    def test_invalid_release_no_step(self):
        """O) Invalid: Hinweis, unverändert, kein Step."""
        self._select_caption(0)
        before_seg = copy.deepcopy(self.screen._transcript_segments[0])
        self._cap_drag("start", 5.8)  # über erstes Wort (5.5) hinweg
        self.assertEqual(self.screen._transcript_segments[0], before_seg)
        self.assertTrue(self.screen._editor_hint.cget("text"))
        self.assertIsNone(self._history(0))

    def test_undo_redo(self):
        """P/Q) Undo/Redo stellt Grenzen exakt wieder her."""
        self._select_caption(0)
        self._cap_drag("end", 8.5)
        self.assertAlmostEqual(self._span()[1], 8.5)
        self.screen._on_undo()
        self.assertAlmostEqual(self._span(), (5.0, 8.0))
        self.screen._on_redo()
        self.assertAlmostEqual(self._span(), (5.0, 8.5))

    def test_redo_branch(self):
        """R) Neue Aktion nach Undo verwirft Redo."""
        self._select_caption(0)
        self._cap_drag("end", 8.5)
        self.screen._on_undo()
        self._cap_drag("end", 9.0)
        self.assertAlmostEqual(self._span()[1], 9.0)
        hist = self._history(0)
        self.assertFalse(hist.can_redo)
        self.screen._on_redo()  # No-Op
        self.assertAlmostEqual(self._span()[1], 9.0)

    def test_word_drag_still_works(self):
        """S) Wort-Drag nach Caption-Änderungen intakt."""
        self._select_caption(0)
        self._cap_drag("end", 8.5)
        self._drag_word_end(0, 6.3)
        words = self.screen._transcript_segments[0]["words"]
        self.assertAlmostEqual(words[0]["end"], 6.3)
        self.assertAlmostEqual(self._span(), (5.0, 8.5))

    def _drag_word_end(self, widx, to_t):
        screen = self.screen
        labels = list(screen._word_option.cget("values"))
        screen._word_option.set(labels[widx])
        screen._on_word_select(None)
        handles = screen._timeline_handles()
        width = screen._timeline_w
        cap = screen._timeline_caption()
        screen._on_timeline_press(SimpleNamespace(x=handles[1]))
        self.assertEqual(screen._timeline_drag["kind"], "word")
        screen._on_timeline_move(
            SimpleNamespace(x=_timeline_x(to_t, width, cap.start, cap.end)))
        screen._on_timeline_release(SimpleNamespace(x=0))

    def test_selection_kept(self):
        """T) Caption- und Wortauswahl bleiben erhalten."""
        self._select_caption(0)
        self.screen._word_option.set(
            list(self.screen._word_option.cget("values"))[1])
        self.screen._on_word_select(None)
        self._cap_drag("end", 8.5)
        self.assertEqual(self.screen._editor_index, 0)
        self.assertEqual(self.screen._word_index, 1)
        self.assertIn("zwei", self.screen._word_option.get())

    def test_absolute_times(self):
        """U) Absolute Zeiten (5.0-Basis, kein 0-Reset)."""
        self._select_caption(0)
        self._cap_drag("start", 5.2)
        self._cap_drag("end", 8.7)
        self.assertAlmostEqual(self._span(), (5.2, 8.7))
        preview = self.screen._preview_caption
        self.assertAlmostEqual((preview.start, preview.end), (5.2, 8.7))

    def test_press_miss(self):
        """Press daneben: kein Drag, Release ist No-Op."""
        self._select_caption(0)
        # x=300: weit weg von allen Handles (Wörter bei ~77/143/210/277).
        self.screen._on_timeline_press(SimpleNamespace(x=300))
        self.assertIsNone(self.screen._timeline_drag)
        self.screen._on_timeline_release(SimpleNamespace(x=300))
        self.assertEqual(self._span(), (5.0, 8.0))
        self.assertIsNone(self._history(0))


def _cap_segments():
    return [
        {"start": 5.0, "end": 8.0, "text": "eins zwei",
         "words": [{"word": "eins", "start": 5.5, "end": 6.0},
                   {"word": "zwei", "start": 6.5, "end": 7.0}]},
        {"start": 0.0, "end": 2.0, "text": "Hallo Welt",
         "words": [{"word": "Hallo", "start": 0.0, "end": 0.5},
                   {"word": "Welt", "start": 1.0, "end": 2.0}]},
    ]


class TestCaptionSnap(unittest.TestCase):
    """Block 38: magnetisches Snappen an Wortgrenzen (nur Vorschau)."""

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
            "video_path": VIDEO_A, "segments": _cap_segments()}
        self.screen.on_show()

    def tearDown(self):
        i18n.set_language(self._prev_lang)
        self.patcher.stop()
        self.tmp.cleanup()
        import contextlib
        with contextlib.suppress(Exception):
            self.screen.destroy()

    # -- Helfer ----------------------------------------------------

    def _select_caption(self, idx):
        labels = list(self.screen._editor_option.cget("values"))
        self.screen._editor_option.set(labels[idx])
        self.screen._on_editor_select(None)

    def _span(self, idx=0):
        seg = self.screen._transcript_segments[idx]
        return (seg["start"], seg["end"])

    def _history(self, idx=0):
        return self.screen._undo_histories.get(idx)

    def _snap_drag(self, which, to_t):
        """Caption-Drag mit ungeklemmter Zielzeit (wie _cap_drag)."""
        screen = self.screen
        handles = screen._timeline_caption_handles()
        self.assertIsNotNone(handles)
        x0 = handles[0] if which == "start" else handles[1]
        screen._on_timeline_press(SimpleNamespace(x=x0))
        self.assertEqual(screen._timeline_drag["kind"], "caption")
        drag = screen._timeline_drag
        width = screen._timeline_w
        span = drag["map_end"] - drag["map_start"]
        move_x = 10 + (to_t - drag["map_start"]) / span * (width - 20)
        screen._on_timeline_move(SimpleNamespace(x=move_x))
        screen._on_timeline_release(SimpleNamespace(x=0))

    # -- Tests -----------------------------------------------------

    def test_snap_helpers(self):
        """Snap-Mapping: Kandidaten, Toleranz, nächster, Gleichstand."""
        from ui.screens.settings import SNAP_TOLERANCE_DEFAULT
        self.assertEqual(SNAP_TOLERANCE_DEFAULT, 8.0)
        words = [{"word": "a", "start": 5.5, "end": 6.0},
                 {"word": "b", "start": "kaputt"},
                 {"word": "c", "start": float("nan"), "end": 1.0},
                 {"word": "d", "start": float("inf"), "end": 2.0},
                 {"word": "e", "start": 6.5, "end": 7.0}]
        self.assertEqual(_snap_candidates(words, "start"), [5.5, 6.5])
        self.assertEqual(_snap_candidates(words, "end"), [6.0, 1.0, 2.0, 7.0])
        self.assertEqual(_snap_candidates([], "start"), [])
        self.assertEqual(_snap_candidates(None, "end"), [])
        px = 400 / 3.0
        self.assertEqual(_snap_time(5.53, [5.5, 6.5], 8, px), 5.5)
        self.assertIsNone(_snap_time(6.0, [5.5, 6.5], 8, px))
        self.assertEqual(_snap_time(6.0, [5.5, 6.5], 100, px), 5.5)
        self.assertIsNone(_snap_time(5.5, [5.5], 8, 0))
        self.assertIsNone(_snap_time(5.5, [5.5], 8, -3))

    def test_start_snap(self):
        """Start springt auf Wort-Start (exakt, 1 Step)."""
        self._select_caption(0)
        self._snap_drag("start", 5.53)
        self.assertAlmostEqual(self._span()[0], 5.5)
        self.assertEqual(self._history(0).depth, 2)
        self.assertIn("5.50", self.screen._editor_time_label.cget("text"))

    def test_end_snap(self):
        """Ende springt auf Wort-Ende (exakt, 1 Step)."""
        self._select_caption(0)
        self._snap_drag("end", 6.97)
        self.assertAlmostEqual(self._span()[1], 7.0)
        self.assertEqual(self._history(0).depth, 2)

    def test_outside_tolerance_linear(self):
        """Außerhalb Toleranz: linearer Wert committet."""
        self._select_caption(0)
        self._snap_drag("start", 5.4)
        self.assertAlmostEqual(self._span()[0], 5.4)

    def test_move_no_commit(self):
        """Move allein: kein Model-, kein History-Wechsel."""
        self._select_caption(0)
        screen = self.screen
        handles = screen._timeline_caption_handles()
        screen._on_timeline_press(SimpleNamespace(x=handles[0]))
        screen._on_timeline_move(SimpleNamespace(x=handles[0] + 5))
        self.assertEqual(self._span(), (5.0, 8.0))
        self.assertIsNone(self._history(0))
        self.assertIn("5.", screen._editor_time_label.cget("text"))
        screen._on_timeline_release(SimpleNamespace(x=0))

    def test_snap_undo_redo(self):
        """Undo/Redo stellt gesnappte Grenzen exakt wieder her."""
        self._select_caption(0)
        self._snap_drag("end", 6.97)
        self.assertAlmostEqual(self._span()[1], 7.0)
        self.screen._on_undo()
        self.assertAlmostEqual(self._span(), (5.0, 8.0))
        self.screen._on_redo()
        self.assertAlmostEqual(self._span(), (5.0, 7.0))

    def test_snap_redo_branch(self):
        """Neuer Drag nach Undo verwirft Redo."""
        self._select_caption(0)
        self._snap_drag("end", 6.97)
        self.screen._on_undo()
        self._snap_drag("end", 8.5)
        self.assertAlmostEqual(self._span()[1], 8.5)
        self.assertFalse(self._history(0).can_redo)
        self.screen._on_redo()  # No-Op
        self.assertAlmostEqual(self._span()[1], 8.5)

    def test_out_of_span_candidate_ignored(self):
        """Wortgrenze außerhalb Spanne: kein Snap, saubere Ablehnung."""
        segments = _cap_segments()
        segments[0]["words"].append(
            {"word": "fern", "start": 9.0, "end": 9.5})
        self.screen.set_transcript(segments)
        self.screen.on_show()
        self._select_caption(0)
        screen = self.screen
        handles = screen._timeline_caption_handles()
        screen._on_timeline_press(SimpleNamespace(x=handles[0]))
        self.assertEqual(screen._timeline_drag["kind"], "caption")
        drag = screen._timeline_drag
        width = screen._timeline_w
        span = drag["map_end"] - drag["map_start"]
        move_x = 10 + (9.0 - drag["map_start"]) / span * (width - 20)
        screen._on_timeline_move(SimpleNamespace(x=move_x))
        screen._on_timeline_release(SimpleNamespace(x=0))
        self.assertEqual(self._span(), (5.0, 8.0))
        self.assertTrue(screen._editor_hint.cget("text"))
        self.assertIsNone(self._history(0))

    def test_wordless_caption_no_snap(self):
        """Caption ohne Wörter: linearer Commit ohne Snap."""
        self.screen.set_transcript(
            [{"start": 5.0, "end": 8.0, "text": "leer", "words": []}])
        self.screen.on_show()
        self._select_caption(0)
        self._snap_drag("start", 5.2)
        self.assertAlmostEqual(self._span()[0], 5.2)
        self.assertEqual(self._history(0).depth, 2)

    def test_selection_kept(self):
        """Auswahl bleibt nach Snap-Commit erhalten."""
        self._select_caption(0)
        self.screen._word_option.set(
            list(self.screen._word_option.cget("values"))[1])
        self.screen._on_word_select(None)
        self._snap_drag("end", 6.97)
        self.assertEqual(self.screen._editor_index, 0)
        self.assertEqual(self.screen._word_index, 1)

    def test_press_miss_and_empty_release(self):
        """Press daneben / Release ohne Move: No-Op, kein Step."""
        self._select_caption(0)
        screen = self.screen
        screen._on_timeline_press(SimpleNamespace(x=300))
        self.assertIsNone(screen._timeline_drag)
        screen._on_timeline_release(SimpleNamespace(x=300))
        self.assertEqual(self._span(), (5.0, 8.0))
        self.assertIsNone(self._history(0))
        # Press ohne Move: temp None -> Refresh, kein Step:
        x0, _x1 = screen._timeline_caption_handles()
        screen._on_timeline_press(SimpleNamespace(x=x0))
        self.assertEqual(screen._timeline_drag["kind"], "caption")
        screen._on_timeline_release(SimpleNamespace(x=x0))
        self.assertEqual(self._span(), (5.0, 8.0))
        self.assertIsNone(self._history(0))

    def test_word_drag_unaffected(self):
        """Wort-Drag funktioniert trotz Snap-Logik (Priorität)."""
        self._select_caption(1)  # Wörter berühren Caption-Bounds
        x0, _x1 = self.screen._timeline_caption_handles()
        self.screen._on_timeline_press(SimpleNamespace(x=x0))
        self.assertEqual(self.screen._timeline_drag["kind"], "word")
        self.screen._on_timeline_release(SimpleNamespace(x=0))
        self.assertIsNone(self._history(1))


class TestWordSnap(unittest.TestCase):
    """Block 39: Wort-Handles snappen an Nachbar-/Caption-Grenzen."""

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
            "video_path": VIDEO_A, "segments": _snap_segments()}
        self.screen.on_show()

    def tearDown(self):
        i18n.set_language(self._prev_lang)
        self.patcher.stop()
        self.tmp.cleanup()
        import contextlib
        with contextlib.suppress(Exception):
            self.screen.destroy()

    # -- Helfer ----------------------------------------------------

    def _select_caption(self, idx):
        labels = list(self.screen._editor_option.cget("values"))
        self.screen._editor_option.set(labels[idx])
        self.screen._on_editor_select(None)

    def _select_word(self, idx):
        labels = list(self.screen._word_option.cget("values"))
        self.screen._word_option.set(labels[idx])
        self.screen._on_word_select(None)

    def _times(self, idx=0):
        return [(w["start"], w["end"]) for w in
                self.screen._transcript_segments[idx]["words"]]

    def _history(self, idx=0):
        return self.screen._undo_histories.get(idx)

    def _move_to(self, to_t):
        screen = self.screen
        cap = screen._timeline_caption()
        width = screen._timeline_w
        move_x = 10 + (to_t - cap.start) / (cap.end - cap.start) * (width - 20)
        screen._on_timeline_move(SimpleNamespace(x=move_x))

    def _press_word_handle(self, widx, side):
        self._select_word(widx)
        x0, x1 = self.screen._timeline_handles()
        self.screen._on_timeline_press(
            SimpleNamespace(x=x0 if side == "start" else x1))
        self.assertEqual(self.screen._timeline_drag["kind"], "word")

    # -- Tests -----------------------------------------------------

    def test_raw_time(self):
        """Reine Hilfslogik: Dict/Objekt/invalid/nonfinite."""
        from ui.screens.caption_style import _raw_time

        class Obj:
            def __init__(self, start):
                self.start = start

        self.assertEqual(_raw_time({"start": 5.5}, "start"), 5.5)
        self.assertEqual(_raw_time(Obj(6.0), "start"), 6.0)
        self.assertIsNone(_raw_time({"start": "kaputt"}, "start"))
        self.assertIsNone(_raw_time({}, "start"))
        self.assertIsNone(_raw_time(None, "start"))
        self.assertIsNone(_raw_time({"start": float("nan")}, "start"))
        self.assertIsNone(_raw_time({"start": float("inf")}, "start"))
        self.assertIsNone(_raw_time({"start": -1.0}, "start"))

    def test_scales(self):
        """Verschiedene Skalierungen (px/s) verhalten sich gleich."""
        from ui.screens.caption_style import _snap_time
        self.assertEqual(_snap_time(5.03, [5.0], 8, 400 / 3.0), 5.0)
        self.assertEqual(_snap_time(5.03, [5.0], 8, 40.0), 5.0)
        self.assertIsNone(_snap_time(5.5, [5.0], 8, 40.0))
        self.assertIsNone(_snap_time(5.03, [5.0], 8, 0))
        self.assertIsNone(_snap_time(5.03, [], 8, 100.0))

    def test_start_snap_cap_start(self):
        """Erstes Wort: Start snappt auf Caption-Start (exakt)."""
        self._select_caption(0)
        self._press_word_handle(0, "start")
        self._move_to(5.03)
        self.assertEqual(self.screen._timeline_drag["snapped"]["time"], 5.0)
        self.screen._on_timeline_release(SimpleNamespace(x=0))
        self.assertAlmostEqual(self._times()[0], (5.0, 6.0))
        self.assertEqual(self._history(0).depth, 2)
        self.assertEqual(self.screen._word_start_entry.get(), "5.000")

    def test_start_snap_prev_end(self):
        """Mittleres Wort: Start snappt auf vorheriges Wort-Ende."""
        self._select_caption(0)
        self._press_word_handle(1, "start")
        self._move_to(6.03)
        self.assertEqual(self.screen._timeline_drag["snapped"]["time"], 6.0)
        self.screen._on_timeline_release(SimpleNamespace(x=0))
        self.assertAlmostEqual(self._times()[1], (6.0, 6.9))

    def test_end_snap_next_start(self):
        """Mittleres Wort: Ende snappt auf nächstes Wort-Start."""
        self._select_caption(0)
        self._press_word_handle(1, "end")
        self._move_to(7.17)
        self.assertEqual(self.screen._timeline_drag["snapped"]["time"], 7.2)
        self.screen._on_timeline_release(SimpleNamespace(x=0))
        self.assertAlmostEqual(self._times()[1], (6.3, 7.2))

    def test_end_snap_cap_end(self):
        """Letztes Wort: Ende snappt auf Caption-Ende."""
        self._select_caption(0)
        self._press_word_handle(2, "end")
        self._move_to(7.97)
        self.assertEqual(self.screen._timeline_drag["snapped"]["time"], 8.0)
        self.screen._on_timeline_release(SimpleNamespace(x=0))
        self.assertAlmostEqual(self._times()[2], (7.2, 8.0))

    def test_single_word(self):
        """Ein Wort: Start -> Caption-Start, Ende -> Caption-Ende."""
        self.controller.last_transcript = {
            "video_path": VIDEO_A,
            "segments": [{"start": 5.0, "end": 8.0, "text": "solo",
                          "words": [{"word": "solo", "start": 5.4,
                                     "end": 7.6}]}]}
        self.screen.on_show()
        self._select_caption(0)
        self._press_word_handle(0, "start")
        self._move_to(5.03)
        self.screen._on_timeline_release(SimpleNamespace(x=0))
        self.assertAlmostEqual(self._times()[0], (5.0, 7.6))
        self._press_word_handle(0, "end")
        self._move_to(7.97)
        self.screen._on_timeline_release(SimpleNamespace(x=0))
        self.assertAlmostEqual(self._times()[0], (5.0, 8.0))

    def test_outside_tolerance_linear(self):
        """Außerhalb Toleranz: linearer Wert committet."""
        self._select_caption(0)
        self._press_word_handle(1, "start")
        self._move_to(6.45)
        self.assertIsNone(self.screen._timeline_drag["snapped"])
        self.screen._on_timeline_release(SimpleNamespace(x=0))
        self.assertAlmostEqual(self._times()[1], (6.45, 6.9))

    def test_exact_point_snaps(self):
        """Cursor exakt auf Kandidat -> Snap."""
        self._select_caption(0)
        self._press_word_handle(1, "start")
        self._move_to(6.0)
        self.assertEqual(self.screen._timeline_drag["snapped"]["time"], 6.0)
        self.screen._on_timeline_release(SimpleNamespace(x=0))
        self.assertAlmostEqual(self._times()[1], (6.0, 6.9))

    def test_move_no_commit(self):
        """Move allein: kein Model-, kein History-Wechsel."""
        self._select_caption(0)
        screen = self.screen
        self._select_word(1)
        x0, _x1 = screen._timeline_handles()
        screen._on_timeline_press(SimpleNamespace(x=x0))
        screen._on_timeline_move(SimpleNamespace(x=x0 + 4))
        self.assertEqual(self._times()[1], (6.3, 6.9))
        self.assertIsNone(self._history(0))
        self.assertEqual(screen._timeline_drag["snapped"], None)
        screen._on_timeline_release(SimpleNamespace(x=0))

    def test_invalid_candidate_rejected(self):
        """Snap zu invalidem Timing -> Release lehnt ab."""
        self.controller.last_transcript = {
            "video_path": VIDEO_A,
            "segments": [{"start": 5.0, "end": 8.0, "text": "a b",
                          "words": [{"word": "a", "start": 5.0, "end": 5.2},
                                    {"word": "b", "start": 5.1,
                                     "end": 5.15}]}]}
        self.screen.on_show()
        self._select_caption(0)
        self._select_word(1)
        screen = self.screen
        x0, _x1 = screen._timeline_handles()
        screen._on_timeline_press(SimpleNamespace(x=x0))
        width = screen._timeline_w
        cap = screen._timeline_caption()
        move_x = 10 + (5.19 - cap.start) / (cap.end - cap.start) * (width - 20)
        screen._on_timeline_move(SimpleNamespace(x=move_x))
        self.assertEqual(screen._timeline_drag["snapped"]["time"], 5.2)
        screen._on_timeline_release(SimpleNamespace(x=0))
        self.assertEqual(self._times(), [(5.0, 5.2), (5.1, 5.15)])
        self.assertTrue(screen._editor_hint.cget("text"))
        self.assertIsNone(self._history(0))

    def test_empty_words_no_word_drag(self):
        """Leere Wortliste: kein Word-Drag möglich."""
        self.controller.last_transcript = {
            "video_path": VIDEO_A,
            "segments": [{"start": 5.0, "end": 8.0, "text": "leer",
                          "words": []}]}
        self.screen.on_show()
        self._select_caption(0)
        screen = self.screen
        self.assertIsNone(screen._timeline_handles())
        screen._on_timeline_press(SimpleNamespace(x=200))
        self.assertIsNone(screen._timeline_drag)

    def test_word_priority_kept(self):
        """Überlappende Handles: Wort gewinnt (intakt)."""
        self._select_caption(1)
        screen = self.screen
        x0, _x1 = screen._timeline_caption_handles()
        screen._word_option.set(
            next(iter(screen._word_option.cget("values"))))
        screen._on_word_select(None)
        screen._on_timeline_press(SimpleNamespace(x=x0))
        self.assertEqual(screen._timeline_drag["kind"], "word")
        screen._on_timeline_release(SimpleNamespace(x=0))
        self.assertIsNone(self._history(1))

    def test_snap_undo_redo_branch(self):
        """Undo/Redo/Branch nach Snap-Drag."""
        self._select_caption(0)
        self._press_word_handle(0, "start")
        self._move_to(5.03)
        self.screen._on_timeline_release(SimpleNamespace(x=0))
        self.assertAlmostEqual(self._times()[0], (5.0, 6.0))
        self.screen._on_undo()
        self.assertAlmostEqual(self._times()[0], (5.4, 6.0))
        self.screen._on_redo()
        self.assertAlmostEqual(self._times()[0], (5.0, 6.0))
        self.screen._on_undo()
        self._press_word_handle(0, "start")
        self._move_to(5.1)
        self.screen._on_timeline_release(SimpleNamespace(x=0))
        self.assertAlmostEqual(self._times()[0], (5.1, 6.0))
        self.assertFalse(self._history(0).can_redo)

    def test_selection_kept(self):
        """Caption-/Wortauswahl bleibt nach Snap-Commit erhalten."""
        self._select_caption(0)
        self._select_word(2)
        self._press_word_handle(2, "end")
        self._move_to(7.97)
        self.screen._on_timeline_release(SimpleNamespace(x=0))
        self.assertEqual(self.screen._editor_index, 0)
        self.assertEqual(self.screen._word_index, 2)
        self.assertAlmostEqual(self._times()[2], (7.2, 8.0))


def _snap_segments():
    return [
        {"start": 5.0, "end": 8.0, "text": "eins zwei drei",
         "words": [{"word": "eins", "start": 5.4, "end": 6.0},
                   {"word": "zwei", "start": 6.3, "end": 6.9},
                   {"word": "drei", "start": 7.2, "end": 7.8}]},
        {"start": 0.0, "end": 2.0, "text": "Hallo Welt",
         "words": [{"word": "Hallo", "start": 0.0, "end": 0.5},
                   {"word": "Welt", "start": 1.0, "end": 2.0}]},
    ]


class TestTimelineSnapIndicator(unittest.TestCase):
    """Block 40: visueller Snap-Indikator (Marker + Handle-Highlight)."""

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
            "video_path": VIDEO_A, "segments": _snap_segments()}
        self.screen.on_show()

    def tearDown(self):
        i18n.set_language(self._prev_lang)
        self.patcher.stop()
        self.tmp.cleanup()
        import contextlib
        with contextlib.suppress(Exception):
            self.screen.destroy()

    # -- Helfer ----------------------------------------------------

    def _select_caption(self, idx):
        labels = list(self.screen._editor_option.cget("values"))
        self.screen._editor_option.set(labels[idx])
        self.screen._on_editor_select(None)

    def _select_word(self, idx):
        labels = list(self.screen._word_option.cget("values"))
        self.screen._word_option.set(labels[idx])
        self.screen._on_word_select(None)

    def _snap_ids(self):
        return self.screen._timeline.find_withtag("snap")

    def _move_to(self, to_t):
        screen = self.screen
        cap = screen._timeline_caption()
        width = screen._timeline_w
        return 10 + (to_t - cap.start) / (cap.end - cap.start) * (width - 20)

    # -- Tests -----------------------------------------------------

    def test_no_snap_no_marker(self):
        """Ohne Snap: kein Marker, kein Highlight, State None."""
        self._select_caption(0)
        self._select_word(1)
        screen = self.screen
        x0, _x1 = screen._timeline_handles()
        screen._on_timeline_press(SimpleNamespace(x=x0))
        screen._on_timeline_move(SimpleNamespace(x=x0 + 60))
        self.assertIsNone(screen._timeline_drag["snapped"])
        self.assertEqual(screen._timeline.find_withtag("snap"), ())
        screen._on_timeline_release(SimpleNamespace(x=0))

    def test_caption_snap_marker(self):
        """Caption-Snap: Marker exakt auf Snap-Zeit."""
        from ui.screens.caption_style import _snap_marker_x
        self._select_caption(0)
        screen = self.screen
        x0, _x1 = screen._timeline_caption_handles()
        screen._on_timeline_press(SimpleNamespace(x=x0))
        screen._on_timeline_move(
            SimpleNamespace(x=self._move_to(5.43)))
        drag = screen._timeline_drag
        self.assertEqual(drag["snapped"]["time"], 5.4)
        items = self._snap_ids()
        self.assertTrue(items)
        expected = _snap_marker_x(5.4, screen._timeline_w, 5.0, 8.0)
        actual = screen._timeline.coords(items[0])[0]
        self.assertAlmostEqual(actual, expected, places=6)
        screen._on_timeline_release(SimpleNamespace(x=0))

    def test_word_snap_marker(self):
        """Word-Snap: Marker + Highlight am aktiven Handle."""
        self._select_caption(0)
        self._select_word(1)
        screen = self.screen
        x0, _x1 = screen._timeline_handles()
        screen._on_timeline_press(SimpleNamespace(x=x0))
        screen._on_timeline_move(
            SimpleNamespace(x=self._move_to(6.03)))
        drag = screen._timeline_drag
        self.assertEqual(drag["snapped"]["time"], 6.0)
        handles = screen._timeline.find_withtag("snap_handle")
        self.assertTrue(handles)
        accent = screen.color("accent")
        self.assertEqual(screen._timeline.itemcget(handles[0], "outline"),
                         accent)
        screen._on_timeline_release(SimpleNamespace(x=0))

    def test_snap_lost_removes_marker(self):
        """Snap-Verlust: Marker/Highlight verschwinden sofort."""
        self._select_caption(0)
        screen = self.screen
        x0, _x1 = screen._timeline_caption_handles()
        screen._on_timeline_press(SimpleNamespace(x=x0))
        screen._on_timeline_move(
            SimpleNamespace(x=self._move_to(5.43)))
        self.assertTrue(self._snap_ids())
        screen._on_timeline_move(
            SimpleNamespace(x=self._move_to(5.2)))
        self.assertIsNone(screen._timeline_drag["snapped"])
        self.assertEqual(screen._timeline.find_withtag("snap"), ())
        screen._on_timeline_release(SimpleNamespace(x=0))

    def test_snap_reacquired(self):
        """Erneuter Snap nach Verlust funktioniert."""
        self._select_caption(0)
        screen = self.screen
        x0, _x1 = screen._timeline_caption_handles()
        screen._on_timeline_press(SimpleNamespace(x=x0))
        screen._on_timeline_move(
            SimpleNamespace(x=self._move_to(5.43)))
        self.assertTrue(self._snap_ids())
        screen._on_timeline_move(
            SimpleNamespace(x=self._move_to(5.2)))
        self.assertEqual(screen._timeline.find_withtag("snap"), ())
        screen._on_timeline_move(
            SimpleNamespace(x=self._move_to(5.42)))
        self.assertTrue(self._snap_ids())
        self.assertEqual(screen._timeline_drag["snapped"]["time"], 5.4)
        screen._on_timeline_release(SimpleNamespace(x=0))

    def test_release_clears_snap_state(self):
        """Nach Release: kein persistenter Snap-State."""
        self._select_caption(0)
        screen = self.screen
        x0, _x1 = screen._timeline_caption_handles()
        screen._on_timeline_press(SimpleNamespace(x=x0))
        screen._on_timeline_move(
            SimpleNamespace(x=self._move_to(5.43)))
        screen._on_timeline_release(SimpleNamespace(x=0))
        self.assertIsNone(screen._timeline_drag)
        self.assertEqual(screen._timeline.find_withtag("snap"), ())
        self.assertAlmostEqual(
            screen._transcript_segments[0]["start"], 5.4)

    def test_reject_clears_snap_state(self):
        """Reject: kein State-Wechsel, kein Marker, kein Step."""
        self._select_caption(0)
        screen = self.screen
        _x0, x1 = screen._timeline_caption_handles()
        screen._on_timeline_press(SimpleNamespace(x=x1))
        screen._on_timeline_move(
            SimpleNamespace(x=self._move_to(6.2)))
        screen._on_timeline_release(SimpleNamespace(x=0))
        self.assertEqual(
            (screen._transcript_segments[0]["start"],
             screen._transcript_segments[0]["end"]), (5.0, 8.0))
        self.assertIsNone(screen._timeline_drag)
        self.assertEqual(screen._timeline.find_withtag("snap"), ())
        self.assertIsNone(screen._undo_histories.get(0))

    def test_all_four_cases(self):
        """A-D: Cap-Start/End + Word-Start/End snappen korrekt."""
        self._select_caption(0)
        screen = self.screen
        # A: Caption-Start -> Wort-Start 5.5:
        x0, _x1 = screen._timeline_caption_handles()
        screen._on_timeline_press(SimpleNamespace(x=x0))
        screen._on_timeline_move(
            SimpleNamespace(x=self._move_to(5.43)))
        self.assertEqual(screen._timeline_drag["snapped"]["time"], 5.4)
        screen._on_timeline_release(SimpleNamespace(x=0))
        self.assertAlmostEqual(screen._transcript_segments[0]["start"], 5.4)
        # B: Caption-Ende -> Wort-Ende 7.0:
        _bx0, bx1 = screen._timeline_caption_handles()
        screen._on_timeline_press(SimpleNamespace(x=bx1))
        screen._on_timeline_move(
            SimpleNamespace(x=self._move_to(7.77)))
        self.assertEqual(screen._timeline_drag["snapped"]["time"], 7.8)
        screen._on_timeline_release(SimpleNamespace(x=0))
        self.assertAlmostEqual(screen._transcript_segments[0]["end"], 7.8)
        # C: Word-Start -> Previous-Ende 6.0:
        self._select_word(1)
        wx0, _wx1 = screen._timeline_handles()
        screen._on_timeline_press(SimpleNamespace(x=wx0))
        screen._on_timeline_move(
            SimpleNamespace(x=self._move_to(6.02)))
        self.assertEqual(screen._timeline_drag["snapped"]["time"], 6.0)
        screen._on_timeline_release(SimpleNamespace(x=0))
        words = screen._transcript_segments[0]["words"]
        self.assertAlmostEqual(words[1]["start"], 6.0)
        # D: Word-Ende -> Next-Start 7.2:
        _dx0, dx1 = screen._timeline_handles()
        screen._on_timeline_press(SimpleNamespace(x=dx1))
        screen._on_timeline_move(
            SimpleNamespace(x=self._move_to(7.18)))
        self.assertEqual(screen._timeline_drag["snapped"]["time"], 7.2)
        screen._on_timeline_release(SimpleNamespace(x=0))
        words = screen._transcript_segments[0]["words"]
        self.assertAlmostEqual(words[1]["end"], 7.2)

    def test_scales_and_absolute(self):
        """Mapping-Korrektheit über Skalen, absolut (5.0-Basis)."""
        from ui.screens.caption_style import _snap_marker_x
        width = self.screen._timeline_w
        for dom, tol in (((5.0, 8.0), 133.33), ((0.0, 2.0), 200.0),
                         ((5.0, 15.0), 40.0)):
            d0, d1 = dom
            for t in (d0, (d0 + d1) / 2, d1):
                expected = 10 + (t - d0) / (d1 - d0) * (width - 20)
                self.assertAlmostEqual(
                    _snap_marker_x(t, width, d0, d1), expected, places=9)

    def test_priority_kept(self):
        """Hit-Priorität Wort > Caption bleibt (Snap ändert nichts)."""
        self._select_caption(1)
        screen = self.screen
        x0, _x1 = screen._timeline_caption_handles()
        screen._word_option.set(
            next(iter(screen._word_option.cget("values"))))
        screen._on_word_select(None)
        screen._on_timeline_press(SimpleNamespace(x=x0))
        self.assertEqual(screen._timeline_drag["kind"], "word")
        screen._on_timeline_release(SimpleNamespace(x=0))

    def test_single_word(self):
        """Einzelnes Wort: Snap an beiden Caption-Grenzen."""
        self.controller.last_transcript = {
            "video_path": VIDEO_A,
            "segments": [{"start": 5.0, "end": 8.0, "text": "solo",
                          "words": [{"word": "solo", "start": 5.4,
                                     "end": 7.6}]}]}
        self.screen.on_show()
        self._select_caption(0)
        screen = self.screen
        x0, _x1 = screen._timeline_caption_handles()
        screen._on_timeline_press(SimpleNamespace(x=x0))
        screen._on_timeline_move(
            SimpleNamespace(x=self._move_to(5.43)))
        self.assertEqual(screen._timeline_drag["snapped"]["time"], 5.4)
        screen._on_timeline_release(SimpleNamespace(x=0))
        _sx0, sx1 = screen._timeline_caption_handles()
        screen._on_timeline_press(SimpleNamespace(x=sx1))
        screen._on_timeline_move(
            SimpleNamespace(x=self._move_to(7.57)))
        self.assertEqual(screen._timeline_drag["snapped"]["time"], 7.6)
        screen._on_timeline_release(SimpleNamespace(x=0))
        seg = screen._transcript_segments[0]
        self.assertAlmostEqual((seg["start"], seg["end"]), (5.4, 7.6))

    def test_nonfinite_ignored(self):
        """Nonfinite/kaputte Wörter: kein Crash, saubere Ablehnung."""
        self.controller.last_transcript = {
            "video_path": VIDEO_A,
            "segments": [{"start": 5.0, "end": 8.0, "text": "a b",
                          "words": [{"word": "a", "start": float("nan"),
                                     "end": 5.2},
                                    {"word": "b", "start": 5.9,
                                     "end": 6.1}]}]}
        self.screen.on_show()
        self._select_caption(0)
        screen = self.screen
        # Auswahl + Zeichnen mit NaN-Wort crasht nicht (Draw-Guard):
        self._select_word(1)
        x0, _x1 = screen._timeline_caption_handles()
        screen._on_timeline_press(SimpleNamespace(x=x0))
        screen._on_timeline_move(
            SimpleNamespace(x=self._move_to(4.97)))
        # NaN-Kandidat ignoriert -> kein Snap:
        self.assertIsNone(screen._timeline_drag["snapped"])
        screen._on_timeline_release(SimpleNamespace(x=0))
        # Core lehnt wegen NaN-Wort ab: unverändert, Hinweis, kein Step:
        self.assertAlmostEqual(
            (screen._transcript_segments[0]["start"],
             screen._transcript_segments[0]["end"]), (5.0, 8.0))
        self.assertTrue(screen._editor_hint.cget("text"))
        self.assertIsNone(screen._undo_histories.get(0))
        self.assertEqual(screen._timeline.find_withtag("snap"), ())

    def test_undo_redo_after_snap(self):
        """Undo/Redo nach Snap-Release exakt, ohne Snap-Reste."""
        self._select_caption(0)
        screen = self.screen
        x0, _x1 = screen._timeline_caption_handles()
        screen._on_timeline_press(SimpleNamespace(x=x0))
        screen._on_timeline_move(
            SimpleNamespace(x=self._move_to(5.43)))
        screen._on_timeline_release(SimpleNamespace(x=0))
        screen._on_undo()
        self.assertAlmostEqual(screen._transcript_segments[0]["start"], 5.0)
        self.assertIsNone(screen._timeline_drag)
        self.assertEqual(screen._timeline.find_withtag("snap"), ())
        screen._on_redo()
        self.assertAlmostEqual(screen._transcript_segments[0]["start"], 5.4)
        self.assertEqual(screen._timeline.find_withtag("snap"), ())

class TestSnapTolerance(unittest.TestCase):
    """Block 41: konfigurierbare Snap-Toleranz (live aus Settings)."""

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
        self._prev_cfg = os.environ.get("CAPTI_CONFIG_FILE")
        os.environ["CAPTI_CONFIG_FILE"] = str(self.config_path)
        self.controller = AppController(self.root)
        self.screen = self.controller.get_screen("caption_style")
        self.controller.pending_project = {"video_path": VIDEO_A,
                                           "model": "tiny", "language": "de"}
        self.controller.last_transcript = {
            "video_path": VIDEO_A, "segments": _snap_segments()}
        self.screen.on_show()

    def tearDown(self):
        i18n.set_language(self._prev_lang)
        self.patcher.stop()
        if self._prev_cfg is None:
            os.environ.pop("CAPTI_CONFIG_FILE", None)
        else:
            os.environ["CAPTI_CONFIG_FILE"] = self._prev_cfg
        self.tmp.cleanup()
        import contextlib
        with contextlib.suppress(Exception):
            self.screen.destroy()

    # -- Helfer ----------------------------------------------------

    def _select_caption(self, idx):
        labels = list(self.screen._editor_option.cget("values"))
        self.screen._editor_option.set(labels[idx])
        self.screen._on_editor_select(None)

    def _select_word(self, idx):
        labels = list(self.screen._word_option.cget("values"))
        self.screen._word_option.set(labels[idx])
        self.screen._on_word_select(None)

    def _cap_move_to(self, to_t):
        """Caption-Drag bis Move (ohne Release); gibt drag zurück."""
        screen = self.screen
        handles = screen._timeline_caption_handles()
        screen._on_timeline_press(SimpleNamespace(x=handles[0]))
        drag = screen._timeline_drag
        width = screen._timeline_w
        span = drag["map_end"] - drag["map_start"]
        move_x = 10 + (to_t - drag["map_start"]) / span * (width - 20)
        screen._on_timeline_move(SimpleNamespace(x=move_x))
        return drag

    def _history(self, idx=0):
        return self.screen._undo_histories.get(idx)

    # -- Tests -----------------------------------------------------

    def test_default_tolerance(self):
        from ui.screens.caption_style import get_snap_tolerance_px
        from ui.screens.settings import SNAP_TOLERANCE_DEFAULT
        self.assertEqual(SNAP_TOLERANCE_DEFAULT, 8.0)
        self.assertEqual(get_snap_tolerance_px(), 8.0)

    def test_small_tolerance_no_snap(self):
        """Toleranz 2 px: kein Snap wo 8 px snappen würde."""
        from config import set_config_value
        from ui.screens import settings as settings_mod
        self._select_caption(0)
        self.assertTrue(set_config_value(
            settings_mod.SNAP_TOLERANCE_KEY, 2.0))
        screen = self.screen
        handles = screen._timeline_caption_handles()
        screen._on_timeline_press(SimpleNamespace(x=handles[0]))
        width = screen._timeline_w
        drag = screen._timeline_drag
        span = drag["map_end"] - drag["map_start"]
        move_x = 10 + (5.53 - drag["map_start"]) / span * (width - 20)
        screen._on_timeline_move(SimpleNamespace(x=move_x))
        self.assertIsNone(screen._timeline_drag["snapped"])
        self.assertEqual(screen._timeline.find_withtag("snap"), ())
        screen._on_timeline_release(SimpleNamespace(x=0))

    def test_large_tolerance_snaps(self):
        """Toleranz 16 px: Snap wo 8 px linear bliebe."""
        from config import set_config_value
        from ui.screens import settings as settings_mod
        self._select_caption(0)
        self.assertTrue(set_config_value(
            settings_mod.SNAP_TOLERANCE_KEY, 16.0))
        screen = self.screen
        handles = screen._timeline_caption_handles()
        screen._on_timeline_press(SimpleNamespace(x=handles[0]))
        width = screen._timeline_w
        drag = screen._timeline_drag
        span = drag["map_end"] - drag["map_start"]
        move_x = 10 + (5.48 - drag["map_start"]) / span * (width - 20)
        screen._on_timeline_move(SimpleNamespace(x=move_x))
        self.assertEqual(screen._timeline_drag["snapped"]["time"], 5.4)
        self.assertTrue(screen._timeline.find_withtag("snap"))
        screen._on_timeline_release(SimpleNamespace(x=0))
        self.assertAlmostEqual(
            screen._transcript_segments[0]["start"], 5.4)

    def test_word_drag_uses_configured_tolerance(self):
        """Word-Drag liest dieselbe Quelle (Single Source)."""
        from config import set_config_value
        from ui.screens import settings as settings_mod
        self._select_caption(0)
        self._select_word(1)
        self.assertTrue(set_config_value(
            settings_mod.SNAP_TOLERANCE_KEY, 2.0))
        screen = self.screen
        x0, _x1 = screen._timeline_handles()
        screen._on_timeline_press(SimpleNamespace(x=x0))
        # 6.03 liegt 4 px neben prev.end 6.0: snappt bei 8, nicht bei 2:
        width = screen._timeline_w
        move_x = 10 + (6.03 - 5.0) / 3.0 * (width - 20)
        screen._on_timeline_move(SimpleNamespace(x=move_x))
        self.assertIsNone(screen._timeline_drag["snapped"])
        screen._on_timeline_release(SimpleNamespace(x=0))
        words = screen._transcript_segments[0]["words"]
        self.assertAlmostEqual(words[1]["start"], 6.03)

    def test_setting_change_no_history_step(self):
        """Settings-Änderung berührt Caption-History nicht."""
        from config import set_config_value
        from ui.screens import settings as settings_mod
        self._select_caption(0)
        drag = self._cap_move_to(5.43)
        self.assertIsNotNone(drag["snapped"])
        screen = self.screen
        screen._on_timeline_release(SimpleNamespace(x=0))
        hist = self._history(0)
        self.assertEqual(hist.depth, 2)
        self.assertTrue(set_config_value(
            settings_mod.SNAP_TOLERANCE_KEY, 2.0))
        self.assertEqual(hist.depth, 2)
        screen._on_undo()
        self.assertAlmostEqual(
            screen._transcript_segments[0]["start"], 5.0)

    def test_live_switch_back_and_forth(self):
        """16 px -> 2 px ohne Neustart, sofort wirksam."""
        from config import set_config_value
        from ui.screens import settings as settings_mod
        from ui.screens.caption_style import get_snap_tolerance_px
        self._select_caption(0)
        screen = self.screen
        self.assertTrue(set_config_value(
            settings_mod.SNAP_TOLERANCE_KEY, 16.0))
        self.assertEqual(get_snap_tolerance_px(), 16.0)
        handles = screen._timeline_caption_handles()
        screen._on_timeline_press(SimpleNamespace(x=handles[0]))
        width = screen._timeline_w
        drag = screen._timeline_drag
        span = drag["map_end"] - drag["map_start"]
        move_x = 10 + (5.48 - drag["map_start"]) / span * (width - 20)
        screen._on_timeline_move(SimpleNamespace(x=move_x))
        self.assertIsNotNone(screen._timeline_drag["snapped"])
        screen._on_timeline_release(SimpleNamespace(x=0))
        self.assertTrue(set_config_value(
            settings_mod.SNAP_TOLERANCE_KEY, 2.0))
        self.assertEqual(get_snap_tolerance_px(), 2.0)


class TestSnapPresets(unittest.TestCase):
    """Block 42: Preset-Klick -> live Snap + Indikator, kein History-Step."""

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
        self._prev_cfg = os.environ.get("CAPTI_CONFIG_FILE")
        os.environ["CAPTI_CONFIG_FILE"] = str(self.config_path)
        self.controller = AppController(self.root)
        self.screen = self.controller.get_screen("caption_style")
        self.settings = self.controller.get_screen("settings")
        self.controller.pending_project = {"video_path": VIDEO_A,
                                           "model": "tiny", "language": "de"}
        self.controller.last_transcript = {
            "video_path": VIDEO_A, "segments": _snap_segments()}
        self.screen.on_show()
        self.settings.load_settings()

    def tearDown(self):
        i18n.set_language(self._prev_lang)
        self.patcher.stop()
        if self._prev_cfg is None:
            os.environ.pop("CAPTI_CONFIG_FILE", None)
        else:
            os.environ["CAPTI_CONFIG_FILE"] = self._prev_cfg
        self.tmp.cleanup()
        import contextlib
        with contextlib.suppress(Exception):
            self.screen.destroy()

    def _select_caption(self, idx):
        labels = list(self.screen._editor_option.cget("values"))
        self.screen._editor_option.set(labels[idx])
        self.screen._on_editor_select(None)

    def _snap_move(self, to_t):
        screen = self.screen
        handles = screen._timeline_caption_handles()
        screen._on_timeline_press(SimpleNamespace(x=handles[0]))
        drag = screen._timeline_drag
        width = screen._timeline_w
        span = drag["map_end"] - drag["map_start"]
        move_x = 10 + (to_t - drag["map_start"]) / span * (width - 20)
        screen._on_timeline_move(SimpleNamespace(x=move_x))
        return drag

    def test_preset_click_live_in_editor(self):
        """Preset 16 px via Settings-UI -> Editor snappt sofort (F)."""
        from ui.screens.caption_style import get_snap_tolerance_px
        self._select_caption(0)
        self.assertEqual(get_snap_tolerance_px(), 8.0)
        self.settings._on_preset_selected_snap(16.0)
        self.assertEqual(get_snap_tolerance_px(), 16.0)
        # 5.48 liegt 10.7 px neben 5.4: snappt bei 16, nicht bei 8:
        drag = self._snap_move(5.48)
        self.assertEqual(drag["snapped"]["time"], 5.4)
        self.screen._on_timeline_release(SimpleNamespace(x=0))
        self.assertAlmostEqual(
            self.screen._transcript_segments[0]["start"], 5.4)

    def test_preset_switch_4px_live(self):
        """Danach 4 px -> neuer Wert sofort wirksam (F)."""
        from ui.screens.caption_style import get_snap_tolerance_px
        self._select_caption(0)
        self.settings._on_preset_selected_snap(16.0)
        self.settings._on_preset_selected_snap(4.0)
        self.assertEqual(get_snap_tolerance_px(), 4.0)
        # 5.43 liegt 4 px neben 5.4: snappt bei 4, nicht bei 2:
        drag = self._snap_move(5.43)
        self.assertEqual(drag["snapped"]["time"], 5.4)
        self.screen._on_timeline_release(SimpleNamespace(x=0))

    def test_preset_no_history_step(self):
        """Preset-Wechsel berührt Undo-History nicht (G)."""
        self._select_caption(0)
        # Erst ein echter Edit (History entsteht lazy):
        drag = self._snap_move(5.43)
        self.assertIsNotNone(drag["snapped"])
        self.screen._on_timeline_release(SimpleNamespace(x=0))
        hist = self.screen._undo_histories.get(0)
        self.assertEqual(hist.depth, 2)
        for preset in (2.0, 4.0, 8.0, 16.0):
            self.settings._on_preset_selected_snap(preset)
            self.assertEqual(hist.depth, 2)
        self.assertAlmostEqual(
            self.screen._transcript_segments[0]["start"], 5.4)
        self.screen._on_undo()
        self.assertAlmostEqual(
            self.screen._transcript_segments[0]["start"], 5.0)

    def test_preset_indicator_uses_new_value(self):
        """Snap-Indikator folgt Preset-Wechsel (H)."""
        self._select_caption(0)
        screen = self.screen
        self.settings._on_preset_selected_snap(16.0)
        drag = self._snap_move(5.48)
        self.assertIsNotNone(drag["snapped"])
        self.assertTrue(screen._timeline.find_withtag("snap"))
        screen._on_timeline_release(SimpleNamespace(x=0))
        self.assertEqual(screen._timeline.find_withtag("snap"), ())


class TestCaptionKeyboardNudge(unittest.TestCase):
    """Block 48: Caption-Nudge per Tastatur (Priorität WORD > CAPTION)."""

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
        self._prev_cfg = os.environ.get("CAPTI_CONFIG_FILE")
        os.environ["CAPTI_CONFIG_FILE"] = str(self.config_path)
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
        if self._prev_cfg is None:
            os.environ.pop("CAPTI_CONFIG_FILE", None)
        else:
            os.environ["CAPTI_CONFIG_FILE"] = self._prev_cfg
        self.tmp.cleanup()
        import contextlib
        with contextlib.suppress(Exception):
            self.screen.destroy()

    # -- Helfer ----------------------------------------------------

    def _select_caption(self, idx):
        labels = list(self.screen._editor_option.cget("values"))
        self.screen._editor_option.set(labels[idx])
        self.screen._on_editor_select(None)
        self.screen._word_index = None  # kein Word-Kontext -> Caption

    def _select_word(self, idx):
        labels = list(self.screen._word_option.cget("values"))
        self.screen._word_option.set(labels[idx])
        self.screen._on_word_select(None)

    def _key(self, keysym, state=0):
        with patch.object(type(self.screen), "focus_get",
                          return_value=self.screen._timeline):
            return self.screen._on_nudge_key(
                SimpleNamespace(keysym=keysym, state=state))

    def _ckey(self, keysym, state=0):
        """Caption-Taste: Word-Kontext löschen (Refresh wählt sonst
        Wort 0 vor), dann Taste (Priorität WORD > CAPTION)."""
        self.screen._word_index = None
        return self._key(keysym, state)

    def _span(self, idx=1):
        seg = self.screen._transcript_segments[idx]
        return (seg["start"], seg["end"])

    def _assertSpan(self, expected, idx=1):
        got = self._span(idx)
        self.assertAlmostEqual(got[0], expected[0])
        self.assertAlmostEqual(got[1], expected[1])

    def _history(self, idx=1):
        return self.screen._undo_histories.get(idx)

    # -- Tests -----------------------------------------------------

    def test_left_right_start(self):
        self._select_caption(1)
        self.assertEqual(self._ckey("Left"), "break")
        self._assertSpan((4.95, 7.0))
        self.assertEqual(self._ckey("Right"), "break")
        self._assertSpan((5.0, 7.0))

    def test_shift_left_right_end(self):
        self._select_caption(1)
        self.assertEqual(self._ckey("Right", state=1), "break")
        self._assertSpan((5.0, 7.05))
        self.assertEqual(self._ckey("Left", state=1), "break")
        self._assertSpan((5.0, 7.0))

    def test_start_nudge_keeps_end(self):
        self._select_caption(1)
        self._ckey("Left")
        self.assertAlmostEqual(self._span()[1], 7.0)

    def test_end_nudge_keeps_start(self):
        self._select_caption(1)
        self._ckey("Right", state=1)
        self.assertAlmostEqual(self._span()[0], 5.0)

    def test_success_one_history_step(self):
        self._select_caption(1)
        self._ckey("Left")
        self.assertEqual(self._history().depth, 2)
        self.assertEqual(
            str(self.screen._undo_btn.cget("state")), "normal")

    def test_invalid_no_history_step(self):
        self._select_caption(0)
        self.assertEqual(self._ckey("Left"), "break")
        self._assertSpan((0.0, 2.0), 0)
        self.assertIsNone(self._history(0))
        self.assertEqual(
            str(self.screen._undo_btn.cget("state")), "disabled")

    def test_undo_restores(self):
        self._select_caption(1)
        self._ckey("Left")
        self._ckey("Right", state=1)
        self._assertSpan((4.95, 7.05))
        self.screen._on_undo()
        self._assertSpan((4.95, 7.0))
        self.screen._on_undo()
        self._assertSpan((5.0, 7.0))

    def test_redo_restores(self):
        self._select_caption(1)
        self._ckey("Left")
        self.screen._on_undo()
        self._assertSpan((5.0, 7.0))
        self.screen._on_redo()
        self._assertSpan((4.95, 7.0))

    def test_live_step(self):
        from config import set_config_value
        from ui.screens import settings as settings_mod
        from ui.screens.caption_style import get_nudge_step
        self._select_caption(1)
        self.assertTrue(set_config_value(
            settings_mod.NUDGE_STEP_KEY, 0.15))
        self.assertAlmostEqual(get_nudge_step(), 0.15)
        before = self._span()[0]
        self._ckey("Left")
        self.assertAlmostEqual(before - self._span()[0], 0.15)
        self.assertTrue(set_config_value(
            settings_mod.NUDGE_STEP_KEY, 0.50))
        self.assertAlmostEqual(get_nudge_step(), 0.50)
        before = self._span()[0]
        self._ckey("Left")
        self.assertAlmostEqual(before - self._span()[0], 0.50)

    def test_word_context_wins(self):
        self._select_caption(1)
        self._select_word(1)
        self.assertEqual(self._key("Left"), "break")
        words = self.screen._transcript_segments[1]["words"]
        self.assertAlmostEqual(words[1]["start"], 5.85)
        self._assertSpan((5.0, 7.0))
        self._select_word(0)
        self.assertEqual(self._key("Right", state=1), "break")
        words = self.screen._transcript_segments[1]["words"]
        self.assertAlmostEqual(words[0]["end"], 5.85)
        self._assertSpan((5.0, 7.0))

    def test_nothing_without_caption(self):
        before = copy.deepcopy(self.screen._transcript_segments)
        self.screen._editor_index = None
        self.assertEqual(self._ckey("Left"), "break")
        self.assertEqual(self._ckey("Right", state=1), "break")
        self.assertEqual(self.screen._transcript_segments, before)

    def test_invalid_keeps_redo_branch(self):
        self._select_caption(1)
        self._ckey("Left")
        self.screen._on_undo()
        self._ckey("Left", state=1)  # ungültig: 6.95 < Wort-Ende 7.0
        self._assertSpan((5.0, 7.0))
        self.assertEqual(
            str(self.screen._redo_btn.cget("state")), "normal")

    def test_containment_rejected(self):
        self._select_caption(1)
        self.assertEqual(self._ckey("Left", state=1), "break")
        self._assertSpan((5.0, 7.0))
        self.assertIsNone(self._history())

    def test_save_load_roundtrip(self):
        self._select_caption(1)
        self._ckey("Left")
        self._ckey("Right", state=1)
        proj = str(Path(self.tmp.name) / "capkey.capti.json")
        self.controller.save_project_state(proj)
        self.controller.last_transcript = None
        self.controller.pending_project = None
        self.screen.clear_transcript()
        self.controller.load_project_state(proj)
        seg = self.controller.last_transcript["segments"][1]
        self.assertAlmostEqual(seg["start"], 4.95)
        self.assertAlmostEqual(seg["end"], 7.05)
        self.assertEqual(seg["text"], "Second here")
        self.assertAlmostEqual(seg["words"][0]["start"], 5.0)
        self.assertAlmostEqual(seg["words"][1]["end"], 7.0)

    def test_preview_controller_sync(self):
        self._select_caption(1)
        self._ckey("Left")
        ctrl = self.controller.last_transcript["segments"][1]
        self.assertAlmostEqual(ctrl["start"], 4.95)
        self.assertAlmostEqual(ctrl["end"], 7.0)
        model_cap = self.screen._transcript_captions[1]
        self.assertAlmostEqual(model_cap.start, 4.95)
        self.assertAlmostEqual(model_cap.end, 7.0)
        preview = self.screen._preview_caption
        self.assertIsNotNone(preview)


class TestCaptionKeyHint(unittest.TestCase):
    """Block 50: Caption-Keyboard-Hinweis (Anzeige, live Step)."""

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
        self._prev_cfg = os.environ.get("CAPTI_CONFIG_FILE")
        os.environ["CAPTI_CONFIG_FILE"] = str(self.config_path)
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
        if self._prev_cfg is None:
            os.environ.pop("CAPTI_CONFIG_FILE", None)
        else:
            os.environ["CAPTI_CONFIG_FILE"] = self._prev_cfg
        self.tmp.cleanup()
        import contextlib
        with contextlib.suppress(Exception):
            self.screen.destroy()

    # -- Tests -----------------------------------------------------

    def test_hint_exists_in_caption_card(self):
        hint = self.screen._cap_key_hint_label
        self.assertIs(hint.master, self.screen._editor_card)
        self.assertIn(hint, self.screen._editor_card.winfo_children())

    def test_de_text(self):
        i18n.set_language("de")
        self.screen._refresh_nudge_hint()
        text = self.screen._cap_key_hint_label.cget("text")
        self.assertIn("Tastatur", text)
        self.assertIn("Shift", text)
        self.assertIn("0,05", text)

    def test_en_text(self):
        i18n.set_language("en")
        self.screen._refresh_nudge_hint()
        text = self.screen._cap_key_hint_label.cget("text")
        self.assertIn("Keyboard", text)
        self.assertIn("Shift", text)
        self.assertIn("0.05", text)

    def test_live_step(self):
        from config import set_config_value
        from ui.screens import settings as settings_mod
        i18n.set_language("de")
        self.assertTrue(set_config_value(
            settings_mod.NUDGE_STEP_KEY, 0.15))
        self.screen._refresh_nudge_hint()
        self.assertIn(
            "0,15", self.screen._cap_key_hint_label.cget("text"))
        self.assertTrue(set_config_value(
            settings_mod.NUDGE_STEP_KEY, 0.50))
        self.screen._refresh_nudge_hint()
        self.assertIn(
            "0,50", self.screen._cap_key_hint_label.cget("text"))

    def test_refresh_no_history_no_change(self):
        labels = list(self.screen._editor_option.cget("values"))
        self.screen._editor_option.set(labels[1])
        self.screen._on_editor_select(None)
        before = copy.deepcopy(self.screen._transcript_segments)
        self.screen._refresh_nudge_hint()
        self.screen._refresh_cap_key_hint()
        self.assertEqual(self.screen._transcript_segments, before)
        self.assertEqual(dict(self.screen._undo_histories), {})

    def test_word_hint_intact(self):
        self.screen._refresh_nudge_hint()
        text = self.screen._nudge_hint_label.cget("text")
        self.assertIn("Schritt", text)
        self.assertIn("0,05", text)

    def test_keyboard_still_works(self):
        labels = list(self.screen._editor_option.cget("values"))
        self.screen._editor_option.set(labels[1])
        self.screen._on_editor_select(None)
        self.screen._word_index = None
        with patch.object(type(self.screen), "focus_get",
                          return_value=self.screen._timeline):
            self.screen._on_nudge_key(
                SimpleNamespace(keysym="Left", state=0))
        seg = self.screen._transcript_segments[1]
        self.assertAlmostEqual(seg["start"], 4.95)

    def test_guards_unchanged(self):
        before = copy.deepcopy(self.screen._transcript_segments)
        with patch.object(type(self.screen), "focus_get",
                          return_value=self.screen._word_start_entry):
            self.assertIsNone(self.screen._on_nudge_key(
                SimpleNamespace(keysym="Left", state=0)))
        with patch.object(type(self.screen), "focus_get",
                          return_value=self.screen._timeline):
            self.assertIsNone(self.screen._on_nudge_key(
                SimpleNamespace(keysym="Left", state=4)))
            self.assertIsNone(self.screen._on_nudge_key(
                SimpleNamespace(keysym="Right", state=8)))
        self.assertEqual(self.screen._transcript_segments, before)


if __name__ == "__main__":
    unittest.main()
