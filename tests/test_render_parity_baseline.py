"""Fix-Block 15: Render-Parity-Baseline (CURRENT BASELINE, kein Soll-Zustand).

Sichert die kanonische Python-Renderer-Logik gegen versehentliche
Aenderung, BEVOR Preview/Export auf gemeinsame Daten umgestellt werden:
Layout, Pop-State, Karaoke, ASS-Output (Golden, kompakt, inline),
Byte-Stabilitaet, Wrapping, Farben/Alpha.

Namen mit test_current_* pinnen bewusst den IST-Stand – sie behaupten
KEINE Preview==Export-Paritaet (die existiert aktuell nicht).
"""

import codecs
import contextlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Hermetisch: echte Nutzer-Config niemals lesen/schreiben
import tempfile as _tmp

if "CAPTI_CONFIG_FILE" not in os.environ:
    os.environ["APPDATA"] = _tmp.mkdtemp(prefix="capti_test_appdata_")

import customtkinter as ctk

from capti_core.caption_style import resolve_caption_style
from caption_renderer import CaptionRenderer
from ui.app_controller import AppController

FIXTURE = Path(__file__).parent / "fixtures" / "render_parity.json"


def _fixture():
    with open(FIXTURE, "r", encoding="utf-8") as f:
        return json.load(f)


def _segments():
    return [{
        "start": 0.5, "end": 2.5, "text": "Capti Test",
        "words": [
            {"word": "Capti", "start": 0.5, "end": 1.5, "probability": 1.0},
            {"word": "Test", "start": 1.5, "end": 2.5, "probability": 1.0},
        ],
    }]


GOLDEN_ASS = """[Script Info]
Title: Capti Captions
ScriptType: v4.00+
WrapStyle: 2
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Arial Black,67,&H0000FFFF,&H00FFFFFF,&H00101010,&H80000000,1,0,0,0,100,100,0,0,1,4,1,2,40,40,384,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text

Dialogue: 0,0:00:00.50,0:00:02.50,Caption,,0,0,0,,{\\k100}{\\t(0,1000,\\fscx112\\fscy112)\\t(1000,1150,\\fscx100\\fscy100)}Capti {\\k100}{\\t(1000,2000,\\fscx112\\fscy112)\\t(2000,2150,\\fscx100\\fscy100)}Test
"""


class TestCurrentLayoutBaseline(unittest.TestCase):

    def test_current_layout_baseline_1080x1920(self):
        layout = CaptionRenderer.compute_layout(1080, 1920)
        self.assertEqual(layout, {
            "format": "portrait", "play_res_x": 1080, "play_res_y": 1920,
            "font_size": 67, "max_words_per_line": 4, "margin_v": 384,
            "chars_per_line": 24,
        })

    def test_current_layout_baseline_1920x1080(self):
        layout = CaptionRenderer.compute_layout(1920, 1080)
        self.assertEqual(layout["format"], "landscape")
        self.assertEqual(
            (layout["play_res_x"], layout["play_res_y"],
             layout["font_size"], layout["max_words_per_line"],
             layout["margin_v"], layout["chars_per_line"]),
            (1920, 1080, 57, 5, 236, 51))

    def test_current_layout_matches_fixture(self):
        data = _fixture()
        self.assertEqual(CaptionRenderer.compute_layout(1080, 1920),
                         data["layout_1080x1920"])
        got = CaptionRenderer.compute_layout(1920, 1080)
        for key, value in data["layout_1920x1080"].items():
            self.assertEqual(got[key], value)


class TestCurrentPopStateBaseline(unittest.TestCase):

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
        from capti_core.render_model import captions_from_segments
        self.controller = AppController(self.root)
        self.screen = self.controller.get_screen("caption_style")
        # Block 18: Pop-State kommt aus RenderCaption – Single-Word-Caption
        # mit identischen Slots wie zuvor (300/750/900), gleiche Pin-Werte.
        (cap,) = captions_from_segments(
            [{"start": 0.3, "end": 0.75, "text": "Hi",
              "words": [{"word": "Hi", "start": 0.3, "end": 0.75}]}],
            dict(self.screen.style),
            CaptionRenderer.compute_layout(1080, 1920))
        self.screen._preview_caption = cap
        self.screen._preview_timeline = [
            {"start": 300.0, "end": 750.0, "decay_end": 900.0}]

    def tearDown(self):
        with contextlib.suppress(Exception):
            self.screen.destroy()

    def test_current_pop_state_baseline_timeline(self):
        cases = [(0, None, 100.0), (299, None, 100.0), (300, 0, 100.0),
                 (525, 0, 109.6), (749, 0, 112.0), (750, 0, 112.0),
                 (800, 0, 108.0), (900, None, 100.0), (1000, None, 100.0)]
        for t_ms, active, scale in cases:
            with self.subTest(t_ms=t_ms):
                got_active, got_scale = self.screen._current_pop_state(t_ms)
                self.assertEqual(got_active, active)
                self.assertAlmostEqual(got_scale, scale)

    def test_current_pop_state_matches_fixture(self):
        data = _fixture()["pop"]
        for t_ms, active, scale in data["cases"]:
            with self.subTest(t_ms=t_ms):
                got_active, got_scale = self.screen._current_pop_state(t_ms)
                self.assertEqual(got_active, active)
                self.assertAlmostEqual(got_scale, scale)


class TestCurrentKaraokeBaseline(unittest.TestCase):

    def setUp(self):
        self.renderer = CaptionRenderer()

    def test_current_karaoke_baseline_order_timing_tags(self):
        text = self.renderer._build_karaoke_text(_segments()[0])
        self.assertEqual(
            text,
            r"{\k100}{\t(0,1000,\fscx112\fscy112)\t(1000,1150,\fscx100\fscy100)}Capti"
            r" {\k100}{\t(1000,2000,\fscx112\fscy112)\t(2000,2150,\fscx100\fscy100)}Test")

    def test_current_karaoke_matches_fixture(self):
        data = _fixture()["karaoke"]
        seg = {"start": 0.5, "end": 2.5, "text": " ".join(data["words"]),
               "words": [{"word": w, "start": 0.5 + i, "end": 1.5 + i,
                          "probability": 1.0}
                         for i, w in enumerate(data["words"])]}
        self.assertEqual(CaptionRenderer()._build_karaoke_text(seg),
                         data["expected"])


class TestCurrentAssOutputBaseline(unittest.TestCase):

    def setUp(self):
        self.renderer = CaptionRenderer()
        self.tmp = tempfile.TemporaryDirectory()
        self.ass_path = os.path.join(self.tmp.name, "golden.ass")

    def tearDown(self):
        self.tmp.cleanup()

    def _generate(self, segments=None):
        self.renderer.generate_ass(
            segments if segments is not None else _segments(),
            self.ass_path, video_width=1080, video_height=1920)
        with open(self.ass_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_current_ass_output_baseline_full_text(self):
        content = self._generate()
        self.assertEqual(content, GOLDEN_ASS)

    def test_current_ass_output_baseline_sections(self):
        content = self._generate()
        self.assertIn("PlayResX: 1080", content)
        self.assertIn("PlayResY: 1920", content)
        self.assertIn("Style: Caption,Arial Black,67,", content)
        dialogues = [l for l in content.splitlines() if l.startswith("Dialogue:")]
        self.assertEqual(len(dialogues), 1)
        self.assertTrue(dialogues[0].startswith("Dialogue: 0,0:00:00.50,0:00:02.50,"))
        self.assertIn("{\\k100}", dialogues[0])
        self.assertIn("\\fscx112", dialogues[0])

    def test_current_ass_positioning_baseline(self):
        content = self._generate()
        self.assertIn(",40,40,384,1", content)  # MarginL, MarginR, MarginV
        self.assertIn("Alignment", content)


class TestCurrentByteStability(unittest.TestCase):

    def test_current_byte_stability_identical_runs(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        first = os.path.join(tmp.name, "a.ass")
        second = os.path.join(tmp.name, "b.ass")
        CaptionRenderer().generate_ass(_segments(), first,
                                       video_width=1080, video_height=1920)
        CaptionRenderer().generate_ass(_segments(), second,
                                       video_width=1080, video_height=1920)
        with open(first, "rb") as f:
            a = f.read()
        with open(second, "rb") as f:
            b = f.read()
        self.assertEqual(a, b)

    def test_current_no_bom_utf8_valid(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "a.ass")
        CaptionRenderer().generate_ass(_segments(), path,
                                       video_width=1080, video_height=1920)
        with open(path, "rb") as f:
            raw = f.read()
        self.assertFalse(raw.startswith(codecs.BOM_UTF8))
        raw.decode("utf-8")  # muss ohne Fehler dekodieren


class TestCurrentWrapBaseline(unittest.TestCase):

    def _renderer(self, max_words, chars):
        r = CaptionRenderer()
        r.max_words_per_line = max_words
        r.chars_per_line = chars
        return r

    def test_current_wrap_baseline_short(self):
        r = self._renderer(4, 24)
        out = r._apply_line_breaks(["aa", "bb"], [2, 2])
        self.assertEqual(out, "aa bb")

    def test_current_wrap_baseline_exact_limit(self):
        r = self._renderer(4, 24)
        out = r._apply_line_breaks(["a", "b", "c", "d"], [1, 1, 1, 1])
        self.assertEqual(out, "a b c d")

    def test_current_wrap_baseline_over_limit(self):
        r = self._renderer(4, 24)
        out = r._apply_line_breaks(["a", "b", "c", "d", "e"], [1, 1, 1, 1, 1])
        self.assertEqual(out, "a b c d\\Ne")

    def test_current_wrap_baseline_max_two_lines(self):
        r = self._renderer(4, 24)
        words = [f"w{i}" for i in range(9)]
        out = r._apply_line_breaks(words, [2] * 9)
        self.assertEqual(out.count("\\N"), 1)
        self.assertTrue(out.startswith("w0 w1 w2 w3\\N"))

    def test_current_wrap_baseline_char_budget(self):
        r = self._renderer(8, 10)
        out = r._apply_line_breaks(["aa", "bb", "ccccc"], [2, 2, 5])
        self.assertEqual(out, "aa bb\\Nccccc")

    def test_current_wrap_baseline_umlaut_unicode(self):
        r = self._renderer(8, 100)
        out = r._apply_line_breaks(["Grüße", "äöü", "日本語"], [5, 3, 3])
        self.assertEqual(out, "Grüße äöü 日本語")


class TestCurrentColorAlphaBaseline(unittest.TestCase):

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
        self.controller = AppController(self.root)
        self.screen = self.controller.get_screen("caption_style")

    def tearDown(self):
        with contextlib.suppress(Exception):
            self.screen.destroy()

    def test_current_ass_color_baseline_opaque(self):
        kwargs = resolve_caption_style({"normal_color": "#FF0000"})
        self.assertEqual(kwargs["normal_color"], "&H000000FF")

    def test_current_ass_color_baseline_alpha(self):
        kwargs = resolve_caption_style(
            {"shadow_color": "#000000", "shadow_alpha": 128})
        self.assertEqual(kwargs["shadow_color"], "&H80000000")

    def test_current_preview_converter_drops_alpha(self):
        # Baseline: Preview ignoriert das ASS-Alpha-Byte (bewusst pinnen,
        # keine neue Spec – siehe Block-14-Matrix).
        self.assertEqual(
            self.screen._ass_or_hex_color("&H80000000", "#FFF"), "#000000")
        self.assertEqual(
            self.screen._ass_or_hex_color("#FF3B30", "#FFF"), "#FF3B30")


if __name__ == "__main__":
    unittest.main()
