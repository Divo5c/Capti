"""Fix-Block 21: CaptionDraft-Logik (Tk-frei).

A) Draft aus RenderCaption
B) Textänderung
C) start/end bleiben erhalten
D) vorhandene Word-Timings bleiben erhalten
E) neue Words: gültige deterministische Timings
F) keine negativen Zeiten
G) RenderCaption wird neu erzeugt (Ableitungen neu)
H) Lines werden neu abgeleitet
I) Pop-Windows werden neu abgeleitet
K) unverändert -> datenidentisch
L) mehrere Captions unabhängig
M) Unicode/Umlaute
N) leere Eingabe
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capti_core.caption_draft import (
    apply_text,
    draft_from_caption,
    merge_segments,
    split_segment,
    to_caption,
    to_segment,
)
from capti_core.render_model import (
    assign_lines,
    captions_from_segments,
    pop_state_at,
    pop_windows,
)


def _segments():
    return [
        {"start": 5.0, "end": 7.0, "text": "Hello world",
         "words": [{"word": "Hello", "start": 5.0, "end": 5.8},
                   {"word": "world", "start": 5.9, "end": 7.0}]},
        {"start": 8.0, "end": 10.0, "text": "Grüße aus München",
         "words": [{"word": "Grüße", "start": 8.0, "end": 8.6},
                   {"word": "aus", "start": 8.7, "end": 9.0},
                   {"word": "München", "start": 9.1, "end": 10.0}]},
    ]


def _snap(cap):
    return (cap.text, cap.start, cap.end,
            tuple((w.word, w.start, w.end) for w in cap.words),
            cap.lines, dict(cap.style), dict(cap.layout))


def _assert_valid_words(testcase, words, cap_start, cap_end):
    for w in words:
        testcase.assertGreaterEqual(w["start"], 0.0, w)          # F
        testcase.assertGreater(w["end"], w["start"], w)          # F
        testcase.assertGreaterEqual(w["start"], cap_start - 1e-9, w)
        testcase.assertLessEqual(w["end"], cap_end + 1e-9, w)


class TestDraftFromCaption(unittest.TestCase):
    """A) Draft aus RenderCaption."""

    def test_draft_copies_values(self):
        (cap,) = captions_from_segments(_segments()[:1], None, None)
        draft = draft_from_caption(cap)
        self.assertEqual(draft.text, "Hello world")
        self.assertEqual(draft.start, 5.0)
        self.assertEqual(draft.end, 7.0)
        self.assertEqual([w["word"] for w in draft.words],
                         ["Hello", "world"])
        self.assertEqual(draft.words[0]["start"], 5.0)

    def test_draft_is_a_copy(self):
        (cap,) = captions_from_segments(_segments()[:1], None, None)
        draft = draft_from_caption(cap)
        draft.words[0]["word"] = "X"
        self.assertEqual(cap.words[0].word, "Hello")


class TestApplyText(unittest.TestCase):
    """B/C/D/E/F) Textänderung mit Timing-Transfer."""

    def test_insert_keeps_existing_timings(self):
        (cap,) = captions_from_segments(_segments()[:1], None, None)
        draft = draft_from_caption(cap)
        apply_text(draft, "Hello beautiful world")
        by_word = {w["word"]: w for w in draft.words}
        self.assertEqual((by_word["Hello"]["start"], by_word["Hello"]["end"]),
                         (5.0, 5.8))                              # D
        self.assertEqual((by_word["world"]["start"], by_word["world"]["end"]),
                         (5.9, 7.0))                              # D
        self.assertEqual(draft.start, 5.0)                        # C
        self.assertEqual(draft.end, 7.0)                          # C
        _assert_valid_words(self, draft.words, 5.0, 7.0)          # E/F

    def test_insert_is_deterministic(self):
        def run():
            (cap,) = captions_from_segments(_segments()[:1], None, None)
            draft = draft_from_caption(cap)
            apply_text(draft, "Hello beautiful world")
            return [(w["word"], w["start"], w["end"]) for w in draft.words]
        self.assertEqual(run(), run())                            # E

    def test_delete_word(self):
        (cap,) = captions_from_segments(_segments()[:1], None, None)
        draft = draft_from_caption(cap)
        apply_text(draft, "Hello")
        self.assertEqual([w["word"] for w in draft.words], ["Hello"])
        self.assertEqual((draft.words[0]["start"], draft.words[0]["end"]),
                         (5.0, 5.8))
        self.assertEqual((draft.start, draft.end), (5.0, 7.0))

    def test_replace_all_words(self):
        (cap,) = captions_from_segments(_segments()[:1], None, None)
        draft = draft_from_caption(cap)
        apply_text(draft, "Guten Morgen zusammen")
        self.assertEqual([w["word"] for w in draft.words],
                         ["Guten", "Morgen", "zusammen"])
        _assert_valid_words(self, draft.words, 5.0, 7.0)
        # Lückenlos, monoton, deckt die Spanne ab
        self.assertAlmostEqual(draft.words[0]["start"], 5.0)
        self.assertAlmostEqual(draft.words[-1]["end"], 7.0)
        for a, b in zip(draft.words, draft.words[1:]):
            self.assertLessEqual(a["end"], b["end"])

    def test_empty_input(self):
        """N) Leere Eingabe: keine Wörter, gültige Spanne."""
        (cap,) = captions_from_segments(_segments()[:1], None, None)
        draft = draft_from_caption(cap)
        apply_text(draft, "   ")
        self.assertEqual(draft.words, [])
        self.assertEqual((draft.start, draft.end), (5.0, 7.0))
        rebuilt = to_caption(draft)
        self.assertEqual(rebuilt.words, ())
        self.assertEqual((rebuilt.start, rebuilt.end), (5.0, 7.0))

    def test_unicode(self):
        """M) Umlaute/Unicode bleiben erhalten, Timings übernommen."""
        (_, cap) = captions_from_segments(_segments(), None, None)
        draft = draft_from_caption(cap)
        apply_text(draft, "Grüße aus dem schönen München")
        by_word = {w["word"]: w for w in draft.words}
        self.assertEqual(by_word["Grüße"]["start"], 8.0)
        self.assertEqual(by_word["München"]["end"], 10.0)
        self.assertIn("schönen", by_word)
        _assert_valid_words(self, draft.words, 8.0, 10.0)
        rebuilt = to_caption(draft)
        self.assertEqual(rebuilt.text, "Grüße aus dem schönen München")


class TestRebuild(unittest.TestCase):
    """G/H/I/K) Neue RenderCaption aus dem Draft."""

    def test_unchanged_is_identical(self):
        """K) Ohne Änderung: datenidentischer Rebuild."""
        (cap,) = captions_from_segments(_segments()[:1], None, None)
        rebuilt = to_caption(draft_from_caption(cap))
        self.assertEqual(_snap(rebuilt), _snap(cap))

    def test_lines_rederived(self):
        """H) Lines stammen aus dem Modell, nicht aus dem Draft."""
        (cap,) = captions_from_segments(_segments()[:1], None, None)
        draft = draft_from_caption(cap)
        apply_text(draft, "eins zwei drei vier fünf sechs sieben")
        rebuilt = to_caption(draft)
        # Unabhängig nachgerechnet (Modell-Regel, Default max. 5/Zeile)
        self.assertEqual(rebuilt.lines,
                         assign_lines(list(rebuilt.words), 5))
        # Konsistenz: Lines decken alle Wort-Indizes genau einmal ab
        covered = sorted(i for line in rebuilt.lines for i in line)
        self.assertEqual(covered, list(range(len(rebuilt.words))))
        self.assertLessEqual(len(rebuilt.lines), 2)

    def test_pop_windows_rederived(self):
        """I) Pop-Windows werden aus der neuen Caption abgeleitet."""
        (cap,) = captions_from_segments(_segments()[:1], None, None)
        draft = draft_from_caption(cap)
        apply_text(draft, "Hello beautiful world")
        rebuilt = to_caption(draft)
        windows = pop_windows(rebuilt)
        self.assertEqual(len(windows), 3)
        self.assertEqual(windows[0][:2], (0, 800))
        self.assertEqual(windows[2][:2], (900, 2000))
        # Absolute Zeiten + Decay: 5960 liegt in "beautiful" (5800–5900+150)
        idx, scale = pop_state_at(rebuilt, 5960)
        self.assertEqual(idx, 1)
        self.assertGreater(scale, 100.0)

    def test_style_layout_survive(self):
        style = {"pop_scale": 140, "pop_decay_ms": 200}
        (cap,) = captions_from_segments(_segments()[:1], style, None)
        draft = draft_from_caption(cap)
        apply_text(draft, "Hello world again")
        rebuilt = to_caption(draft)
        self.assertEqual(dict(rebuilt.style), dict(cap.style))
        self.assertEqual(dict(rebuilt.layout), dict(cap.layout))

    def test_independent_captions(self):
        """L) Mehrere Captions: Edit betrifft nur eine."""
        caps = captions_from_segments(_segments(), None, None)
        drafts = [draft_from_caption(c) for c in caps]
        apply_text(drafts[0], "Hello beautiful world")
        rebuilt = [to_caption(d) for d in drafts]
        self.assertEqual(_snap(rebuilt[1]), _snap(caps[1]))
        self.assertEqual(rebuilt[0].text, "Hello beautiful world")

    def test_to_segment_export_shape(self):
        """Export-Vorbereitung: Whisper-/ASS-Adapter-Format."""
        (cap,) = captions_from_segments(_segments()[:1], None, None)
        draft = draft_from_caption(cap)
        apply_text(draft, "Hello beautiful world")
        seg = to_segment(draft)
        self.assertEqual(set(seg), {"start", "end", "text", "words"})
        self.assertEqual(seg["text"], "Hello beautiful world")
        for w in seg["words"]:
            self.assertEqual(set(w), {"word", "start", "end"})
        # Direkt in captions_from_segments rückführbar (ASS-Pfad)
        (back,) = captions_from_segments([seg], None, None)
        self.assertEqual(back.text, seg["text"])
        self.assertEqual(len(back.words), 3)


class TestSplitSegment(unittest.TestCase):
    """Block 55: Caption-Split (rein, validiert, ohne Mutation)."""

    def _seg(self):
        return {
            "start": 5.0, "end": 8.0, "text": "eins zwei drei",
            "words": [{"word": "eins", "start": 5.4, "end": 6.0},
                      {"word": "zwei", "start": 6.3, "end": 6.9},
                      {"word": "drei", "start": 7.2, "end": 7.8}],
        }

    def test_valid_split(self):
        left, right = split_segment(self._seg(), 1)
        self.assertEqual(left["text"], "eins")
        self.assertEqual(right["text"], "zwei drei")
        self.assertAlmostEqual(left["start"], 5.0)
        self.assertAlmostEqual(left["end"], 6.0)
        self.assertAlmostEqual(right["start"], 6.3)
        self.assertAlmostEqual(right["end"], 8.0)

    def test_first_possible_word(self):
        left, right = split_segment(self._seg(), 1)
        self.assertEqual([w["word"] for w in left["words"]], ["eins"])
        self.assertEqual([w["word"] for w in right["words"]],
                         ["zwei", "drei"])

    def test_last_possible_word(self):
        left, right = split_segment(self._seg(), 2)
        self.assertEqual([w["word"] for w in left["words"]],
                         ["eins", "zwei"])
        self.assertEqual([w["word"] for w in right["words"]], ["drei"])
        self.assertAlmostEqual(right["start"], 7.2)
        self.assertAlmostEqual(right["end"], 8.0)

    def test_invalid_split(self):
        seg = self._seg()
        self.assertIsNone(split_segment(seg, 0))
        self.assertIsNone(split_segment(seg, 3))
        self.assertIsNone(split_segment(seg, -1))
        self.assertIsNone(split_segment(seg, True))
        self.assertIsNone(split_segment(seg, "1"))

    def test_word_timestamps_kept(self):
        left, right = split_segment(self._seg(), 1)
        self.assertEqual(
            [(w["word"], w["start"], w["end"]) for w in left["words"]],
            [("eins", 5.4, 6.0)])
        self.assertEqual(
            [(w["word"], w["start"], w["end"]) for w in right["words"]],
            [("zwei", 6.3, 6.9), ("drei", 7.2, 7.8)])

    def test_timing_derived(self):
        seg = {"start": 0.0, "end": 10.0, "text": "a b",
               "words": [{"word": "a", "start": 2.0, "end": 3.0},
                         {"word": "b", "start": 7.0, "end": 9.0}]}
        left, right = split_segment(seg, 1)
        self.assertAlmostEqual(left["start"], 0.0)
        self.assertAlmostEqual(left["end"], 3.0)
        self.assertAlmostEqual(right["start"], 7.0)
        self.assertAlmostEqual(right["end"], 10.0)

    def test_order_kept(self):
        left, right = split_segment(self._seg(), 2)
        all_words = [w["word"] for w in left["words"]] + \
            [w["word"] for w in right["words"]]
        self.assertEqual(all_words, ["eins", "zwei", "drei"])

    def test_no_mutation(self):
        seg = self._seg()
        before = repr(seg)
        split_segment(seg, 1)
        self.assertEqual(repr(seg), before)

    def test_garbage_rejected(self):
        self.assertIsNone(split_segment(None, 1))
        self.assertIsNone(split_segment({}, 1))
        self.assertIsNone(split_segment({"words": "xx"}, 1))
        one = {"start": 0.0, "end": 1.0, "text": "x",
               "words": [{"word": "x", "start": 0.0, "end": 1.0}]}
        self.assertIsNone(split_segment(one, 1))
        self.assertIsNone(split_segment(one, 0))


class TestMergeSegments(unittest.TestCase):
    """Block 59: Caption-Merge (rein, validiert, ohne Mutation)."""

    def _ab(self):
        a = {"start": 5.0, "end": 6.0, "text": "eins",
             "words": [{"word": "eins", "start": 5.4, "end": 6.0}]}
        b = {"start": 6.3, "end": 8.0, "text": "zwei drei",
             "words": [{"word": "zwei", "start": 6.3, "end": 6.9},
                       {"word": "drei", "start": 7.2, "end": 7.8}]}
        return a, b

    def test_valid_merge(self):
        merged = merge_segments(*self._ab())
        self.assertAlmostEqual(merged["start"], 5.0)
        self.assertAlmostEqual(merged["end"], 8.0)
        self.assertEqual(merged["text"], "eins zwei drei")
        self.assertEqual([w["word"] for w in merged["words"]],
                         ["eins", "zwei", "drei"])

    def test_word_order_timing_kept(self):
        merged = merge_segments(*self._ab())
        self.assertEqual(
            [(w["word"], w["start"], w["end"]) for w in merged["words"]],
            [("eins", 5.4, 6.0), ("zwei", 6.3, 6.9), ("drei", 7.2, 7.8)])

    def test_text_edits_kept(self):
        a, b = self._ab()
        a["text"] = "Eins!"
        b["text"] = "zwei  drei?"
        merged = merge_segments(a, b)
        self.assertEqual(merged["text"], "Eins! zwei  drei?")

    def test_single_words(self):
        a = {"start": 0.0, "end": 1.0, "text": "a",
             "words": [{"word": "a", "start": 0.0, "end": 1.0}]}
        b = {"start": 1.0, "end": 2.0, "text": "b",
             "words": [{"word": "b", "start": 1.0, "end": 2.0}]}
        merged = merge_segments(a, b)
        self.assertAlmostEqual(merged["start"], 0.0)
        self.assertAlmostEqual(merged["end"], 2.0)
        self.assertEqual(merged["text"], "a b")

    def test_invalid_inputs(self):
        a, _b = self._ab()
        self.assertIsNone(merge_segments(None, a))
        self.assertIsNone(merge_segments(a, None))
        self.assertIsNone(merge_segments({}, {}))
        self.assertIsNone(merge_segments("x", "y"))
        empty = {"start": 0.0, "end": 1.0, "text": "",
                 "words": []}
        self.assertIsNone(merge_segments(empty, a))
        self.assertIsNone(merge_segments(a, empty))

    def test_invalid_result_rejected(self):
        a = {"start": 5.0, "end": 8.0, "text": "spät",
             "words": [{"word": "spät", "start": 7.0, "end": 8.0}]}
        b = {"start": 0.0, "end": 2.0, "text": "früh",
             "words": [{"word": "früh", "start": 0.0, "end": 2.0}]}
        self.assertIsNone(merge_segments(a, b))
        bad = {"start": 0.0, "end": 1.0, "text": "x",
               "words": [{"word": "x", "start": "inf", "end": 1.0}]}
        good = {"start": 1.0, "end": 2.0, "text": "y",
                "words": [{"word": "y", "start": 1.0, "end": 2.0}]}
        self.assertIsNone(merge_segments(bad, good))

    def test_no_mutation(self):
        a, b = self._ab()
        before = (repr(a), repr(b))
        merge_segments(a, b)
        self.assertEqual((repr(a), repr(b)), before)


if __name__ == "__main__":
    unittest.main()
