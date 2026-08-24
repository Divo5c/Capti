"""
Tests für die UI-agnostische CaptiPipeline (Callbacks, Orchestrierung).

Die Pipeline selbst wird ohne echtes Whisper-Modell getestet:
Engine/Processor/Renderer werden gemockt (Monkeypatching).
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import CaptiPipeline


def make_segments():
    return [
        {
            "start": 0.0,
            "end": 2.0,
            "text": "Hallo wie geht es dir",
            "words": [
                {"word": "Hallo", "start": 0.0, "end": 0.5, "probability": 0.9},
                {"word": "wie", "start": 0.6, "end": 0.8, "probability": 0.9},
                {"word": "geht", "start": 0.9, "end": 1.2, "probability": 0.9},
                {"word": "es", "start": 1.3, "end": 1.4, "probability": 0.9},
                {"word": "dir", "start": 1.5, "end": 1.9, "probability": 0.9},
            ],
        },
    ]


class TestCaptiPipeline(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.events = {"status": [], "progress": [], "log": [], "done": [], "error": []}
        self.pipeline = CaptiPipeline(
            temp_dir=self.tmp.name,
            on_status=lambda m: self.events["status"].append(m),
            on_progress=lambda p: self.events["progress"].append(p),
            on_log=lambda l, m: self.events["log"].append((l, m)),
            on_done=lambda p: self.events["done"].append(p),
            on_error=lambda e: self.events["error"].append(e),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _mock_engines(self):
        """Mockt Engine/Processor/Renderer innerhalb der Pipeline."""
        engine = MagicMock()
        engine.transcribe.return_value = make_segments()
        processor = MagicMock()
        processor.extract_audio.side_effect = lambda v, a: a
        processor.get_video_info.return_value = {"streams": [{"width": 720, "height": 1280}]}
        renderer = MagicMock()

        def fake_generate_ass(segments, path, video_width=None, video_height=None):
            with open(path, "w", encoding="utf-8") as f:
                f.write("[Script Info]" + chr(10))
            return path

        renderer.generate_ass.side_effect = fake_generate_ass
        processor.embed_ass.side_effect = lambda v, a, o: o

        self.pipeline.subtitle_engine = engine
        self.pipeline.video_processor = processor
        self.pipeline.caption_renderer = renderer
        return engine, processor, renderer

    @patch("pipeline.create_subtitle_engine")
    @patch("pipeline.create_video_processor")
    @patch("pipeline.create_caption_renderer")
    def test_run_success_flow(self, mock_renderer_factory, mock_vp_factory, mock_se_factory):
        """Kompletter Erfolgs-Durchlauf: Callbacks + Output-Pfad."""
        engine, processor, renderer = self._mock_engines()
        mock_se_factory.return_value = engine
        mock_vp_factory.return_value = processor
        mock_renderer_factory.return_value = renderer

        # dirname("video.mp4") ist leer -> Output relativ: "video_subtitled.mp4"
        out_path = "video_subtitled.mp4"
        result = self.pipeline.run("video.mp4", model_size="tiny", language="de")

        self.assertEqual(result, out_path)
        self.assertEqual(self.events["done"], [out_path])
        self.assertEqual(self.events["error"], [])
        # Progress endet bei 100
        self.assertEqual(self.events["progress"][-1], 100)
        # Gruppierung wurde angewendet (Layout aus 720x1280 -> portrait)
        grouped_arg = renderer.generate_ass.call_args[0][0]
        self.assertIsInstance(grouped_arg, list)
        # PlayRes wurde an Renderer übergeben
        kwargs = renderer.generate_ass.call_args[1]
        self.assertEqual(kwargs["video_width"], 720)
        self.assertEqual(kwargs["video_height"], 1280)

    @patch("pipeline.create_subtitle_engine")
    @patch("pipeline.create_video_processor")
    @patch("pipeline.create_caption_renderer")
    def test_error_callback_and_raise(self, mock_renderer_factory, mock_vp_factory, mock_se_factory):
        """Fehler werden an on_error gemeldet und erneut geworfen."""
        engine = MagicMock()
        engine.transcribe.side_effect = RuntimeError("boom")
        mock_se_factory.return_value = engine  # Pipeline erstellt Engine neu -> Factory mocken

        with self.assertRaises(RuntimeError):
            self.pipeline.run("video.mp4")
        self.assertEqual(len(self.events["error"]), 1)
        self.assertIn("boom", self.events["error"][0])
        self.assertEqual(self.events["done"], [])

    def test_callbacks_optional(self):
        """Pipeline funktioniert auch ohne Callbacks."""
        p = CaptiPipeline(temp_dir=self.tmp.name)
        self.assertIsNotNone(p)

    def test_progress_clamped(self):
        """Progress wird auf 0..100 begrenzt."""
        captured = []
        p = CaptiPipeline(temp_dir=self.tmp.name, on_progress=captured.append)
        p._progress(150)
        p._progress(-5)
        self.assertEqual(captured, [100, 0])


if __name__ == "__main__":
    unittest.main()