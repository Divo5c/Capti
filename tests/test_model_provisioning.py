"""Fix-Block 9 (C6): Whisper-Modell-Bereitstellung ohne Netzwerk.

- Cache-Hit: kein Download-Status, direkt weiter (kein Re-Download).
- Cache-Miss: STATUS_DOWNLOAD_MODEL + Log vor Engine-Erstellung, SUCCESS danach.
- Fehler/Timeout: verstaendliche Meldung, kein Erfolg.
- Cancel: vor/während Laden -> CANCELLED, kein Transcribe.
- Kein Test lädt echte Modelle oder nutzt Netzwerk (Mocks/Fakes).
"""

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipeline as pipeline_mod
from pipeline import STATUS_DOWNLOAD_MODEL, CaptiPipeline
from subtitle_engine import SubtitleEngine


def _tmpdir(testcase, prefix="capti_modelprov_"):
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    testcase.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
    return tmp


def _segments():
    return [{
        "start": 0.0, "end": 1.0, "text": "Hallo",
        "words": [{"word": "Hallo", "start": 0.0, "end": 1.0, "probability": 1.0}],
    }]


def _make_pipeline(tmp, **overrides):
    events = {"status": [], "progress": [], "log": [],
              "done": [], "error": [], "cancelled": []}
    pipe = CaptiPipeline(
        temp_dir=str(tmp / "_temp"),
        on_status=lambda m: events["status"].append(m),
        on_progress=lambda p: events["progress"].append(p),
        on_log=lambda l, m: events["log"].append((l, m)),
        on_done=lambda p: events["done"].append(p),
        on_error=lambda e: events["error"].append(e),
        on_cancelled=lambda m: events["cancelled"].append(m),
        **overrides,
    )
    return pipe, events


def _mock_stack(engine=None, processor=None, renderer=None):
    engine = engine if engine is not None else MagicMock()
    processor = processor if processor is not None else MagicMock()
    renderer = renderer if renderer is not None else MagicMock()
    if isinstance(engine, MagicMock):
        engine.transcribe.return_value = _segments()
    if isinstance(processor, MagicMock):
        processor.extract_audio.side_effect = lambda v, a, **k: a
        processor.get_video_info.return_value = {"streams": [{"width": 720, "height": 1280}]}
        processor.embed_ass.side_effect = lambda v, a, o, **k: o
    if isinstance(renderer, MagicMock):
        def fake_ass(segments, path, video_width=None, video_height=None):
            Path(path).write_text("[Script Info]", encoding="utf-8")
            return path
        renderer.generate_ass.side_effect = fake_ass
    return engine, processor, renderer


def _patched_run(pipe, src, engine, processor, renderer):
    stack = (patch("pipeline.create_subtitle_engine", return_value=engine),
             patch("pipeline.create_video_processor", return_value=processor),
             patch("pipeline.create_caption_renderer", return_value=renderer))
    for ctx in stack:
        ctx.__enter__()
    try:
        return pipe.run(str(src), model_size="tiny", language="de")
    finally:
        for ctx in reversed(stack):
            ctx.__exit__(None, None, None)


class TestCacheHitNoDownload(unittest.TestCase):

    def test_cached_model_skips_download_status(self):
        tmp = _tmpdir(self)
        (tmp / "clip.mp4").write_bytes(b"x")
        pipe, events = _make_pipeline(tmp)
        engine, processor, renderer = _mock_stack()
        with patch.object(pipeline_mod.SubtitleEngine, "is_model_cached",
                          return_value=True):
            result = _patched_run(pipe, tmp / "clip.mp4", engine, processor, renderer)
        self.assertTrue(result.endswith("clip_subtitled.mp4"))
        self.assertNotIn(STATUS_DOWNLOAD_MODEL, events["status"])
        self.assertTrue(any("bereits vorhanden" in m for _, m in events["log"]))
        self.assertTrue(any("bereit" in m for _, m in events["log"]))
        self.assertEqual(len(events["done"]), 1)

    def test_cached_model_no_extra_progress(self):
        tmp = _tmpdir(self)
        (tmp / "clip.mp4").write_bytes(b"x")
        pipe, events = _make_pipeline(tmp)
        engine, processor, renderer = _mock_stack()
        with patch.object(pipeline_mod.SubtitleEngine, "is_model_cached",
                          return_value=True):
            _patched_run(pipe, tmp / "clip.mp4", engine, processor, renderer)
        # Kein Zwischen-Progress zwischen 5 und 15 (kein Fake-Fortschritt)
        between = [p for p in events["progress"] if 5.0 < p < 15.0]
        self.assertEqual(between, [])


class TestCacheMissDownloadFlow(unittest.TestCase):

    def test_download_status_before_factory(self):
        tmp = _tmpdir(self)
        (tmp / "clip.mp4").write_bytes(b"x")
        pipe, events = _make_pipeline(tmp)
        engine, processor, renderer = _mock_stack()

        def recording_factory(**kwargs):
            events["status"].append("factory-called")
            return engine

        with patch.object(pipeline_mod.SubtitleEngine, "is_model_cached",
                          return_value=False), \
             patch("pipeline.create_subtitle_engine",
                   side_effect=recording_factory), \
             patch("pipeline.create_video_processor", return_value=processor), \
             patch("pipeline.create_caption_renderer", return_value=renderer):
            pipe.run(str(tmp / "clip.mp4"), model_size="tiny", language="de")
        self.assertIn(STATUS_DOWNLOAD_MODEL, events["status"])
        dl_idx = events["status"].index(STATUS_DOWNLOAD_MODEL)
        fac_idx = events["status"].index("factory-called")
        self.assertLess(dl_idx, fac_idx)
        self.assertTrue(any("wird geladen" in m for _, m in events["log"]))
        self.assertTrue(any("bereit" in m for _, m in events["log"]))

    def test_unknown_cache_state_shows_download_status(self):
        tmp = _tmpdir(self)
        (tmp / "clip.mp4").write_bytes(b"x")
        pipe, events = _make_pipeline(tmp)
        engine, processor, renderer = _mock_stack()
        with patch.object(pipeline_mod.SubtitleEngine, "is_model_cached",
                          return_value=None):
            _patched_run(pipe, tmp / "clip.mp4", engine, processor, renderer)
        self.assertIn(STATUS_DOWNLOAD_MODEL, events["status"])
        self.assertEqual(len(events["done"]), 1)


class TestDownloadErrors(unittest.TestCase):

    def test_connection_error_no_success(self):
        tmp = _tmpdir(self)
        (tmp / "clip.mp4").write_bytes(b"x")
        pipe, events = _make_pipeline(tmp)
        engine, processor, renderer = _mock_stack()
        with patch.object(pipeline_mod.SubtitleEngine, "is_model_cached",
                          return_value=False), \
             patch("pipeline.create_subtitle_engine",
                   side_effect=ConnectionError("Netz weg")), \
             patch("pipeline.create_video_processor", return_value=processor), \
             patch("pipeline.create_caption_renderer", return_value=renderer), \
             self.assertRaises(ConnectionError):
            pipe.run(str(tmp / "clip.mp4"), model_size="tiny")
        self.assertEqual(events["done"], [])
        self.assertEqual(len(events["error"]), 1)
        engine.transcribe.assert_not_called()

    def test_load_model_wraps_with_hint(self):
        with patch("subtitle_engine.WhisperModel",
                   side_effect=ConnectionError("Netz weg")):
            eng = SubtitleEngine.__new__(SubtitleEngine)
            eng.model_size = "small"
            eng.device = "cpu"
            eng.compute_type = "int8"
            eng.model = None
            with self.assertRaises(RuntimeError) as ctx:
                eng._load_model()
        msg = str(ctx.exception)
        self.assertIn("small", msg)
        self.assertIn("Internetverbindung", msg)
        self.assertIsInstance(ctx.exception.__cause__, ConnectionError)

    def test_invalid_model_size_reported(self):
        with patch("subtitle_engine.WhisperModel",
                   side_effect=ValueError("Invalid model size")):
            eng = SubtitleEngine.__new__(SubtitleEngine)
            eng.model_size = "riesig"
            eng.device = "cpu"
            eng.compute_type = "int8"
            eng.model = None
            with self.assertRaises(RuntimeError) as ctx:
                eng._load_model()
        self.assertIn("riesig", str(ctx.exception))


class TestIsModelCached(unittest.TestCase):

    def test_cached_true(self):
        with patch("faster_whisper.utils.download_model", return_value="/cache/m"):
            self.assertTrue(SubtitleEngine.is_model_cached("tiny"))

    def test_missing_is_false(self):
        from huggingface_hub.utils import LocalEntryNotFoundError
        with patch("faster_whisper.utils.download_model",
                   side_effect=LocalEntryNotFoundError("missing")):
            self.assertFalse(SubtitleEngine.is_model_cached("tiny"))

    def test_other_error_is_unknown(self):
        with patch("faster_whisper.utils.download_model",
                   side_effect=ValueError("Invalid model size")):
            self.assertIsNone(SubtitleEngine.is_model_cached("riesig"))

    def test_valid_models_multilingual(self):
        from capti_core.project import VALID_MODELS
        for m in VALID_MODELS:
            self.assertNotIn(".en", m)
        from faster_whisper.utils import available_models
        for m in VALID_MODELS:
            self.assertIn(m, available_models())


class TestCancelDuringLoad(unittest.TestCase):

    def test_cancel_before_load_no_factory(self):
        tmp = _tmpdir(self)
        (tmp / "clip.mp4").write_bytes(b"x")
        pipe, events = _make_pipeline(tmp)
        engine, processor, renderer = _mock_stack()
        factory = MagicMock(return_value=engine)
        pipe.cancel()
        with patch("pipeline.create_subtitle_engine", factory), \
             patch("pipeline.create_video_processor", return_value=processor), \
             patch("pipeline.create_caption_renderer", return_value=renderer):
            from video_processor import CancelledError
            with self.assertRaises(CancelledError):
                pipe.run(str(tmp / "clip.mp4"), model_size="tiny")
        factory.assert_not_called()
        self.assertEqual(len(events["cancelled"]), 1)
        self.assertEqual(events["done"], [])

    def test_cancel_during_slow_load_no_transcribe(self):
        tmp = _tmpdir(self)
        (tmp / "clip.mp4").write_bytes(b"x")
        pipe, events = _make_pipeline(tmp)
        engine, processor, renderer = _mock_stack()
        started = threading.Event()

        def slow_factory(**kwargs):
            started.set()
            time.sleep(2.0)
            return engine

        with patch.object(pipeline_mod.SubtitleEngine, "is_model_cached",
                          return_value=False), \
             patch("pipeline.create_subtitle_engine", side_effect=slow_factory), \
             patch("pipeline.create_video_processor", return_value=processor), \
             patch("pipeline.create_caption_renderer", return_value=renderer):
            job = pipe.run_async(str(tmp / "clip.mp4"), model_size="tiny")
            self.assertTrue(started.wait(timeout=5))
            job.cancel()
            self.assertTrue(job.wait(timeout=10))
        engine.transcribe.assert_not_called()
        self.assertEqual(len(events["cancelled"]), 1)
        self.assertEqual(events["done"], [])

    def test_success_after_slow_load_without_cancel(self):
        tmp = _tmpdir(self)
        (tmp / "clip.mp4").write_bytes(b"x")
        pipe, events = _make_pipeline(tmp)
        engine, processor, renderer = _mock_stack()

        def slow_factory(**kwargs):
            time.sleep(0.3)
            return engine

        with patch.object(pipeline_mod.SubtitleEngine, "is_model_cached",
                          return_value=False), \
             patch("pipeline.create_subtitle_engine", side_effect=slow_factory), \
             patch("pipeline.create_video_processor", return_value=processor), \
             patch("pipeline.create_caption_renderer", return_value=renderer):
            job = pipe.run_async(str(tmp / "clip.mp4"), model_size="tiny")
            self.assertTrue(job.wait(timeout=10))
        self.assertEqual(len(events["done"]), 1)
        self.assertEqual(events["cancelled"], [])


if __name__ == "__main__":
    unittest.main()
