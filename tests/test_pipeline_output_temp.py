"""Fix-Block 3: B4 (kollisionsfreie Outputs) + B5 (System-Temp).

B4: resolve_output_path() vergibt <name>_subtitled[_N].mp4, niemals stilles
    Ueberschreiben, Fallback bei nicht beschreibbarem Zielordner.
B5: capti_core.paths.temp_dir() liegt im System-Temp (nicht neben EXE/Projekt),
    funktioniert in Development und Frozen, Pipeline kann dort arbeiten.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import CaptiPipeline, resolve_output_path


def _tmpdir(testcase, prefix="capti_out_"):
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    testcase.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
    return tmp


class TestResolveOutputPath(unittest.TestCase):

    def test_first_output_next_to_source(self):
        tmp = _tmpdir(self)
        src = tmp / "clip.mp4"
        src.write_bytes(b"x")
        out = resolve_output_path(str(src))
        self.assertEqual(out, str(tmp / "clip_subtitled.mp4"))

    def test_existing_output_gets_suffix(self):
        tmp = _tmpdir(self)
        (tmp / "clip.mp4").write_bytes(b"x")
        (tmp / "clip_subtitled.mp4").write_bytes(b"alt")
        out = resolve_output_path(str(tmp / "clip.mp4"))
        self.assertEqual(out, str(tmp / "clip_subtitled_1.mp4"))
        # Original bleibt unberuehrt
        self.assertEqual((tmp / "clip_subtitled.mp4").read_bytes(), b"alt")

    def test_multiple_collisions(self):
        tmp = _tmpdir(self)
        (tmp / "clip.mp4").write_bytes(b"x")
        for i in ["", "_1", "_2", "_3"]:
            (tmp / f"clip_subtitled{i}.mp4").write_bytes(b"alt")
        out = resolve_output_path(str(tmp / "clip.mp4"))
        self.assertEqual(out, str(tmp / "clip_subtitled_4.mp4"))

    def test_umlauts_special_chars(self):
        tmp = _tmpdir(self)
        src = tmp / "Grüße Video äöü (2024).mp4"
        src.write_bytes(b"x")
        out = resolve_output_path(str(src))
        self.assertEqual(out, str(tmp / "Grüße Video äöü (2024)_subtitled.mp4"))

    def test_unwritable_dir_falls_back_to_system_temp(self):
        tmp = _tmpdir(self)
        src = tmp / "clip.mp4"
        src.write_bytes(b"x")
        with patch("os.access", return_value=False):
            out = resolve_output_path(str(src))
        fallback = Path(tempfile.gettempdir()) / "Capti"
        self.assertEqual(Path(out).parent, fallback)
        self.assertTrue(out.endswith("clip_subtitled.mp4"))
        self.assertTrue(fallback.is_dir())

    def test_no_random_names(self):
        tmp = _tmpdir(self)
        (tmp / "clip.mp4").write_bytes(b"x")
        outs = {resolve_output_path(str(tmp / "clip.mp4")) for _ in range(3)}
        # deterministisch: solange nichts erstellt wird, immer derselbe Name
        self.assertEqual(outs, {str(tmp / "clip_subtitled.mp4")})


class TestPipelineUsesUniqueOutput(unittest.TestCase):

    def _pipeline(self):
        tmp = _tmpdir(self)
        events = {"done": [], "error": []}
        pipe = CaptiPipeline(
            temp_dir=str(tmp / "_temp"),
            on_done=lambda p: events["done"].append(p),
            on_error=lambda e: events["error"].append(e),
        )
        return pipe, tmp, events

    def _mock_engines(self, pipe):
        engine = MagicMock()
        engine.transcribe.return_value = [{
            "start": 0.0, "end": 1.0, "text": "Hi",
            "words": [{"word": "Hi", "start": 0.0, "end": 1.0, "probability": 1.0}],
        }]
        processor = MagicMock()
        processor.extract_audio.side_effect = lambda v, a: a
        processor.get_video_info.return_value = {"streams": [{"width": 720, "height": 1280}]}
        renderer = MagicMock()

        def fake_ass(segments, path, video_width=None, video_height=None):
            Path(path).write_text("[Script Info]", encoding="utf-8")
            return path

        renderer.generate_ass.side_effect = fake_ass
        processor.embed_ass.side_effect = lambda v, a, o: o
        return engine, processor, renderer

    def test_existing_output_not_overwritten(self):
        pipe, tmp, events = self._pipeline()
        engine, processor, renderer = self._mock_engines(pipe)
        src = tmp / "clip.mp4"
        src.write_bytes(b"orig-video")
        (tmp / "clip_subtitled.mp4").write_bytes(b"alter-output")
        with patch("pipeline.create_subtitle_engine", return_value=engine), \
             patch("pipeline.create_video_processor", return_value=processor), \
             patch("pipeline.create_caption_renderer", return_value=renderer):
            result = pipe.run(str(src), model_size="tiny", language="de")
        self.assertTrue(result.endswith("clip_subtitled_1.mp4"))
        self.assertEqual((tmp / "clip_subtitled.mp4").read_bytes(), b"alter-output")
        called_out = processor.embed_ass.call_args[0][2]
        self.assertTrue(called_out.endswith("clip_subtitled_1.mp4"))
        self.assertEqual(events["done"], [result])
        self.assertEqual(events["error"], [])


class TestCaptiTempDir(unittest.TestCase):

    def test_temp_dir_in_system_temp(self):
        from capti_core.paths import temp_dir
        td = temp_dir()
        self.assertEqual(td.parent, Path(tempfile.gettempdir()))
        self.assertEqual(td.name, "Capti")

    def test_temp_dir_not_under_project_or_exe(self):
        from capti_core.paths import temp_dir
        td = temp_dir()
        repo = Path(__file__).resolve().parent.parent
        self.assertNotEqual(td, repo / "_temp")
        self.assertFalse(str(td).startswith(str(repo)))
        self.assertFalse(str(td).startswith(os.path.dirname(sys.executable)))

    def test_temp_dir_creatable_and_usable(self):
        from capti_core.paths import temp_dir
        td = temp_dir()
        td.mkdir(parents=True, exist_ok=True)
        probe = td / "capti_tmp_probe.tmp"
        try:
            probe.write_bytes(b"x")
            self.assertTrue(probe.exists())
        finally:
            try:
                probe.unlink()
            except OSError:
                pass

    def test_main_temp_dir_matches(self):
        import main
        from capti_core.paths import temp_dir
        self.assertEqual(Path(main.TEMP_DIR), temp_dir())

    def test_processing_temp_dir_matches(self):
        from capti_core.paths import temp_dir
        from ui.screens.processing import ProcessingScreen
        self.assertEqual(Path(ProcessingScreen._temp_dir()), temp_dir())

    def test_pipeline_temp_roundtrip_and_cleanup(self):
        from capti_core.paths import temp_dir
        td = temp_dir()
        td.mkdir(parents=True, exist_ok=True)
        work = td / "capti_test_roundtrip"
        work.mkdir(exist_ok=True)
        try:
            pipe = CaptiPipeline(temp_dir=str(work))
            pipe.temp_dir.mkdir(parents=True, exist_ok=True)
            f = work / "clip_audio.wav"
            f.write_bytes(b"RIFF")
            self.assertTrue(f.exists())
        finally:
            import shutil
            shutil.rmtree(work, ignore_errors=True)
        self.assertFalse(work.exists())


if __name__ == "__main__":
    unittest.main()
