"""Fix-Block 4 (B2): Cancel-Lifecycle, ffmpeg-Cleanup, Temp-/Output-Cleanup.

START -> RUNNING -> CANCEL_REQUESTED -> CLEANUP -> CANCELLED/FAILED/FINISHED.
Subprocess-Tests nutzen Fake-Popen (kein echtes ffmpeg), deterministisch.
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

from pipeline import CaptiPipeline, PipelineJob
from video_processor import CancelledError, VideoProcessor


def _segments():
    return [{
        "start": 0.0, "end": 1.0, "text": "Hallo Welt",
        "words": [
            {"word": "Hallo", "start": 0.0, "end": 0.5, "probability": 0.9},
            {"word": "Welt", "start": 0.6, "end": 1.0, "probability": 0.9},
        ],
    }]


def _tmpdir(testcase, prefix="capti_cancel_"):
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    testcase.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
    return tmp


def _make_pipeline(tmp, **overrides):
    events = {"status": [], "progress": [], "log": [],
              "done": [], "error": [], "cancelled": []}
    pipe = CaptiPipeline(
        temp_dir=str(tmp),
        on_status=lambda m: events["status"].append(m),
        on_progress=lambda p: events["progress"].append(p),
        on_log=lambda l, m: events["log"].append((l, m)),
        on_done=lambda p: events["done"].append(p),
        on_error=lambda e: events["error"].append(e),
        on_cancelled=lambda m: events["cancelled"].append(m),
        **overrides,
    )
    return pipe, events


def _mock_factories(engine=None, processor=None, renderer=None):
    engine = engine or MagicMock()
    processor = processor or MagicMock()
    renderer = renderer or MagicMock()
    if isinstance(engine, MagicMock):
        engine.transcribe.return_value = _segments()
    if isinstance(processor, MagicMock):
        processor.extract_audio.side_effect = lambda v, a, **k: a
        processor.get_video_info.return_value = {"streams": [{"width": 720, "height": 1280}]}
    if isinstance(renderer, MagicMock):
        def fake_ass(segments, path, video_width=None, video_height=None):
            Path(path).write_text("[Script Info]", encoding="utf-8")
            return path
        renderer.generate_ass.side_effect = fake_ass
    processor.embed_ass.side_effect = lambda v, a, o, **k: o
    return engine, processor, renderer


class TestCancelBeforeStart(unittest.TestCase):

    def test_cancel_before_start_runs_nothing(self):
        tmp = _tmpdir(self)
        pipe, events = _make_pipeline(tmp)
        engine, processor, renderer = _mock_factories()
        pipe.cancel()
        self.assertTrue(pipe.cancel_requested)
        with patch("pipeline.create_subtitle_engine", return_value=engine), \
             patch("pipeline.create_video_processor", return_value=processor), \
             patch("pipeline.create_caption_renderer", return_value=renderer), \
             self.assertRaises(CancelledError):
            pipe.run(str(tmp / "clip.mp4"), model_size="tiny", language="de")
        engine.transcribe.assert_not_called()
        processor.extract_audio.assert_not_called()
        processor.embed_ass.assert_not_called()
        self.assertEqual(len(events["cancelled"]), 1)
        self.assertEqual(events["done"], [])
        self.assertEqual(events["error"], [])


class TestCancelMidJob(unittest.TestCase):

    def test_cancel_during_transcribe_stops_before_embed(self):
        tmp = _tmpdir(self)
        pipe, events = _make_pipeline(tmp)
        engine, processor, renderer = _mock_factories()
        started = threading.Event()

        def slow_transcribe(audio, language, **kwargs):
            started.set()
            time.sleep(2.0)
            return _segments()

        engine.transcribe.side_effect = slow_transcribe
        with patch("pipeline.create_subtitle_engine", return_value=engine), \
             patch("pipeline.create_video_processor", return_value=processor), \
             patch("pipeline.create_caption_renderer", return_value=renderer):
            job = pipe.run_async(str(tmp / "clip.mp4"), model_size="tiny", language="de")
            self.assertIsInstance(job, PipelineJob)
            self.assertTrue(started.wait(timeout=5))
            self.assertTrue(job.is_running)
            job.cancel()
            job.cancel()  # idempotent
            self.assertTrue(job.cancelled)
            self.assertTrue(job.wait(timeout=10))
        self.assertFalse(job.is_running)
        processor.embed_ass.assert_not_called()
        self.assertEqual(len(events["cancelled"]), 1)
        self.assertEqual(events["done"], [])
        self.assertEqual(events["error"], [])

    def test_cancel_idempotent(self):
        tmp = _tmpdir(self)
        pipe, _ = _make_pipeline(tmp)
        pipe.cancel()
        pipe.cancel()
        pipe.cancel()
        self.assertTrue(pipe.cancel_requested)

    def test_job_handle_states(self):
        tmp = _tmpdir(self)
        pipe, events = _make_pipeline(tmp)
        engine, processor, renderer = _mock_factories()
        with patch("pipeline.create_subtitle_engine", return_value=engine), \
             patch("pipeline.create_video_processor", return_value=processor), \
             patch("pipeline.create_caption_renderer", return_value=renderer):
            job = pipe.run_async(str(tmp / "clip.mp4"), model_size="tiny", language="de")
            self.assertTrue(job.wait(timeout=10))
        self.assertFalse(job.is_running)
        self.assertFalse(job.cancelled)
        self.assertEqual(len(events["done"]), 1)
        self.assertEqual(events["cancelled"], [])
        self.assertEqual(events["error"], [])


class FakePopen:
    """Simulierter Langläufer-Prozess (kein echtes ffmpeg)."""

    def __init__(self, *args, **kwargs):
        self.args = args
        self.returncode = None
        self.terminated = False
        self.killed = False
        self._ticks = 0

    def poll(self):
        return self.returncode

    def communicate(self, timeout=None):
        if self.terminated:
            self.returncode = -15
            return ("", "")
        if self.killed:
            self.returncode = -9
            return ("", "")
        time.sleep(0.01)
        self._ticks += 1
        if self._ticks >= 100000:
            self.returncode = 0
            return ("out", "")
        import subprocess as _sp
        raise _sp.TimeoutExpired(self.args, timeout)

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


class FakePopenIgnoreTerminate(FakePopen):
    """Ignoriert terminate() -> kill-Fallback muss greifen."""

    def terminate(self):
        pass  # kein Effekt


def _make_processor(tmp):
    vp = VideoProcessor.__new__(VideoProcessor)
    vp.ffmpeg_path = "ffmpeg"
    vp._cancel_event = None
    vp._current_process = None
    vp._proc_lock = threading.Lock()
    return vp


def _wait_until(predicate, timeout=10.0, interval=0.01):
    """Wartet ereignisgesteuert statt per Fixed-Sleep (robust unter Last)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _without_cyclic_gc():
    """Hermetik gegen Cross-Test-GC-Gefahr (Block-19-Root-Cause).

    UI-Tests hinterlassen Tk-Objekte (u.a. tkinter Fonts aus der animierten
    Preview) in Referenzzyklen. Liefe die zyklische GC während eines
    Worker-Threads, würde tkinter.Font.__del__ dort Tcl aufrufen (falscher
    Thread / ggf. zerstörter Interpreter -> Hang). Darum: Altlasten vorab
    deterministisch im Main-Thread finalisieren, GC für das Worker-Fenster
    sperren, danach wieder einschalten. Assertions unverändert.
    """
    import gc as _gc

    class _Guard:
        def __enter__(self):
            _gc.collect()
            _gc.disable()
            return self

        def __exit__(self, *exc):
            _gc.enable()
            return False

    return _Guard()


def _assert_thread_done(testcase, thread, timeout=30.0):
    """Join mit Worker-Stack-Dump bei Timeout (Diagnose statt Rätselraten)."""
    thread.join(timeout=timeout)
    if thread.is_alive():
        import io
        import sys as _sys
        import traceback
        buf = io.StringIO()
        for tid, frame in _sys._current_frames().items():
            if tid == thread.ident:
                buf.write(f"Worker-Thread {tid} hängt hier:\n")
                traceback.print_stack(frame, file=buf)
        testcase.fail(f"Worker-Thread beendet nicht: {buf.getvalue()[:2000]}")
    return True


class TestSubprocessCancel(unittest.TestCase):

    def test_terminate_on_cancel(self):
        tmp = _tmpdir(self)
        vp = _make_processor(tmp)
        vp._cancel_event = threading.Event()
        FakePopen.instances = []
        holder = {}

        def run():
            try:
                with patch("video_processor.subprocess.Popen",
                           side_effect=lambda *a, **k: holder.setdefault("p", FakePopen(*a, **k))):
                    vp._run_cmd(["ffmpeg", "-i", "x"], timeout=60)
            except CancelledError as e:
                holder["err"] = e

        t = threading.Thread(target=run, daemon=True)
        with _without_cyclic_gc():
            t.start()
            self.assertTrue(_wait_until(lambda: "p" in holder, timeout=10),
                            "Worker hat _run_cmd nicht erreicht")
            vp._cancel_event.set()
            _assert_thread_done(self, t)
        self.assertIsInstance(holder.get("err"), CancelledError)
        self.assertTrue(holder["p"].terminated)
        self.assertIsNotNone(holder["p"].poll())  # kein Zombie
        self.assertIsNone(vp._current_process)  # Slot aufgeräumt

    def test_kill_fallback_after_timeout(self):
        tmp = _tmpdir(self)
        vp = _make_processor(tmp)
        vp._cancel_event = threading.Event()
        holder = {}

        def run():
            try:
                with patch("video_processor.subprocess.Popen",
                           side_effect=lambda *a, **k: holder.setdefault("p", FakePopenIgnoreTerminate(*a, **k))), \
                     patch("video_processor._CANCEL_KILL_TIMEOUT", 0.2), \
                     patch("video_processor._POLL_INTERVAL", 0.01):
                    vp._run_cmd(["ffmpeg", "-i", "x"], timeout=60)
            except CancelledError as e:
                holder["err"] = e

        t = threading.Thread(target=run, daemon=True)
        with _without_cyclic_gc():
            t.start()
            self.assertTrue(_wait_until(lambda: "p" in holder, timeout=10),
                            "Worker hat _run_cmd nicht erreicht")
            vp._cancel_event.set()
            _assert_thread_done(self, t)
        self.assertIsInstance(holder.get("err"), CancelledError)
        self.assertTrue(holder["p"].killed)

    def test_timeout_preserved_without_cancel(self):
        tmp = _tmpdir(self)
        vp = _make_processor(tmp)
        import subprocess as _sp
        with patch("video_processor.subprocess.Popen",
                   side_effect=lambda *a, **k: FakePopen(*a, **k)), \
             patch("video_processor._POLL_INTERVAL", 0.01), \
             self.assertRaises(_sp.TimeoutExpired):
            vp._run_cmd(["ffmpeg", "-i", "x"], timeout=0.3)

    def test_request_cancel_idempotent(self):
        tmp = _tmpdir(self)
        vp = _make_processor(tmp)
        vp.request_cancel()
        vp.request_cancel()
        self.assertTrue(vp._cancel_event.is_set())


class TestCleanup(unittest.TestCase):

    def _real_files_run(self, tmp, transcribe=None):
        """Echte Dateien via Fakes (kein ffmpeg/Modell nötig)."""
        pipe, events = _make_pipeline(tmp / "_temp")
        engine = MagicMock()
        engine.transcribe.side_effect = transcribe or (lambda a, l, **k: _segments())
        processor = MagicMock()

        def fake_extract(v, a, **kwargs):
            Path(a).write_bytes(b"RIFF")
            return a

        def fake_embed(v, a, o, **kwargs):
            Path(o).write_bytes(b"video-bytes-vollstaendig")
            return o

        processor.extract_audio.side_effect = fake_extract
        processor.get_video_info.return_value = {"streams": [{"width": 720, "height": 1280}]}
        processor.embed_ass.side_effect = fake_embed
        renderer = MagicMock()

        def fake_ass(segments, path, video_width=None, video_height=None):
            Path(path).write_text("[Script Info]", encoding="utf-8")
            return path

        renderer.generate_ass.side_effect = fake_ass
        src = tmp / "clip.mp4"
        src.write_bytes(b"orig")
        return pipe, events, engine, processor, renderer, src

    def _run_patched(self, pipe, src, engine, processor, renderer):
        with patch("pipeline.create_subtitle_engine", return_value=engine), \
             patch("pipeline.create_video_processor", return_value=processor), \
             patch("pipeline.create_caption_renderer", return_value=renderer):
            return pipe.run(str(src), model_size="tiny", language="de")

    def test_cleanup_after_success_keeps_only_output(self):
        tmp = _tmpdir(self)
        foreign = tmp / "_temp" / "fremd.txt"
        foreign.parent.mkdir(parents=True, exist_ok=True)
        foreign.write_bytes(b"fremd")
        pipe, events, engine, processor, renderer, src = self._real_files_run(tmp)
        result = self._run_patched(pipe, src, engine, processor, renderer)
        self.assertTrue(Path(result).exists())
        self.assertEqual(events["done"], [result])
        # Eigene Temps weg, fremde Datei bleibt
        leftovers = [p.name for p in (tmp / "_temp").iterdir()]
        self.assertNotIn("clip_audio.wav", leftovers)
        self.assertNotIn("clip.srt", leftovers)
        self.assertNotIn("clip.ass", leftovers)
        self.assertTrue(foreign.exists())

    def test_cleanup_after_error(self):
        tmp = _tmpdir(self)
        pipe, events, engine, processor, renderer, src = self._real_files_run(tmp)

        def boom(audio, language, **kwargs):
            raise RuntimeError("whisper kaputt")

        engine.transcribe.side_effect = boom
        with patch("pipeline.create_subtitle_engine", return_value=engine), \
             patch("pipeline.create_video_processor", return_value=processor), \
             patch("pipeline.create_caption_renderer", return_value=renderer), \
             self.assertRaises(RuntimeError):
            pipe.run(str(src), model_size="tiny", language="de")
        self.assertEqual(len(events["error"]), 1)
        self.assertEqual(events["done"], [])
        leftovers = [p.name for p in (tmp / "_temp").iterdir()] if (tmp / "_temp").exists() else []
        self.assertNotIn("clip_audio.wav", leftovers)

    def test_cleanup_after_cancel(self):
        tmp = _tmpdir(self)
        pipe, events, engine, processor, renderer, src = self._real_files_run(tmp)
        started = threading.Event()

        def slow(audio, language, **kwargs):
            started.set()
            time.sleep(2.0)
            return _segments()

        engine.transcribe.side_effect = slow
        with patch("pipeline.create_subtitle_engine", return_value=engine), \
             patch("pipeline.create_video_processor", return_value=processor), \
             patch("pipeline.create_caption_renderer", return_value=renderer):
            job = pipe.run_async(str(src), model_size="tiny", language="de")
            self.assertTrue(started.wait(timeout=5))
            job.cancel()
            self.assertTrue(job.wait(timeout=10))
        self.assertEqual(len(events["cancelled"]), 1)
        leftovers = [p.name for p in (tmp / "_temp").iterdir()] if (tmp / "_temp").exists() else []
        self.assertNotIn("clip_audio.wav", leftovers)
        self.assertNotIn("clip.srt", leftovers)

    def test_partial_output_removed_on_failure(self):
        tmp = _tmpdir(self)
        pipe, events, engine, processor, renderer, src = self._real_files_run(tmp)

        def partial_embed(v, a, o, **kwargs):
            Path(o).write_bytes(b"halb")
            raise RuntimeError("ffmpeg abgestuerzt")

        processor.embed_ass.side_effect = partial_embed
        with patch("pipeline.create_subtitle_engine", return_value=engine), \
             patch("pipeline.create_video_processor", return_value=processor), \
             patch("pipeline.create_caption_renderer", return_value=renderer), \
             self.assertRaises(RuntimeError):
            pipe.run(str(src), model_size="tiny", language="de")
        partials = list(tmp.glob("clip_subtitled*.mp4"))
        self.assertEqual(partials, [])
        self.assertEqual(events["done"], [])

    def test_success_output_kept(self):
        tmp = _tmpdir(self)
        pipe, events, engine, processor, renderer, src = self._real_files_run(tmp)
        result = self._run_patched(pipe, src, engine, processor, renderer)
        self.assertTrue(Path(result).exists())
        self.assertGreater(Path(result).stat().st_size, 0)
        self.assertEqual(events["done"], [result])


class TestWindowCloseCancels(unittest.TestCase):
    """Fenster/Destroy während Processing fordert Cancel an (nicht blockierend)."""

    @classmethod
    def setUpClass(cls):
        import customtkinter as ctk
        ctk.set_appearance_mode("dark")
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except Exception:
            pass

    def test_destroy_requests_cancel(self):
        from ui.app_controller import AppController
        controller = AppController(self.root)
        screen = controller.get_screen("processing")
        pipe = MagicMock()
        screen._pipeline = pipe
        screen.destroy()
        pipe.cancel.assert_called_once_with()

    def test_destroy_without_pipeline_no_crash(self):
        from ui.app_controller import AppController
        controller = AppController(self.root)
        screen = controller.get_screen("processing")
        if hasattr(screen, "_pipeline"):
            delattr(screen, "_pipeline")
        screen.destroy()  # kein Crash

    def test_show_cancelled_state(self):
        from ui import i18n
        from ui.app_controller import AppController
        controller = AppController(self.root)
        screen = controller.get_screen("processing")
        screen.show_cancelled("x")
        self.assertEqual(screen.status_label.cget("text"), i18n.t("proc.cancelled"))
        self.assertEqual(str(screen.btn_back.cget("state")), "normal")
        screen.destroy()


class TestNormalRunUnaffected(unittest.TestCase):

    def test_success_with_cancel_machinery_idle(self):
        tmp = _tmpdir(self)
        pipe, events = _make_pipeline(tmp)
        engine, processor, renderer = _mock_factories()
        with patch("pipeline.create_subtitle_engine", return_value=engine), \
             patch("pipeline.create_video_processor", return_value=processor), \
             patch("pipeline.create_caption_renderer", return_value=renderer):
            result = pipe.run(str(tmp / "clip.mp4"), model_size="tiny", language="de")
        self.assertTrue(result.endswith("clip_subtitled.mp4"))
        self.assertEqual(events["done"], [result])
        self.assertEqual(events["cancelled"], [])
        self.assertFalse(pipe.cancel_requested)


if __name__ == "__main__":
    unittest.main()
