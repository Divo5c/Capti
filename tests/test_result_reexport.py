"""Fix-Block 23: Re-Export mit Edits aus dem Result-Screen.

A) Result erkennt vorhandenen Edit-State (Hinweis)
B) Button fehlt ohne passenden Transcript-State
C) Button vorhanden bei passendem Transcript
D) Klick startet bestehenden Override-Export (set_project)
E) aktueller Edit-State wird verwendet
F) erneuter Edit -> nächster Re-Export nutzt neue Daten
G) Video-Mismatch verhindert falschen Export
H) Cancel behält Edits
I) Failure behält Edits
J) erfolgreicher Re-Export öffnet wieder Result Screen
K) alter Result-Workflow unverändert (bestehende Suite)
L) keine Whisper-Neutranskription beim Re-Export
N) Unicode/Umlaute funktionieren
(M: keine zweite ASS-Implementierung -> strukturell: derselbe
    generate_ass-Pfad, in E/F über ASS-Input mitgeprüft.)
"""

import copy
import os
import queue
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tempfile as _tmp

if "CAPTI_CONFIG_FILE" not in os.environ:
    os.environ["APPDATA"] = _tmp.mkdtemp(prefix="capti_test_appdata_")

import customtkinter as ctk

from pipeline import CaptiPipeline
from ui import i18n
from ui.app_controller import AppController

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


def _tmpdir(testcase, prefix="capti_re23_"):
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    testcase.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
    return tmp


def _mock_stack(captured):
    engine = MagicMock()
    engine.transcribe.return_value = _segments()
    processor = MagicMock()
    processor.extract_audio.side_effect = lambda v, a, **k: a
    processor.get_video_info.return_value = {"streams": [{"width": 720, "height": 1280}]}
    processor.embed_ass.side_effect = lambda v, a, o, **k: o
    renderer = MagicMock()

    def fake_ass(segments, path, video_width=None, video_height=None):
        captured["ass_segments"] = copy.deepcopy(segments)
        Path(path).write_text("ASS", encoding="utf-8")
        return path

    renderer.generate_ass.side_effect = fake_ass
    return engine, processor, renderer


class TestResultReexport(unittest.TestCase):

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
        self._prev_lang = i18n.get_language()
        i18n.set_language("de")
        self.controller = AppController(self.root)
        self.screen = self.controller.get_screen("result")
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            self.out_name = f.name
        self.addCleanup(lambda: Path(self.out_name).unlink(missing_ok=True))

    def tearDown(self):
        i18n.set_language(self._prev_lang)
        import contextlib
        with contextlib.suppress(Exception):
            self.screen.reset()

    def _show_result(self, video=VIDEO_A, with_edits=False):
        self.controller.last_transcript = {
            "video_path": video, "segments": _segments()}
        self.screen.set_result(self.out_name, filename="clipA.mp4",
                               model="tiny", language="de",
                               video_path=video, with_edits=with_edits)

    def _shown(self):
        return bool(self.screen.btn_reexport.grid_info())

    def test_button_hidden_without_state(self):
        """B) Kein Transkript -> bisheriges Verhalten, kein Button."""
        self.controller.last_transcript = None
        self.screen.set_result(self.out_name, filename="clipA.mp4",
                               video_path=VIDEO_A)
        self.assertFalse(self._shown())
        self.assertEqual(self.screen.edited_label.cget("text"), "")

    def test_button_hidden_on_mismatch(self):
        """G) Transcript von anderem Video -> kein Button, Re-Export No-Op."""
        self.controller.last_transcript = {
            "video_path": VIDEO_B, "segments": _segments()}
        self.screen.set_result(self.out_name, filename="clipA.mp4",
                               video_path=VIDEO_A)
        self.assertFalse(self._shown())
        with patch.object(
                self.controller.get_screen("processing"),
                "set_project") as sp:
            self.screen.reexport()
        sp.assert_not_called()

    def test_button_shown_with_matching_state(self):
        """C) Passender State -> Button sichtbar."""
        self._show_result()
        self.assertTrue(self._shown())

    def test_edited_hint(self):
        """A) Hinweis nur bei Export mit Edits."""
        self._show_result(with_edits=True)
        self.assertTrue(self.screen.edited_label.cget("text"))
        self._show_result(with_edits=False)
        self.assertEqual(self.screen.edited_label.cget("text"), "")

    def test_reexport_calls_set_project(self):
        """D) Klick -> bestehende Processing-Mechanik mit Kontext."""
        self._show_result()
        processing = self.controller.get_screen("processing")
        with patch.object(processing, "set_project") as sp:
            self.screen.reexport()
        sp.assert_called_once_with(VIDEO_A, model="tiny", language="de",
                                   caption_style=None)

    def test_reexport_uses_current_edits(self):
        """E/F) Aktueller Edit-State fließt ein; neuer Edit -> neue Daten."""
        import ui.screens.processing as proc_mod
        self._show_result()
        self.controller.last_transcript["segments"][0]["text"] = \
            "Hello beautiful world"
        processing = self.controller.get_screen("processing")
        with patch.object(proc_mod, "CaptiPipeline") as mk_pipe, \
             patch.object(type(processing), "_cleanup_temp",
                          lambda self: None):
            self.screen.reexport()
        _a, kwargs = mk_pipe.return_value.run_async.call_args
        self.assertEqual(kwargs["override_segments"][0]["text"],
                         "Hello beautiful world")
        # F: erneuter Edit -> nächster Re-Export nutzt neue Daten
        self.controller.last_transcript["segments"][0]["text"] = \
            "Hello amazing beautiful world"
        with patch.object(proc_mod, "CaptiPipeline") as mk_pipe2, \
             patch.object(type(processing), "_cleanup_temp",
                          lambda self: None):
            self.screen.reexport()
        _a2, kwargs2 = mk_pipe2.return_value.run_async.call_args
        self.assertEqual(kwargs2["override_segments"][0]["text"],
                         "Hello amazing beautiful world")

    def test_done_returns_to_result_with_flag(self):
        """J) Erfolg -> Result Screen, with_edits propagiert."""
        processing = self.controller.get_screen("processing")
        processing.video_path = VIDEO_A
        processing.model = "tiny"
        processing.language = "de"
        processing.project_caption_style = None
        processing._last_run_used_edits = True
        pipe = MagicMock()
        pipe.last_segments = _segments()
        processing._pipeline = pipe
        processing._on_pipeline_done(self.out_name)
        self.assertEqual(self.controller.current_screen, "result")
        result = self.controller.get_screen("result")
        self.assertEqual(result.video_path, VIDEO_A)
        self.assertTrue(result.with_edits)
        self.assertTrue(result.edited_label.cget("text"))

    def test_cancel_and_error_keep_edits(self):
        """H/I) Cancel/Failure nach Re-Export-Start behalten Edits."""
        self._show_result()
        processing = self.controller.get_screen("processing")
        for kind, payload in (("cancelled", "Abbruch"), ("error", "boom")):
            processing._ui_queue = queue.Queue()
            processing._polling = True
            processing._ui_queue.put((kind, payload))
            processing._drain_ui_queue()
            kept = self.controller.get_transcript_segments(VIDEO_A)
            self.assertEqual(kept[0]["text"], "Hello world")

    def test_reexport_skips_whisper(self):
        """L/N) Override-Lauf: keine Transkription, Umlaute intakt."""
        tmp = _tmpdir(self)
        (tmp / "clip.mp4").write_bytes(b"x")
        captured = {}
        engine, processor, renderer = _mock_stack(captured)
        helper_segs = copy.deepcopy(_segments())
        helper_segs[0]["text"] = "Hello beautiful world"
        pipe = CaptiPipeline(temp_dir=str(tmp / "_temp"))
        with patch("pipeline.create_subtitle_engine", return_value=engine), \
             patch("pipeline.create_video_processor", return_value=processor), \
             patch("pipeline.create_caption_renderer", return_value=renderer):
            pipe.run(str(tmp / "clip.mp4"), model_size="tiny", language="de",
                     override_segments=helper_segs)
        engine.transcribe.assert_not_called()                       # L
        self.assertEqual(captured["ass_segments"][0]["text"],
                         "Hello beautiful world")
        self.assertEqual(captured["ass_segments"][1]["text"],
                         "Grüße aus München")                       # N


if __name__ == "__main__":
    unittest.main()
