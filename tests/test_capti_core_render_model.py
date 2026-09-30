"""Fix-Block 16: Common Caption Render Model (nur Einführung, keine Adapter).

Das Modell beschreibt WAS gerendert wird (Text/Wörter/Timing/Style/Layout/
Zeilen) – keine ASS-Tags, kein Tk, kein Flutter, kein ffmpeg.
"""

import os
import sys
import unittest
from types import MappingProxyType

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capti_core.caption_style import CaptionStyle
from capti_core.render_model import (
    RenderCaption,
    RenderWord,
    assign_lines,
    captions_from_segments,
    layout_of,
    pop_windows,
    style_of,
)
from caption_renderer import (
    CaptionRenderer,
)


def _seg(words=((0.5, 1.5, "Capti"), (1.5, 2.5, "Test")), start=0.5, end=2.5):
    return {
        "start": start, "end": end,
        "text": " ".join(w[2] for w in words),
        "words": [{"word": w[2], "start": w[0], "end": w[1]} for w in words],
    }


class TestRenderModelConstruction(unittest.TestCase):

    def test_single_segment_real_timings(self):
        (cap,) = captions_from_segments([_seg()], CaptionStyle())
        self.assertEqual(cap.text, "Capti Test")
        self.assertEqual([(w.word, w.start, w.end) for w in cap.words],
                         [("Capti", 0.5, 1.5), ("Test", 1.5, 2.5)])
        self.assertEqual((cap.start, cap.end), (0.5, 2.5))
        self.assertIsInstance(cap.words[0], RenderWord)
        self.assertIsInstance(cap, RenderCaption)

    def test_multiple_words_unicode(self):
        seg = _seg(words=((0.0, 0.4, "Grüße"), (0.4, 0.9, "日本語"),
                          (0.9, 1.2, "Welt!")))
        (cap,) = captions_from_segments([seg], CaptionStyle())
        self.assertEqual([w.word for w in cap.words],
                         ["Grüße", "日本語", "Welt!"])

    def test_empty_words_supported(self):
        seg = {"start": 1.0, "end": 2.0, "text": "Nur Text", "words": []}
        (cap,) = captions_from_segments([seg], CaptionStyle())
        self.assertEqual(cap.words, ())
        self.assertEqual(cap.lines, ())
        self.assertEqual(cap.text, "Nur Text")

    def test_broken_segment_skipped(self):
        segs = [{"text": "ohne Zeit"}, _seg()]
        caps = captions_from_segments(segs, CaptionStyle())
        self.assertEqual(len(caps), 1)
        self.assertEqual(caps[0].text, "Capti Test")

    def test_dict_style_normalized(self):
        (cap,) = captions_from_segments(
            [_seg()], {"font_name": "  ", "pop_scale": 999})
        # from_dict-Normalisierung: leer -> Default, out-of-range -> Default
        self.assertEqual(cap.style["font_name"], "Arial Black")
        self.assertEqual(cap.style["pop_scale"], 112)


class TestStyleSnapshotImmutability(unittest.TestCase):

    def test_later_style_changes_do_not_leak(self):
        style = CaptionStyle()
        (cap,) = captions_from_segments([_seg()], style)
        style.font_name = "Geändert"
        style.pop_scale = 150
        self.assertEqual(cap.style["font_name"], "Arial Black")
        self.assertEqual(cap.style["pop_scale"], 112)

    def test_snapshot_is_mapping_proxy(self):
        (cap,) = captions_from_segments([_seg()], CaptionStyle())
        self.assertIsInstance(cap.style, MappingProxyType)
        with self.assertRaises(TypeError):
            cap.style["font_name"] = "X"

    def test_layout_snapshot_matches_compute_layout(self):
        expected = CaptionRenderer.compute_layout(1080, 1920)
        (cap,) = captions_from_segments([_seg()], CaptionStyle(),
                                        video_width=1080, video_height=1920)
        self.assertIsInstance(cap.layout, MappingProxyType)
        self.assertEqual(dict(cap.layout), expected)
        self.assertEqual(cap.layout["font_size"], 67)
        self.assertEqual(cap.layout["margin_v"], 384)

    def test_style_of_layout_of_helpers(self):
        (cap,) = captions_from_segments([_seg()], CaptionStyle())
        self.assertIsInstance(style_of(cap), dict)
        self.assertNotIsInstance(style_of(cap), MappingProxyType)
        self.assertEqual(style_of(cap)["font_name"], "Arial Black")
        self.assertIsInstance(layout_of(cap), dict)


class TestLineAssignment(unittest.TestCase):

    def test_short_single_line(self):
        words = (RenderWord("a", 0.0, 0.2), RenderWord("b", 0.2, 0.4))
        self.assertEqual(assign_lines(list(words), 4, 24), ((0, 1),))

    def test_word_limit_splits(self):
        words = tuple(RenderWord(f"w{i}", float(i), float(i) + 0.4)
                      for i in range(5))
        self.assertEqual(assign_lines(list(words), 4, 1000),
                         ((0, 1, 2, 3), (4,)))

    def test_char_budget_splits_like_export(self):
        # Gleiche Entscheidung wie _apply_line_breaks (aa bb | ccccc)
        words = (RenderWord("aa", 0.0, 0.2), RenderWord("bb", 0.2, 0.4),
                 RenderWord("ccccc", 0.4, 0.9))
        self.assertEqual(assign_lines(list(words), 8, 10),
                         ((0, 1), (2,)))

    def test_max_two_lines(self):
        words = tuple(RenderWord(f"w{i}", float(i), float(i) + 0.4)
                      for i in range(9))
        lines = assign_lines(list(words), 4, 1000)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], (0, 1, 2, 3))

    def test_model_lines_agree_with_export_rule(self):
        # Echte Parität: Modell-Lines == Export-Cut bei gleichen Limits.
        from caption_renderer import CaptionRenderer as CR
        words = ["eins", "zwei", "drei", "vier", "fünf"]
        seg = {"start": 0.0, "end": 3.0, "text": " ".join(words),
               "words": [{"word": w, "start": float(i), "end": float(i) + 0.9}
                         for i, w in enumerate(words)]}
        (cap,) = captions_from_segments([seg], CaptionStyle(),
                                        video_width=1080, video_height=1920)
        r = CR()
        r.max_words_per_line = cap.layout["max_words_per_line"]
        r.chars_per_line = cap.layout["chars_per_line"]
        text = r._apply_line_breaks(
            list(words), [len(w) for w in words])
        export_lines = tuple(
            tuple(words.index(w) for w in line.split(" "))
            for line in text.split("\\N"))
        self.assertEqual(cap.lines, export_lines)
        self.assertLessEqual(len(cap.lines), 2)


class TestPopWindows(unittest.TestCase):

    def test_pop_windows_match_export_math(self):
        (cap,) = captions_from_segments([_seg()], {"pop_decay_ms": 150})
        # Identisch zu den \t-Zeiten im ASS-Golden (ohne Tags)
        self.assertEqual(pop_windows(cap), ((0, 1000, 1150), (1000, 2000, 2150)))

    def test_pop_disabled_empty(self):
        (cap,) = captions_from_segments([_seg()], {"pop_enabled": False})
        self.assertEqual(pop_windows(cap), ())

    def test_pop_decay_from_style(self):
        (cap,) = captions_from_segments([_seg()], {"pop_decay_ms": 120})
        self.assertEqual(pop_windows(cap)[0][2] - pop_windows(cap)[0][1], 120)


class TestNoBackendLeakage(unittest.TestCase):

    def test_no_ass_tags_tk_flutter_ffmpeg_in_data(self):
        (cap,) = captions_from_segments([_seg()], CaptionStyle())
        blobs = [cap.text] + [w.word for w in cap.words]
        blobs += [str(v) for v in list(cap.style.values()) + list(cap.layout.values())]
        for b in blobs:
            self.assertNotIn("{\\k", b)
            self.assertNotIn("\\t(", b)
        for w in cap.words:
            self.assertIsInstance(w, RenderWord)

    def test_import_loads_no_gui_or_media_libs(self):
        import subprocess
        code = ("import sys, capti_core.render_model; "
                "bad = sorted(m for m in sys.modules "
                "if m.split('.')[0] in {'tkinter', 'customtkinter', 'ffmpeg', "
                "'libass', 'whisper', 'faster_whisper', 'PyQt5', 'PySide6'}); "
                "print('BAD:' + ','.join(bad) if bad else 'CLEAN')")
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=60, check=False,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.assertEqual(proc.returncode, 0, proc.stderr[-500:])
        self.assertIn("CLEAN", proc.stdout)


if __name__ == "__main__":
    unittest.main()
