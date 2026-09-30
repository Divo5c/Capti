"""
Tests für den Caption-Style-Screen (Phase 11).

Die Config wird auf eine temporäre Datei umgeleitet.
"""

import contextlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Hermetisch: echte Nutzer-Config niemals lesen/schreiben
import tempfile as _tmp
if "CAPTI_CONFIG_FILE" not in os.environ:
    os.environ["APPDATA"] = _tmp.mkdtemp(prefix="capti_test_appdata_")


import customtkinter as ctk

from ui.app_controller import AppController
from ui import i18n
from ui.screens import caption_style as cs_mod
from ui.screens.caption_style import CaptionStyleScreen, DEFAULT_STYLE, PRESETS
from capti_core.render_model import (
    RenderCaption, captions_from_segments, pop_state_at, pop_windows,
    style_of, layout_of,
)
from caption_renderer import CaptionRenderer


class TestCaptionStyleScreen(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        ctk.set_appearance_mode("dark")
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except Exception:
            pass

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config_path = Path(self.tmp.name) / "config.json"
        self.patcher = patch.object(cs_mod, "_config_file",
                                    return_value=self.config_path)
        self.patcher.start()
        self.controller = AppController(self.root)
        self.screen = self.controller.get_screen("caption_style")

    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    def test_screen_builds(self):
        self.assertIsInstance(self.screen, CaptionStyleScreen)
        for attr in ("_preview_card", "_color_vars", "pop_scale_slider",
                     "pop_decay_slider", "success_label"):
            self.assertIsNotNone(getattr(self.screen, attr, None))

    def test_defaults_loaded(self):
        """Ohne Config -> exakte Capti-Defaults."""
        self.assertEqual(self.screen.style["normal_color"], "#FFFFFF")
        self.assertEqual(self.screen.style["highlight_color"], "#FFFF00")
        self.assertEqual(self.screen.style["outline_color"], "#101010")
        self.assertEqual(self.screen.style["shadow_alpha"], 128)
        self.assertEqual(self.screen.style["font_name"], "Arial Black")
        self.assertEqual(self.screen.style["pop_scale"], 112)
        self.assertEqual(self.screen.style["pop_decay_ms"], 150)
        self.assertTrue(self.screen.style["pop_enabled"])

    def test_config_values_loaded(self):
        self.config_path.write_text(json.dumps(
            {"caption_style": {"highlight_color": "#FF3B30", "pop_scale": 120}}),
            encoding="utf-8")
        self.screen.load_style()
        self.assertEqual(self.screen.style["highlight_color"], "#FF3B30")
        self.assertEqual(self.screen.style["pop_scale"], 120)
        # Nicht gespeicherte Keys behalten Defaults
        self.assertEqual(self.screen.style["normal_color"], "#FFFFFF")

    def test_color_change_updates_style_and_preview(self):
        self.screen._color_vars["highlight_color"].set("#FF3B30")
        self.screen._on_color_change("highlight_color")
        self.assertEqual(self.screen.style["highlight_color"], "#FF3B30")
        # Phase 32: Vorschau ist ein Canvas – Highlight-Farbe muss in
        # den gezeichneten Text-Items sichtbar sein.
        fills = {self.screen.preview_canvas.itemcget(item, "fill")
                 for item in self.screen.preview_canvas.find_all()
                 if self.screen.preview_canvas.type(item) == "text"}
        # Rahmen während des ersten Worts: Highlight muss sichtbar sein
        slot = self.screen._preview_timeline[0]
        self.screen._draw_preview_frame(slot["start"] + 200)
        fills = {self.screen.preview_canvas.itemcget(item, "fill")
                 for item in self.screen.preview_canvas.find_all()
                 if self.screen.preview_canvas.type(item) == "text"}
        self.assertIn("#FF3B30", fills)

    def test_invalid_color_ignored(self):
        self.screen._color_vars["normal_color"].set("not-a-color")
        self.screen._on_color_change("normal_color")
        self.assertEqual(self.screen.style["normal_color"], "#FFFFFF")

    def test_pop_settings_saved(self):
        self.screen.pop_switch_var.set(False)
        self.screen.pop_scale_slider.set(125)
        self.screen.pop_decay_slider.set(200)
        self.screen.save_style()
        saved = json.loads(self.config_path.read_text(encoding="utf-8"))
        cs = saved["caption_style"]
        self.assertFalse(cs["pop_enabled"])
        self.assertEqual(cs["pop_scale"], 125)
        self.assertEqual(cs["pop_decay_ms"], 200)

    def test_presets(self):
        self.screen.apply_preset("Clean")
        self.assertFalse(self.screen.style["pop_enabled"])
        self.assertEqual(self.screen.style["highlight_color"], "#FFFFFF")
        self.screen.apply_preset("Strong")
        self.assertEqual(self.screen.style["pop_scale"], 125)
        self.screen.apply_preset("Capti Default")
        # C2: Leeres Preset – keine Felder vorgesehen, Strong-Werte bleiben
        self.assertEqual(self.screen.style["pop_scale"], 125)
        self.assertTrue(self.screen.style["pop_enabled"])

    def test_preset_merge_preserves_unset_and_custom_fields(self):
        """C2: Nur Preset-Felder ändern sich; Rest inkl. Custom-Keys bleibt."""
        self.screen.style["custom_field"] = "bleibt"
        self.screen.style["font_size"] = 90
        self.screen.apply_preset("Clean")
        # Preset-Felder gesetzt
        self.assertFalse(self.screen.style["pop_enabled"])
        self.assertEqual(self.screen.style["highlight_color"], "#FFFFFF")
        # Nicht angesprochene Felder bleiben
        self.assertEqual(self.screen.style["font_size"], 90)
        self.assertEqual(self.screen.style["custom_field"], "bleibt")
        # Mehrere Presets nacheinander
        self.screen.apply_preset("Strong")
        self.assertEqual(self.screen.style["pop_scale"], 125)
        self.assertEqual(self.screen.style["custom_field"], "bleibt")
        self.assertEqual(self.screen.style["font_size"], 90)

    def test_unknown_preset_changes_nothing(self):
        """C2: Unbekanntes Preset ist No-op (kein Reset auf Defaults)."""
        before = dict(self.screen.style)
        self.screen.apply_preset("GibtEsNicht")
        self.assertEqual(self.screen.style, before)

    def test_save_preserves_other_config_keys(self):
        self.config_path.write_text(json.dumps({"theme": "yellow", "name": "Diraj"}),
                                    encoding="utf-8")
        self.screen.save_style()
        saved = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["theme"], "yellow")
        self.assertEqual(saved["name"], "Diraj")
        self.assertIn("caption_style", saved)

    def test_broken_config_is_safe(self):
        self.config_path.write_text("{broken", encoding="utf-8")
        self.screen.load_style()
        self.assertEqual(self.screen.style, {**DEFAULT_STYLE})

    def test_reset(self):
        self.screen.apply_preset("Strong")
        self.screen.reset()
        self.assertEqual(self.screen.style, {**DEFAULT_STYLE})
        self.assertEqual(self.screen.success_label.cget("text"), "")

    def test_back_navigation_to_home(self):
        self.controller.show_screen("caption_style")
        self.screen.navigate("home")
        self.assertEqual(self.controller.current_screen, "home")

    def test_all_themes_valid(self):
        """Screen baut mit allen drei Themes ohne Fehler."""
        for theme in ("dark", "light", "yellow"):
            controller = AppController(self.root, theme_name=theme)
            screen = controller.get_screen("caption_style")
            self.assertIsInstance(screen, CaptionStyleScreen)


class TestPreviewRenderModel(unittest.TestCase):
    """Block 18: Preview nutzt RenderCaption als Quelle der Wahrheit."""

    @classmethod
    def setUpClass(cls):
        ctk.set_appearance_mode("dark")
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
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
        with contextlib.suppress(Exception):
            self.screen.destroy()

    def _sentence(self):
        return i18n.t("cs.preview_sentence").split()

    def test_preview_builds_render_caption(self):
        """A: Preview baut RenderCaption mit Wörtern in Reihenfolge."""
        cap = self.screen._preview_caption
        self.assertIsInstance(cap, RenderCaption)
        self.assertEqual([w.word for w in cap.words], self._sentence())

    def test_preview_word_timings_identical(self):
        """C: Wort-Timings = Legacy-Schedule (300 ms + i*510 ms, +450 ms)."""
        cap = self.screen._preview_caption
        for i, w in enumerate(cap.words):
            with self.subTest(i=i):
                self.assertAlmostEqual(w.start, (300 + i * 510) / 1000.0)
                self.assertAlmostEqual(w.end, (300 + i * 510 + 450) / 1000.0)

    def test_preview_timeline_from_pop_windows(self):
        """Timeline-Slots stammen aus pop_windows (keine eigene Berechnung)."""
        cap = self.screen._preview_caption
        expected = [{"start": s, "end": e, "decay_end": d}
                    for (s, e, d) in pop_windows(cap)]
        self.assertEqual(self.screen._preview_timeline, expected)
        first = self.screen._preview_timeline[0]
        self.assertEqual((first["start"], first["end"], first["decay_end"]),
                         (300, 750, 900))

    def test_preview_lines_from_caption(self):
        """D: Pixel-Zeilen folgen cap.lines (statt eigener Chunk-Logik)."""
        cap = self.screen._preview_caption
        expected_groups = [[cap.words[i].word for i in idxs]
                           for idxs in cap.lines][:2]
        got_groups = []
        current_y = None
        for entry in self.screen._preview_words:
            if entry["y"] != current_y:
                current_y = entry["y"]
                got_groups.append([])
            got_groups[-1].append(entry["text"])
        self.assertEqual(got_groups, expected_groups)

    def test_pop_state_uses_model(self):
        """E: _current_pop_state == pop_state_at (keine Zweitberechnung)."""
        cap = self.screen._preview_caption
        for t_ms in (0, 299, 300, 525, 749, 800, 901, 5000):
            with self.subTest(t_ms=t_ms):
                self.assertEqual(self.screen._current_pop_state(t_ms),
                                 pop_state_at(cap, t_ms))
        self.assertEqual(self.screen._current_pop_state(300), (0, 100.0))
        active, scale = self.screen._current_pop_state(525)
        self.assertEqual(active, 0)
        self.assertAlmostEqual(scale, 109.6)

    def test_style_layout_snapshot_used(self):
        """F: Style-/Layout-Snapshot aus Modell, Snapshot-gefroren."""
        cap = self.screen._preview_caption
        self.assertEqual(style_of(cap)["highlight_color"],
                         self.screen.style["highlight_color"])
        self.assertEqual(layout_of(cap),
                         CaptionRenderer.compute_layout(1080, 1920))
        self.screen.style["highlight_color"] = "#123456"
        self.assertNotEqual(style_of(cap)["highlight_color"], "#123456")

    def test_sample_behavior_preserved(self):
        """G: Sample-Satz vollständig und in Reihenfolge auf dem Canvas."""
        self.assertEqual([e["text"] for e in self.screen._preview_words],
                         self._sentence())

    def test_style_change_rebuilds_caption(self):
        """Style-Wechsel erzeugt neuen Snapshot (keine alten Daten)."""
        old = self.screen._preview_caption
        self.screen._color_vars["highlight_color"].set("#FF3B30")
        self.screen._on_color_change("highlight_color")
        new = self.screen._preview_caption
        self.assertIsNot(old, new)
        self.assertEqual(style_of(new)["highlight_color"], "#FF3B30")

    def test_preview_parity_single_caption(self):
        """Parität: unabhängig aufgebaute Caption == Screen-Caption-Daten."""
        words = self._sentence()
        synth = [{"word": w,
                  "start": (300 + i * 510) / 1000.0,
                  "end": (300 + i * 510 + 450) / 1000.0}
                 for i, w in enumerate(words)]
        (expected,) = captions_from_segments(
            [{"start": 0.0, "end": synth[-1]["end"],
              "text": " ".join(words), "words": synth}],
            dict(self.screen.style),
            CaptionRenderer.compute_layout(1080, 1920))
        cap = self.screen._preview_caption
        self.assertEqual([(w.word, w.start, w.end) for w in cap.words],
                         [(w.word, w.start, w.end) for w in expected.words])
        self.assertEqual(cap.lines, expected.lines)
        self.assertEqual(pop_windows(cap), pop_windows(expected))
        self.assertEqual(style_of(cap), style_of(expected))
        self.assertEqual(layout_of(cap), layout_of(expected))
        for t_ms in (0, 300, 525, 800, 5000):
            self.assertEqual(self.screen._current_pop_state(t_ms),
                             pop_state_at(expected, t_ms))


class TestTranscriptPreview(unittest.TestCase):
    """Block 19: echte Transkript-Segmente über das Render-Modell."""

    @classmethod
    def setUpClass(cls):
        ctk.set_appearance_mode("dark")
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
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
        with contextlib.suppress(Exception):
            self.screen.destroy()

    def _tx_segments(self):
        return [
            {"start": 5.0, "end": 7.0, "text": "Hallo Welt",
             "words": [{"word": "Hallo", "start": 5.0, "end": 5.8},
                       {"word": "Welt", "start": 5.9, "end": 7.0}]},
            {"start": 8.0, "end": 9.5, "text": "Pause danach Grüße",
             "words": [{"word": "Pause", "start": 8.0, "end": 8.6},
                       {"word": "danach", "start": 8.7, "end": 9.0},
                       {"word": "Grüße", "start": 9.0, "end": 9.5}]},
        ]

    def test_transcript_builds_captions_absolute(self):
        """A+B: Segmente behalten absolute Zeiten (kein Reset auf 0)."""
        self.screen.set_transcript(self._tx_segments())
        self.assertEqual(self.screen._preview_mode, "transcript")
        caps = self.screen._transcript_captions
        self.assertEqual(len(caps), 2)
        self.assertEqual((caps[0].start, caps[0].end), (5.0, 7.0))
        self.assertEqual((caps[1].start, caps[1].end), (8.0, 9.5))
        self.assertEqual(
            [(w.word, w.start, w.end) for w in caps[0].words],
            [("Hallo", 5.0, 5.8), ("Welt", 5.9, 7.0)])

    def test_real_word_timings_no_synthetic_schedule(self):
        """C+Block-18-Regression: echte Timings, keine 450/60/300."""
        self.screen.set_transcript(self._tx_segments())
        first = self.screen._preview_timeline[0]
        self.assertEqual(
            (first["start"], first["end"], first["decay_end"]),
            (5000, 5800, 5950))
        for slot in self.screen._preview_timeline:
            self.assertNotIn(slot["start"], (300, 810))

    def test_lines_from_caption(self):
        """D: Pixel-Zeilen folgen cap.lines."""
        self.screen.set_transcript(self._tx_segments())
        cap = self.screen._preview_caption
        expected = [[cap.words[i].word for i in idxs]
                    for idxs in cap.lines][:2]
        got, current = [], None
        for entry in self.screen._preview_words:
            if entry["y"] != current:
                current = entry["y"]
                got.append([])
            got[-1].append(entry["text"])
        self.assertEqual(got, expected)

    def test_pop_windows_from_caption(self):
        """E: Pop-State aus Modell (Highlight bei echtem Wort)."""
        self.screen.set_transcript(self._tx_segments())
        cap = self.screen._preview_caption
        self.assertEqual(self.screen._current_pop_state(5100),
                         pop_state_at(cap, 5100))
        active, scale = self.screen._current_pop_state(5100)
        self.assertEqual(active, 0)
        self.assertGreater(scale, 100.0)

    def test_pause_preserved_upcoming_shown(self):
        """F: Pause 7.0-8.0 bleibt Lücke; danach kommende Caption."""
        self.screen.set_transcript(self._tx_segments())
        self.screen._draw_preview_frame(7500)
        cap = self.screen._preview_caption
        self.assertEqual([w.word for w in cap.words],
                         ["Pause", "danach", "Grüße"])
        active, _ = self.screen._current_pop_state(7500)
        self.assertIsNone(active)

    def test_multi_segment_selection(self):
        """Mehrere Segmente: aktiv/bevorstehend/letzte Auswahl."""
        self.screen.set_transcript(self._tx_segments())
        self.screen._draw_preview_frame(8500)
        self.assertEqual(self.screen._preview_caption.start, 8.0)
        self.screen._draw_preview_frame(100)
        self.assertEqual(self.screen._preview_caption.start, 5.0)
        self.screen._draw_preview_frame(60000)
        self.assertEqual(self.screen._preview_caption.start, 8.0)

    def test_empty_words_segment(self):
        """G: Segment ohne Wörter – kein Crash, leere Fläche."""
        self.screen.set_transcript([
            {"start": 1.0, "end": 2.0, "text": "Nur Text", "words": []}])
        cap = self.screen._preview_caption
        self.assertEqual(cap.words, ())
        self.screen._draw_preview_frame(1500)
        texts = [self.screen.preview_canvas.itemcget(i, "text")
                 for i in self.screen.preview_canvas.find_all()
                 if self.screen.preview_canvas.type(i) == "text"]
        self.assertEqual(texts, [])

    def test_missing_word_end_normalized(self):
        """H: fehlendes Ende -> Modell-Normalisierung, valide Slots."""
        self.screen.set_transcript([
            {"start": 2.0, "end": 4.0, "text": "A B",
             "words": [{"word": "A", "start": 2.0},
                       {"word": "B", "start": 3.0, "end": 3.8}]}])
        cap = self.screen._preview_caption
        self.assertGreater(cap.words[0].end, cap.words[0].start)
        for slot in self.screen._preview_timeline:
            self.assertGreater(slot["end"], slot["start"])

    def test_unicode_and_long_words(self):
        """I: Umlaute/CJK/sehr lange Wörter fließen durch."""
        long_word = "Donaudampfschifffahrtsgesellschaftskapitän"
        self.screen.set_transcript([
            {"start": 0.0, "end": 3.0, "text": "Grüße 日本語 " + long_word,
             "words": [{"word": "Grüße", "start": 0.0, "end": 1.0},
                       {"word": "日本語", "start": 1.0, "end": 2.0},
                       {"word": long_word, "start": 2.0, "end": 3.0}]}])
        texts = [e["text"] for e in self.screen._preview_words]
        self.assertIn("Grüße", texts)
        self.assertIn("日本語", texts)
        self.assertIn(long_word, texts)

    def test_consecutive_segments(self):
        """Direkt aufeinanderfolgende Segmente ohne Pause."""
        self.screen.set_transcript([
            {"start": 0.0, "end": 1.0, "text": "Eins",
             "words": [{"word": "Eins", "start": 0.0, "end": 1.0}]},
            {"start": 1.0, "end": 2.0, "text": "Zwei",
             "words": [{"word": "Zwei", "start": 1.0, "end": 2.0}]},
        ])
        self.assertEqual(len(self.screen._transcript_captions), 2)
        self.screen._draw_preview_frame(1500)
        self.assertEqual(self.screen._preview_caption.start, 1.0)

    def test_sample_mode_preserved(self):
        """J: Sample-Modus unverändert; clear_transcript stellt ihn her."""
        before_words = [e["text"] for e in self.screen._preview_words]
        before_timeline = list(self.screen._preview_timeline)
        self.screen.set_transcript(self._tx_segments())
        self.assertEqual(self.screen._preview_mode, "transcript")
        self.screen.clear_transcript()
        self.assertEqual(self.screen._preview_mode, "sample")
        self.assertEqual([e["text"] for e in self.screen._preview_words],
                         before_words)
        self.assertEqual(self.screen._preview_timeline, before_timeline)

    def test_short_segments(self):
        """Kurze Segmente (0.2 s) funktionieren."""
        self.screen.set_transcript([
            {"start": 0.0, "end": 0.2, "text": "Kurz",
             "words": [{"word": "Kurz", "start": 0.0, "end": 0.2}]}])
        cap = self.screen._preview_caption
        self.assertEqual(len(cap.words), 1)
        active, _ = self.screen._current_pop_state(100)
        self.assertEqual(active, 0)


if __name__ == "__main__":
    unittest.main()