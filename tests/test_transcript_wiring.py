"""Fix-Block 20: Pipeline-Ergebnis -> Transkript-Preview-Verdrahtung.

Whisper -> pipeline.last_segments -> controller.last_transcript
-> CaptionStyle.on_show -> set_transcript() -> RenderCaption -> Preview.
Keine echten Whisper-/FFmpeg-Läufe (Mocks/Fakes).
"""

import os
import queue
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Hermetisch: echte Nutzer-Config/History niemals lesen/schreiben
import tempfile as _tmp

import customtkinter as ctk

if "CAPTI_CONFIG_FILE" not in os.environ:
    os.environ["APPDATA"] = _tmp.mkdtemp(prefix="capti_test_appdata_")

from pipeline import CaptiPipeline
from ui import i18n
from ui.app_controller import AppController
from ui.screens import caption_style as cs_mod


def _segments():
    return [{
        "start": 5.0, "end": 7.0, "text": "Hallo Welt",
        "words": [
            {"word": "Hallo", "start": 5.0, "end": 5.8, "probability": 0.9},
            {"word": "Welt", "start": 5.9, "end": 7.0, "probability": 0.9},
        ],
    }]


def _tmpdir(testcase, prefix="capti_txwire_"):
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    testcase.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
    return tmp


def _mock_stack():
    engine = MagicMock()
    engine.transcribe.return_value = _segments()
    processor = MagicMock()
    processor.extract_audio.side_effect = lambda v, a, **k: a
    processor.get_video_info.return_value = {"streams": [{"width": 720, "height": 1280}]}
    processor.embed_ass.side_effect = lambda v, a, o, **k: o
    renderer = MagicMock()

    def fake_ass(segments, path, video_width=None, video_height=None):
        Path(path).write_text("[Script Info]", encoding="utf-8")
        return path

    renderer.generate_ass.side_effect = fake_ass
    return engine, processor, renderer


class TestPipelineStoresTranscript(unittest.TestCase):

    def test_last_segments_after_success(self):
        tmp = _tmpdir(self)
        (tmp / "clip.mp4").write_bytes(b"x")
        pipe = CaptiPipeline(temp_dir=str(tmp / "_temp"))
        self.assertIsNone(pipe.last_segments)
        self.assertIsNone(pipe.last_video_path)
        engine, processor, renderer = _mock_stack()
        with patch("pipeline.create_subtitle_engine", return_value=engine), \
             patch("pipeline.create_video_processor", return_value=processor), \
             patch("pipeline.create_caption_renderer", return_value=renderer):
            pipe.run(str(tmp / "clip.mp4"), model_size="tiny", language="de")
        self.assertEqual(pipe.last_video_path, str(tmp / "clip.mp4"))
        self.assertEqual(len(pipe.last_segments), 1)
        self.assertEqual(pipe.last_segments[0]["text"], "Hallo Welt")
        self.assertEqual(
            [w["word"] for w in pipe.last_segments[0]["words"]],
            ["Hallo", "Welt"])
        self.assertAlmostEqual(pipe.last_segments[0]["words"][0]["start"], 5.0)


class TestProcessingWiring(unittest.TestCase):

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

    def tearDown(self):
        i18n.set_language(self._prev_lang)
        self.patcher.stop()
        self.tmp.cleanup()

    def _processing_screen(self, video="C:/vids/clip.mp4"):
        screen = self.controller.get_screen("processing")
        screen.video_path = video
        screen.model = "tiny"
        screen.language = "de"
        return screen

    def test_done_stores_controller_transcript(self):
        screen = self._processing_screen()
        pipe = MagicMock()
        pipe.last_segments = _segments()
        screen._pipeline = pipe
        screen._on_pipeline_done("C:/vids/clip_subtitled.mp4")
        last = self.controller.last_transcript
        self.assertIsNotNone(last)
        self.assertEqual(last["video_path"], "C:/vids/clip.mp4")
        self.assertEqual(len(last["segments"]), 1)
        self.assertAlmostEqual(last["segments"][0]["words"][0]["start"], 5.0)

    def test_done_without_segments_stores_nothing(self):
        screen = self._processing_screen()
        pipe = MagicMock()
        pipe.last_segments = None
        screen._pipeline = pipe
        screen._on_pipeline_done("C:/vids/clip_subtitled.mp4")
        self.assertIsNone(self.controller.last_transcript)

    def test_error_keeps_transcript(self):
        # Block 22: Fehler löscht keinen bestehenden Edit-State
        # (last_transcript wird nur bei Erfolg geschrieben; der
        # Video-Match-Guard verhindert veraltete Anzeige).
        screen = self.controller.get_screen("processing")
        kept = {"video_path": "x", "segments": _segments()}
        self.controller.last_transcript = kept
        screen._ui_queue = queue.Queue()
        screen._polling = True
        screen._ui_queue.put(("error", "boom"))
        screen._drain_ui_queue()
        self.assertEqual(self.controller.last_transcript, kept)

    def test_cancel_keeps_transcript(self):
        # Block 22: Cancel lässt bestehenden Edit-State intakt.
        screen = self.controller.get_screen("processing")
        kept = {"video_path": "x", "segments": _segments()}
        self.controller.last_transcript = kept
        screen._ui_queue = queue.Queue()
        screen._polling = True
        screen._ui_queue.put(("cancelled", "Abbruch"))
        screen._drain_ui_queue()
        self.assertEqual(self.controller.last_transcript, kept)

    def test_done_event_from_worker_thread(self):
        """Queue-Mechanismus: Worker stellt ein, Main-Thread verarbeitet."""
        screen = self._processing_screen()
        pipe = MagicMock()
        pipe.last_segments = _segments()
        screen._pipeline = pipe

        def worker():
            screen._ui_queue.put(("done", "C:/vids/clip_subtitled.mp4"))

        screen._ui_queue = queue.Queue()
        screen._polling = True
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        t.join(timeout=10)
        screen._drain_ui_queue()
        last = self.controller.last_transcript
        self.assertIsNotNone(last)
        self.assertEqual(last["segments"][0]["text"], "Hallo Welt")


class TestCaptionStylePull(unittest.TestCase):

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

    def tearDown(self):
        i18n.set_language(self._prev_lang)
        self.patcher.stop()
        self.tmp.cleanup()
        import contextlib
        with contextlib.suppress(Exception):
            self.screen.destroy()

    def test_no_transcript_stays_sample(self):
        self.controller.pending_project = {"video_path": "C:/vids/a.mp4"}
        self.controller.last_transcript = None
        self.screen.on_show()
        self.assertEqual(self.screen._preview_mode, "sample")

    def test_matching_pull_uses_transcript(self):
        self.controller.pending_project = {"video_path": "C:/vids/clip.mp4"}
        self.controller.last_transcript = {
            "video_path": "C:/vids/clip.mp4", "segments": _segments()}
        self.screen.on_show()
        self.assertEqual(self.screen._preview_mode, "transcript")
        self.assertEqual([w.word for w in self.screen._preview_caption.words],
                         ["Hallo", "Welt"])
        self.assertEqual([e["text"] for e in self.screen._preview_words],
                         ["Hallo", "Welt"])

    def test_mismatch_stays_sample(self):
        self.controller.pending_project = {"video_path": "C:/vids/neu.mp4"}
        self.controller.last_transcript = {
            "video_path": "C:/vids/alt.mp4", "segments": _segments()}
        self.screen.on_show()
        self.assertEqual(self.screen._preview_mode, "sample")

    def test_stale_replaced_by_new_transcript(self):
        self.controller.pending_project = {"video_path": "C:/vids/clip.mp4"}
        self.controller.last_transcript = {
            "video_path": "C:/vids/clip.mp4", "segments": _segments()}
        self.screen.on_show()
        self.assertEqual(self.screen._preview_mode, "transcript")
        other = [{"start": 20.0, "end": 21.0, "text": "Neu",
                  "words": [{"word": "Neu", "start": 20.0, "end": 21.0}]}]
        self.controller.last_transcript = {
            "video_path": "C:/vids/clip.mp4", "segments": other}
        self.screen.on_show()
        self.assertEqual([w.word for w in self.screen._preview_caption.words],
                         ["Neu"])


if __name__ == "__main__":
    unittest.main()
