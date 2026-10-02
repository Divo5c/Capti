"""Fix-Block 26: E2E-Regression des kompletten Caption-Workflows.

VIDEO -> AUDIO -> WHISPER/TRANSCRIPT -> PREVIEW -> CAPTION EDIT
-> WORD EDIT -> PROJEKT SPEICHERN -> PROJEKT LADEN
-> PREVIEW WIEDERHERSTELLEN -> RE-EXPORT -> ASS/OUTPUT.

Ebenen:
- LEVEL 1 (Core, Tk-frei): Edit-Kette -> Datei -> Reload -> RenderModel.
- LEVEL 2 (Pipeline, kontrollierte Fakes): echter Pipeline-Ablauf +
  echter ASS-Renderer; nur Audio/Transkription/Embed gemockt.
- LEVEL 3 (UI, Tk): Load -> Editor/Preview, Re-Export nach Load.

Matrix: E2E-01 bis E2E-20 (s. Klassennamen).
Kein Internet, kein Whisper-Download, kein echtes FFmpeg.
"""

import copy
import os
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

from capti_core.caption_draft import (
    apply_text,
    draft_from_caption,
    merge_words,
    set_word_timing,
    split_word,
    to_segment,
)
from capti_core.project_state import load_project
from capti_core.render_model import captions_from_segments
from caption_renderer import create_caption_renderer
from pipeline import CaptiPipeline
from ui.screens.caption_style import _timeline_x
from video_processor import CancelledError

STYLE = {"pop_scale": 140, "normal_color": "#FFFFFF",
         "highlight_color": "#FFFF00"}


def _original_segments():
    return [
        {"start": 0.0, "end": 2.0, "text": "Hallo Welt",
         "words": [{"word": "Hallo", "start": 0.0, "end": 0.8},
                   {"word": "Welt", "start": 1.0, "end": 2.0}]},
        {"start": 5.0, "end": 8.0, "text": "Grüße aus München heute",
         "words": [{"word": "Grüße", "start": 5.1, "end": 5.7},
                   {"word": "aus", "start": 5.8, "end": 6.1},
                   {"word": "München", "start": 6.2, "end": 7.0},
                   {"word": "heute", "start": 7.1, "end": 8.0}]},
    ]


def combined_edits(segments):
    """Kombinierte Edit-Kette (J): Timing -> Split -> Merge -> Text."""
    caps = captions_from_segments(copy.deepcopy(segments), dict(STYLE), None)
    drafts = [draft_from_caption(c) for c in caps]
    # 1. Timing ändern
    assert set_word_timing(drafts[0], 0, 0.0, 0.9)
    # 2. Split
    assert split_word(drafts[0], 1, ["We", "lt"])
    # 3. Merge (Nachbarn 0+1 der zweiten Caption)
    assert merge_words(drafts[1], 0)
    # 4. Text ändern (Anker-Timings bleiben, neue Wörter deterministisch)
    apply_text(drafts[1], "Grüße aus dem schönen München")
    return [to_segment(d) for d in drafts]


def _tmpdir(testcase, prefix="capti_e2e26_"):
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    testcase.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
    return tmp


def _stack(captured, transcribe_segments=None):
    """Fakes: Transkription/Audio/Embed; Renderer ECHT (mit Spy)."""
    engine = MagicMock()
    engine.transcribe.return_value = copy.deepcopy(
        transcribe_segments if transcribe_segments is not None
        else _original_segments())
    engine.transcribe.side_effect = None
    processor = MagicMock()
    processor.extract_audio.side_effect = lambda v, a, **k: a
    processor.get_video_info.return_value = {"streams": []}
    processor.embed_ass.side_effect = lambda v, a, o, **k: o
    renderer = create_caption_renderer()
    real_generate = renderer.generate_ass

    def spy(segments, path, video_width=None, video_height=None):
        captured["ass_segments"] = copy.deepcopy(segments)
        result = real_generate(segments, path,
                               video_width=video_width,
                               video_height=video_height)
        # B2-Cleanup entfernt Temp-Dateien nach Erfolg -> Inhalt sichern:
        captured["ass_text"] = Path(path).read_text(encoding="utf-8")
        return result

    renderer.generate_ass = spy
    srt_seen = {}

    def fake_srt(segments, path):
        srt_seen["segments"] = copy.deepcopy(segments)
        Path(path).write_text("SRT", encoding="utf-8")
        return path

    engine.generate_srt.side_effect = fake_srt
    return engine, processor, renderer, srt_seen


def _run(testcase, tmp, captured, override=None, group_spy=None,
         fail_embed=False, cancel_before=False):
    (tmp / "clip.mp4").write_bytes(b"x")
    engine, processor, renderer, srt_seen = _stack(captured)
    if fail_embed:
        def boom(v, a, o, **k):
            Path(o).write_bytes(b"partial")
            raise RuntimeError("ffmpeg boom")
        processor.embed_ass.side_effect = boom
    pipe = CaptiPipeline(temp_dir=str(tmp / "_temp"))
    if cancel_before:
        pipe.cancel()
    patches = [patch("pipeline.create_subtitle_engine", return_value=engine),
               patch("pipeline.create_video_processor", return_value=processor),
               patch("pipeline.create_caption_renderer", return_value=renderer)]
    if group_spy is not None:
        import pipeline as _pl
        real_group = _pl.group_caption_segments

        def counting(segments, layout):
            group_spy["calls"] += 1
            return real_group(segments, layout)

        patches.append(patch("pipeline.group_caption_segments",
                             side_effect=counting))
    for p in patches:
        testcase.addCleanup(p.stop)
        p.start()
    out = pipe.run(str(tmp / "clip.mp4"), model_size="tiny", language="de",
                   override_segments=override)
    return pipe, engine, out, srt_seen


class TestE2ECoreChain(unittest.TestCase):
    """LEVEL 1: Edit-Kette -> Datei -> Reload -> RenderModel."""

    def test_e2e02_combined_edits_save_load(self):
        """E2E-02/20: kombinierte Edits überstehen Datei-Roundtrip."""
        tmp = _tmpdir(self)
        edited = combined_edits(_original_segments())
        from capti_core.project_state import ProjectState, save_project
        state = ProjectState(video_path="C:/vids/clip.mp4", model="tiny",
                             language="de", caption_style=dict(STYLE),
                             segments=edited)
        path = tmp / "clip.capti.json"
        save_project(path, state)
        # Echte Datei, UTF-8:
        raw = path.read_bytes()
        self.assertIn("Grüße".encode(), raw)
        loaded = load_project(path)
        self.assertEqual(loaded.video_path, "C:/vids/clip.mp4")  # E2E-02
        self.assertEqual(loaded.model, "tiny")
        self.assertEqual(loaded.language, "de")
        self.assertEqual(loaded.caption_style, STYLE)            # E2E-16
        self.assertEqual(len(loaded.segments), 2)
        # Reihenfolge + Texte:
        self.assertEqual([s["text"] for s in loaded.segments],
                         [edited[0]["text"], edited[1]["text"]])
        # Caption-Zeiten:
        self.assertEqual([(s["start"], s["end"]) for s in loaded.segments],
                         [(0.0, 2.0), (5.0, 8.0)])
        # Wörter + Timings exakt:
        self.assertEqual(loaded.segments, edited)
        # E2E-17/18/19/20: Split/Merge/Timing einzeln nachweisbar:
        w0 = [w["word"] for w in loaded.segments[0]["words"]]
        self.assertEqual(w0, ["Hallo", "We", "lt"])              # Split
        self.assertIn("schönen",                                 # Merge+Text
                      [w["word"] for w in loaded.segments[1]["words"]])
        self.assertEqual(loaded.segments[0]["words"][0]["end"], 0.9)  # Timing

    def test_e2e09_absolute_timings_survive(self):
        """E2E-09: 5.0/5.1 bleiben absolut über Kette + RenderModel."""
        tmp = _tmpdir(self)
        edited = combined_edits(_original_segments())
        from capti_core.project_state import ProjectState, save_project
        path = tmp / "a.capti.json"
        save_project(path, ProjectState(video_path="v", segments=edited))
        loaded = load_project(path)
        caps = captions_from_segments(loaded.segments, dict(STYLE), None)
        self.assertAlmostEqual(caps[1].start, 5.0)
        # "München" überlebt Merge+Text-Edit als Anker -> absolut erhalten:
        muenchen = next(w for w in caps[1].words if w.word == "München")
        self.assertAlmostEqual(muenchen.start, 6.2)
        # Neues Wort "Grüße" füllt Lücke ab Caption-Start (Transfer-Regel):
        self.assertAlmostEqual(caps[1].words[0].start, 5.0)
        # Preview-relevante Ableitung aus denselben Daten:
        self.assertEqual(caps[1].words[0].word, "Grüße")

    def test_e2e10_unicode_roundtrip(self):
        """E2E-10: Umlaute/Sonderzeichen über Kette + RenderModel."""
        tmp = _tmpdir(self)
        edited = combined_edits(_original_segments())
        from capti_core.project_state import ProjectState, save_project
        path = tmp / "u.capti.json"
        save_project(path, ProjectState(video_path="v", segments=edited))
        loaded = load_project(path)
        caps = captions_from_segments(loaded.segments, dict(STYLE), None)
        text = " ".join(c.text for c in caps)
        self.assertIn("Grüße", text)
        self.assertIn("schönen", text)


class TestE2EPipeline(unittest.TestCase):
    """LEVEL 2: echter Pipeline-Ablauf + echter ASS-Renderer."""

    def test_e2e01_normal_path(self):
        """E2E-01: Original -> Whisper-Pfad, Grouping, ASS-Output."""
        tmp = _tmpdir(self)
        captured, group_spy = {}, {"calls": 0}
        pipe, engine, out, _srt_seen = _run(
            self, tmp, captured, group_spy=group_spy)
        engine.transcribe.assert_called_once()
        self.assertGreaterEqual(group_spy["calls"], 1)
        self.assertTrue(out and str(out).endswith(".mp4"))
        content = captured.get("ass_text", "")
        self.assertTrue(content.strip())
        self.assertIn("Hallo", content)
        self.assertIn("\\t(", content)  # Karaoke-Tags des echten Renderers
        self.assertEqual(pipe.last_video_path, str(tmp / "clip.mp4"))

    def test_e2e04_reexport_uses_loaded_edits(self):
        """E2E-04/06/07/08: ASS-Input == geladene Edits (Text/Wörter/Zeiten)."""
        tmp = _tmpdir(self)
        edited = combined_edits(_original_segments())
        from capti_core.project_state import ProjectState, save_project
        path = tmp / "clip.capti.json"
        save_project(path, ProjectState(video_path="v", segments=edited))
        loaded = load_project(path)
        captured, group_spy = {}, {"calls": 0}
        pipe, _engine, _out, srt_seen = _run(
            self, tmp, captured, override=loaded.segments,
            group_spy=group_spy)
        self.assertEqual(group_spy["calls"], 0)          # kein Regrouping
        self.assertEqual(captured["ass_segments"], loaded.segments)  # D
        self.assertEqual(                                 # E2E-08
            [s["text"] for s in captured["ass_segments"]],
            [s["text"] for s in loaded.segments])
        self.assertEqual(                                 # E2E-06/07
            captured["ass_segments"][0]["words"],
            loaded.segments[0]["words"])
        self.assertEqual(srt_seen["segments"], loaded.segments)
        self.assertEqual(pipe.last_segments, loaded.segments)

    def test_e2e05_whisper_skipped(self):
        """E2E-05: Override -> transcribe() wird NIE aufgerufen."""
        tmp = _tmpdir(self)
        captured = {}
        _pipe, engine, _out, _srt = _run(
            self, tmp, captured,
            override=combined_edits(_original_segments()))
        engine.transcribe.assert_not_called()
        self.assertEqual(engine.transcribe.call_count, 0)

    def test_e2e11_mismatch_runs_normal_path(self):
        """E2E-11: falsches Video -> kein Override (Guard)."""
        from ui.app_controller import AppController
        stub = type("S", (), {"last_transcript": {
            "video_path": "C:/vids/A.mp4",
            "segments": combined_edits(_original_segments())}})()
        self.assertIsNone(
            AppController.get_transcript_segments(stub, "C:/vids/B.mp4"))
        tmp = _tmpdir(self)
        captured = {}
        _pipe, engine, _out, _srt = _run(self, tmp, captured, override=None)
        engine.transcribe.assert_called_once()

    def test_e2e12_success_preserves_state(self):
        """E2E-12: Erfolg -> Edit-State (Input) unverändert vorhanden."""
        tmp = _tmpdir(self)
        edited = combined_edits(_original_segments())
        snapshot = copy.deepcopy(edited)
        captured = {}
        pipe, _engine, _out, _srt = _run(self, tmp, captured, override=edited)
        self.assertEqual(edited, snapshot)  # Pipeline mutiert Input nicht
        self.assertEqual(pipe.last_segments, snapshot)

    def test_e2e13_cancel_preserves_state(self):
        """E2E-13: Cancel -> Edit-State unberührt, kein Output."""
        tmp = _tmpdir(self)
        edited = combined_edits(_original_segments())
        snapshot = copy.deepcopy(edited)
        captured = {}
        with self.assertRaises(CancelledError):
            _run(self, tmp, captured, override=edited, cancel_before=True)
        self.assertEqual(edited, snapshot)
        self.assertFalse((tmp / "clip_subtitled.mp4").exists())

    def test_e2e14_failure_preserves_state(self):
        """E2E-14: Failure -> Edit-State unberührt."""
        tmp = _tmpdir(self)
        edited = combined_edits(_original_segments())
        snapshot = copy.deepcopy(edited)
        captured = {}
        with self.assertRaises(RuntimeError):
            _run(self, tmp, captured, override=edited, fail_embed=True)
        self.assertEqual(edited, snapshot)

    def test_e2e15_partial_output_cleanup(self):
        """E2E-15/K: Partial Output entfernt, Erfolg-Output bleibt."""
        tmp = _tmpdir(self)
        captured = {}
        with self.assertRaises(RuntimeError):
            _run(self, tmp, captured,
                 override=combined_edits(_original_segments()),
                 fail_embed=True)
        leftovers = [p for p in tmp.rglob("*subtitled*")]
        self.assertEqual(leftovers, [])
        captured_ok = {}
        _pipe, _engine, out_ok, _srt = _run(
            self, tmp, captured_ok,
            override=combined_edits(_original_segments()))
        self.assertTrue(out_ok)  # Erfolg liefert Output-Pfad


class TestE2EUI(unittest.TestCase):
    """LEVEL 3: minimale UI-Kette (Tk) – Load -> Editor/Preview/Re-Export."""

    @classmethod
    def setUpClass(cls):
        import customtkinter as ctk
        ctk.set_appearance_mode("dark")
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        import contextlib
        with contextlib.suppress(Exception):
            cls.root.destroy()

    def setUp(self):
        from ui import i18n
        from ui.app_controller import AppController
        from ui.screens import caption_style as cs_mod
        self.tmp = tempfile.TemporaryDirectory()
        self.config_path = Path(self.tmp.name) / "config.json"
        self.patcher = patch.object(cs_mod, "_config_file",
                                    return_value=self.config_path)
        self.patcher.start()
        self._prev_lang = i18n.get_language()
        i18n.set_language("de")
        self.controller = AppController(self.root)
        self.proj_path = str(Path(self.tmp.name) / "e2e.capti.json")

    def tearDown(self):
        from ui import i18n
        i18n.set_language(self._prev_lang)
        self.patcher.stop()
        self.tmp.cleanup()
        import contextlib
        with contextlib.suppress(Exception):
            for name in ("caption_style", "result", "processing"):
                screen = self.controller._screens.get(name)
                if screen is not None:
                    screen.destroy()

    def test_e2e_caption_drag_chain(self):
        """Block 37: Caption-Drag -> Undo/Redo -> Save -> Load
        -> Preview -> Override -> ASS (absolute Zeiten 5.0-8.0).

        Kette: Editor == Controller == RenderModel == ProjectState
        == Reload == Override == ASS-Input; Whisper wird übersprungen.
        """
        from types import SimpleNamespace

        video = "C:/vids/clip.mp4"
        segments = [{
            "start": 5.0, "end": 8.0, "text": "eins zwei",
            "words": [{"word": "eins", "start": 5.5, "end": 6.0},
                      {"word": "zwei", "start": 6.5, "end": 7.0}],
        }]
        self.controller.pending_project = {"video_path": video,
                                           "model": "tiny", "language": "de"}
        self.controller.last_transcript = {
            "video_path": video, "segments": segments,
            "model": "tiny", "language": "de"}
        screen = self.controller.get_screen("caption_style")
        screen.on_show()
        labels = list(screen._editor_option.cget("values"))
        screen._editor_option.set(labels[0])
        screen._on_editor_select(None)

        def cap_drag(which, to_t):
            handles = screen._timeline_caption_handles()
            x0 = handles[0] if which == "start" else handles[1]
            screen._on_timeline_press(SimpleNamespace(x=x0))
            drag = screen._timeline_drag
            width = screen._timeline_w
            span = drag["map_end"] - drag["map_start"]
            move_x = 10 + (to_t - drag["map_start"]) / span * (width - 20)
            screen._on_timeline_move(SimpleNamespace(x=move_x))
            screen._on_timeline_release(SimpleNamespace(x=0))

        # Start 5.0 -> 5.2, Ende 8.0 -> 8.6 (Wörter 5.5-7.0 bleiben drin):
        cap_drag("start", 5.2)
        cap_drag("end", 8.6)
        editor = screen._transcript_segments[0]
        self.assertAlmostEqual((editor["start"], editor["end"]), (5.2, 8.6))
        self.assertEqual(
            [(w["word"], w["start"], w["end"]) for w in editor["words"]],
            [("eins", 5.5, 6.0), ("zwei", 6.5, 7.0)])
        # Controller == Editor:
        ctrl = self.controller.last_transcript["segments"][0]
        self.assertAlmostEqual((ctrl["start"], ctrl["end"]), (5.2, 8.6))
        # RenderModel == Editor:
        model_cap = screen._transcript_captions[0]
        self.assertAlmostEqual((model_cap.start, model_cap.end), (5.2, 8.6))
        # Undo -> Redo:
        screen._on_undo()
        self.assertAlmostEqual(screen._transcript_segments[0]["end"], 8.0)
        screen._on_undo()
        self.assertAlmostEqual(screen._transcript_segments[0]["start"], 5.0)
        screen._on_redo()
        screen._on_redo()
        self.assertAlmostEqual(
            (screen._transcript_segments[0]["start"],
             screen._transcript_segments[0]["end"]), (5.2, 8.6))
        # Save -> Clear -> Load:
        self.controller.save_project_state(self.proj_path)
        self.controller.last_transcript = None
        self.controller.pending_project = None
        screen.clear_transcript()
        loaded = load_project(self.proj_path)
        # ProjectState == Reload:
        self.assertAlmostEqual(
            (loaded.segments[0]["start"], loaded.segments[0]["end"]),
            (5.2, 8.6))
        self.controller.load_project_state(self.proj_path)
        screen.on_show()
        # Preview == Reload:
        preview_words = [(w.word, w.start, w.end)
                         for w in screen._preview_caption.words]
        self.assertEqual(preview_words,
                         [(w["word"], w["start"], w["end"])
                          for w in loaded.segments[0]["words"]])
        # Re-Export (Override + echter ASS-Renderer):
        tmp = _tmpdir(self)
        captured = {}
        _pipe, engine, _out, _srt = _run(
            self, tmp, captured, override=loaded.segments)
        engine.transcribe.assert_not_called()
        ass_words = captured["ass_segments"][0]["words"]
        self.assertEqual(
            [(w["word"], w["start"], w["end"]) for w in ass_words],
            preview_words)
        self.assertAlmostEqual(captured["ass_segments"][0]["start"], 5.2)
        self.assertAlmostEqual(captured["ass_segments"][0]["end"], 8.6)

    def test_e2e03_load_preview_editor_reexport(self):
        """E2E-03: Datei -> Preview/Editor -> Re-Export mit Override."""
        import ui.screens.processing as proc_mod
        from capti_core.project_state import ProjectState, save_project
        edited = combined_edits(_original_segments())
        save_project(self.proj_path, ProjectState(
            video_path="C:/vids/clip.mp4", model="tiny", language="de",
            caption_style=dict(STYLE), segments=edited))
        self.controller.load_project_state(self.proj_path)
        screen = self.controller.get_screen("caption_style")
        screen.on_show()
        # Preview + Editor zeigen geladenen Stand:
        self.assertEqual(screen._preview_mode, "transcript")
        self.assertEqual(screen._editor_entry.get(), "Hallo We lt")
        preview_words = [(w.word, w.start, w.end)
                         for w in screen._preview_caption.words]
        self.assertEqual([w[0] for w in preview_words],
                         ["Hallo", "We", "lt"])
        # Re-Export nach Load nutzt geladene Edits:
        processing = self.controller.get_screen("processing")
        processing.video_path = "C:/vids/clip.mp4"
        processing.model = "tiny"
        processing.language = "de"
        with patch.object(proc_mod, "CaptiPipeline") as mk_pipe, \
             patch.object(type(processing), "_cleanup_temp",
                          lambda self: None):
            processing._start_pipeline()
        _a, kwargs = mk_pipe.return_value.run_async.call_args
        self.assertEqual(kwargs["override_segments"], edited)
        # Result-Kontext nach Load:
        result = self.controller.get_screen("result")
        result.set_result("C:/vids/out.mp4", video_path="C:/vids/clip.mp4")
        self.assertTrue(bool(result.btn_reexport.grid_info()))

    def test_e2e_undo_redo_chain(self):
        """Edit -> Undo -> Redo -> Save -> Load -> Preview -> Re-Export.

        Kette: Preview == ProjectState == Reload == Override == ASS-Input
        (Text, Wörter, Zeiten, Style).
        """
        import ui.screens.processing as proc_mod
        video = "C:/vids/clip.mp4"
        self.controller.pending_project = {"video_path": video,
                                           "model": "tiny", "language": "de"}
        from capti_core.project_state import load_project
        self.controller.last_transcript = {
            "video_path": video, "segments": _original_segments(),
            "model": "tiny", "language": "de"}
        screen = self.controller.get_screen("caption_style")
        screen.on_show()
        # Edit -> Undo -> Redo:
        screen._editor_entry.delete(0, "end")
        screen._editor_entry.insert(0, "Hallo We lt")
        screen._on_editor_apply()
        screen._on_undo()
        self.assertEqual(screen._transcript_segments[0]["text"], "Hallo Welt")
        screen._on_redo()
        self.assertEqual(screen._transcript_segments[0]["text"], "Hallo We lt")
        # Save -> Session-Clear -> Load:
        self.controller.save_project_state(self.proj_path)
        self.controller.last_transcript = None
        self.controller.pending_project = None
        screen.clear_transcript()
        loaded = load_project(self.proj_path)
        self.controller.load_project_state(self.proj_path)
        screen.on_show()
        # Preview == Reload:
        preview = screen._preview_caption
        self.assertEqual(preview.text, loaded.segments[0]["text"])
        self.assertEqual([(w.word, w.start, w.end) for w in preview.words],
                         [(w["word"], w["start"], w["end"])
                          for w in loaded.segments[0]["words"]])
        # Re-Export == Reload (Override):
        processing = self.controller.get_screen("processing")
        processing.video_path = video
        processing.model = "tiny"
        processing.language = "de"
        with patch.object(proc_mod, "CaptiPipeline") as mk_pipe, \
             patch.object(type(processing), "_cleanup_temp",
                          lambda self: None):
            processing._start_pipeline()
        _a, kwargs = mk_pipe.return_value.run_async.call_args
        override = kwargs["override_segments"]
        self.assertEqual(override, loaded.segments)
        self.assertEqual(override[0]["text"], preview.text)
        self.assertEqual(loaded.caption_style["pop_scale"],
                         screen.style["pop_scale"])

    def test_e2e_word_ops_chain(self):
        """Original -> Split -> Insert -> Delete -> Undo -> Redo
        -> Save -> Load -> Preview -> Re-Export (ASS-Input).

        Kette: Editor == ProjectState == Reload == Preview == Override
        == ASS-Input (Wörter + Timings).
        """
        video = "C:/vids/clip.mp4"
        self.controller.pending_project = {"video_path": video,
                                           "model": "tiny", "language": "de"}
        self.controller.last_transcript = {
            "video_path": video, "segments": _original_segments(),
            "model": "tiny", "language": "de"}
        screen = self.controller.get_screen("caption_style")
        screen.on_show()

        def select_word(idx):
            labels = list(screen._word_option.cget("values"))
            screen._word_option.set(labels[idx])
            screen._on_word_select(None)

        # Manual Split: "Hallo" bei 2 -> "Ha"+"llo":
        select_word(0)
        screen._split_index_entry.delete(0, "end")
        screen._split_index_entry.insert(0, "2")
        screen._on_word_split_at()
        # Insert: "schöne" hinter "llo" (Lücke 0.32-1.0):
        select_word(1)
        screen._insert_word_entry.delete(0, "end")
        screen._insert_word_entry.insert(0, "schöne")
        screen._on_word_insert_after()
        # Delete: "Welt" entfernen:
        select_word(3)
        screen._on_word_delete()
        self.assertEqual(
            [w["word"]
             for w in screen._transcript_segments[0]["words"]],
            ["Ha", "llo", "schöne"])
        # Undo -> Redo:
        screen._on_undo()
        self.assertEqual(
            [w["word"]
             for w in screen._transcript_segments[0]["words"]],
            ["Ha", "llo", "schöne", "Welt"])
        screen._on_redo()
        self.assertEqual(
            [w["word"]
             for w in screen._transcript_segments[0]["words"]],
            ["Ha", "llo", "schöne"])
        # Save -> Clear -> Load:
        self.controller.save_project_state(self.proj_path)
        self.controller.last_transcript = None
        self.controller.pending_project = None
        screen.clear_transcript()
        loaded = load_project(self.proj_path)
        self.controller.load_project_state(self.proj_path)
        screen.on_show()
        # Editor == Reload == Preview:
        reloaded_words = loaded.segments[0]["words"]
        self.assertEqual([w["word"] for w in reloaded_words],
                         ["Ha", "llo", "schöne"])
        preview_words = [(w.word, w.start, w.end)
                         for w in screen._preview_caption.words]
        self.assertEqual(preview_words,
                         [(w["word"], w["start"], w["end"])
                          for w in reloaded_words])
        # Re-Export (Override + echter ASS-Renderer):
        tmp = _tmpdir(self)
        captured = {}
        _pipe, engine, _out, _srt = _run(
            self, tmp, captured, override=loaded.segments)
        engine.transcribe.assert_not_called()
        ass_words = captured["ass_segments"][0]["words"]
        self.assertEqual(
            [(w["word"], w["start"], w["end"]) for w in ass_words],
            preview_words)
        self.assertIn("schöne", captured.get("ass_text", ""))


    def test_e2e_timing_chain(self):
        """Caption wählen -> Wort wählen -> Timing ändern (Komma)
        -> Preview -> Undo/Redo -> Save -> Load -> Re-Export.

        Kette: Editor == Draft == ProjectState == Reload == Controller
        == RenderModel == Override == ASS-Input (Start/Ende, absolut).
        """
        video = "C:/vids/clip.mp4"
        self.controller.pending_project = {"video_path": video,
                                           "model": "tiny", "language": "de"}
        self.controller.last_transcript = {
            "video_path": video, "segments": _original_segments(),
            "model": "tiny", "language": "de"}
        screen = self.controller.get_screen("caption_style")
        screen.on_show()
        # Caption 1 (5.0-8.0) + Wort 2 ("München") wählen:
        cap_labels = list(screen._editor_option.cget("values"))
        screen._editor_option.set(cap_labels[1])
        screen._on_editor_select(None)
        word_labels = list(screen._word_option.cget("values"))
        screen._word_option.set(word_labels[2])
        screen._on_word_select(None)
        screen._word_start_entry.delete(0, "end")
        screen._word_start_entry.insert(0, "6,3")
        screen._word_end_entry.delete(0, "end")
        screen._word_end_entry.insert(0, "7.0")
        screen._on_word_set()
        # Editor == Controller == Preview (absolut, kein Relativieren):
        editor_times = (screen._transcript_segments[1]["words"][2]["start"],
                        screen._transcript_segments[1]["words"][2]["end"])
        self.assertEqual(editor_times, (6.3, 7.0))
        ctrl_times = (
            self.controller.last_transcript["segments"][1]["words"][2]["start"],
            self.controller.last_transcript["segments"][1]["words"][2]["end"])
        self.assertEqual(ctrl_times, (6.3, 7.0))
        preview_times = [(w.start, w.end)
                         for w in screen._preview_caption.words
                         if w.word == "München"]
        self.assertEqual(preview_times, [(6.3, 7.0)])
        # Undo -> alt, Redo -> neu:
        screen._on_undo()
        self.assertEqual(
            screen._transcript_segments[1]["words"][2]["end"], 7.0)
        self.assertEqual(
            screen._transcript_segments[1]["words"][2]["start"], 6.2)
        screen._on_redo()
        self.assertEqual(
            (screen._transcript_segments[1]["words"][2]["start"],
             screen._transcript_segments[1]["words"][2]["end"]),
            (6.3, 7.0))
        # Save -> Clear -> Load:
        self.controller.save_project_state(self.proj_path)
        self.controller.last_transcript = None
        self.controller.pending_project = None
        screen.clear_transcript()
        loaded = load_project(self.proj_path)
        self.assertEqual(
            (loaded.segments[1]["words"][2]["start"],
             loaded.segments[1]["words"][2]["end"]),
            (6.3, 7.0))
        self.controller.load_project_state(self.proj_path)
        screen.on_show()
        # RenderModel aus Reload == Editor (Transkript-Captions sind
        # RenderCaption-Objekte aus den geladenen Segmenten):
        model_times = [(w.start, w.end)
                       for w in screen._transcript_captions[1].words
                       if w.word == "München"]
        self.assertEqual(model_times, [(6.3, 7.0)])
        self.assertEqual(screen._transcript_captions[1].text,
                         loaded.segments[1]["text"])
        # Re-Export: Override == ASS-Input, kein Whisper:
        tmp = _tmpdir(self)
        captured = {}
        _pipe, engine, _out, _srt = _run(
            self, tmp, captured, override=loaded.segments)
        engine.transcribe.assert_not_called()
        ass_times = [(w["start"], w["end"])
                     for w in captured["ass_segments"][1]["words"]
                     if w["word"] == "München"]
        self.assertEqual(ass_times, [(6.3, 7.0)])

    def test_e2e_timing_drag_chain(self):
        """Drag-Timing (absolut, 5.0-8.0) -> Undo/Redo -> Save -> Load
        -> Preview -> Re-Export (ASS-Input), kein Whisper.

        Kette: Editor == Controller == RenderModel == ProjectState
        == Reload == Override == ASS-Input (Start/Ende).
        """
        video = "C:/vids/clip.mp4"
        segments = [{
            "start": 5.0, "end": 8.0, "text": "Test caption here",
            "words": [{"word": "Test", "start": 5.0, "end": 5.3},
                      {"word": "caption", "start": 5.4, "end": 6.2},
                      {"word": "here", "start": 6.5, "end": 8.0}],
        }]
        self.controller.pending_project = {"video_path": video,
                                           "model": "tiny", "language": "de"}
        self.controller.last_transcript = {
            "video_path": video, "segments": segments,
            "model": "tiny", "language": "de"}
        screen = self.controller.get_screen("caption_style")
        screen.on_show()
        labels = list(screen._word_option.cget("values"))
        screen._word_option.set(labels[1])
        screen._on_word_select(None)
        # Drag: End-Marker von 6.2 auf 6.4 (Lücke bis 6.5, absolut):
        _ax0, ax1 = screen._timeline_handles()
        width = screen._timeline_w
        screen._on_timeline_press(SimpleNamespace(x=ax1 - 2))
        screen._on_timeline_move(
            SimpleNamespace(x=_timeline_x(6.4, width, 5.0, 8.0)))
        screen._on_timeline_release(SimpleNamespace(x=0))
        editor_times = (screen._transcript_segments[0]["words"][1]["start"],
                        screen._transcript_segments[0]["words"][1]["end"])
        self.assertEqual(editor_times, (5.4, 6.4))
        ctrl_times = (
            self.controller.last_transcript["segments"][0]["words"][1]["start"],
            self.controller.last_transcript["segments"][0]["words"][1]["end"])
        self.assertEqual(ctrl_times, (5.4, 6.4))
        model_times = [(w.start, w.end)
                       for w in screen._preview_caption.words
                       if w.word == "caption"]
        self.assertEqual(model_times, [(5.4, 6.4)])
        # Undo -> alt, Redo -> neu:
        screen._on_undo()
        self.assertEqual(
            screen._transcript_segments[0]["words"][1]["end"], 6.2)
        screen._on_redo()
        self.assertEqual(
            (screen._transcript_segments[0]["words"][1]["start"],
             screen._transcript_segments[0]["words"][1]["end"]),
            (5.4, 6.4))
        # Save -> Clear -> Load -> Preview:
        self.controller.save_project_state(self.proj_path)
        self.controller.last_transcript = None
        self.controller.pending_project = None
        screen.clear_transcript()
        loaded = load_project(self.proj_path)
        self.assertEqual(
            (loaded.segments[0]["words"][1]["start"],
             loaded.segments[0]["words"][1]["end"]),
            (5.4, 6.4))
        self.controller.load_project_state(self.proj_path)
        screen.on_show()
        reloaded = [(w.word, w.start, w.end)
                    for w in screen._preview_caption.words]
        self.assertEqual(reloaded,
                         [(w["word"], w["start"], w["end"])
                          for w in loaded.segments[0]["words"]])
        # Re-Export: Override == ASS-Input, kein Whisper:
        tmp = _tmpdir(self)
        captured = {}
        _pipe, engine, _out, _srt = _run(
            self, tmp, captured, override=loaded.segments)
        engine.transcribe.assert_not_called()
        ass_times = [(w["start"], w["end"])
                     for w in captured["ass_segments"][0]["words"]
                     if w["word"] == "caption"]
        self.assertEqual(ass_times, [(5.4, 6.4)])

    def test_e2e_nudge_chain(self):
        """Nudge (absolut, 5.0-8.0) -> Undo/Redo -> Save -> Load
        -> Preview -> Re-Export (ASS-Input), kein Whisper.

        Kette: Editor == Controller == RenderModel == ProjectState
        == Reload == Override == ASS-Input (Start/Ende).
        """
        video = "C:/vids/clip.mp4"
        self.controller.pending_project = {"video_path": video,
                                           "model": "tiny", "language": "de"}
        self.controller.last_transcript = {
            "video_path": video, "segments": _original_segments(),
            "model": "tiny", "language": "de"}
        screen = self.controller.get_screen("caption_style")
        screen.on_show()
        cap_labels = list(screen._editor_option.cget("values"))
        screen._editor_option.set(cap_labels[1])
        screen._on_editor_select(None)
        word_labels = list(screen._word_option.cget("values"))
        screen._word_option.set(word_labels[2])
        screen._on_word_select(None)
        # "München" 6.2-7.0 -> Start +0.05, Ende -0.05:
        screen._on_nudge("start", 0.05)
        screen._on_nudge("end", -0.05)
        edited = (screen._transcript_segments[1]["words"][2]["start"],
                  screen._transcript_segments[1]["words"][2]["end"])
        self.assertAlmostEqual(edited[0], 6.25)
        self.assertAlmostEqual(edited[1], 6.95)
        # Undo -> schrittweise zurück, Redo -> wieder hin:
        screen._on_undo()
        self.assertAlmostEqual(
            screen._transcript_segments[1]["words"][2]["end"], 7.0)
        screen._on_undo()
        self.assertAlmostEqual(
            screen._transcript_segments[1]["words"][2]["start"], 6.2)
        screen._on_redo()
        screen._on_redo()
        self.assertAlmostEqual(
            screen._transcript_segments[1]["words"][2]["start"], 6.25)
        # Save -> Clear -> Load -> Preview:
        self.controller.save_project_state(self.proj_path)
        self.controller.last_transcript = None
        self.controller.pending_project = None
        screen.clear_transcript()
        loaded = load_project(self.proj_path)
        self.assertAlmostEqual(loaded.segments[1]["words"][2]["start"], 6.25)
        self.assertAlmostEqual(loaded.segments[1]["words"][2]["end"], 6.95)
        self.controller.load_project_state(self.proj_path)
        screen.on_show()
        cap_labels = list(screen._editor_option.cget("values"))
        screen._editor_option.set(cap_labels[1])
        screen._on_editor_select(None)
        # Preview deterministisch auf Caption 1 fahren (t=6 s):
        screen._select_transcript_caption(6000)
        preview = [(w.word, w.start, w.end)
                   for w in screen._preview_caption.words]
        self.assertEqual(
            preview,
            [(w["word"], w["start"], w["end"])
             for w in loaded.segments[1]["words"]])
        # Re-Export: Override == ASS-Input, kein Whisper:
        tmp = _tmpdir(self)
        captured = {}
        _pipe, engine, _out, _srt = _run(
            self, tmp, captured, override=loaded.segments)
        engine.transcribe.assert_not_called()
        ass_times = [(w["start"], w["end"])
                     for w in captured["ass_segments"][1]["words"]
                     if w["word"] == "München"]
        self.assertEqual(len(ass_times), 1)
        self.assertAlmostEqual(ass_times[0][0], 6.25)
        self.assertAlmostEqual(ass_times[0][1], 6.95)

    def test_e2e_nudge_key_chain(self):
        """Keyboard-Nudge (absolut) -> Undo/Redo -> Save -> Load
        -> Preview -> Re-Export (ASS-Input), kein Whisper.

        Kette: Editor == Controller == RenderModel == ProjectState
        == Reload == Override == ASS-Input (Start/Ende).
        """
        from unittest.mock import patch as _patch
        video = "C:/vids/clip.mp4"
        segments = [{
            "start": 5.0, "end": 8.0, "text": "Test caption here",
            "words": [{"word": "Test", "start": 5.0, "end": 5.3},
                      {"word": "caption", "start": 5.4, "end": 6.2},
                      {"word": "here", "start": 6.5, "end": 8.0}],
        }]
        self.controller.pending_project = {"video_path": video,
                                           "model": "tiny", "language": "de"}
        self.controller.last_transcript = {
            "video_path": video, "segments": segments,
            "model": "tiny", "language": "de"}
        screen = self.controller.get_screen("caption_style")
        screen.on_show()
        labels = list(screen._word_option.cget("values"))
        screen._word_option.set(labels[1])
        screen._on_word_select(None)

        def key(keysym, state=0):
            with _patch.object(type(screen), "focus_get",
                               return_value=screen._timeline):
                return screen._on_nudge_key(
                    SimpleNamespace(keysym=keysym, state=state))

        # Right -> 5.45, Shift+Left -> 6.15 (absolut, kein Reset auf 0):
        self.assertEqual(key("Right"), "break")
        self.assertEqual(key("Left", state=1), "break")
        edited = (screen._transcript_segments[0]["words"][1]["start"],
                  screen._transcript_segments[0]["words"][1]["end"])
        self.assertAlmostEqual(edited[0], 5.45)
        self.assertAlmostEqual(edited[1], 6.15)
        # Undo -> alt, Redo -> neu:
        screen._on_undo()
        self.assertAlmostEqual(
            screen._transcript_segments[0]["words"][1]["end"], 6.2)
        screen._on_undo()
        self.assertAlmostEqual(
            screen._transcript_segments[0]["words"][1]["start"], 5.4)
        screen._on_redo()
        screen._on_redo()
        self.assertAlmostEqual(
            screen._transcript_segments[0]["words"][1]["start"], 5.45)
        # Save -> Clear -> Load -> Preview:
        self.controller.save_project_state(self.proj_path)
        self.controller.last_transcript = None
        self.controller.pending_project = None
        screen.clear_transcript()
        loaded = load_project(self.proj_path)
        self.assertAlmostEqual(loaded.segments[0]["words"][1]["start"], 5.45)
        self.assertAlmostEqual(loaded.segments[0]["words"][1]["end"], 6.15)
        self.controller.load_project_state(self.proj_path)
        screen.on_show()
        reloaded = [(w.word, w.start, w.end)
                    for w in screen._preview_caption.words]
        self.assertEqual(reloaded,
                         [(w["word"], w["start"], w["end"])
                          for w in loaded.segments[0]["words"]])
        # Re-Export: Override == ASS-Input, kein Whisper:
        tmp = _tmpdir(self)
        captured = {}
        _pipe, engine, _out, _srt = _run(
            self, tmp, captured, override=loaded.segments)
        engine.transcribe.assert_not_called()
        ass_times = [(w["start"], w["end"])
                     for w in captured["ass_segments"][0]["words"]
                     if w["word"] == "caption"]
        self.assertEqual(len(ass_times), 1)
        self.assertAlmostEqual(ass_times[0][0], 5.45)
        self.assertAlmostEqual(ass_times[0][1], 6.15)

    def test_e2e_nudge_step_chain(self):
        """Konfigurierter Step (0.10) -> Button + Keyboard -> Undo/Redo
        -> Save -> Load -> Preview -> Re-Export (ASS-Input), kein Whisper.

        Kette: Editor == Controller == RenderModel == ProjectState
        == Reload == Override == ASS-Input (Start/Ende).
        """
        from unittest.mock import patch as _patch

        from config import set_config_value
        from ui.screens import settings as settings_mod
        video = "C:/vids/clip.mp4"
        segments = [{
            "start": 5.0, "end": 8.0, "text": "Test caption here",
            "words": [{"word": "Test", "start": 5.0, "end": 5.3},
                      {"word": "caption", "start": 5.4, "end": 6.2},
                      {"word": "here", "start": 6.5, "end": 8.0}],
        }]
        self.controller.pending_project = {"video_path": video,
                                           "model": "tiny", "language": "de"}
        self.controller.last_transcript = {
            "video_path": video, "segments": segments,
            "model": "tiny", "language": "de"}
        screen = self.controller.get_screen("caption_style")
        screen.on_show()
        labels = list(screen._word_option.cget("values"))
        screen._word_option.set(labels[1])
        screen._on_word_select(None)
        old_env = os.environ.get("CAPTI_CONFIG_FILE")
        os.environ["CAPTI_CONFIG_FILE"] = str(Path(self.tmp.name)
                                              / "config.json")
        try:
            self.assertTrue(
                set_config_value(settings_mod.NUDGE_STEP_KEY, 0.10))
            screen._refresh_nudge_hint()
            self.assertIn(
                "0,10", screen._nudge_hint_label.cget("text"))
            # Button: Start +0.10; Keyboard: Shift+Left -> Ende -0.10:
            screen._end_minus_btn.invoke()
            with _patch.object(type(screen), "focus_get",
                               return_value=screen._timeline):
                screen._on_nudge_key(
                    SimpleNamespace(keysym="Right", state=0))
            edited = (screen._transcript_segments[0]["words"][1]["start"],
                      screen._transcript_segments[0]["words"][1]["end"])
            self.assertAlmostEqual(edited[0], 5.5)
            self.assertAlmostEqual(edited[1], 6.1)
            # Undo -> alt, Redo -> neu:
            screen._on_undo()
            screen._on_undo()
            self.assertAlmostEqual(
                screen._transcript_segments[0]["words"][1]["start"], 5.4)
            screen._on_redo()
            screen._on_redo()
            self.assertAlmostEqual(
                screen._transcript_segments[0]["words"][1]["start"], 5.5)
            # Save -> Clear -> Load -> Preview:
            self.controller.save_project_state(self.proj_path)
        finally:
            if old_env is None:
                os.environ.pop("CAPTI_CONFIG_FILE", None)
            else:
                os.environ["CAPTI_CONFIG_FILE"] = old_env
        self.controller.last_transcript = None
        self.controller.pending_project = None
        screen.clear_transcript()
        loaded = load_project(self.proj_path)
        self.assertAlmostEqual(loaded.segments[0]["words"][1]["start"], 5.5)
        self.assertAlmostEqual(loaded.segments[0]["words"][1]["end"], 6.1)
        self.controller.load_project_state(self.proj_path)
        screen.on_show()
        reloaded = [(w.word, w.start, w.end)
                    for w in screen._preview_caption.words]
        self.assertEqual(reloaded,
                         [(w["word"], w["start"], w["end"])
                          for w in loaded.segments[0]["words"]])
        # Re-Export: Override == ASS-Input, kein Whisper:
        tmp = _tmpdir(self)
        captured = {}
        _pipe, engine, _out, _srt = _run(
            self, tmp, captured, override=loaded.segments)
        engine.transcribe.assert_not_called()
        ass_times = [(w["start"], w["end"])
                     for w in captured["ass_segments"][0]["words"]
                     if w["word"] == "caption"]
        self.assertEqual(len(ass_times), 1)
        self.assertAlmostEqual(ass_times[0][0], 5.5)
        self.assertAlmostEqual(ass_times[0][1], 6.1)

    def test_e2e_preset_chain(self):
        """Preset-Klick (0.10) -> Nudge -> Undo/Redo -> Save -> Load
        -> Preview -> Re-Export (ASS-Input), kein Whisper.

        Kette: Editor == Controller == RenderModel == ProjectState
        == Reload == Override == ASS-Input (Start/Ende).
        """
        from unittest.mock import patch as _patch

        from ui.screens import settings as settings_mod
        video = "C:/vids/clip.mp4"
        segments = [{
            "start": 5.0, "end": 8.0, "text": "Test caption here",
            "words": [{"word": "Test", "start": 5.0, "end": 5.3},
                      {"word": "caption", "start": 5.4, "end": 6.2},
                      {"word": "here", "start": 6.5, "end": 8.0}],
        }]
        self.controller.pending_project = {"video_path": video,
                                           "model": "tiny", "language": "de"}
        self.controller.last_transcript = {
            "video_path": video, "segments": segments,
            "model": "tiny", "language": "de"}
        screen = self.controller.get_screen("caption_style")
        screen.on_show()
        labels = list(screen._word_option.cget("values"))
        screen._word_option.set(labels[1])
        screen._on_word_select(None)
        old_env = os.environ.get("CAPTI_CONFIG_FILE")
        os.environ["CAPTI_CONFIG_FILE"] = str(Path(self.tmp.name)
                                              / "config.json")
        try:
            # Preset-Klick schreibt Settings; Editor liest Settings:
            settings_screen = self.controller.get_screen("settings")
            settings_screen._on_preset_selected(0.10)
            self.assertEqual(settings_mod.read_nudge_step(), 0.10)
            from ui.screens.caption_style import get_nudge_step
            self.assertEqual(get_nudge_step(), 0.10)
            screen._refresh_nudge_hint()
            self.assertIn(
                "0,10", screen._nudge_hint_label.cget("text"))
            screen._end_minus_btn.invoke()
            with _patch.object(type(screen), "focus_get",
                               return_value=screen._timeline):
                screen._on_nudge_key(
                    SimpleNamespace(keysym="Right", state=0))
            edited = (screen._transcript_segments[0]["words"][1]["start"],
                      screen._transcript_segments[0]["words"][1]["end"])
            self.assertAlmostEqual(edited[0], 5.5)
            self.assertAlmostEqual(edited[1], 6.1)
            screen._on_undo()
            screen._on_undo()
            self.assertAlmostEqual(
                screen._transcript_segments[0]["words"][1]["start"], 5.4)
            screen._on_redo()
            screen._on_redo()
            self.assertAlmostEqual(
                screen._transcript_segments[0]["words"][1]["start"], 5.5)
            self.controller.save_project_state(self.proj_path)
        finally:
            if old_env is None:
                os.environ.pop("CAPTI_CONFIG_FILE", None)
            else:
                os.environ["CAPTI_CONFIG_FILE"] = old_env
        self.controller.last_transcript = None
        self.controller.pending_project = None
        screen.clear_transcript()
        loaded = load_project(self.proj_path)
        self.assertAlmostEqual(loaded.segments[0]["words"][1]["start"], 5.5)
        self.assertAlmostEqual(loaded.segments[0]["words"][1]["end"], 6.1)
        self.controller.load_project_state(self.proj_path)
        screen.on_show()
        reloaded = [(w.word, w.start, w.end)
                    for w in screen._preview_caption.words]
        self.assertEqual(reloaded,
                         [(w["word"], w["start"], w["end"])
                          for w in loaded.segments[0]["words"]])
        tmp = _tmpdir(self)
        captured = {}
        _pipe, engine, _out, _srt = _run(
            self, tmp, captured, override=loaded.segments)
        engine.transcribe.assert_not_called()
        ass_times = [(w["start"], w["end"])
                     for w in captured["ass_segments"][0]["words"]
                     if w["word"] == "caption"]
        self.assertEqual(len(ass_times), 1)
        self.assertAlmostEqual(ass_times[0][0], 5.5)
        self.assertAlmostEqual(ass_times[0][1], 6.1)

    def test_e2e_caption_nudge_chain(self):
        """Caption-Grenzen-Nudge -> Undo/Redo -> Save -> Load
        -> Preview/Model -> Override-Re-Export -> ASS.

        Kette: Editor == Controller == RenderModel == ProjectState
        == Reload == Override == ASS-Input (Start/Ende/Wörter/Text),
        Whisper call_count == 0 beim Override.
        """
        video = "C:/vids/clip.mp4"
        self.controller.pending_project = {"video_path": video,
                                           "model": "tiny", "language": "de"}
        self.controller.last_transcript = {
            "video_path": video, "segments": _original_segments(),
            "model": "tiny", "language": "de"}
        screen = self.controller.get_screen("caption_style")
        screen.on_show()
        labels = list(screen._editor_option.cget("values"))
        screen._editor_option.set(labels[1])
        screen._on_editor_select(None)
        # Start +0.05 (5.05, Wörter ab 5.1 bleiben drin), End +0.05:
        screen._cap_start_plus_btn.invoke()
        screen._cap_end_plus_btn.invoke()
        edited = (screen._transcript_segments[1]["start"],
                  screen._transcript_segments[1]["end"])
        self.assertAlmostEqual(edited[0], 5.05)
        self.assertAlmostEqual(edited[1], 8.05)
        # Wörter/Text unverändert:
        self.assertEqual(
            [(w["word"], w["start"], w["end"]) for w in
             screen._transcript_segments[1]["words"]],
            [("Grüße", 5.1, 5.7), ("aus", 5.8, 6.1),
             ("München", 6.2, 7.0), ("heute", 7.1, 8.0)])
        self.assertEqual(screen._transcript_segments[1]["text"],
                         "Grüße aus München heute")
        # Undo -> schrittweise zurück, Redo -> wieder hin:
        screen._on_undo()
        self.assertAlmostEqual(screen._transcript_segments[1]["end"], 8.0)
        screen._on_undo()
        self.assertAlmostEqual(screen._transcript_segments[1]["start"], 5.0)
        screen._on_redo()
        screen._on_redo()
        self.assertAlmostEqual(screen._transcript_segments[1]["start"], 5.05)
        self.assertAlmostEqual(screen._transcript_segments[1]["end"], 8.05)
        # Controller synchron:
        ctrl = self.controller.last_transcript["segments"][1]
        self.assertAlmostEqual(ctrl["start"], 5.05)
        self.assertAlmostEqual(ctrl["end"], 8.05)
        # Save -> Clear -> Load -> RenderModel:
        self.controller.save_project_state(self.proj_path)
        self.controller.last_transcript = None
        self.controller.pending_project = None
        screen.clear_transcript()
        loaded = load_project(self.proj_path)
        self.assertAlmostEqual(loaded.segments[1]["start"], 5.05)
        self.assertAlmostEqual(loaded.segments[1]["end"], 8.05)
        self.controller.load_project_state(self.proj_path)
        screen.on_show()
        model_cap = screen._transcript_captions[1]
        self.assertAlmostEqual(model_cap.start, 5.05)
        self.assertAlmostEqual(model_cap.end, 8.05)
        self.assertEqual(
            [(w.word, w.start, w.end) for w in model_cap.words],
            [(w["word"], w["start"], w["end"])
             for w in loaded.segments[1]["words"]])
        # Re-Export (Override + echter ASS-Renderer):
        tmp = _tmpdir(self)
        captured = {}
        _pipe, engine, _out, _srt = _run(
            self, tmp, captured, override=loaded.segments)
        engine.transcribe.assert_not_called()
        ass_seg = captured["ass_segments"][1]
        self.assertAlmostEqual(ass_seg["start"], 5.05)
        self.assertAlmostEqual(ass_seg["end"], 8.05)
        self.assertEqual(
            [(w["word"], w["start"], w["end"]) for w in ass_seg["words"]],
            [(w["word"], w["start"], w["end"])
             for w in loaded.segments[1]["words"]])

    def test_e2e_caption_snap_chain(self):
        """Block 38: Drag nahe Wortgrenze -> Snap -> Undo/Redo -> Save
        -> Load -> Preview -> Override -> ASS (absolute Zeiten 5.0-8.0).

        Kette: Editor == Controller == RenderModel == ProjectState
        == Reload == Override == ASS-Input; Whisper wird übersprungen.
        """
        from types import SimpleNamespace

        video = "C:/vids/clip.mp4"
        segments = [{
            "start": 5.0, "end": 8.0, "text": "eins zwei",
            "words": [{"word": "eins", "start": 5.5, "end": 6.0},
                      {"word": "zwei", "start": 6.5, "end": 7.0}],
        }]
        self.controller.pending_project = {"video_path": video,
                                           "model": "tiny", "language": "de"}
        self.controller.last_transcript = {
            "video_path": video, "segments": segments,
            "model": "tiny", "language": "de"}
        screen = self.controller.get_screen("caption_style")
        screen.on_show()
        labels = list(screen._editor_option.cget("values"))
        screen._editor_option.set(labels[0])
        screen._on_editor_select(None)

        def snap_drag(which, near_t):
            handles = screen._timeline_caption_handles()
            x0 = handles[0] if which == "start" else handles[1]
            screen._on_timeline_press(SimpleNamespace(x=x0))
            drag = screen._timeline_drag
            width = screen._timeline_w
            span = drag["map_end"] - drag["map_start"]
            move_x = 10 + (near_t - drag["map_start"]) / span * (width - 20)
            screen._on_timeline_move(SimpleNamespace(x=move_x))
            screen._on_timeline_release(SimpleNamespace(x=0))

        # Ende nahe 7.0 (6.97) -> Snap exakt 7.0; Start nahe 5.5 -> 5.5:
        snap_drag("end", 6.97)
        snap_drag("start", 5.53)
        editor = screen._transcript_segments[0]
        self.assertAlmostEqual((editor["start"], editor["end"]), (5.5, 7.0))
        self.assertEqual(
            [(w["word"], w["start"], w["end"]) for w in editor["words"]],
            [("eins", 5.5, 6.0), ("zwei", 6.5, 7.0)])
        # Controller == Editor:
        ctrl = self.controller.last_transcript["segments"][0]
        self.assertAlmostEqual((ctrl["start"], ctrl["end"]), (5.5, 7.0))
        # RenderModel == Editor:
        model_cap = screen._transcript_captions[0]
        self.assertAlmostEqual((model_cap.start, model_cap.end), (5.5, 7.0))
        # Undo -> Redo (LIFO: erst Start-, dann End-Drag zurück):
        screen._on_undo()
        self.assertAlmostEqual(
            (screen._transcript_segments[0]["start"],
             screen._transcript_segments[0]["end"]), (5.0, 7.0))
        screen._on_undo()
        self.assertAlmostEqual(
            (screen._transcript_segments[0]["start"],
             screen._transcript_segments[0]["end"]), (5.0, 8.0))
        screen._on_redo()
        screen._on_redo()
        self.assertAlmostEqual(
            (screen._transcript_segments[0]["start"],
             screen._transcript_segments[0]["end"]), (5.5, 7.0))
        # Save -> Clear -> Load:
        self.controller.save_project_state(self.proj_path)
        self.controller.last_transcript = None
        self.controller.pending_project = None
        screen.clear_transcript()
        loaded = load_project(self.proj_path)
        # ProjectState == Reload:
        self.assertAlmostEqual(
            (loaded.segments[0]["start"], loaded.segments[0]["end"]),
            (5.5, 7.0))
        self.controller.load_project_state(self.proj_path)
        screen.on_show()
        # Preview == Reload:
        preview_words = [(w.word, w.start, w.end)
                         for w in screen._preview_caption.words]
        self.assertEqual(preview_words,
                         [(w["word"], w["start"], w["end"])
                          for w in loaded.segments[0]["words"]])
        # Re-Export (Override + echter ASS-Renderer):
        tmp = _tmpdir(self)
        captured = {}
        _pipe, engine, _out, _srt = _run(
            self, tmp, captured, override=loaded.segments)
        engine.transcribe.assert_not_called()
        self.assertAlmostEqual(captured["ass_segments"][0]["start"], 5.5)
        self.assertAlmostEqual(captured["ass_segments"][0]["end"], 7.0)
        ass_words = captured["ass_segments"][0]["words"]
        self.assertEqual(
            [(w["word"], w["start"], w["end"]) for w in ass_words],
            preview_words)

    def test_e2e_snap_tolerance_chain(self):
        """Block 41: konfigurierte Toleranz (16 px) -> Snap -> Undo/Redo
        -> Save -> Load -> Preview -> Override -> ASS (5.0-8.0).

        Kette: Editor == Controller == RenderModel == ProjectState
        == Reload == Override == ASS-Input; Whisper wird übersprungen.
        """
        from types import SimpleNamespace

        from config import set_config_value
        from ui.screens import settings as settings_mod
        video = "C:/vids/clip.mp4"
        segments = [{
            "start": 5.0, "end": 8.0, "text": "eins zwei",
            "words": [{"word": "eins", "start": 5.4, "end": 6.0},
                      {"word": "zwei", "start": 6.5, "end": 7.0}],
        }]
        old_env = os.environ.get("CAPTI_CONFIG_FILE")
        os.environ["CAPTI_CONFIG_FILE"] = str(Path(self.tmp.name)
                                              / "config.json")
        try:
            self.assertTrue(set_config_value(
                settings_mod.SNAP_TOLERANCE_KEY, 16.0))
            self.controller.pending_project = {"video_path": video,
                                               "model": "tiny",
                                               "language": "de"}
            self.controller.last_transcript = {
                "video_path": video, "segments": segments,
                "model": "tiny", "language": "de"}
            screen = self.controller.get_screen("caption_style")
            screen.on_show()
            labels = list(screen._editor_option.cget("values"))
            screen._editor_option.set(labels[0])
            screen._on_editor_select(None)

            def snap_drag(which, near_t):
                handles = screen._timeline_caption_handles()
                x0 = handles[0] if which == "start" else handles[1]
                screen._on_timeline_press(SimpleNamespace(x=x0))
                drag = screen._timeline_drag
                width = screen._timeline_w
                span = drag["map_end"] - drag["map_start"]
                move_x = 10 + (near_t - drag["map_start"]) / span * (width - 20)
                screen._on_timeline_move(SimpleNamespace(x=move_x))
                screen._on_timeline_release(SimpleNamespace(x=0))

            # 5.48 liegt 10.7 px neben 5.4: Snap nur dank 16 px:
            snap_drag("start", 5.48)
            editor = screen._transcript_segments[0]
            self.assertAlmostEqual((editor["start"], editor["end"]),
                                   (5.4, 8.0))
            self.assertEqual(
                [(w["word"], w["start"], w["end"]) for w in editor["words"]],
                [("eins", 5.4, 6.0), ("zwei", 6.5, 7.0)])
            ctrl = self.controller.last_transcript["segments"][0]
            self.assertAlmostEqual((ctrl["start"], ctrl["end"]), (5.4, 8.0))
            model_cap = screen._transcript_captions[0]
            self.assertAlmostEqual((model_cap.start, model_cap.end),
                                   (5.4, 8.0))
            screen._on_undo()
            self.assertAlmostEqual(
                screen._transcript_segments[0]["start"], 5.0)
            screen._on_redo()
            self.assertAlmostEqual(
                screen._transcript_segments[0]["start"], 5.4)
            self.controller.save_project_state(self.proj_path)
        finally:
            if old_env is None:
                os.environ.pop("CAPTI_CONFIG_FILE", None)
            else:
                os.environ["CAPTI_CONFIG_FILE"] = old_env
        self.controller.last_transcript = None
        self.controller.pending_project = None
        screen.clear_transcript()
        loaded = load_project(self.proj_path)
        self.assertAlmostEqual(
            (loaded.segments[0]["start"], loaded.segments[0]["end"]),
            (5.4, 8.0))
        self.controller.load_project_state(self.proj_path)
        screen.on_show()
        preview_words = [(w.word, w.start, w.end)
                         for w in screen._preview_caption.words]
        self.assertEqual(preview_words,
                         [(w["word"], w["start"], w["end"])
                          for w in loaded.segments[0]["words"]])
        tmp = _tmpdir(self)
        captured = {}
        _pipe, engine, _out, _srt = _run(
            self, tmp, captured, override=loaded.segments)
        engine.transcribe.assert_not_called()
        self.assertAlmostEqual(captured["ass_segments"][0]["start"], 5.4)
        ass_words = captured["ass_segments"][0]["words"]
        self.assertEqual(
            [(w["word"], w["start"], w["end"]) for w in ass_words],
            preview_words)

    def test_e2e_snap_preset_chain(self):
        """Block 42: Preset 8->16->Drag->Snap->Undo->Redo->4->Drag
        ->Save->Load->Preview->Override->ASS.

        Kette: Preset == Editor == Controller == RenderModel ==
        ProjectState == Reload == Override == ASS-Input. Snap-Settings
        landen NICHT in ProjectState; Whisper wird übersprungen.
        """
        from types import SimpleNamespace

        from config import set_config_value
        from ui.screens import settings as settings_mod
        video = "C:/vids/clip.mp4"
        segments = [{
            "start": 5.0, "end": 8.0, "text": "eins zwei",
            "words": [{"word": "eins", "start": 5.4, "end": 6.0},
                      {"word": "zwei", "start": 6.5, "end": 7.0}],
        }]
        old_env = os.environ.get("CAPTI_CONFIG_FILE")
        os.environ["CAPTI_CONFIG_FILE"] = str(Path(self.tmp.name)
                                              / "config.json")
        try:
            settings_screen = self.controller.get_screen("settings")
            settings_screen.load_settings()
            # Start: 8-px-Preset aktiv:
            settings_screen._on_preset_selected_snap(8.0)
            self.controller.pending_project = {"video_path": video,
                                               "model": "tiny",
                                               "language": "de"}
            self.controller.last_transcript = {
                "video_path": video, "segments": segments,
                "model": "tiny", "language": "de"}
            screen = self.controller.get_screen("caption_style")
            screen.on_show()
            labels = list(screen._editor_option.cget("values"))
            screen._editor_option.set(labels[0])
            screen._on_editor_select(None)

            def snap_drag(which, near_t):
                handles = screen._timeline_caption_handles()
                x0 = handles[0] if which == "start" else handles[1]
                screen._on_timeline_press(SimpleNamespace(x=x0))
                screen._on_timeline_move(SimpleNamespace(
                    x=10 + (near_t - screen._timeline_drag["map_start"])
                    / (screen._timeline_drag["map_end"]
                       - screen._timeline_drag["map_start"])
                    * (screen._timeline_w - 20)))
                screen._on_timeline_release(SimpleNamespace(x=0))

            # 16 px: 5.48 (10.7 px neben 5.4) snappt exakt 5.4:
            settings_screen._on_preset_selected_snap(16.0)
            snap_drag("start", 5.48)
            editor = screen._transcript_segments[0]
            self.assertAlmostEqual((editor["start"], editor["end"]),
                                   (5.4, 8.0))
            # Undo -> Redo:
            screen._on_undo()
            self.assertAlmostEqual(
                screen._transcript_segments[0]["start"], 5.0)
            screen._on_redo()
            self.assertAlmostEqual(
                screen._transcript_segments[0]["start"], 5.4)
            # 4 px: 6.975 (3.3 px neben 7.0) snappt Ende exakt 7.0:
            settings_screen._on_preset_selected_snap(4.0)
            snap_drag("end", 6.975)
            editor = screen._transcript_segments[0]
            self.assertAlmostEqual(editor["start"], 5.4)
            self.assertAlmostEqual(editor["end"], 7.0)
            self.assertEqual(editor["text"], "eins zwei")
            self.controller.save_project_state(self.proj_path)
        finally:
            if old_env is None:
                os.environ.pop("CAPTI_CONFIG_FILE", None)
            else:
                os.environ["CAPTI_CONFIG_FILE"] = old_env
        self.controller.last_transcript = None
        self.controller.pending_project = None
        screen.clear_transcript()
        loaded = load_project(self.proj_path)
        self.assertAlmostEqual(
            (loaded.segments[0]["start"], loaded.segments[0]["end"]),
            (5.4, 7.0))
        self.assertEqual(loaded.segments[0]["text"], "eins zwei")
        # Snap-Settings NICHT in ProjectState:
        proj_raw = open(self.proj_path, encoding="utf-8").read()
        self.assertNotIn("snap_tolerance", proj_raw)
        self.controller.load_project_state(self.proj_path)
        screen.on_show()
        preview_words = [(w.word, w.start, w.end)
                         for w in screen._preview_caption.words]
        self.assertEqual(preview_words,
                         [(w["word"], w["start"], w["end"])
                          for w in loaded.segments[0]["words"]])
        tmp = _tmpdir(self)
        captured = {}
        _pipe, engine, _out, _srt = _run(
            self, tmp, captured, override=loaded.segments)
        engine.transcribe.assert_not_called()
        self.assertAlmostEqual(captured["ass_segments"][0]["start"], 5.4)
        self.assertAlmostEqual(captured["ass_segments"][0]["end"], 7.0)
        ass_words = captured["ass_segments"][0]["words"]
        self.assertEqual(
            [(w["word"], w["start"], w["end"]) for w in ass_words],
            preview_words)

    def test_e2e_caption_keyboard_nudge_chain(self):
        """Block 48: Keyboard Start-/End-Nudge -> Undo -> Redo -> Save
        -> Load -> Preview -> Override -> ASS.

        Kette: Editor == Controller == RenderModel == ProjectState
        == Reload == Override == ASS-Input; Whisper wird übersprungen.
        """
        from types import SimpleNamespace

        video = "C:/vids/clip.mp4"
        segments = [{
            "start": 5.0, "end": 8.0, "text": "eins zwei",
            "words": [{"word": "eins", "start": 5.4, "end": 6.0},
                      {"word": "zwei", "start": 6.5, "end": 7.0}],
        }]
        old_env = os.environ.get("CAPTI_CONFIG_FILE")
        os.environ["CAPTI_CONFIG_FILE"] = str(Path(self.tmp.name)
                                              / "config.json")
        try:
            self.controller.pending_project = {"video_path": video,
                                               "model": "tiny",
                                               "language": "de"}
            self.controller.last_transcript = {
                "video_path": video, "segments": segments,
                "model": "tiny", "language": "de"}
            screen = self.controller.get_screen("caption_style")
            screen.on_show()
            labels = list(screen._editor_option.cget("values"))
            screen._editor_option.set(labels[0])
            screen._on_editor_select(None)
            screen._word_index = None
            # Block 50: Caption-Hint vorhanden, zeigt Live-Step:
            hint = screen._cap_key_hint_label.cget("text")
            self.assertIn("0,05", hint)

            def key(keysym, state=0):
                # Caption-Kontext: Commit-Refresh wählt sonst Wort 0 vor:
                screen._word_index = None
                with patch.object(type(screen), "focus_get",
                                  return_value=screen._timeline):
                    return screen._on_nudge_key(
                        SimpleNamespace(keysym=keysym, state=state))

            # Start -0.05, Ende +0.05 (exakt, kein Snap):
            self.assertEqual(key("Left"), "break")
            self.assertEqual(key("Right", state=1), "break")
            editor = screen._transcript_segments[0]
            self.assertAlmostEqual(editor["start"], 4.95)
            self.assertAlmostEqual(editor["end"], 8.05)
            self.assertEqual(editor["text"], "eins zwei")
            self.assertEqual(
                [(w["word"], w["start"], w["end"])
                 for w in editor["words"]],
                [("eins", 5.4, 6.0), ("zwei", 6.5, 7.0)])
            # Undo -> Undo -> Redo -> Redo:
            screen._on_undo()
            self.assertAlmostEqual(
                screen._transcript_segments[0]["end"], 8.0)
            screen._on_undo()
            self.assertAlmostEqual(
                screen._transcript_segments[0]["start"], 5.0)
            screen._on_redo()
            screen._on_redo()
            editor = screen._transcript_segments[0]
            self.assertAlmostEqual(editor["start"], 4.95)
            self.assertAlmostEqual(editor["end"], 8.05)
            self.controller.save_project_state(self.proj_path)
        finally:
            if old_env is None:
                os.environ.pop("CAPTI_CONFIG_FILE", None)
            else:
                os.environ["CAPTI_CONFIG_FILE"] = old_env
        self.controller.last_transcript = None
        self.controller.pending_project = None
        screen.clear_transcript()
        loaded = load_project(self.proj_path)
        self.assertAlmostEqual(loaded.segments[0]["start"], 4.95)
        self.assertAlmostEqual(loaded.segments[0]["end"], 8.05)
        self.assertEqual(loaded.segments[0]["text"], "eins zwei")
        self.controller.load_project_state(self.proj_path)
        screen.on_show()
        preview_words = [(w.word, w.start, w.end)
                         for w in screen._preview_caption.words]
        self.assertEqual(preview_words,
                         [(w["word"], w["start"], w["end"])
                          for w in loaded.segments[0]["words"]])
        tmp = _tmpdir(self)
        captured = {}
        _pipe, engine, _out, _srt = _run(
            self, tmp, captured, override=loaded.segments)
        engine.transcribe.assert_not_called()
        self.assertAlmostEqual(captured["ass_segments"][0]["start"], 4.95)
        self.assertAlmostEqual(captured["ass_segments"][0]["end"], 8.05)
        ass_words = captured["ass_segments"][0]["words"]
        self.assertEqual(
            [(w["word"], w["start"], w["end"]) for w in ass_words],
            preview_words)

    def test_e2e_snap_indicator_chain(self):
        """Block 40: Snap-Indikator ist rein temporär (kein Persistenz-
        oder Export-Effekt); Kette Editor == Reload == Override == ASS.
        """
        from types import SimpleNamespace

        video = "C:/vids/clip.mp4"
        segments = [{
            "start": 5.0, "end": 8.0, "text": "eins zwei",
            "words": [{"word": "eins", "start": 5.5, "end": 6.0},
                      {"word": "zwei", "start": 6.5, "end": 7.0}],
        }]
        self.controller.pending_project = {"video_path": video,
                                           "model": "tiny", "language": "de"}
        self.controller.last_transcript = {
            "video_path": video, "segments": segments,
            "model": "tiny", "language": "de"}
        screen = self.controller.get_screen("caption_style")
        screen.on_show()
        labels = list(screen._editor_option.cget("values"))
        screen._editor_option.set(labels[0])
        screen._on_editor_select(None)
        # Press + Move mit Snap: Indikator sichtbar, State gesetzt:
        x0, _x1 = screen._timeline_caption_handles()
        screen._on_timeline_press(SimpleNamespace(x=x0))
        width = screen._timeline_w
        drag = screen._timeline_drag
        span = drag["map_end"] - drag["map_start"]
        move_x = 10 + (5.53 - drag["map_start"]) / span * (width - 20)
        screen._on_timeline_move(SimpleNamespace(x=move_x))
        self.assertEqual(screen._timeline_drag["snapped"]["time"], 5.5)
        self.assertTrue(screen._timeline.find_withtag("snap"))
        # Release: Commit, danach kein Snap-State mehr:
        screen._on_timeline_release(SimpleNamespace(x=0))
        self.assertIsNone(screen._timeline_drag)
        self.assertEqual(screen._timeline.find_withtag("snap"), ())
        self.assertAlmostEqual(screen._transcript_segments[0]["start"], 5.5)
        # Save enthält keine Snap-Eigenschaft:
        self.controller.save_project_state(self.proj_path)
        with open(self.proj_path, encoding="utf-8") as handle:
            saved_text = handle.read()
        self.assertNotIn("snapped", saved_text)
        self.assertNotIn("snap_handle", saved_text)
        # Load -> Preview -> Override -> ASS:
        self.controller.last_transcript = None
        self.controller.pending_project = None
        screen.clear_transcript()
        loaded = load_project(self.proj_path)
        self.controller.load_project_state(self.proj_path)
        screen.on_show()
        preview_words = [(w.word, w.start, w.end)
                         for w in screen._preview_caption.words]
        self.assertEqual(preview_words,
                         [(w["word"], w["start"], w["end"])
                          for w in loaded.segments[0]["words"]])
        tmp = _tmpdir(self)
        captured = {}
        _pipe, engine, _out, _srt = _run(
            self, tmp, captured, override=loaded.segments)
        engine.transcribe.assert_not_called()
        self.assertAlmostEqual(captured["ass_segments"][0]["start"], 5.5)
        ass_words = captured["ass_segments"][0]["words"]
        self.assertEqual(
            [(w["word"], w["start"], w["end"]) for w in ass_words],
            preview_words)

    def test_e2e_word_snap_chain(self):
        """Block 39: Word-Start-Drag -> Snap -> Commit -> Undo/Redo
        -> Save -> Load -> Preview -> Override -> ASS (5.0-8.0).

        Kette: Editor == Controller == RenderModel == ProjectState
        == Reload == Override == ASS-Input; Whisper wird übersprungen.
        """
        from types import SimpleNamespace

        video = "C:/vids/clip.mp4"
        segments = [{
            "start": 5.0, "end": 8.0, "text": "eins zwei drei",
            "words": [{"word": "eins", "start": 5.4, "end": 6.0},
                      {"word": "zwei", "start": 6.0, "end": 6.7},
                      {"word": "drei", "start": 6.7, "end": 7.5}],
        }]
        self.controller.pending_project = {"video_path": video,
                                           "model": "tiny", "language": "de"}
        self.controller.last_transcript = {
            "video_path": video, "segments": segments,
            "model": "tiny", "language": "de"}
        screen = self.controller.get_screen("caption_style")
        screen.on_show()
        labels = list(screen._editor_option.cget("values"))
        screen._editor_option.set(labels[0])
        screen._on_editor_select(None)
        word_labels = list(screen._word_option.cget("values"))
        screen._word_option.set(word_labels[0])
        screen._on_word_select(None)

        def word_drag(to_t):
            x0, _x1 = screen._timeline_handles()
            screen._on_timeline_press(SimpleNamespace(x=x0))
            width = screen._timeline_w
            cap = screen._timeline_caption()
            move_x = 10 + (to_t - cap.start) / (cap.end - cap.start) \
                * (width - 20)
            screen._on_timeline_move(SimpleNamespace(x=move_x))
            screen._on_timeline_release(SimpleNamespace(x=0))

        # Start nahe Caption-Start (5.03) -> Snap exakt 5.0:
        word_drag(5.03)
        editor = screen._transcript_segments[0]
        self.assertAlmostEqual(editor["words"][0]["start"], 5.0)
        self.assertEqual(
            [(w["word"], w["start"], w["end"]) for w in editor["words"]],
            [("eins", 5.0, 6.0), ("zwei", 6.0, 6.7), ("drei", 6.7, 7.5)])
        # Controller == Editor:
        ctrl = self.controller.last_transcript["segments"][0]
        self.assertAlmostEqual(ctrl["words"][0]["start"], 5.0)
        # RenderModel == Editor:
        model_cap = screen._transcript_captions[0]
        self.assertAlmostEqual(model_cap.words[0].start, 5.0)
        # Undo -> Redo:
        screen._on_undo()
        self.assertAlmostEqual(
            screen._transcript_segments[0]["words"][0]["start"], 5.4)
        screen._on_redo()
        self.assertAlmostEqual(
            screen._transcript_segments[0]["words"][0]["start"], 5.0)
        # Save -> Clear -> Load:
        self.controller.save_project_state(self.proj_path)
        self.controller.last_transcript = None
        self.controller.pending_project = None
        screen.clear_transcript()
        loaded = load_project(self.proj_path)
        # ProjectState == Reload:
        self.assertAlmostEqual(loaded.segments[0]["words"][0]["start"], 5.0)
        self.controller.load_project_state(self.proj_path)
        screen.on_show()
        # Preview == Reload:
        preview_words = [(w.word, w.start, w.end)
                         for w in screen._preview_caption.words]
        self.assertEqual(preview_words,
                         [(w["word"], w["start"], w["end"])
                          for w in loaded.segments[0]["words"]])
        # Re-Export (Override + echter ASS-Renderer):
        tmp = _tmpdir(self)
        captured = {}
        _pipe, engine, _out, _srt = _run(
            self, tmp, captured, override=loaded.segments)
        engine.transcribe.assert_not_called()
        ass_words = captured["ass_segments"][0]["words"]
        self.assertEqual(
            [(w["word"], w["start"], w["end"]) for w in ass_words],
            preview_words)

    def test_e2e_home_open_chain(self):
        """L: Home-Open -> Editor zeigt Edit-State."""
        from capti_core.project_state import ProjectState, save_project
        edited = combined_edits(_original_segments())
        save_project(self.proj_path, ProjectState(
            video_path="C:/vids/clip.mp4", segments=edited))
        home = self.controller.get_screen("home")
        home.open_project_file(path=self.proj_path)
        self.assertEqual(self.controller.current_screen, "caption_style")
        screen = self.controller.get_screen("caption_style")
        self.assertEqual(screen._editor_entry.get(), "Hallo We lt")


if __name__ == "__main__":
    unittest.main()
