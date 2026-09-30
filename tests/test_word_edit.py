"""Fix-Block 25: Word-Edit – Split / Merge / Timing (Core Tk-frei + UI).

CORE 1-18, TEXT 19-23, PREVIEW 24-27, PERSIST 28-31, EXPORT 32-37.
REGRESSION 38-40 via Full-Suite.
"""

import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capti_core.caption_draft import (
    apply_text,
    delete_word,
    draft_from_caption,
    insert_word,
    merge_words,
    set_caption_timing,
    set_word_timing,
    split_word,
    split_word_at,
    to_caption,
    to_segment,
)
from capti_core.render_model import captions_from_segments


def _segments():
    return [
        {"start": 5.0, "end": 7.0, "text": "Hello world",
         "words": [{"word": "Hello", "start": 5.0, "end": 5.8},
                   {"word": "world", "start": 5.9, "end": 7.0}]},
        {"start": 8.0, "end": 10.0, "text": "HalloWelt grüßt",
         "words": [{"word": "HalloWelt", "start": 8.0, "end": 9.0},
                   {"word": "grüßt", "start": 9.1, "end": 10.0}]},
    ]


def _draft(idx=0):
    (cap,) = captions_from_segments([_segments()[idx]], None, None)
    return draft_from_caption(cap)


class TestWordTimingCore(unittest.TestCase):
    """K1-6) Auswahl + Timing-Edit + Ablehnungen."""

    def test_select_word_data(self):
        """1) Word-Auswahl basiert auf Plain Data (Text/Start/Ende/Dauer)."""
        draft = _draft()
        w = draft.words[1]
        self.assertEqual(w["word"], "world")
        self.assertEqual((w["start"], w["end"]), (5.9, 7.0))
        self.assertAlmostEqual(w["end"] - w["start"], 1.1)

    def test_set_word_timing(self):
        """2) Gültiges Timing wird übernommen, Rest unberührt."""
        draft = _draft()
        self.assertTrue(set_word_timing(draft, 0, 5.1, 5.7))
        self.assertEqual((draft.words[0]["start"], draft.words[0]["end"]),
                         (5.1, 5.7))
        self.assertEqual((draft.words[1]["start"], draft.words[1]["end"]),
                         (5.9, 7.0))
        self.assertEqual((draft.start, draft.end), (5.0, 7.0))

    def test_timing_normalization(self):
        """3) to_caption übernimmt exakte Zeiten (kein Reset)."""
        draft = _draft()
        set_word_timing(draft, 1, 6.0, 6.9)
        cap = to_caption(draft)
        self.assertEqual([(w.word, w.start, w.end) for w in cap.words],
                         [("Hello", 5.0, 5.8), ("world", 6.0, 6.9)])

    def test_negative_rejected(self):
        """4) Negative Zeiten werden abgelehnt (Draft unberührt)."""
        draft = _draft()
        before = copy.deepcopy(draft.words)
        self.assertFalse(set_word_timing(draft, 0, -1.0, 5.7))
        self.assertEqual(draft.words, before)

    def test_end_le_start_rejected(self):
        """5) end <= start wird abgelehnt."""
        draft = _draft()
        before = copy.deepcopy(draft.words)
        self.assertFalse(set_word_timing(draft, 0, 5.7, 5.7))
        self.assertFalse(set_word_timing(draft, 0, 5.8, 5.7))
        self.assertEqual(draft.words, before)

    def test_outside_caption_rejected(self):
        """6) Außerhalb der Caption-Spanne wird abgelehnt."""
        draft = _draft()
        before = copy.deepcopy(draft.words)
        self.assertFalse(set_word_timing(draft, 0, 4.9, 5.7))
        self.assertFalse(set_word_timing(draft, 1, 5.9, 7.1))
        self.assertEqual(draft.words, before)

    def test_garbage_input_rejected(self):
        draft = _draft()
        before = copy.deepcopy(draft.words)
        for bad in ("abc", "", None, float("nan")):
            self.assertFalse(set_word_timing(draft, 0, bad, 5.7))
        self.assertFalse(set_word_timing(draft, 99, 5.0, 5.5))
        self.assertFalse(set_word_timing(draft, 0, 5.0, "x"))
        self.assertEqual(draft.words, before)

    def test_neighbor_overlap_rejected(self):
        """Block 29: Überschneidung mit Nachbarn wird abgelehnt."""
        draft = _draft()
        before = copy.deepcopy(draft.words)
        # Wort 0 überlappt Wort 1 (Start 5.9):
        self.assertFalse(set_word_timing(draft, 0, 5.0, 6.0))
        # Wort 1 überlappt Wort 0 (Ende 5.8):
        self.assertFalse(set_word_timing(draft, 1, 5.7, 7.0))
        self.assertEqual(draft.words, before)

    def test_touching_neighbors_allowed(self):
        """Berühren (Ende == Nachbar-Start) bleibt gültig."""
        draft = _draft()
        self.assertTrue(set_word_timing(draft, 0, 5.0, 5.9))
        self.assertTrue(set_word_timing(draft, 1, 5.9, 7.0))
        cap = to_caption(draft)
        self.assertEqual((cap.words[0].end, cap.words[1].start),
                         (5.9, 5.9))

    def test_absolute_caption_bounds(self):
        """Absolute Zeiten fernab 0 bleiben absolut (Caption ab 5.0)."""
        draft = _draft()
        self.assertTrue(set_word_timing(draft, 1, 6.2, 6.8))
        cap = to_caption(draft)
        self.assertEqual((cap.start, cap.words[1].start, cap.words[1].end),
                         (5.0, 6.2, 6.8))

    def test_drag_to_caption_edges(self):
        """Block 30: Drag auf exakte Caption-Grenzen ist gültig."""
        draft = _draft()
        self.assertTrue(set_word_timing(draft, 0, 5.0, 5.8))
        self.assertTrue(set_word_timing(draft, 1, 5.9, 7.0))
        cap = to_caption(draft)
        self.assertEqual((cap.words[0].start, cap.words[1].end),
                         (5.0, 7.0))

    def test_drag_into_neighbor_rejected(self):
        """Block 30: Drag 1 ms in den Nachbarn wird abgelehnt."""
        draft = _draft()
        before = copy.deepcopy(draft.words)
        self.assertFalse(set_word_timing(draft, 0, 5.0, 5.9005))
        self.assertFalse(set_word_timing(draft, 1, 5.799, 7.0))
        self.assertEqual(draft.words, before)

    def test_nan_rejected(self):
        import math
        draft = _draft()
        before = copy.deepcopy(draft.words)
        # nan verletzt "keine negativen Dauern"/Bounds nicht direkt –
        # Vergleich schlägt fehl -> Ablehnung über Guards.
        ok = set_word_timing(draft, 0, math.nan, 5.7)
        self.assertFalse(ok)
        self.assertEqual(draft.words, before)


class TestSplitCore(unittest.TestCase):
    """K7-10) Split."""

    def test_split_explicit_proportional(self):
        """7/8) Explizite Teile, proportional zur Zeichenanzahl."""
        draft = _draft(1)
        self.assertTrue(split_word(draft, 0, ["Hallo", "Welt"]))
        words = draft.words
        self.assertEqual([w["word"] for w in words],
                         ["Hallo", "Welt", "grüßt"])
        # Proportional 5/9-Zeichen auf Spanne 8.0-9.0:
        self.assertAlmostEqual(words[0]["start"], 8.0)             # 8
        self.assertAlmostEqual(words[0]["end"], 8.0 + 5.0 / 9.0)
        self.assertAlmostEqual(words[1]["start"], 8.0 + 5.0 / 9.0)
        self.assertAlmostEqual(words[1]["end"], 9.0)  # exakt E

    def test_split_preserves_total_span(self):
        """9) Gesamtspanne S..E bleibt erhalten."""
        draft = _draft(1)
        split_word(draft, 0, ["Hallo", "Welt"])
        self.assertAlmostEqual(draft.words[0]["start"], 8.0)
        self.assertAlmostEqual(draft.words[1]["end"], 9.0)
        for w in draft.words[:2]:
            self.assertGreater(w["end"], w["start"])

    def test_split_auto_whitespace(self):
        draft = _draft()
        self.assertTrue(split_word(draft, 0, ["Hel", "lo"]))
        self.assertEqual(draft.words[0]["word"], "Hel")
        self.assertEqual(draft.text, "Hel lo world")

    def test_split_auto_halves(self):
        draft = _draft(1)
        self.assertTrue(split_word(draft, 0))
        self.assertEqual([w["word"] for w in draft.words[:2]],
                         ["Hall", "oWelt"])

    def test_split_minimum_duration(self):
        """10) Winzige Spanne: gültig oder kontrolliert abgelehnt."""
        (cap,) = captions_from_segments(
            [{"start": 1.0, "end": 1.0 + 1e-9, "text": "ab",
              "words": [{"word": "ab", "start": 1.0,
                         "end": 1.0 + 1e-9}]}],
            None, None)
        draft = draft_from_caption(cap)
        ok = split_word(draft, 0, ["a", "b"])
        if ok:
            for w in draft.words:
                self.assertGreater(w["end"], w["start"])
        else:
            self.assertEqual(len(draft.words), 1)  # unberührt

    def test_split_rejections(self):
        draft = _draft()
        self.assertFalse(split_word(draft, 0, []))
        self.assertFalse(split_word(draft, 0, ["", "x"]))
        self.assertFalse(split_word(draft, 0, ["falsch", "Teile"]))
        self.assertFalse(split_word(draft, 5))
        # Ein-Teil-Split ist ein gültiger No-Op (Spanne bleibt exakt).
        self.assertTrue(split_word(draft, 0, ["Hello"]))
        self.assertEqual([(w["word"], w["start"], w["end"])
                          for w in draft.words],
                         [("Hello", 5.0, 5.8), ("world", 5.9, 7.0)])

    def test_split_single_char_rejected(self):
        (cap,) = captions_from_segments(
            [{"start": 1.0, "end": 2.0, "text": "a b",
              "words": [{"word": "a", "start": 1.0, "end": 1.5},
                        {"word": "b", "start": 1.5, "end": 2.0}]}],
            None, None)
        draft = draft_from_caption(cap)
        self.assertFalse(split_word(draft, 0))

    def test_split_umlaut(self):
        draft = _draft(1)
        self.assertTrue(split_word(draft, 1, ["grü", "ßt"]))
        self.assertEqual(draft.words[1]["word"], "grü")
        cap = to_caption(draft)
        self.assertIn("grü", cap.text)


class TestMergeCore(unittest.TestCase):
    """K11-16) Merge."""

    def test_merge_adjacent(self):
        """11-14) Nachbarn -> ein Wort (Text/Start/Ende)."""
        draft = _draft()
        self.assertTrue(merge_words(draft, 0))
        self.assertEqual(len(draft.words), 1)
        merged = draft.words[0]
        self.assertEqual(merged["word"], "Hello world")  # 14
        self.assertEqual(merged["start"], 5.0)           # 12
        self.assertEqual(merged["end"], 7.0)             # 13
        self.assertEqual(draft.text, "Hello world")

    def test_merge_keeps_gap(self):
        """Lücke geht nicht verloren (start1..end2)."""
        draft = _draft(1)
        self.assertTrue(merge_words(draft, 0))
        merged = draft.words[0]
        self.assertEqual((merged["start"], merged["end"]), (8.0, 10.0))

    def test_merge_boundary_rejected(self):
        """15) Kein Merge am Ende / bei 1 Wort / über Captions."""
        draft = _draft()
        self.assertFalse(merge_words(draft, 1))
        self.assertFalse(merge_words(draft, 5))
        (cap,) = captions_from_segments(
            [{"start": 1.0, "end": 2.0, "text": "solo",
              "words": [{"word": "solo", "start": 1.0, "end": 2.0}]}],
            None, None)
        solo = draft_from_caption(cap)
        self.assertFalse(merge_words(solo, 0))
        self.assertEqual(len(solo.words), 1)

    def test_split_merge_roundtrip(self):
        """16) Split -> Merge stellt Spanne wieder her."""
        draft = _draft(1)
        split_word(draft, 0, ["Hallo", "Welt"])
        self.assertTrue(merge_words(draft, 0))
        merged = draft.words[0]
        self.assertEqual((merged["start"], merged["end"]), (8.0, 9.0))

    def test_long_chain(self):
        """8 Wörter: Kette mergen -> ein Wort, Spanne bleibt."""
        words = [{"word": f"w{i}", "start": float(i),
                  "end": float(i) + 0.9} for i in range(8)]
        (cap,) = captions_from_segments(
            [{"start": 0.0, "end": 8.0, "text": " ".join(w["word"] for w in words),
              "words": words}], None, None)
        draft = draft_from_caption(cap)
        for _ in range(7):
            self.assertTrue(merge_words(draft, 0))
        self.assertEqual(len(draft.words), 1)
        self.assertEqual((draft.words[0]["start"], draft.words[0]["end"]),
                         (0.0, 7.9))


class TestDraftInteraction(unittest.TestCase):
    """K17-23) Zusammenspiel mit Text-Edit + Konvertierung."""

    def test_edit_to_caption_segment(self):
        """17/18) Timing-Edit -> Caption + Segment konsistent."""
        draft = _draft()
        set_word_timing(draft, 0, 5.2, 5.6)
        cap = to_caption(draft)
        seg = to_segment(draft)
        self.assertEqual(cap.words[0].start, 5.2)
        self.assertEqual(seg["words"][0]["start"], 5.2)
        self.assertEqual(seg["text"], cap.text)

    def test_text_edit_still_works(self):
        """19) Bestehender Text-Edit unverändert."""
        draft = _draft()
        apply_text(draft, "Hello beautiful world")
        self.assertEqual(draft.words[1]["word"], "beautiful")

    def test_text_edit_after_split(self):
        """20) Text-Edit nach Split funktioniert."""
        draft = _draft(1)
        split_word(draft, 0, ["Hallo", "Welt"])
        apply_text(draft, "Hallo Welt und grüßt")
        self.assertIn("grüßt", [w["word"] for w in draft.words])
        cap = to_caption(draft)
        self.assertEqual(cap.text, "Hallo Welt und grüßt")

    def test_split_after_text_edit(self):
        """21) Split nach Text-Edit funktioniert."""
        draft = _draft()
        apply_text(draft, "Hello beautiful world")
        self.assertTrue(split_word(draft, 1, ["beau", "tiful"]))
        self.assertEqual(draft.words[1]["word"], "beau")

    def test_merge_after_text_edit(self):
        """22) Merge nach Text-Edit funktioniert."""
        draft = _draft()
        apply_text(draft, "Hello beautiful world")
        self.assertTrue(merge_words(draft, 1))
        self.assertEqual(draft.words[1]["word"], "beautiful world")

    def test_timing_edit_after_text_edit(self):
        """23) Timing-Edit nach Text-Edit funktioniert."""
        draft = _draft()
        apply_text(draft, "Hello beautiful world")
        word = next(w for w in draft.words if w["word"] == "beautiful")
        idx = draft.words.index(word)
        self.assertTrue(set_word_timing(draft, idx, word["start"],
                                        word["end"]))
        cap = to_caption(draft)
        self.assertIn("beautiful", cap.text)

    def test_empty_caption_ops_rejected(self):
        """Caption ohne words: alle Ops abgelehnt."""
        (cap,) = captions_from_segments(
            [{"start": 1.0, "end": 2.0, "text": "", "words": []}],
            None, None)
        draft = draft_from_caption(cap)
        self.assertFalse(set_word_timing(draft, 0, 1.0, 2.0))
        self.assertFalse(split_word(draft, 0))
        self.assertFalse(merge_words(draft, 0))

    def test_missing_end_recovered(self):
        """Wort mit fehlendem Ende: Ops nutzen Fallback, kein Crash."""
        draft = _draft()
        del draft.words[0]["end"]
        self.assertTrue(set_word_timing(draft, 0, 5.0, 5.5))
        del draft.words[1]["end"]
        self.assertTrue(merge_words(draft, 0))
        self.assertEqual(draft.words[0]["end"], 7.0)


class TestCaptionTimingCore(unittest.TestCase):
    """Block 36: Caption-Grenzen (Tk-frei)."""

    def test_start_end_within_bounds(self):
        """1/2) Start/End innerhalb erlaubter Grenzen."""
        (cap,) = captions_from_segments(
            [{"start": 4.5, "end": 7.5, "text": "Hello world",
              "words": [{"word": "Hello", "start": 5.0, "end": 5.8},
                        {"word": "world", "start": 5.9, "end": 7.0}]}],
            None, None)
        draft = draft_from_caption(cap)
        self.assertTrue(set_caption_timing(draft, 4.55, 7.5))
        self.assertEqual((draft.start, draft.end), (4.55, 7.5))
        self.assertTrue(set_caption_timing(draft, 4.55, 7.45))
        self.assertEqual((draft.start, draft.end), (4.55, 7.45))

    def test_start_not_negative(self):
        """3) Start darf nicht < 0."""
        draft = _draft()
        before = (draft.start, draft.end)
        self.assertFalse(set_caption_timing(draft, -0.05, 7.0))
        self.assertEqual((draft.start, draft.end), before)

    def test_start_not_beyond_end(self):
        """4) Start darf nicht >= End."""
        draft = _draft()
        before = (draft.start, draft.end)
        self.assertFalse(set_caption_timing(draft, 7.0, 7.0))
        self.assertFalse(set_caption_timing(draft, 7.5, 7.0))
        self.assertEqual((draft.start, draft.end), before)

    def test_end_not_before_start(self):
        """5) End darf nicht <= Start."""
        draft = _draft()
        before = (draft.start, draft.end)
        self.assertFalse(set_caption_timing(draft, 5.0, 5.0))
        self.assertFalse(set_caption_timing(draft, 5.0, 4.9))
        self.assertEqual((draft.start, draft.end), before)

    def test_start_not_past_first_word(self):
        """6) Start darf nicht über erstes Wort springen."""
        draft = _draft()
        before = (draft.start, draft.end)
        self.assertFalse(set_caption_timing(draft, 5.9, 7.0))
        self.assertEqual((draft.start, draft.end), before)

    def test_end_not_before_last_word(self):
        """7) End darf nicht unter letztes Wort springen."""
        draft = _draft()
        before = (draft.start, draft.end)
        self.assertFalse(set_caption_timing(draft, 5.0, 6.5))
        self.assertEqual((draft.start, draft.end), before)

    def test_words_unchanged(self):
        """8) Word-Timings bleiben unverändert."""
        draft = _draft()
        before = [(w["word"], w["start"], w["end"]) for w in draft.words]
        self.assertTrue(set_caption_timing(draft, 4.5, 7.5))
        self.assertEqual(
            [(w["word"], w["start"], w["end"]) for w in draft.words],
            before)
        self.assertEqual(draft.text, "Hello world")

    def test_touching_bounds_allowed(self):
        """9) Berührung an Grenzen ist erlaubt."""
        draft = _draft()
        self.assertTrue(set_caption_timing(draft, 5.0, 7.0))
        self.assertTrue(set_caption_timing(draft, 5.0, 7.0))

    def test_absolute_caption(self):
        """10) Absolute Caption 5.0-8.0, kein Reset."""
        (cap,) = captions_from_segments(
            [{"start": 5.0, "end": 8.0, "text": "Grüße aus München",
              "words": [{"word": "Grüße", "start": 5.1, "end": 5.7},
                        {"word": "aus", "start": 5.8, "end": 6.1},
                        {"word": "München", "start": 6.2, "end": 7.0}]}],
            None, None)
        draft = draft_from_caption(cap)
        self.assertTrue(set_caption_timing(draft, 5.05, 7.95))
        rebuilt = to_caption(draft)
        self.assertEqual((rebuilt.start, rebuilt.end), (5.05, 7.95))
        self.assertEqual(
            [(w.word, w.start, w.end) for w in rebuilt.words],
            [("Grüße", 5.1, 5.7), ("aus", 5.8, 6.1), ("München", 6.2, 7.0)])

    def test_repeated_nudge_to_boundary(self):
        """11) Mehrfaches Nudge bis zur Grenze, dann Ablehnung."""
        (cap,) = captions_from_segments(
            [{"start": 4.5, "end": 7.5, "text": "Hello world",
              "words": [{"word": "Hello", "start": 5.0, "end": 5.8},
                        {"word": "world", "start": 5.9, "end": 7.0}]}],
            None, None)
        draft = draft_from_caption(cap)
        steps = 0
        while set_caption_timing(draft, round(draft.start + 0.05, 10),
                                 draft.end):
            steps += 1
            self.assertLess(steps, 100)
        self.assertAlmostEqual(draft.start, 5.0)
        self.assertGreater(steps, 0)
        self.assertFalse(set_caption_timing(draft, 5.05, draft.end))

    def test_invalid_leaves_draft_untouched(self):
        """12) Invalid -> Draft vollständig unverändert."""
        draft = _draft()
        snapshot = (draft.text, draft.start, draft.end,
                    [(w["word"], w["start"], w["end"]) for w in draft.words])
        for bad in [("x", 7.0), (5.0, "y"), (None, 7.0),
                    (float("nan"), 7.0), (5.0, float("inf")),
                    (5.05, 7.0), (6.0, 6.0)]:
            self.assertFalse(set_caption_timing(draft, *bad), msg=repr(bad))
        self.assertEqual(
            (draft.text, draft.start, draft.end,
             [(w["word"], w["start"], w["end"]) for w in draft.words]),
            snapshot)

    def test_empty_words_span_free(self):
        """Leere Caption: Spanne frei wählbar (Start/End-Regeln gelten)."""
        (cap,) = captions_from_segments(
            [{"start": 1.0, "end": 2.0, "text": "", "words": []}],
            None, None)
        draft = draft_from_caption(cap)
        self.assertTrue(set_caption_timing(draft, 0.5, 3.0))
        self.assertEqual((draft.start, draft.end), (0.5, 3.0))
        self.assertFalse(set_caption_timing(draft, 3.0, 3.0))

    def test_nonfinite_word_times_reject(self):
        """Block 37: nicht-finite Wortzeiten -> Ablehnung, Draft intakt."""
        draft = _draft()
        before = (draft.start, draft.end)
        draft.words[0] = {"word": "Hello", "start": 5.0, "end": float("inf")}
        self.assertFalse(set_caption_timing(draft, 4.5, 7.5))
        self.assertEqual((draft.start, draft.end), before)

    def test_unparseable_word_tolerated(self):
        """Block 37: unlesbares Wort blockiert gültige Spannen nicht."""
        draft = _draft()
        draft.words.append({"word": "???", "start": "kaputt"})
        self.assertTrue(set_caption_timing(draft, 4.5, 7.5))
        self.assertEqual((draft.start, draft.end), (4.5, 7.5))


import tempfile as _tmp2

if "CAPTI_CONFIG_FILE" not in os.environ:
    os.environ["APPDATA"] = _tmp2.mkdtemp(prefix="capti_test_appdata_")

import customtkinter as ctk

from ui import i18n
from ui.app_controller import AppController
from ui.screens import caption_style as cs_mod

VIDEO_A = "C:/vids/clipA.mp4"


def _ui_segments():
    return [
        {"start": 5.0, "end": 7.0, "text": "Hello world",
         "words": [{"word": "Hello", "start": 5.0, "end": 5.8},
                   {"word": "world", "start": 5.9, "end": 7.0}]},
        {"start": 8.0, "end": 10.0, "text": "Grüße aus München",
         "words": [{"word": "Grüße", "start": 8.0, "end": 8.6},
                   {"word": "aus", "start": 8.7, "end": 9.0},
                   {"word": "München", "start": 9.1, "end": 10.0}]},
    ]


def _mock_stack(captured):
    engine = MagicMock()
    engine.transcribe.return_value = _ui_segments()
    processor = MagicMock()
    processor.extract_audio.side_effect = lambda v, a, **k: a
    processor.get_video_info.return_value = {"streams": [{"width": 720, "height": 1280}]}
    processor.embed_ass.side_effect = lambda v, a, o, **k: o
    renderer = MagicMock()

    def fake_ass(segments, path, video_width=None, video_height=None):
        captured["ass_segments"] = copy.deepcopy(segments)
        Path(path).write_text("ASS", encoding="utf-8")
        return path

    renderer.generate_ass.side_effect = fake_ass
    return engine, processor, renderer


class TestWordUI(unittest.TestCase):
    """K24-27) Word-Aktionen in Preview (+ Invalid-Handling)."""

    @classmethod
    def setUpClass(cls):
        ctk.set_appearance_mode("dark")
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        import contextlib
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
        self.controller.pending_project = {"video_path": VIDEO_A,
                                           "model": "tiny", "language": "de"}
        self.controller.last_transcript = {
            "video_path": VIDEO_A, "segments": _ui_segments()}
        self.screen.on_show()

    def tearDown(self):
        i18n.set_language(self._prev_lang)
        self.patcher.stop()
        self.tmp.cleanup()
        import contextlib
        with contextlib.suppress(Exception):
            self.screen.destroy()

    def _select_word(self, idx):
        labels = list(self.screen._word_option.cget("values"))
        self.screen._word_option.set(labels[idx])
        self.screen._on_word_select(None)

    def test_timing_edit_updates_preview(self):
        """24) Timing-Edit landet in Preview + Segment (absolut)."""
        self._select_word(1)
        self.screen._word_start_entry.delete(0, "end")
        self.screen._word_start_entry.insert(0, "6,0")
        self.screen._word_end_entry.delete(0, "end")
        self.screen._word_end_entry.insert(0, "6.9")
        self.screen._on_word_set()
        words = {w.word: w for w in self.screen._preview_caption.words}
        self.assertEqual((words["world"].start, words["world"].end),
                         (6.0, 6.9))                               # 27
        seg = self.screen._transcript_segments[0]["words"][1]
        self.assertEqual((seg["start"], seg["end"]), (6.0, 6.9))

    def test_split_updates_preview(self):
        """25) Split landet in Preview (Auto-Hälften)."""
        self._select_word(0)
        self.screen._on_word_split()
        got = [w.word for w in self.screen._preview_caption.words]
        self.assertEqual(got[:2], ["He", "llo"])
        self.assertEqual(got[2], "world")

    def test_merge_updates_preview(self):
        """26) Merge landet in Preview."""
        self._select_word(0)
        self.screen._on_word_merge()
        got = [(w.word, w.start, w.end)
               for w in self.screen._preview_caption.words]
        self.assertEqual(got, [("Hello world", 5.0, 7.0)])

    def test_word_select_shows_data(self):
        """B) Auswahl zeigt Text/Start/Ende/Dauer."""
        self._select_word(1)
        self.assertEqual(self.screen._word_start_entry.get(), "5.900")
        self.assertEqual(self.screen._word_end_entry.get(), "7.000")
        self.assertIn("1.100", self.screen._word_info_label.cget("text"))

    def test_invalid_inputs_rejected(self):
        """J) Ungültiges -> Hinweis, State unberührt."""
        before = copy.deepcopy(self.screen._transcript_segments[0])
        self._select_word(0)
        for start, end in (("abc", "5.7"), ("", "5.7"), ("-1", "5.7"),
                           ("5.7", "5.7"), ("5.8", "5.7"), ("4.9", "5.7"),
                           ("5.0", "7.1")):
            self.screen._word_start_entry.delete(0, "end")
            self.screen._word_start_entry.insert(0, start)
            self.screen._word_end_entry.delete(0, "end")
            self.screen._word_end_entry.insert(0, end)
            self.screen._on_word_set()
            self.assertTrue(self.screen._editor_hint.cget("text"))
        self.assertEqual(self.screen._transcript_segments[0], before)

    def test_merge_last_word_rejected(self):
        self._select_word(1)
        before = copy.deepcopy(self.screen._transcript_segments[0])
        self.screen._on_word_merge()
        self.assertTrue(self.screen._editor_hint.cget("text"))
        self.assertEqual(self.screen._transcript_segments[0], before)


class TestWordExportPersist(unittest.TestCase):
    """K28-37) Persistenz + Export mit Word-Edits."""

    @classmethod
    def setUpClass(cls):
        ctk.set_appearance_mode("dark")
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        import contextlib
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
        self.controller.pending_project = {"video_path": VIDEO_A,
                                           "model": "tiny", "language": "de"}
        self.controller.last_transcript = {
            "video_path": VIDEO_A, "segments": _ui_segments()}
        self.screen.on_show()
        self.proj_path = str(Path(self.tmp.name) / "w.capti.json")

    def tearDown(self):
        i18n.set_language(self._prev_lang)
        self.patcher.stop()
        self.tmp.cleanup()
        import contextlib
        with contextlib.suppress(Exception):
            self.screen.destroy()

    def _select_word(self, idx):
        labels = list(self.screen._word_option.cget("values"))
        self.screen._word_option.set(labels[idx])
        self.screen._on_word_select(None)

    def _set_timing(self, start, end):
        self.screen._word_start_entry.delete(0, "end")
        self.screen._word_start_entry.insert(0, start)
        self.screen._word_end_entry.delete(0, "end")
        self.screen._word_end_entry.insert(0, end)
        self.screen._on_word_set()

    def _run_override(self, segments, captured):
        from pipeline import CaptiPipeline
        tmp = Path(tempfile.mkdtemp(prefix="capti_w25_"))
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        (tmp / "clip.mp4").write_bytes(b"x")
        engine, processor, renderer = _mock_stack(captured)
        pipe = CaptiPipeline(temp_dir=str(tmp / "_temp"))
        with patch("pipeline.create_subtitle_engine", return_value=engine), \
             patch("pipeline.create_video_processor", return_value=processor), \
             patch("pipeline.create_caption_renderer", return_value=renderer):
            pipe.run(str(tmp / "clip.mp4"), model_size="tiny", language="de",
                     override_segments=segments)
        return engine

    def test_timing_save_load(self):
        """30) Timing-Edit übersteht Save/Load identisch."""
        self._select_word(1)
        self._set_timing("6.0", "6.9")
        self.controller.save_project_state(self.proj_path)
        self.controller.last_transcript = None
        self.controller.pending_project = None
        self.screen.clear_transcript()
        self.controller.load_project_state(self.proj_path)
        words = self.controller.last_transcript["segments"][0]["words"]
        self.assertEqual((words[1]["start"], words[1]["end"]), (6.0, 6.9))

    def test_split_save_load(self):
        """28) Split übersteht Save/Load."""
        self._select_word(0)
        self.screen._on_word_split()
        self.controller.save_project_state(self.proj_path)
        self.controller.last_transcript = None
        self.controller.pending_project = None
        self.screen.clear_transcript()
        self.controller.load_project_state(self.proj_path)
        words = self.controller.last_transcript["segments"][0]["words"]
        self.assertEqual([w["word"] for w in words], ["He", "llo", "world"])

    def test_merge_save_load(self):
        """29) Merge übersteht Save/Load."""
        self._select_word(0)
        self.screen._on_word_merge()
        self.controller.save_project_state(self.proj_path)
        self.controller.last_transcript = None
        self.controller.pending_project = None
        self.screen.clear_transcript()
        state = self.controller.load_project_state(self.proj_path)
        self.assertEqual(state.segments[0]["words"],
                         [{"word": "Hello world", "start": 5.0, "end": 7.0}])

    def test_unicode_save_load(self):
        """31) Umlaut-Timing übersteht Save/Load."""
        labels = list(self.screen._editor_option.cget("values"))
        self.screen._editor_option.set(labels[1])
        self.screen._on_editor_select(None)
        self._select_word(0)
        self._set_timing("8.1", "8.7")
        self.controller.save_project_state(self.proj_path)
        self.controller.last_transcript = None
        self.controller.pending_project = None
        self.screen.clear_transcript()
        state = self.controller.load_project_state(self.proj_path)
        w = state.segments[1]["words"][0]
        self.assertEqual((w["word"], w["start"], w["end"]),
                         ("Grüße", 8.1, 8.7))

    def test_timing_reaches_override(self):
        """32) Editiertes Timing erreicht override_segments."""
        import ui.screens.processing as proc_mod
        self._select_word(1)
        self._set_timing("6.0", "6.9")
        processing = self.controller.get_screen("processing")
        processing.video_path = VIDEO_A
        processing.model = "tiny"
        processing.language = "de"
        with patch.object(proc_mod, "CaptiPipeline") as mk_pipe, \
             patch.object(type(processing), "_cleanup_temp",
                          lambda self: None):
            processing._start_pipeline()
        _a, kwargs = mk_pipe.return_value.run_async.call_args
        self.assertEqual(
            [(w["word"], w["start"], w["end"])
             for w in kwargs["override_segments"][0]["words"]],
            [("Hello", 5.0, 5.8), ("world", 6.0, 6.9)])

    def test_split_merge_reach_ass_and_skip_whisper(self):
        """33/34/35/36/37) Split+Merge -> ASS-Input, kein Whisper."""
        self._select_word(0)
        self.screen._on_word_split()
        self._select_word(1)
        self.screen._on_word_merge()  # "llo" + "world" -> "llo world"
        preview_words = [(w.word, w.start, w.end)
                         for w in self.screen._preview_caption.words]
        captured = {}
        engine = self._run_override(
            self.controller.get_transcript_segments(VIDEO_A), captured)
        engine.transcribe.assert_not_called()                    # 35
        ass_words = [(w["word"], w["start"], w["end"])
                     for w in captured["ass_segments"][0]["words"]]
        self.assertEqual([w[0] for w in ass_words],
                         ["He", "llo world"])                   # 33/34
        self.assertEqual(ass_words, preview_words)               # 36/37


class TestManualSplit(unittest.TestCase):
    """Block 28: manueller Split-Punkt."""

    def _draft(self):
        (cap,) = captions_from_segments(
            [{"start": 1.0, "end": 2.0, "text": "Hallo Welt",
              "words": [{"word": "Hallo", "start": 1.0, "end": 1.8},
                        {"word": "Welt", "start": 1.8, "end": 2.0}]}],
            None, None)
        return draft_from_caption(cap)

    def test_valid_split(self):
        draft = self._draft()
        self.assertTrue(split_word_at(draft, 0, 2))
        self.assertEqual([w["word"] for w in draft.words],
                         ["Ha", "llo", "Welt"])

    def test_split_at_1_and_len_minus_1(self):
        draft = self._draft()
        self.assertTrue(split_word_at(draft, 0, 1))
        self.assertEqual([w["word"] for w in draft.words[:2]], ["H", "allo"])
        draft = self._draft()
        self.assertTrue(split_word_at(draft, 0, 4))
        self.assertEqual([w["word"] for w in draft.words[:2]], ["Hall", "o"])

    def test_boundaries_rejected(self):
        draft = self._draft()
        before = copy.deepcopy(draft.words)
        for bad in (0, 5, -1, 99, "x", None, 2.5):
            self.assertFalse(split_word_at(draft, 0, bad), msg=bad)
        self.assertFalse(split_word_at(draft, 9, 2))
        self.assertEqual(draft.words, before)

    def test_proportional_timing(self):
        draft = self._draft()
        split_word_at(draft, 0, 2)  # "Ha"(2)/"llo"(3) auf 1.0-1.8
        self.assertAlmostEqual(draft.words[0]["start"], 1.0)
        self.assertAlmostEqual(draft.words[0]["end"], 1.0 + 0.8 * 2 / 5)
        self.assertAlmostEqual(draft.words[1]["start"], 1.0 + 0.8 * 2 / 5)
        self.assertAlmostEqual(draft.words[1]["end"], 1.8)
        for w in draft.words:
            self.assertGreater(w["end"], w["start"])
            self.assertGreaterEqual(w["start"], 0.0)

    def test_unicode_split(self):
        (cap,) = captions_from_segments(
            [{"start": 1.0, "end": 2.0, "text": "grüßt",
              "words": [{"word": "grüßt", "start": 1.0, "end": 2.0}]}],
            None, None)
        draft = draft_from_caption(cap)
        self.assertTrue(split_word_at(draft, 0, 3))
        self.assertEqual([w["word"] for w in draft.words], ["grü", "ßt"])
        cap2 = to_caption(draft)
        self.assertEqual(cap2.text, "grü ßt")

    def test_tiny_span(self):
        (cap,) = captions_from_segments(
            [{"start": 1.0, "end": 1.0 + 1e-9, "text": "ab",
              "words": [{"word": "ab", "start": 1.0,
                         "end": 1.0 + 1e-9}]}],
            None, None)
        draft = draft_from_caption(cap)
        ok = split_word_at(draft, 0, 1)
        if ok:
            for w in draft.words:
                self.assertGreater(w["end"], w["start"])
        else:
            self.assertEqual(len(draft.words), 1)


class TestInsertWord(unittest.TestCase):
    """Block 28: Wort einfügen."""

    def _draft(self):
        (cap,) = captions_from_segments(
            [{"start": 0.0, "end": 2.0, "text": "Hallo Welt",
              "words": [{"word": "Hallo", "start": 0.0, "end": 0.5},
                        {"word": "Welt", "start": 1.0, "end": 2.0}]}],
            None, None)
        return draft_from_caption(cap)

    def test_insert_middle_uses_gap(self):
        draft = self._draft()
        self.assertTrue(insert_word(draft, 1, "schöne"))
        self.assertEqual([w["word"] for w in draft.words],
                         ["Hallo", "schöne", "Welt"])
        self.assertEqual((draft.words[1]["start"], draft.words[1]["end"]),
                         (0.5, 1.0))
        self.assertEqual(draft.text, "Hallo schöne Welt")

    def test_insert_beginning_no_room(self):
        # Anfang: Hallo startet bei Caption-Start -> kein Platz -> False.
        draft = self._draft()
        self.assertFalse(insert_word(draft, 0, "Oh"))
        self.assertEqual([w["word"] for w in draft.words],
                         ["Hallo", "Welt"])

    def test_insert_deterministic(self):
        draft = self._draft()
        draft2 = self._draft()
        self.assertEqual(insert_word(draft, 1, "x"),
                         insert_word(draft2, 1, "x"))
        self.assertEqual(draft.words, draft2.words)

    def test_insert_end(self):
        (cap,) = captions_from_segments(
            [{"start": 0.0, "end": 2.0, "text": "Hallo",
              "words": [{"word": "Hallo", "start": 0.0, "end": 0.5}]}],
            None, None)
        draft = draft_from_caption(cap)
        self.assertTrue(insert_word(draft, 1, "Welt"))
        self.assertEqual((draft.words[1]["start"], draft.words[1]["end"]),
                         (0.5, 2.0))

    def test_empty_word_rejected(self):
        draft = self._draft()
        before = copy.deepcopy(draft.words)
        for bad in ("", "   ", "zwei wörter", None, 42):
            self.assertFalse(insert_word(draft, 1, bad), msg=repr(bad))
        self.assertEqual(draft.words, before)

    def test_invalid_timing_rejected(self):
        draft = self._draft()
        before = copy.deepcopy(draft.words)
        self.assertFalse(insert_word(draft, 1, "x", 0.9, 0.9))
        self.assertFalse(insert_word(draft, 1, "x", 0.9, 0.8))
        self.assertFalse(insert_word(draft, 1, "x", -1.0, 0.2))
        self.assertFalse(insert_word(draft, 1, "x", 0.6, 3.0))
        self.assertFalse(insert_word(draft, 1, "x", 0.4, 0.6))  # Overlap
        self.assertFalse(insert_word(draft, 1, "x", 0.6, None))
        self.assertFalse(insert_word(draft, 9, "x"))
        self.assertEqual(draft.words, before)

    def test_explicit_timing(self):
        draft = self._draft()
        self.assertTrue(insert_word(draft, 1, "schöne", 0.6, 0.9))
        self.assertEqual((draft.words[1]["start"], draft.words[1]["end"]),
                         (0.6, 0.9))
        # Nachbarn unberührt:
        self.assertEqual((draft.words[0]["start"], draft.words[0]["end"]),
                         (0.0, 0.5))
        self.assertEqual((draft.words[2]["start"], draft.words[2]["end"]),
                         (1.0, 2.0))

    def test_span_unchanged(self):
        draft = self._draft()
        insert_word(draft, 1, "schöne")
        self.assertEqual((draft.start, draft.end), (0.0, 2.0))
        cap = to_caption(draft)
        self.assertEqual((cap.start, cap.end), (0.0, 2.0))


class TestDeleteWord(unittest.TestCase):
    """Block 28: Wort löschen."""

    def _draft(self):
        (cap,) = captions_from_segments(
            [{"start": 0.0, "end": 2.0, "text": "Hallo schöne Welt",
              "words": [{"word": "Hallo", "start": 0.0, "end": 0.5},
                        {"word": "schöne", "start": 0.6, "end": 0.9},
                        {"word": "Welt", "start": 1.0, "end": 2.0}]}],
            None, None)
        return draft_from_caption(cap)

    def test_delete_middle(self):
        draft = self._draft()
        self.assertTrue(delete_word(draft, 1))
        self.assertEqual([w["word"] for w in draft.words],
                         ["Hallo", "Welt"])
        self.assertEqual(draft.text, "Hallo Welt")

    def test_delete_first_last(self):
        draft = self._draft()
        delete_word(draft, 0)
        self.assertEqual([w["word"] for w in draft.words],
                         ["schöne", "Welt"])
        draft = self._draft()
        delete_word(draft, 2)
        self.assertEqual([w["word"] for w in draft.words],
                         ["Hallo", "schöne"])

    def test_delete_only_word(self):
        (cap,) = captions_from_segments(
            [{"start": 1.0, "end": 2.0, "text": "solo",
              "words": [{"word": "solo", "start": 1.0, "end": 2.0}]}],
            None, None)
        draft = draft_from_caption(cap)
        self.assertTrue(delete_word(draft, 0))
        self.assertEqual(draft.words, [])
        self.assertEqual((draft.start, draft.end), (1.0, 2.0))
        cap2 = to_caption(draft)
        self.assertEqual(cap2.words, ())

    def test_invalid_index(self):
        draft = self._draft()
        before = copy.deepcopy(draft.words)
        self.assertFalse(delete_word(draft, 9))
        self.assertFalse(delete_word(draft, -1))
        self.assertFalse(delete_word(draft, "x"))
        self.assertEqual(draft.words, before)

    def test_timings_and_span_kept(self):
        draft = self._draft()
        delete_word(draft, 1)
        self.assertEqual([(w["start"], w["end"]) for w in draft.words],
                         [(0.0, 0.5), (1.0, 2.0)])
        self.assertEqual((draft.start, draft.end), (0.0, 2.0))


class TestNudgeSteps(unittest.TestCase):
    """Block 31: ±0,05s-Schritte über set_word_timing() (Core-Regeln)."""

    def test_step_within_caption(self):
        draft = _draft()
        self.assertTrue(set_word_timing(draft, 1, 5.85, 7.0))
        self.assertTrue(set_word_timing(draft, 1, 5.9, 6.95))
        self.assertEqual((draft.words[1]["start"], draft.words[1]["end"]),
                         (5.9, 6.95))

    def test_step_at_caption_boundary(self):
        draft = _draft()
        self.assertFalse(set_word_timing(draft, 1, 5.9, 7.05))
        self.assertFalse(set_word_timing(draft, 0, 4.95, 5.8))
        self.assertEqual(
            [(w["start"], w["end"]) for w in draft.words],
            [(5.0, 5.8), (5.9, 7.0)])

    def test_step_at_neighbor_boundary(self):
        draft = _draft()
        self.assertTrue(set_word_timing(draft, 0, 5.0, 5.9))
        self.assertFalse(set_word_timing(draft, 0, 5.0, 5.9001))
        self.assertFalse(set_word_timing(draft, 1, 5.799, 7.0))

    def test_step_collision_terminal(self):
        """Wiederholtes -0,05 endet exakt an der Nachbargrenze."""
        draft = _draft()
        start = 5.9
        while set_word_timing(draft, 1, round(start - 0.05, 10), 7.0):
            start = round(start - 0.05, 10)
        self.assertAlmostEqual(start, 5.8)
        self.assertEqual(draft.words[1]["start"], 5.8)

    def test_step_absolute_times(self):
        draft = _draft()
        self.assertTrue(set_word_timing(draft, 1, 6.2, 6.8))
        cap = to_caption(draft)
        self.assertEqual((cap.start, cap.words[1].start, cap.words[1].end),
                         (5.0, 6.2, 6.8))


if __name__ == "__main__":
    unittest.main()
