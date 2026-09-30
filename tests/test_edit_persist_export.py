"""Fix-Block 22: Edits persistieren + mit Edits exportieren.

A) Edit überlebt Screen-Wechsel
B) mehrere Edits überleben Screen-Wechsel
C) Edit-State ist projektbezogen (Helper, Tk-frei)
D) Projektwechsel isoliert (kein Leak in anderes Video)
E) kein Edit -> originale Segmente (Whisper-Pfad)
F) ein Edit -> Export bekommt editierte Segmente
G) mehrere Edits -> Export bekommt alle
H) Preview und Export nutzen dieselbe Quelle
I) Segmentreihenfolge bleibt erhalten
J) Word-Timings im Export korrekt
K) RenderCaption-Rebuild aus Export-Segmenten
L) ASS-Output unverändert datenidentisch (Byte-Parität)
M) Export-Fehler lässt Edit-State intakt
N) Cancel lässt Edit-State intakt
O) Unicode/Umlaute im Export
P) leere Wortliste gemäß Block-21-Regeln
"""

import copy
import os
import queue
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tempfile as _tmp

if "CAPTI_CONFIG_FILE" not in os.environ:
    os.environ["APPDATA"] = _tmp.mkdtemp(prefix="capti_test_appdata_")

import customtkinter as ctk

from capti_core.render_model import captions_from_segments
from pipeline import CaptiPipeline
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
        {"start": 8.0, "end": 10.0, "text": "Grüße aus München",
         "words": [{"word": "Grüße", "start": 8.0, "end": 8.6},
                   {"word": "aus", "start": 8.7, "end": 9.0},
                   {"word": "München", "start": 9.1, "end": 10.0}]},
    ]


def _edited_segments():
    segs = _segments()
    segs[0] = {"start": 5.0, "end": 7.0, "text": "Hello beautiful world",
               "words": [{"word": "Hello", "start": 5.0, "end": 5.8},
                         {"word": "beautiful", "start": 5.8, "end": 5.9},
                         {"word": "world", "start": 5.9, "end": 7.0}]}
    return segs


def _tmpdir(testcase, prefix="capti_ed22_"):
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    testcase.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
    return tmp


def _mock_stack(captured):
    """Mocks; captured['ass_segments'] <- generate_ass-Input (deep copy)."""
    engine = MagicMock()
    engine.transcribe.return_value = _segments()
    processor = MagicMock()
    processor.extract_audio.side_effect = lambda v, a, **k: a
    processor.get_video_info.return_value = {"streams": [{"width": 720, "height": 1280}]}
    processor.embed_ass.side_effect = lambda v, a, o, **k: o
    renderer = MagicMock()

    def fake_ass(segments, path, video_width=None, video_height=None):
        captured["ass_segments"] = copy.deepcopy(segments)
        Path(path).write_text(
            "\n".join(s["text"] for s in segments), encoding="utf-8")
        return path

    renderer.generate_ass.side_effect = fake_ass
    return engine, processor, renderer


def _run_pipeline(testcase, tmp, override, captured):
    (tmp / "clip.mp4").write_bytes(b"x")
    pipe = CaptiPipeline(temp_dir=str(tmp / "_temp"))
    engine, processor, renderer = _mock_stack(captured)
    with patch("pipeline.create_subtitle_engine", return_value=engine) as mk_engine, \
         patch("pipeline.create_video_processor", return_value=processor), \
         patch("pipeline.create_caption_renderer", return_value=renderer):
        out = pipe.run(str(tmp / "clip.mp4"), model_size="tiny", language="de",
                       override_segments=override)
    return pipe, engine, mk_engine, out


class TestTranscriptHelper(unittest.TestCase):
    """C) Edit-State-Helper (Tk-frei, unbound auf Stub-State)."""

    def _state(self, video, segments):
        return SimpleNamespace(
            last_transcript={"video_path": video, "segments": segments})

    def test_match_returns_deep_copy(self):
        stub = self._state(VIDEO_A, _segments())
        got = AppController.get_transcript_segments(stub, VIDEO_A)
        self.assertEqual(got, _segments())
        got[0]["text"] = "MUTIERT"
        got[0]["words"].append({"word": "x", "start": 0, "end": 1})
        self.assertEqual(stub.last_transcript["segments"][0]["text"],
                         "Hello world")  # State entkoppelt

    def test_mismatch_returns_none(self):
        stub = self._state(VIDEO_A, _segments())
        self.assertIsNone(AppController.get_transcript_segments(stub, VIDEO_B))

    def test_missing_or_empty_returns_none(self):
        self.assertIsNone(AppController.get_transcript_segments(
            SimpleNamespace(last_transcript=None), VIDEO_A))
        self.assertIsNone(AppController.get_transcript_segments(
            SimpleNamespace(last_transcript={"video_path": VIDEO_A,
                                             "segments": []}), VIDEO_A))
        self.assertIsNone(AppController.get_transcript_segments(
            SimpleNamespace(last_transcript={"video_path": VIDEO_A}), VIDEO_A))


class TestExportOverride(unittest.TestCase):
    """E/F/G/I/J/K/L/O/P) Pipeline-Override (Tk-frei)."""

    def test_no_override_uses_whisper(self):
        """E) Ohne Edit: bisheriger Pfad, Transkription läuft."""
        tmp = _tmpdir(self)
        captured = {}
        pipe, engine, _mk, _out = _run_pipeline(self, tmp, None, captured)
        engine.transcribe.assert_called_once()
        self.assertEqual([s["text"] for s in captured["ass_segments"]],
                         ["Hello world", "Grüße aus München"])
        self.assertEqual(pipe.last_segments, captured["ass_segments"])

    def test_single_edit_reaches_export(self):
        """F/J) Ein Edit: Transkription entfällt, Edit im ASS-Input."""
        tmp = _tmpdir(self)
        captured = {}
        pipe, engine, _mk, _out = _run_pipeline(
            self, tmp, _edited_segments(), captured)
        engine.transcribe.assert_not_called()
        seg = captured["ass_segments"][0]
        self.assertEqual(seg["text"], "Hello beautiful world")   # F
        self.assertEqual(seg["start"], 5.0)
        self.assertEqual(seg["end"], 7.0)
        self.assertEqual([(w["word"], w["start"], w["end"])
                          for w in seg["words"]],
                         [("Hello", 5.0, 5.8), ("beautiful", 5.8, 5.9),
                          ("world", 5.9, 7.0)])                  # J
        self.assertEqual(pipe.last_segments, captured["ass_segments"])

    def test_multiple_edits_order_kept(self):
        """G/I) Mehrere Edits: alle da, Reihenfolge stabil."""
        tmp = _tmpdir(self)
        captured = {}
        edited = _edited_segments()
        edited[1] = {"start": 8.0, "end": 10.0, "text": "Servus München",
                     "words": [{"word": "Servus", "start": 8.0, "end": 8.8},
                               {"word": "München", "start": 9.1, "end": 10.0}]}
        _run_pipeline(self, tmp, edited, captured)
        self.assertEqual([s["text"] for s in captured["ass_segments"]],
                         ["Hello beautiful world", "Servus München"])  # G/I
        self.assertEqual([s["start"] for s in captured["ass_segments"]],
                         [5.0, 8.0])

    def test_rebuild_from_export_segments(self):
        """K) Export-Segmente -> RenderCaption (Modell-Regeln)."""
        tmp = _tmpdir(self)
        captured = {}
        _run_pipeline(self, tmp, _edited_segments(), captured)
        caps = captions_from_segments(captured["ass_segments"], None, None)
        self.assertEqual(len(caps), 2)
        self.assertEqual(caps[0].text, "Hello beautiful world")
        self.assertEqual(len(caps[0].words), 3)
        covered = sorted(i for line in caps[0].lines for i in line)
        self.assertEqual(covered, [0, 1, 2])

    def test_unedited_byte_parity(self):
        """L) Kein Edit -> Override-Pfad liefert identische Bytes."""
        tmp = _tmpdir(self)
        cap1, cap2 = {}, {}
        pipe, _e, _m, _o = _run_pipeline(self, tmp, None, cap1)
        # Override mit den Original-Segmenten -> identische ASS-Eingabe
        _run_pipeline(self, tmp, copy.deepcopy(pipe.last_segments), cap2)
        self.assertEqual(cap1["ass_segments"], cap2["ass_segments"])
        # Determinismus: zweimal Whisper-Pfad -> gleiche ASS-Eingabe
        cap3 = {}
        _run_pipeline(self, tmp, None, cap3)
        self.assertEqual(cap1["ass_segments"], cap3["ass_segments"])

    def test_unicode_export(self):
        """O) Umlaute im Edit kommen im Export an."""
        tmp = _tmpdir(self)
        captured = {}
        _run_pipeline(self, tmp, _edited_segments(), captured)
        self.assertEqual(captured["ass_segments"][1]["text"],
                         "Grüße aus München")

    def test_empty_words_export(self):
        """P) Leere Wortliste: kein Crash, Spanne bleibt."""
        tmp = _tmpdir(self)
        captured = {}
        edited = _edited_segments()
        edited[0] = {"start": 5.0, "end": 7.0, "text": "",
                     "words": []}
        _run_pipeline(self, tmp, edited, captured)
        self.assertEqual(captured["ass_segments"][0]["words"], [])
        self.assertEqual((captured["ass_segments"][0]["start"],
                          captured["ass_segments"][0]["end"]), (5.0, 7.0))


class TestEditPersistUI(unittest.TestCase):
    """A/B/D/H/M/N) Persistenz + Quelle (Tk)."""

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

    def _apply_text(self, idx, text):
        labels = list(self.screen._editor_option.cget("values"))
        self.screen._editor_option.set(labels[idx])
        self.screen._on_editor_select(None)
        self.screen._editor_entry.delete(0, "end")
        self.screen._editor_entry.insert(0, text)
        self.screen._on_editor_apply()

    def _reopen(self):
        self.controller.show_screen("home")
        self.controller.show_screen("caption_style")
        return self.controller.get_screen("caption_style")

    def test_edit_survives_screen_switch(self):
        """A) Edit -> weg -> zurück: Änderung vorhanden."""
        self._apply_text(0, "Hello beautiful world")
        screen = self._reopen()
        screen.on_show()
        self.assertEqual(screen._transcript_segments[0]["text"],
                         "Hello beautiful world")
        self.assertEqual(screen._editor_entry.get(), "Hello beautiful world")

    def test_multiple_edits_survive(self):
        """B) Zwei Edits überleben gemeinsam."""
        self._apply_text(0, "Hello beautiful world")
        self._apply_text(1, "Servus München")
        screen = self._reopen()
        screen.on_show()
        self.assertEqual(screen._transcript_segments[0]["text"],
                         "Hello beautiful world")
        self.assertEqual(screen._transcript_segments[1]["text"],
                         "Servus München")

    def test_project_switch_isolates(self):
        """D) Anderes Video: kein Leak; zurück: Edits wieder da."""
        self._apply_text(0, "Hello beautiful world")
        self.controller.pending_project = {"video_path": VIDEO_B,
                                           "model": "tiny", "language": "de"}
        self.screen.on_show()
        self.assertEqual(self.screen._preview_mode, "sample")
        self.assertIsNone(
            self.controller.get_transcript_segments(VIDEO_B))
        self.controller.pending_project = {"video_path": VIDEO_A,
                                           "model": "tiny", "language": "de"}
        self.screen.on_show()
        self.assertEqual(self.screen._transcript_segments[0]["text"],
                         "Hello beautiful world")

    def test_preview_and_export_share_source(self):
        """H) Preview-Text == Export-Input-Text nach Edit."""
        self._apply_text(0, "Hello beautiful world")
        preview_text = self.screen._preview_caption.text
        export_segs = self.controller.get_transcript_segments(VIDEO_A)
        self.assertEqual(export_segs[0]["text"], preview_text)
        tmp = _tmpdir(self)
        captured = {}
        _run_pipeline(self, tmp, export_segs, captured)
        self.assertEqual(captured["ass_segments"][0]["text"], preview_text)

    def test_start_pipeline_passes_override(self):
        """Handoff: Edits -> run_async(override_segments)."""
        import ui.screens.processing as proc_mod
        screen = self.controller.get_screen("processing")
        screen.video_path = VIDEO_A
        screen.model = "tiny"
        screen.language = "de"
        self._apply_text(0, "Hello beautiful world")
        with patch.object(proc_mod, "CaptiPipeline") as mk_pipe, \
             patch.object(type(screen), "_cleanup_temp", lambda self: None):
            screen._start_pipeline()
        _args, kwargs = mk_pipe.return_value.run_async.call_args
        self.assertEqual(kwargs["override_segments"][0]["text"],
                         "Hello beautiful world")

    def test_start_pipeline_without_edits_unchanged(self):
        """Handoff ohne Edits: exakt bisheriger Call (kein Override-Kwarg)."""
        import ui.screens.processing as proc_mod
        screen = self.controller.get_screen("processing")
        screen.video_path = VIDEO_B
        screen.model = "tiny"
        screen.language = "de"
        with patch.object(proc_mod, "CaptiPipeline") as mk_pipe, \
             patch.object(type(screen), "_cleanup_temp", lambda self: None):
            screen._start_pipeline()
        _args, kwargs = mk_pipe.return_value.run_async.call_args
        self.assertNotIn("override_segments", kwargs)

    def test_error_keeps_edit_state(self):
        """M) Export-Fehler lässt Edit-State intakt."""
        self._apply_text(0, "Hello beautiful world")
        screen = self.controller.get_screen("processing")
        screen._ui_queue = queue.Queue()
        screen._polling = True
        screen._ui_queue.put(("error", "boom"))
        screen._drain_ui_queue()
        kept = self.controller.get_transcript_segments(VIDEO_A)
        self.assertEqual(kept[0]["text"], "Hello beautiful world")

    def test_cancel_keeps_edit_state(self):
        """N) Cancel lässt Edit-State intakt."""
        self._apply_text(0, "Hello beautiful world")
        screen = self.controller.get_screen("processing")
        screen._ui_queue = queue.Queue()
        screen._polling = True
        screen._ui_queue.put(("cancelled", "Abbruch"))
        screen._drain_ui_queue()
        kept = self.controller.get_transcript_segments(VIDEO_A)
        self.assertEqual(kept[0]["text"], "Hello beautiful world")


if __name__ == "__main__":
    unittest.main()
