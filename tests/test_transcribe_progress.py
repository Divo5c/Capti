"""Fix-Block 6 (C3): echter Transkriptionsfortschritt.

Belastbar: Segment-Endzeiten / Audio-Dauer (kein Timer-Fake).
Mapping: Transkription 30 -> 70 im Gesamtfortschritt.
Fake-Transcriber statt Whisper-Modell-Downloads.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import CaptiPipeline
from subtitle_engine import SubtitleEngine
from video_processor import CancelledError


def _tmpdir(testcase, prefix="capti_txprog_"):
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    testcase.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
    return tmp


class _FakeSegment:
    def __init__(self, start, end, text="w", words=None):
        self.start = start
        self.end = end
        self.text = text
        self.words = words or []


class _FakeInfo:
    def __init__(self, duration=None, language="de"):
        self.duration = duration
        self.language = language


class _FakeModel:
    """Simuliert faster-whisper: Segmente kommen lazy, info sofort."""

    def __init__(self, segments, duration):
        self._segments = segments
        self._duration = duration

    def transcribe(self, audio_path, **kwargs):
        return iter(self._segments), _FakeInfo(duration=self._duration)


def _engine_with(segments, duration):
    eng = SubtitleEngine.__new__(SubtitleEngine)
    eng.model_size = "tiny"
    eng.device = "cpu"
    eng.compute_type = "int8"
    eng.model = _FakeModel(segments, duration)
    return eng


def _wav(tmp: Path, name="a.wav", seconds=10.0, rate=16000):
    import wave
    path = tmp / name
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * int(seconds * rate))
    return str(path)


class TestTranscribeProgress(unittest.TestCase):

    def test_progress_fires_with_real_fractions(self):
        tmp = _tmpdir(self)
        audio = _wav(tmp, seconds=120.0)
        eng = _engine_with([
            _FakeSegment(0.0, 30.0), _FakeSegment(30.0, 60.0),
            _FakeSegment(60.0, 120.0),
        ], duration=120.0)
        seen = []
        out = eng.transcribe(audio, "de", on_progress=seen.append)
        self.assertEqual(len(out), 3)
        self.assertEqual(len(seen), 3)
        self.assertAlmostEqual(seen[0], 0.25)
        self.assertAlmostEqual(seen[1], 0.5)
        self.assertAlmostEqual(seen[2], 1.0)

    def test_fractions_clamped_to_unit_interval(self):
        tmp = _tmpdir(self)
        audio = _wav(tmp, seconds=10.0)
        eng = _engine_with([_FakeSegment(0.0, 999.0)], duration=10.0)
        seen = []
        eng.transcribe(audio, None, on_progress=seen.append)
        self.assertEqual(len(seen), 1)
        self.assertGreaterEqual(seen[0], 0.0)
        self.assertLessEqual(seen[0], 1.0)

    def test_progress_never_goes_backwards(self):
        tmp = _tmpdir(self)
        audio = _wav(tmp, seconds=100.0)
        eng = _engine_with([
            _FakeSegment(0.0, 80.0), _FakeSegment(80.0, 20.0),
            _FakeSegment(20.0, 100.0),
        ], duration=100.0)
        seen = []
        eng.transcribe(audio, None, on_progress=seen.append)
        from itertools import pairwise
        for a, b in pairwise(seen):
            self.assertLessEqual(a, b)

    def test_unknown_duration_fallback_no_progress(self):
        tmp = _tmpdir(self)
        # Keine WAV-Datei (kein Header-Fallback moeglich), info ohne Dauer
        raw = tmp / "a.raw"
        raw.write_bytes(b"\x00" * 100)
        eng = _engine_with([_FakeSegment(0.0, 5.0)], duration=None)
        seen = []
        out = eng.transcribe(str(raw), None, on_progress=seen.append)
        self.assertEqual(len(out), 1)  # Transkription funktioniert trotzdem
        self.assertEqual(seen, [])  # ehrlich: kein Fortschritt ohne Dauer

    def test_wav_header_fallback_duration(self):
        tmp = _tmpdir(self)
        audio = _wav(tmp, seconds=20.0)
        eng = _engine_with([_FakeSegment(0.0, 10.0)], duration=None)
        seen = []
        eng.transcribe(audio, None, on_progress=seen.append)
        self.assertEqual(len(seen), 1)
        self.assertAlmostEqual(seen[0], 0.5)

    def test_no_progress_after_completion(self):
        tmp = _tmpdir(self)
        audio = _wav(tmp, seconds=10.0)
        eng = _engine_with([_FakeSegment(0.0, 10.0)], duration=10.0)
        seen = []
        eng.transcribe(audio, None, on_progress=seen.append)
        count = len(seen)
        self.assertGreater(count, 0)
        # Nach Rueckkehr darf nichts mehr nachkommen (Loop ist beendet)
        self.assertEqual(len(seen), count)

    def test_cancel_stops_progress(self):
        tmp = _tmpdir(self)
        audio = _wav(tmp, seconds=100.0)
        eng = _engine_with(
            [_FakeSegment(float(i), float(i + 1)) for i in range(100)],
            duration=100.0)
        seen = []
        calls = {"n": 0}

        def cancel_after_two():
            calls["n"] += 1
            return calls["n"] > 2

        with self.assertRaises(CancelledError):
            eng.transcribe(audio, None, on_progress=seen.append,
                           should_cancel=cancel_after_two)
        n_at_cancel = len(seen)
        self.assertLess(n_at_cancel, 100)
        # Danach kommt nichts mehr (Schleife abgebrochen)
        self.assertEqual(len(seen), n_at_cancel)
        for f in seen:
            self.assertGreaterEqual(f, 0.0)
            self.assertLessEqual(f, 1.0)

    def test_normal_transcribe_unaffected(self):
        tmp = _tmpdir(self)
        audio = _wav(tmp, seconds=10.0)
        eng = _engine_without_progress(duration=10.0)
        out = eng.transcribe(audio, "de")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["words"], [])


def _engine_without_progress(duration):
    return _engine_with([_FakeSegment(0.0, 5.0)], duration=duration)


class FakeTxEngine:
    """Pipeline-taugliche Fake-Engine mit Fortschritt (Callable-Signatur)."""

    def __init__(self, segments, duration):
        self._segments = segments
        self._duration = duration

    def transcribe(self, audio_path, language=None, on_progress=None,
                   should_cancel=None):
        out = []
        for s in self._segments:
            if should_cancel is not None and should_cancel():
                from video_processor import CancelledError as _CE
                raise _CE("Verarbeitung abgebrochen")
            out.append({"start": s[0], "end": s[1], "text": "t", "words": []})
            if on_progress is not None and self._duration:
                on_progress(max(0.0, min(1.0, s[1] / self._duration)))
        return out

    @staticmethod
    def generate_srt(segments, output_path):
        with open(output_path, "w", encoding="utf-8") as f:
            f.writelines(
                f"{i}\n00:00:00,000 --> 00:00:01,000\n{s['text']}\n\n"
                for i, s in enumerate(segments, 1)
            )
        return output_path


class TestPipelineTranscribeMapping(unittest.TestCase):

    def _pipe(self, tmp):
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
        )
        return pipe, events

    def _processor(self):
        processor = MagicMock()
        processor.extract_audio.side_effect = lambda v, a: a
        processor.get_video_info.return_value = {"streams": [{"width": 720, "height": 1280}]}
        processor.embed_ass.side_effect = lambda v, a, o: o
        return processor

    def _renderer(self):
        renderer = MagicMock()

        def fake_ass(segments, path, video_width=None, video_height=None):
            Path(path).write_text("[Script Info]", encoding="utf-8")
            return path

        renderer.generate_ass.side_effect = fake_ass
        return renderer

    def test_transcribe_progress_mapped_30_to_70(self):
        tmp = _tmpdir(self)
        (tmp / "clip.mp4").write_bytes(b"x")
        pipe, events = self._pipe(tmp)
        engine = FakeTxEngine([(0.0, 30.0), (30.0, 60.0), (60.0, 120.0)], 120.0)
        with patch("pipeline.create_subtitle_engine", return_value=engine), \
             patch("pipeline.create_video_processor", return_value=self._processor()), \
             patch("pipeline.create_caption_renderer", return_value=self._renderer()):
            result = pipe.run(str(tmp / "clip.mp4"), model_size="tiny", language="de")
        self.assertTrue(result.endswith("clip_subtitled.mp4"))
        tx_values = [p for p in events["progress"] if 30.0 < p < 70.0]
        self.assertTrue(tx_values, "kein Transkriptionsfortschritt zwischen 30 und 70")
        for p in events["progress"]:
            self.assertGreaterEqual(p, 0.0)
            self.assertLessEqual(p, 100.0)
        from itertools import pairwise
        for a, b in pairwise(tx_values):
            self.assertLessEqual(a, b)
        # Naeherungswerte 40 / 50 / 70 (30 + f*40)
        self.assertAlmostEqual(tx_values[0], 40.0)
        self.assertAlmostEqual(tx_values[1], 50.0)

    def test_pipeline_cancel_during_transcribe(self):
        tmp = _tmpdir(self)
        (tmp / "clip.mp4").write_bytes(b"x")
        pipe, events = self._pipe(tmp)
        processor = self._processor()

        class SlowEngine(FakeTxEngine):
            def transcribe(self, audio_path, language=None, on_progress=None,
                           should_cancel=None):
                import time as _t
                _t.sleep(2.0)
                return super().transcribe(audio_path, language, on_progress,
                                          should_cancel)

        engine = SlowEngine([(0.0, 60.0)], 120.0)
        with patch("pipeline.create_subtitle_engine", return_value=engine), \
             patch("pipeline.create_video_processor", return_value=processor), \
             patch("pipeline.create_caption_renderer", return_value=self._renderer()):
            job = pipe.run_async(str(tmp / "clip.mp4"), model_size="tiny")
            import time as _t
            _t.sleep(0.3)
            job.cancel()
            self.assertTrue(job.wait(timeout=10))
        processor.embed_ass.assert_not_called()
        self.assertEqual(len(events["cancelled"]), 1)
        self.assertEqual(events["done"], [])


if __name__ == "__main__":
    unittest.main()
