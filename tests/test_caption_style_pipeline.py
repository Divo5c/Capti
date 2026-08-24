"""
Tests: Caption-Style -> Pipeline -> Renderer (Phase 14).

Prüft Validierung, Backwards-Compatibility, Pop Enable/Disable und
die Weiterreichung Processing -> Pipeline.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from caption_renderer import CaptionRenderer
from pipeline import (
    CaptiPipeline, resolve_caption_style, CAPTION_STYLE_DEFAULTS,
)


def _sample_segments():
    return [{
        "start": 0.0, "end": 2.0, "text": "Hallo Welt",
        "words": [
            {"word": "Hallo", "start": 0.0, "end": 1.0},
            {"word": "Welt", "start": 1.0, "end": 2.0},
        ],
    }]


class TestResolveCaptionStyle(unittest.TestCase):

    def test_none_returns_defaults(self):
        """Ohne Style exakt die bisherigen Renderer-Defaults."""
        self.assertEqual(resolve_caption_style(None), CAPTION_STYLE_DEFAULTS)
        self.assertEqual(resolve_caption_style({}), CAPTION_STYLE_DEFAULTS)

    def test_valid_colors_converted(self):
        style = resolve_caption_style({
            "normal_color": "#FF0000", "highlight_color": "#00FF00",
            "outline_color": "#0000FF", "shadow_color": "#101010",
            "shadow_alpha": 200,
        })
        self.assertEqual(style["normal_color"], "&H000000FF")   # BGR
        self.assertEqual(style["highlight_color"], "&H0000FF00")
        self.assertEqual(style["outline_color"], "&H00FF0000")
        self.assertTrue(style["shadow_color"].startswith("&HC8"))  # Alpha C8

    def test_invalid_values_fall_back(self):
        style = resolve_caption_style({
            "normal_color": "invalid", "pop_scale": "abc",
            "pop_decay_ms": -500, "font_size": 9999,
            "shadow_alpha": "not-a-number",
        })
        self.assertEqual(style["normal_color"], CAPTION_STYLE_DEFAULTS["normal_color"])
        self.assertEqual(style["pop_scale"], 112)
        self.assertEqual(style["pop_decay_ms"], 150)
        self.assertEqual(style["font_size"], 68)
        self.assertEqual(style["shadow_color"], "&H80000000")

    def test_pop_disabled(self):
        style = resolve_caption_style({"pop_enabled": False})
        self.assertFalse(style["pop_enabled"])


class TestRendererPop(unittest.TestCase):

    def _ass_text(self, renderer):
        import tempfile
        path = tempfile.mktemp(suffix=".ass")
        renderer.generate_ass(_sample_segments(), path)
        with open(path, encoding="utf-8-sig") as f:
            return f.read()

    def test_pop_enabled_keeps_transforms(self):
        text = self._ass_text(CaptionRenderer())
        self.assertIn("\\fscx112\\fscy112", text)

    def test_pop_disabled_no_transforms(self):
        text = self._ass_text(CaptionRenderer(pop_enabled=False))
        self.assertNotIn("\\t(", text)
        # Karaoke bleibt erhalten
        self.assertIn("\\k", text)

    def test_custom_colors_in_style_line(self):
        r = CaptionRenderer(normal_color="&H00123456",
                            highlight_color="&H00654321")
        text = self._ass_text(r)
        self.assertIn("&H00123456", text)   # SecondaryColour (normal)
        self.assertIn("&H00654321", text)   # PrimaryColour (highlight)


class TestPipelineStylePassing(unittest.TestCase):

    def test_run_without_style_uses_default_renderer(self):
        p = CaptiPipeline(temp_dir="_tmp_test")
        p._run = lambda *a, **k: "out.mp4"
        p.run("video.mp4")
        # _run gemockt -> Renderer nicht erstellt; Verhalten unverändert
        self.assertIsNone(p.caption_renderer)

    def test_resolve_used_by_renderer_kwargs_shape(self):
        kwargs = resolve_caption_style({"highlight_color": "#FF3B30",
                                        "pop_scale": 125})
        r = CaptionRenderer(**kwargs)
        self.assertEqual(r.highlight_color, "&H00303BFF")
        self.assertEqual(r.pop_scale, 125)


if __name__ == "__main__":
    unittest.main()