"""
Regressionstests Phase 21: Caption-Layout für extreme Videoformate.
"""

import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from caption_renderer import (
    CaptionRenderer, MAX_CHARS_PER_LINE, MAX_FONT_RATIO,
    group_caption_segments,
)


class TestLayoutNormalFormats(unittest.TestCase):
    """Normale Formate müssen exakt die bisherigen Werte liefern."""

    def test_portrait_1080x1920(self):
        layout = CaptionRenderer.compute_layout(1080, 1920)
        self.assertEqual(layout["format"], "portrait")
        self.assertEqual(layout["font_size"], 67)      # min(1080,1920)*0.062
        self.assertEqual(layout["max_words_per_line"], 4)
        self.assertEqual(layout["margin_v"], 384)      # 1920*0.20
        self.assertLessEqual(layout["chars_per_line"], MAX_CHARS_PER_LINE)

    def test_portrait_720x1280(self):
        layout = CaptionRenderer.compute_layout(720, 1280)
        self.assertEqual(layout["format"], "portrait")
        self.assertEqual(layout["font_size"], 45)      # 720*0.062 -> 45
        self.assertEqual(layout["margin_v"], 256)

    def test_landscape_1920x1080(self):
        layout = CaptionRenderer.compute_layout(1920, 1080)
        self.assertEqual(layout["format"], "landscape")
        self.assertEqual(layout["font_size"], 57)      # 1080*68/1280
        self.assertEqual(layout["max_words_per_line"], 5)
        self.assertEqual(layout["margin_v"], 236)      # 1080*280/1280

    def test_landscape_1280x720(self):
        layout = CaptionRenderer.compute_layout(1280, 720)
        self.assertEqual(layout["font_size"], 38)


class TestLayoutExtremeFormats(unittest.TestCase):

    def test_tiny_square_200x200_font_capped(self):
        layout = CaptionRenderer.compute_layout(200, 200)
        # Font darf nie größer als 8 % der Videohöhe sein
        self.assertLessEqual(layout["font_size"], int(200 * MAX_FONT_RATIO))
        self.assertGreaterEqual(layout["font_size"], 12)

    def test_ultra_wide_4000x300_chars_capped(self):
        layout = CaptionRenderer.compute_layout(4000, 300)
        self.assertEqual(layout["format"], "landscape")
        self.assertLessEqual(layout["chars_per_line"], MAX_CHARS_PER_LINE)
        self.assertLessEqual(layout["font_size"], int(300 * MAX_FONT_RATIO))

    def test_tiny_portrait_180x320(self):
        layout = CaptionRenderer.compute_layout(180, 320)
        self.assertEqual(layout["format"], "portrait")
        self.assertLessEqual(layout["font_size"], int(320 * MAX_FONT_RATIO))
        self.assertGreaterEqual(layout["font_size"], 12)
        self.assertEqual(layout["max_words_per_line"], 4)

    def test_very_wide_landscape_3440x1440(self):
        layout = CaptionRenderer.compute_layout(3440, 1440)
        self.assertLessEqual(layout["chars_per_line"], MAX_CHARS_PER_LINE)
        # Font bleibt proportional (normales Verhalten)
        self.assertEqual(layout["font_size"], 76)  # 1440*68/1280

    def test_zero_height_does_not_crash(self):
        layout = CaptionRenderer.compute_layout(1000, 0)
        self.assertIsInstance(layout["font_size"], int)
        self.assertGreaterEqual(layout["font_size"], 12)


class TestLayoutInvariants(unittest.TestCase):

    FORMATS = [(200, 200), (4000, 300), (720, 1280), (1080, 1920),
               (1920, 1080), (180, 320), (3440, 1440)]

    def test_max_two_lines_everywhere(self):
        for w, h in self.FORMATS:
            layout = CaptionRenderer.compute_layout(w, h)
            self.assertIn(layout["max_words_per_line"], (4, 5))

    def test_safe_area_ratio_preserved(self):
        for w, h in self.FORMATS:
            layout = CaptionRenderer.compute_layout(w, h)
            if w / h < 1.0:
                self.assertAlmostEqual(layout["margin_v"] / h, 0.20, places=2)
            else:
                self.assertAlmostEqual(layout["margin_v"] / h, 280 / 1280, places=2)

    def test_chars_per_line_positive(self):
        for w, h in self.FORMATS:
            layout = CaptionRenderer.compute_layout(w, h)
            self.assertGreaterEqual(layout["chars_per_line"], 10)


class TestExtremeFormatEndToEnd(unittest.TestCase):
    """Echter Renderer-Durchlauf mit einem extremen Format."""

    def test_ass_generation_ultra_wide_and_tiny(self):
        renderer = CaptionRenderer(pop_enabled=True)
        segments = [{
            "start": 1.0, "end": 3.0, "text": "Hallo Welt dies ist ein Test",
            "words": [
                {"word": "Hallo", "start": 1.0, "end": 1.3},
                {"word": "Welt", "start": 1.4, "end": 1.7},
                {"word": "dies", "start": 1.8, "end": 2.0},
                {"word": "ist", "start": 2.1, "end": 2.3},
                {"word": "ein", "start": 2.4, "end": 2.6},
                {"word": "Test", "start": 2.7, "end": 2.9},
            ],
        }]
        tmp = tempfile.TemporaryDirectory()
        try:
            for w, h in ((4000, 300), (200, 200)):
                path = os.path.join(tmp.name, f"out_{w}x{h}.ass")
                renderer.generate_ass(segments, path, w, h)
                content = open(path, encoding="utf-8-sig").read()
                dialogues = [l for l in content.splitlines() if l.startswith("Dialogue:")]
                self.assertTrue(dialogues)
                for line in dialogues:
                    m = re.match(r"Dialogue: 0,([^,]+),([^,]+),", line)
                    self.assertIsNotNone(m)
                    ks = [int(k) for k in re.findall(r"\\k(\d+)", line)]
                    self.assertTrue(ks)
                    self.assertTrue(all(k > 0 for k in ks))
                self.assertIn(f"PlayResX: {w}", content)
                self.assertIn(f"PlayResY: {h}", content)
        finally:
            tmp.cleanup()

    def test_grouping_with_extreme_layout(self):
        segment = {
            "start": 1.0, "end": 3.0, "text": "a b c d e f g h",
            "words": [{"word": c, "start": 1.0 + i * 0.2, "end": 1.15 + i * 0.2}
                      for i, c in enumerate("abcdefgh")],
        }
        for w, h in ((4000, 300), (200, 200), (1080, 1920)):
            layout = CaptionRenderer.compute_layout(w, h)
            groups = group_caption_segments([segment], layout)
            self.assertTrue(groups)
            for g in groups:
                self.assertGreater(g["end"], g["start"])
                self.assertTrue(g["words"])


if __name__ == "__main__":
    unittest.main()