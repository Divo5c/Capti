"""
Tests für CaptionRenderer (ASS-Generierung mit Word-Highlighting)
und die bestehende SRT-Erzeugung.

Ausführen: uv run python -m unittest discover tests -v
"""

import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from caption_renderer import (
    CaptionRenderer,
    create_caption_renderer,
    escape_ass_text,
    group_caption_segments,
)
from subtitle_engine import SubtitleEngine


def make_segments():
    """Test-Segmente mit Word-Timestamps (wie von subtitle_engine.transcribe)."""
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
        {
            "start": 2.5,
            "end": 3.5,
            "text": "Zweites Segment",
            "words": [
                {"word": "Zweites", "start": 2.5, "end": 3.0, "probability": 0.9},
                {"word": "Segment", "start": 3.1, "end": 3.5, "probability": 0.9},
            ],
        },
    ]


class TestCaptionRenderer(unittest.TestCase):

    def setUp(self):
        self.renderer = create_caption_renderer()
        self.tmp = tempfile.TemporaryDirectory()
        self.ass_path = os.path.join(self.tmp.name, "test.ass")

    def tearDown(self):
        self.tmp.cleanup()

    def read_ass(self):
        with open(self.ass_path, "r", encoding="utf-8-sig") as f:
            return f.read()

    def test_ass_file_created(self):
        """1. ASS-Datei wird korrekt erzeugt."""
        result = self.renderer.generate_ass(make_segments(), self.ass_path)
        self.assertEqual(result, self.ass_path)
        self.assertTrue(os.path.exists(self.ass_path))
        content = self.read_ass()
        self.assertIn("[Script Info]", content)
        self.assertIn("[V4+ Styles]", content)
        self.assertIn("[Events]", content)

    def test_word_timestamps_used(self):
        """2. Word-Timestamps werden korrekt übernommen (Karaoke-Dauern)."""
        text = self.renderer._build_karaoke_text(make_segments()[0])
        # Erwartete Dauern: bis zum Start des nächsten Wortes bzw. Segmentende
        # Hallo: 0.6-0.0=60cs, wie: 0.9-0.6=30cs, geht: 1.3-0.9=40cs, es: 20cs, dir: 2.0-1.5=50cs
        self.assertIn(r"{\k60}", text)
        self.assertIn("Hallo", text)
        self.assertIn(r"{\k30}", text)
        self.assertIn(r"{\k40}", text)
        self.assertIn(r"{\k20}", text)
        self.assertIn(r"{\k50}", text)

    def test_word_order_preserved(self):
        """3. Word-Reihenfolge bleibt erhalten."""
        text = self.renderer._build_karaoke_text(make_segments()[0])
        positions = [text.index(w) for w in ["Hallo", "wie", "geht", "es", "dir"]]
        self.assertEqual(positions, sorted(positions))

    def test_highlight_times_match_words(self):
        """4. Highlight-Zeit entspricht den Word-Timestamps (Dialogue-Zeiten)."""
        content = self.read_ass() if os.path.exists(self.ass_path) else None
        if content is None:
            self.renderer.generate_ass(make_segments(), self.ass_path)
            content = self.read_ass()
        dialogues = [l for l in content.splitlines() if l.startswith("Dialogue:")]
        self.assertEqual(len(dialogues), 2)
        # Erste Dialogue-Zeile: Segment 0.00 -> 2.00
        m = re.match(r"Dialogue: 0,([\d:.]+),([\d:.]+),Caption", dialogues[0])
        self.assertEqual(m.group(1), "0:00:00.00")
        self.assertEqual(m.group(2), "0:00:02.00")

    def test_multiple_words_and_segments(self):
        """5. Mehrere Wörter und Segmente funktionieren."""
        self.renderer.generate_ass(make_segments(), self.ass_path)
        content = self.read_ass()
        dialogues = [l for l in content.splitlines() if l.startswith("Dialogue:")]
        self.assertEqual(len(dialogues), 2)
        self.assertEqual(dialogues[0].count(r"{\k"), 5)
        self.assertEqual(dialogues[1].count(r"{\k"), 2)

    def test_style_colors(self):
        """Normal (weiß) und Highlight (gelb) sind im Style definiert."""
        self.renderer.generate_ass(make_segments(), self.ass_path)
        content = self.read_ass()
        style_line = [l for l in content.splitlines() if l.startswith("Style: Caption")][0]
        self.assertIn("&H00FFFFFF", style_line)   # Normal weiß (SecondaryColour)
        self.assertIn("&H0000FFFF", style_line)   # Highlight gelb (PrimaryColour)

    def test_modern_design(self):
        """Font, Outline, Shadow, Safe-Area-Margin im Style."""
        self.renderer.generate_ass(make_segments(), self.ass_path)
        content = self.read_ass()
        style_line = [l for l in content.splitlines() if l.startswith("Style: Caption")][0]
        self.assertIn("Arial Black", style_line)  # Moderner, fetter Font
        self.assertIn("&H00101010", style_line)   # Dunkle Outline
        self.assertIn("&H80000000", style_line)   # Dezenter Shadow
        fields = style_line.split(",")
        self.assertEqual(int(fields[16]), 4)      # Outline-Stärke
        self.assertEqual(int(fields[21]), 280)    # MarginV (Safe Area)

    def test_pop_transform_tag_generated(self):
        """Pop/Transform-Tag (\\t + \\fscx/\\fscy) wird pro Wort erzeugt."""
        text = self.renderer._build_karaoke_text(make_segments()[0])
        self.assertEqual(text.count(r"\t("), 10)  # 2 Transform-Tags pro Wort (5 Wörter)
        self.assertIn(r"\fscx112\fscy112", text)  # Pop-Skalierung
        self.assertIn(r"\fscx100\fscy100", text)  # Rückkehr auf 100 %

    def test_pop_uses_word_timestamps(self):
        """Animation-Zeiten entsprechen den Word-Timestamps (ms relativ zum Segment)."""
        seg = make_segments()[0]  # Segment startet bei 0.0
        text = self.renderer._build_karaoke_text(seg)
        # "geht": start 0.9s -> t_up=900, end 1.2s -> t_down=1200, back=1350
        self.assertIn(r"\t(900,1200,\fscx112\fscy112)", text)
        self.assertIn(r"\t(1200,1350,\fscx100\fscy100)", text)

    def test_highlighting_preserved_with_pop(self):
        """Karaoke-Highlight bleibt neben dem Pop-Tag erhalten."""
        text = self.renderer._build_karaoke_text(make_segments()[0])
        self.assertIn(r"{\k60}", text)
        self.assertLess(text.index(r"{\k40}"), text.index("geht"))
        self.assertEqual(text.count(r"{\k"), 5)

    def test_two_line_wrap(self):
        """Längere Captions werden auf max. 2 Zeilen aufgeteilt."""
        long_segment = {
            "start": 0.0,
            "end": 5.0,
            "text": "Heute zeige ich euch wie ihr dieses Problem ganz einfach loesen koennt",
            "words": [
                {"word": w, "start": float(i), "end": float(i) + 0.5, "probability": 0.9}
                for i, w in enumerate(
                    ["Heute", "zeige", "ich", "euch", "wie", "ihr",
                     "dieses", "Problem", "ganz", "einfach"]
                )
            ],
        }
        text = self.renderer._build_karaoke_text(long_segment)
        lines = text.split(r"\N")
        self.assertEqual(len(lines), 2)
        # Ausbalanciert: 5 + 5 Wörter
        self.assertEqual(lines[0].count(r"{\k"), 5)
        self.assertEqual(lines[1].count(r"{\k"), 5)
        # Reihenfolge bleibt erhalten
        self.assertLess(text.index("Heute"), text.index("einfach"))

    def test_two_line_wrap_with_pop(self):
        """Zwei-Zeilen-Captions funktionieren weiterhin mit Pop-Effekt."""
        long_segment = {
            "start": 0.0,
            "end": 5.0,
            "text": "Heute zeige ich euch wie ihr dieses Problem ganz einfach loesen koennt",
            "words": [
                {"word": w, "start": float(i), "end": float(i) + 0.5, "probability": 0.9}
                for i, w in enumerate(
                    ["Heute", "zeige", "ich", "euch", "wie", "ihr",
                     "dieses", "Problem", "ganz", "einfach"]
                )
            ],
        }
        text = self.renderer._build_karaoke_text(long_segment)
        lines = text.split(r"\N")
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0].count(r"{\k"), 5)
        self.assertEqual(lines[1].count(r"{\k"), 5)
        self.assertEqual(text.count(r"\t("), 20)  # 2 Tags x 10 Wörter


class TestAdaptiveLayout(unittest.TestCase):
    """Adaptives Layout für verschiedene Videoformate."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ass_path = os.path.join(self.tmp.name, "test.ass")

    def tearDown(self):
        self.tmp.cleanup()

    def read_ass(self):
        with open(self.ass_path, "r", encoding="utf-8-sig") as f:
            return f.read()

    def test_landscape_1920x1080(self):
        layout = CaptionRenderer.compute_layout(1920, 1080)
        self.assertEqual(layout["format"], "landscape")
        self.assertEqual(layout["play_res_x"], 1920)
        self.assertEqual(layout["play_res_y"], 1080)
        self.assertEqual(layout["font_size"], round(1080 * 68 / 1280))  # proportional
        self.assertEqual(layout["max_words_per_line"], 5)

    def test_landscape_1280x720(self):
        layout = CaptionRenderer.compute_layout(1280, 720)
        self.assertEqual(layout["format"], "landscape")
        self.assertEqual(layout["font_size"], round(720 * 68 / 1280))
        self.assertEqual(layout["max_words_per_line"], 5)

    def test_portrait_1080x1920(self):
        layout = CaptionRenderer.compute_layout(1080, 1920)
        self.assertEqual(layout["format"], "portrait")
        self.assertEqual(layout["play_res_x"], 1080)
        self.assertEqual(layout["play_res_y"], 1920)
        self.assertEqual(layout["font_size"], int(round(1080 * 0.062)))
        self.assertEqual(layout["max_words_per_line"], 4)
        self.assertEqual(layout["margin_v"], int(1920 * 0.20))

    def test_portrait_720x1280(self):
        layout = CaptionRenderer.compute_layout(720, 1280)
        self.assertEqual(layout["format"], "portrait")
        self.assertEqual(layout["font_size"], int(round(720 * 0.062)))
        self.assertEqual(layout["max_words_per_line"], 4)

    def test_layouts_differ(self):
        """Portrait und Landscape wählen unterschiedliche Layoutwerte."""
        p = CaptionRenderer.compute_layout(1080, 1920)
        l = CaptionRenderer.compute_layout(1920, 1080)
        self.assertNotEqual(p["font_size"], l["font_size"])
        self.assertNotEqual(p["max_words_per_line"], l["max_words_per_line"])
        self.assertNotEqual(p["format"], l["format"])

    def test_generate_ass_uses_video_resolution(self):
        """PlayRes entspricht der echten Videoauflösung."""
        renderer = create_caption_renderer()
        renderer.generate_ass(make_segments(), self.ass_path, video_width=1080, video_height=1920)
        content = self.read_ass()
        self.assertIn("PlayResX: 1080", content)
        self.assertIn("PlayResY: 1920", content)
        # Karaoke + Pop weiterhin vorhanden
        self.assertIn(r"{\k", content)
        self.assertIn(r"\fscx112\fscy112", content)

    def test_fallback_without_resolution(self):
        """Ohne Auflösung wird das bisherige Standard-Layout verwendet."""
        renderer = create_caption_renderer()
        renderer.generate_ass(make_segments(), self.ass_path)
        content = self.read_ass()
        self.assertIn("PlayResX: 720", content)
        self.assertIn("PlayResY: 1280", content)

    def test_char_based_wrap(self):
        """Lange Wörter führen früher zum Zeilenumbruch (Zeichenbudget)."""
        renderer = create_caption_renderer()
        renderer.generate_ass(make_segments(), self.ass_path, video_width=1080, video_height=1920)
        # chars_per_line wurde gesetzt und ist plausibel begrenzt
        self.assertIsNotNone(renderer.chars_per_line)
        self.assertLessEqual(renderer.chars_per_line, 40)


class TestCaptionGrouping(unittest.TestCase):
    """Intelligente Caption-Gruppierung langer Segmente."""

    def _long_segment(self):
        """Segment mit 12 Wörtern, Pause nach Wort 5 und Wort 9."""
        words = []
        t = 0.0
        plan = [("Das", 0.3), ("ist", 0.3), ("ein", 0.3), ("sehr", 0.4), ("langer", 0.5),
                ("Satz", 0.3), ("der", 0.3), ("gerade", 0.4), ("komplett", 0.5),
                ("gesprochen", 0.4), ("wurde", 0.3), ("ja", 0.2)]
        for i, (w, dur) in enumerate(plan):
            words.append({"word": w, "start": round(t, 2), "end": round(t + dur, 2), "probability": 0.9})
            t += dur
            if i in (4, 8):  # Pause nach "langer" und "komplett"
                t += 0.6
        return {
            "start": words[0]["start"],
            "end": words[-1]["end"],
            "text": " ".join(w["word"] for w in words),
            "words": words,
        }

    def test_pause_break(self):
        """Natürliche Pausen (>0.4s) erzeugen neue Gruppen."""
        seg = self._long_segment()
        groups = group_caption_segments([seg], pause_threshold=0.4)
        # Pausen nach Wort 5 und Wort 9 -> 3 Gruppen
        self.assertEqual(len(groups), 3)
        self.assertEqual([len(g["words"]) for g in groups], [5, 4, 3])

    def test_word_limit(self):
        """Wortlimit beendet Gruppen auch ohne Pausen."""
        seg = self._long_segment()
        groups = group_caption_segments([seg], pause_threshold=999, max_words_per_group=4)
        self.assertEqual(len(groups), 3)
        self.assertTrue(all(len(g["words"]) <= 4 for g in groups))

    def test_char_budget(self):
        """Zeichenbudget beendet Gruppen bei langen Wörtern."""
        seg = {
            "start": 0.0,
            "end": 4.0,
            "text": "Donaudampfschifffahrtsgesellschaftskapitaen Extraordinarius",
            "words": [
                {"word": "Donaudampfschifffahrtsgesellschaftskapitaen", "start": 0.0, "end": 2.0, "probability": 0.9},
                {"word": "Extraordinarius", "start": 2.0, "end": 4.0, "probability": 0.9},
            ],
        }
        groups = group_caption_segments([seg], max_chars_per_group=20)
        self.assertEqual(len(groups), 2)

    def test_timestamps_preserved(self):
        """Gruppen übernehmen exakte Word-Timestamps; Original bleibt unverändert."""
        seg = self._long_segment()
        original_words = [dict(w) for w in seg["words"]]
        groups = group_caption_segments([seg], pause_threshold=0.4)
        all_grouped = [w for g in groups for w in g["words"]]
        self.assertEqual(all_grouped, original_words)
        # Gruppen-Grenzen = erstes/letztes Wort der Gruppe
        self.assertEqual(groups[0]["start"], original_words[0]["start"])
        self.assertEqual(groups[0]["end"], original_words[4]["end"])
        self.assertEqual(groups[-1]["end"], original_words[-1]["end"])
        # Text korrekt zusammengefügt
        self.assertEqual(groups[0]["text"], "Das ist ein sehr langer")

    def test_short_segments_untouched(self):
        """Kurze/leere Segmente bleiben unverändert."""
        short = {"start": 0.0, "end": 1.0, "text": "Hallo", "words": [
            {"word": "Hallo", "start": 0.0, "end": 1.0, "probability": 0.9}]}
        empty = {"start": 2.0, "end": 3.0, "text": "", "words": []}
        groups = group_caption_segments([short, empty])
        self.assertEqual(groups[0], short)
        self.assertEqual(groups[1], empty)

    def test_layout_derived_limits(self):
        """Layout steuert Portrait/Landscape-Limits zentral."""
        portrait = CaptionRenderer.compute_layout(1080, 1920)
        landscape = CaptionRenderer.compute_layout(1920, 1080)
        seg = self._long_segment()
        gp = group_caption_segments([seg], layout=portrait)
        gl = group_caption_segments([seg], layout=landscape)
        # Beide gruppieren (12 Wörter > Limits), ohne Fehler
        self.assertGreater(len(gp), 1)
        self.assertGreater(len(gl), 1)

    def test_karaoke_and_pop_work_on_groups(self):
        """Karaoke + Pop funktionieren exakt auf gruppierten Segmenten."""
        seg = self._long_segment()
        groups = group_caption_segments([seg], pause_threshold=0.4)
        renderer = create_caption_renderer()
        text = renderer._build_karaoke_text(groups[0])
        self.assertEqual(text.count(r"{\k"), 5)
        self.assertIn(r"\fscx112\fscy112", text)
        # Pop-Zeiten relativ zum Gruppenstart (erstes Wort startet bei 0)
        self.assertIn(r"\t(0,", text)


class TestSrtStillWorks(unittest.TestCase):
    """6. Bestehende SRT-Erzeugung funktioniert weiterhin."""

    def setUp(self):
        self.engine = SubtitleEngine.__new__(SubtitleEngine)  # ohne Modell laden
        self.tmp = tempfile.TemporaryDirectory()
        self.srt_path = os.path.join(self.tmp.name, "test.srt")

    def tearDown(self):
        self.tmp.cleanup()

    def test_generate_srt_ignores_extra_fields(self):
        segments = make_segments()  # enthält zusätzliches "words"-Feld
        self.engine.generate_srt(segments, self.srt_path)
        with open(self.srt_path, "r", encoding="utf-8") as f:
            content = f.read()
        nl = chr(10)
        self.assertIn(nl.join(["1", "00:00:00,000 --> 00:00:02,000", "Hallo wie geht es dir"]), content)
        self.assertIn(nl.join(["2", "00:00:02,500 --> 00:00:03,500", "Zweites Segment"]), content)


class TestAssTextEscaping(unittest.TestCase):
    """Block 11: Transkript-Sonderzeichen vs. Renderer-Override-Tags."""

    def setUp(self):
        self.renderer = create_caption_renderer()
        self.tmp = tempfile.TemporaryDirectory()
        self.ass_path = os.path.join(self.tmp.name, "test.ass")

    def tearDown(self):
        self.tmp.cleanup()

    def _karaoke(self, text, words=None):
        seg = {"start": 0.0, "end": 2.0, "text": text,
               "words": words if words is not None else []}
        return self.renderer._build_karaoke_text(seg)

    def test_normal_text_unchanged(self):
        self.assertEqual(escape_ass_text("Hallo Welt"), "Hallo Welt")
        self.assertEqual(self._karaoke("Hallo Welt"), "Hallo Welt")

    def test_brace_escaped_as_literal(self):
        out = self._karaoke("Hallo {Welt}")
        self.assertIn("Hallo \\{Welt\\}", out)
        self.assertNotIn("{Welt}", out.replace("\\{Welt\\}", ""))

    def test_backslash_escaped(self):
        out = self._karaoke("C:\\Pfad\\Datei")
        self.assertIn("C:\\\\Pfad\\\\Datei", out)

    def test_combination_all_three(self):
        out = self._karaoke("A{B}\\C")
        self.assertIn("A\\{B\\}\\\\C", out)

    def test_karaoke_tags_stay_valid(self):
        seg = {"start": 0.0, "end": 2.0, "text": "Hi {x}\\y",
               "words": [{"word": "Hi", "start": 0.0, "end": 1.0, "probability": 1.0},
                         {"word": "{x}\\y", "start": 1.0, "end": 2.0, "probability": 1.0}]}
        text = self.renderer._build_karaoke_text(seg)
        # Renderer-Tags roh und valide ...
        self.assertIn(r"{\k", text)
        self.assertIn(r"\t(", text)
        self.assertIn(r"\fscx", text)
        # ... Usertext escapet und sichtbar
        self.assertIn("\\{x\\}\\\\y", text)

    def test_unicode_umlauts_unchanged(self):
        self.assertEqual(escape_ass_text("Grüße äöü ß €"), "Grüße äöü ß €")
        self.assertIn("Grüße", self._karaoke("Grüße äöü"))

    def test_empty_and_none_safe(self):
        self.assertEqual(escape_ass_text(""), "")
        self.assertEqual(escape_ass_text(None), "")

    def test_no_bom_in_generated_ass(self):
        """Block 11: ASS ohne UTF-8-BOM."""
        import codecs
        self.renderer.generate_ass(make_segments(), self.ass_path)
        with open(self.ass_path, "rb") as f:
            head = f.read(3)
        self.assertNotEqual(head, codecs.BOM_UTF8)
        with open(self.ass_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("[Script Info]", content)
        self.assertIn("Dialogue:", content)


ADAPTER_FIXTURE_DIALOGUES = {
    "A": [
        'Dialogue: 0,0:00:00.50,0:00:02.50,Caption,,0,0,0,,{\\k100}{\\t(0,1000,\\fscx112\\fscy112)\\t(1000,1150,\\fscx100\\fscy100)}Capti {\\k100}{\\t(1000,2000,\\fscx112\\fscy112)\\t(2000,2150,\\fscx100\\fscy100)}Test',
    ],
    "B": [
        'Dialogue: 0,0:00:00.00,0:00:02.00,Caption,,0,0,0,,{\\k60}{\\t(0,500,\\fscx112\\fscy112)\\t(500,650,\\fscx100\\fscy100)}Hallo {\\k30}{\\t(600,800,\\fscx112\\fscy112)\\t(800,950,\\fscx100\\fscy100)}wie {\\k40}{\\t(900,1200,\\fscx112\\fscy112)\\t(1200,1350,\\fscx100\\fscy100)}geht {\\k20}{\\t(1300,1400,\\fscx112\\fscy112)\\t(1400,1550,\\fscx100\\fscy100)}es\\N{\\k50}{\\t(1500,1900,\\fscx112\\fscy112)\\t(1900,2050,\\fscx100\\fscy100)}dir',
    ],
    "C": [
        'Dialogue: 0,0:00:00.32,0:00:01.55,Caption,,0,0,0,,{\\k63}{\\t(0,590,\\fscx112\\fscy112)\\t(590,740,\\fscx100\\fscy100)}Echt {\\k60}{\\t(630,1230,\\fscx112\\fscy112)\\t(1230,1380,\\fscx100\\fscy100)}krumm',
    ],
    "D": [
        'Dialogue: 0,0:00:00.00,0:00:05.00,Caption,,0,0,0,,{\\k100}{\\t(0,300,\\fscx112\\fscy112)\\t(300,450,\\fscx100\\fscy100)}A {\\k200}{\\t(1000,1200,\\fscx112\\fscy112)\\t(1200,1350,\\fscx100\\fscy100)}B {\\k200}{\\t(3000,4000,\\fscx112\\fscy112)\\t(4000,4150,\\fscx100\\fscy100)}C',
    ],
    "E": [
        'Dialogue: 0,0:00:00.50,0:00:02.50,Caption,,0,0,0,,{\\k100}{\\t(0,1000,\\fscx125\\fscy125)\\t(1000,1120,\\fscx100\\fscy100)}Capti {\\k100}{\\t(1000,2000,\\fscx125\\fscy125)\\t(2000,2120,\\fscx100\\fscy100)}Test',
    ],
    "F": [
        'Dialogue: 0,0:00:00.00,0:00:05.00,Caption,,0,0,0,,{\\k50}{\\t(0,400,\\fscx112\\fscy112)\\t(400,550,\\fscx100\\fscy100)}w0 {\\k50}{\\t(500,900,\\fscx112\\fscy112)\\t(900,1050,\\fscx100\\fscy100)}w1 {\\k50}{\\t(1000,1400,\\fscx112\\fscy112)\\t(1400,1550,\\fscx100\\fscy100)}w2 {\\k50}{\\t(1500,1900,\\fscx112\\fscy112)\\t(1900,2050,\\fscx100\\fscy100)}w3\\N{\\k50}{\\t(2000,2400,\\fscx112\\fscy112)\\t(2400,2550,\\fscx100\\fscy100)}w4 {\\k50}{\\t(2500,2900,\\fscx112\\fscy112)\\t(2900,3050,\\fscx100\\fscy100)}w5 {\\k50}{\\t(3000,3400,\\fscx112\\fscy112)\\t(3400,3550,\\fscx100\\fscy100)}w6 {\\k50}{\\t(3500,3900,\\fscx112\\fscy112)\\t(3900,4050,\\fscx100\\fscy100)}w7 {\\k100}{\\t(4000,4400,\\fscx112\\fscy112)\\t(4400,4550,\\fscx100\\fscy100)}w8',
    ],
    "G": [
        'Dialogue: 0,0:00:00.00,0:00:02.00,Caption,,0,0,0,,{\\k60}{\\t(0,600,\\fscx112\\fscy112)\\t(600,750,\\fscx100\\fscy100)}Grüße {\\k60}{\\t(600,1200,\\fscx112\\fscy112)\\t(1200,1350,\\fscx100\\fscy100)}日本語 {\\k80}{\\t(1200,1900,\\fscx112\\fscy112)\\t(1900,2050,\\fscx100\\fscy100)}Welt!',
    ],
    "H": [
        'Dialogue: 0,0:00:00.00,0:00:02.00,Caption,,0,0,0,,{\\k100}{\\t(0,1000,\\fscx112\\fscy112)\\t(1000,1150,\\fscx100\\fscy100)}A\\{B\\}\\\\C {\\k100}{\\t(1000,2000,\\fscx112\\fscy112)\\t(2000,2150,\\fscx100\\fscy100)}x',
    ],
    "I": [
        'Dialogue: 0,0:00:00.00,0:00:01.00,Caption,,0,0,0,,{\\k100}{\\t(0,1000,\\fscx112\\fscy112)\\t(1000,1150,\\fscx100\\fscy100)}Eins',
        'Dialogue: 0,0:00:02.00,0:00:03.00,Caption,,0,0,0,,{\\k40}{\\t(0,400,\\fscx112\\fscy112)\\t(400,550,\\fscx100\\fscy100)}Zwei {\\k60}{\\t(400,1000,\\fscx112\\fscy112)\\t(1000,1150,\\fscx100\\fscy100)}Stücke',
        'Dialogue: 0,0:00:05.00,0:00:05.01,Caption,,0,0,0,,{\\k1}{\\t(0,10,\\fscx112\\fscy112)\\t(10,160,\\fscx100\\fscy100)}Kurz',
    ],
    "J_strong": [
        'Dialogue: 0,0:00:00.50,0:00:02.50,Caption,,0,0,0,,{\\k100}{\\t(0,1000,\\fscx125\\fscy125)\\t(1000,1120,\\fscx100\\fscy100)}Capti {\\k100}{\\t(1000,2000,\\fscx125\\fscy125)\\t(2000,2120,\\fscx100\\fscy100)}Test',
    ],
    "J_clean": [
        'Dialogue: 0,0:00:00.50,0:00:02.50,Caption,,0,0,0,,{\\k100}Capti {\\k100}Test',
    ],
    "K": [
        'Dialogue: 0,0:00:00.50,0:00:02.50,Caption,,0,0,0,,{\\k100}Capti {\\k100}Test',
    ],
    "L": [
        'Dialogue: 0,0:00:03.00,0:00:03.01,Caption,,0,0,0,,{\\k1}{\\t(0,1,\\fscx112\\fscy112)\\t(1,151,\\fscx100\\fscy100)}Null',
        'Dialogue: 0,0:00:04.00,0:00:05.00,Caption,,0,0,0,,{\\k100}{\\t(0,1,\\fscx112\\fscy112)\\t(1,151,\\fscx100\\fscy100)}Solo',
        'Dialogue: 0,0:00:06.00,0:00:07.00,Caption,,0,0,0,,Kein Wortstamm',
    ],
}

ADAPTER_FIXTURE_STYLES = {
    "A": 'Style: Caption,Arial Black,67,&H0000FFFF,&H00FFFFFF,&H00101010,&H80000000,1,0,0,0,100,100,0,0,1,4,1,2,40,40,384,1',
    "J_strong": 'Style: Caption,Arial Black,57,&H0000FFFF,&H00FFFFFF,&H00101010,&H80000000,1,0,0,0,100,100,0,0,1,4,1,2,40,40,236,1',
    "J_clean": 'Style: Caption,Arial Black,57,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,4,1,2,40,40,236,1',
}


class TestAssAdapterByteIdentity(unittest.TestCase):
    """Block 17: NEU-Pfad (RenderCaption -> Adapter) ist byte-identisch zum
    ALT-Pfad. Erwartungswerte wurden mit dem Code VOR dem Refactor erzeugt
    und als Literale eingebettet (Source of Truth)."""

    def _w(self, word, s, e, p=0.9):
        return {"word": word, "start": s, "end": e, "probability": p}

    def _s(self, start, end, text, words):
        return {"start": start, "end": end, "text": text, "words": words}

    def _strong_kwargs(self):
        return {"normal_color": "&H00FFFFFF", "highlight_color": "&H0000FFFF",
                "outline_color": "&H00101010", "shadow_color": "&H80000000",
                "font_name": "Arial Black", "font_size": 68,
                "pop_enabled": True, "pop_scale": 125, "pop_decay_ms": 120}

    def _clean_kwargs(self):
        return {"normal_color": "&H00FFFFFF", "highlight_color": "&H00FFFFFF",
                "outline_color": "&H00000000", "shadow_color": "&H80000000",
                "font_name": "Arial Black", "font_size": 68,
                "pop_enabled": False, "pop_scale": 112, "pop_decay_ms": 150}

    def _fixtures(self):
        W, S = self._w, self._s
        return {
            "A": {"segments": [S(0.5, 2.5, "Capti Test",
                                 [W("Capti", 0.5, 1.5), W("Test", 1.5, 2.5)])],
                  "kwargs": {}, "dims": (1080, 1920)},
            "B": {"segments": [S(0.0, 2.0, "Hallo wie geht es dir",
                                 [W("Hallo", 0.0, 0.5), W("wie", 0.6, 0.8),
                                  W("geht", 0.9, 1.2), W("es", 1.3, 1.4),
                                  W("dir", 1.5, 1.9)])],
                  "kwargs": {}, "dims": (1080, 1920)},
            "C": {"segments": [S(0.32, 1.55, "Echt krumm",
                                 [W("Echt", 0.32, 0.91), W("krumm", 0.95, 1.55)])],
                  "kwargs": {}, "dims": (720, 1280)},
            "D": {"segments": [S(0.0, 5.0, "A B C",
                                 [W("A", 0.0, 0.3), W("B", 1.0, 1.2),
                                  W("C", 3.0, 4.0)])],
                  "kwargs": {}, "dims": (1080, 1920)},
            "E": {"segments": [S(0.5, 2.5, "Capti Test",
                                 [W("Capti", 0.5, 1.5), W("Test", 1.5, 2.5)])],
                  "kwargs": self._strong_kwargs(), "dims": (1080, 1920)},
            "F": {"segments": [S(0.0, 5.0, " ".join(f"w{i}" for i in range(9)),
                                 [W(f"w{i}", float(i) * 0.5, float(i) * 0.5 + 0.4)
                                  for i in range(9)])],
                  "kwargs": {}, "dims": (1080, 1920)},
            "G": {"segments": [S(0.0, 2.0, "Grüße 日本語 Welt",
                                 [W("Grüße", 0.0, 0.6), W("日本語", 0.6, 1.2),
                                  W("Welt!", 1.2, 1.9)])],
                  "kwargs": {}, "dims": (1080, 1920)},
            "H": {"segments": [S(0.0, 2.0, "A{B}\\C",
                                 [W("A{B}\\C", 0.0, 1.0), W("x", 1.0, 2.0)])],
                  "kwargs": {}, "dims": (1080, 1920)},
            "I": {"segments": [
                S(0.0, 1.0, "Eins", [W("Eins", 0.0, 1.0)]),
                S(2.0, 3.0, "Zwei Stücke",
                  [W("Zwei", 2.0, 2.4), W("Stücke", 2.4, 3.0)]),
                S(5.0, 5.01, "Kurz", [W("Kurz", 5.0, 5.01)]),
            ], "kwargs": {}, "dims": (1920, 1080)},
            "J_strong": {"segments": [S(0.5, 2.5, "Capti Test",
                                        [W("Capti", 0.5, 1.5), W("Test", 1.5, 2.5)])],
                         "kwargs": self._strong_kwargs(), "dims": (1920, 1080)},
            "J_clean": {"segments": [S(0.5, 2.5, "Capti Test",
                                       [W("Capti", 0.5, 1.5), W("Test", 1.5, 2.5)])],
                        "kwargs": self._clean_kwargs(), "dims": (1920, 1080)},
            "K": {"segments": [S(0.5, 2.5, "Capti Test",
                                 [W("Capti", 0.5, 1.5), W("Test", 1.5, 2.5)])],
                  "kwargs": self._clean_kwargs(), "dims": (1080, 1920)},
            "L": {"segments": [
                S(3.0, 3.0, "Null", [W("Null", 3.0, 3.0)]),
                {"start": 4.0, "end": 5.0, "text": "Solo",
                 "words": [{"word": "Solo", "start": 4.0}]},
                {"start": 6.0, "end": 7.0, "text": "Kein Wortstamm", "words": []},
            ], "kwargs": {}, "dims": (1080, 1920)},
        }

    def _dialogues_of(self, name):
        fx = self._fixtures()[name]
        renderer = CaptionRenderer(**fx["kwargs"])
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, f"{name}.ass")
        w, h = fx["dims"]
        renderer.generate_ass(fx["segments"], path, video_width=w, video_height=h)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return [l for l in content.splitlines() if l.startswith("Dialogue:")]

    def test_adapter_byte_identity_all_fixtures(self):
        for name, expected in ADAPTER_FIXTURE_DIALOGUES.items():
            with self.subTest(fixture=name):
                self.assertEqual(self._dialogues_of(name), expected)

    def test_adapter_style_lines(self):
        for name, expected in ADAPTER_FIXTURE_STYLES.items():
            with self.subTest(fixture=name):
                fx = self._fixtures()[name]
                renderer = CaptionRenderer(**fx["kwargs"])
                tmp = tempfile.TemporaryDirectory()
                self.addCleanup(tmp.cleanup)
                path = os.path.join(tmp.name, "s.ass")
                w, h = fx["dims"]
                renderer.generate_ass(fx["segments"], path,
                                      video_width=w, video_height=h)
                with open(path, "r", encoding="utf-8") as f:
                    styles = [l for l in f.read().splitlines()
                              if l.startswith("Style:")]
                self.assertEqual(styles, [expected])

    def test_ass_from_captions_standalone(self):
        from caption_renderer import _captions_for_ass, ass_from_captions
        fx = self._fixtures()["A"]
        renderer = CaptionRenderer(**fx["kwargs"])
        w, h = fx["dims"]
        layout = renderer.compute_layout(w, h)
        style = {k: getattr(renderer, k) for k in (
            "normal_color", "highlight_color", "outline_color",
            "shadow_color", "font_name", "font_size",
            "pop_enabled", "pop_scale", "pop_decay_ms")}
        captions = _captions_for_ass(fx["segments"], style, dict(layout))
        texts = ass_from_captions(captions)
        self.assertEqual(len(texts), 1)
        full = self._dialogues_of("A")[0]
        self.assertTrue(full.endswith(texts[0]))
        self.assertIn("{\\k100}", texts[0])


if __name__ == "__main__":
    unittest.main()