"""Fix-Block 27: Undo/Redo-History + Draft-Snapshots (Tk-frei).

A. Initialzustand
B. Undo/Redo einer Änderung
C. Mehrfaches Undo
D. Mehrfaches Redo
E. Redo-Verzweigung nach neuer Änderung
F. Undo bei leerer Historie
G. Redo bei leerer Historie
H. Snapshot-Immutability
I. kompletter Draft-State wird restauriert
J. identischer Push = kein Schritt
K. History clear
+ Snapshot-Roundtrip, Max-Limit.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capti_core.caption_draft import (
    apply_snapshot,
    apply_text,
    draft_from_caption,
    merge_words,
    set_word_timing,
    snapshot_of_draft,
    split_word,
    to_caption,
)
from capti_core.render_model import captions_from_segments
from capti_core.undo_history import MAX_HISTORY, UndoHistory


def _draft():
    (cap,) = captions_from_segments(
        [{"start": 5.0, "end": 7.0, "text": "Hallo Welt",
          "words": [{"word": "Hallo", "start": 5.0, "end": 5.8},
                    {"word": "Welt", "start": 5.9, "end": 7.0}]}],
        {"pop_scale": 140}, {"play_res_y": 1920})
    return draft_from_caption(cap)


class TestHistorySemantics(unittest.TestCase):
    """A-G, J, K) History-Verhalten auf Plain-Data."""

    def test_initial_state(self):
        """A) Leer: kein Undo/Redo, kein Crash."""
        hist = UndoHistory()
        self.assertFalse(hist.can_undo)
        self.assertFalse(hist.can_redo)
        self.assertEqual(hist.depth, 0)

    def test_single_change(self):
        """B) A -> B -> Undo=A -> Redo=B."""
        hist = UndoHistory("A")
        hist.push("B")
        self.assertTrue(hist.can_undo)
        self.assertEqual(hist.undo(), "A")
        self.assertTrue(hist.can_redo)
        self.assertEqual(hist.redo(), "B")
        self.assertFalse(hist.can_redo)

    def test_multi_undo_redo(self):
        """C/D) A -> B -> C -> D, zurück bis A, vor bis D."""
        hist = UndoHistory("A")
        for state in ("B", "C", "D"):
            hist.push(state)
        self.assertEqual([hist.undo(), hist.undo(), hist.undo()],
                         ["C", "B", "A"])
        self.assertFalse(hist.can_undo)
        self.assertEqual([hist.redo(), hist.redo(), hist.redo()],
                         ["B", "C", "D"])
        self.assertFalse(hist.can_redo)

    def test_branch_discards_redo(self):
        """E) Neue Änderung nach Undo verwirft alten Zweig."""
        hist = UndoHistory("A")
        hist.push("B")
        hist.push("C")
        self.assertEqual(hist.undo(), "B")
        hist.push("C2")
        self.assertFalse(hist.can_redo)
        self.assertIsNone(hist.redo())
        self.assertEqual(hist.undo(), "B")
        self.assertEqual(hist.undo(), "A")

    def test_empty_undo_redo_safe(self):
        """F/G) Leere Ränder crashen nicht."""
        hist = UndoHistory()
        self.assertIsNone(hist.undo())
        self.assertIsNone(hist.redo())
        hist.push("A")
        self.assertIsNone(hist.undo())   # nur Basis, kein davor
        self.assertIsNone(hist.redo())

    def test_identical_push_no_step(self):
        """J) Gleicher Stand = kein Schritt."""
        hist = UndoHistory("A")
        self.assertFalse(hist.push("A"))
        self.assertEqual(hist.depth, 1)
        self.assertFalse(hist.can_undo)

    def test_clear(self):
        """K) clear() vergisst alles."""
        hist = UndoHistory("A")
        hist.push("B")
        hist.clear()
        self.assertFalse(hist.can_undo)
        self.assertFalse(hist.can_redo)
        self.assertEqual(hist.depth, 0)
        self.assertIsNone(hist.undo())

    def test_max_limit(self):
        hist = UndoHistory()
        for i in range(MAX_HISTORY + 10):
            hist.push({"n": i})
        self.assertEqual(hist.depth, MAX_HISTORY)
        # Älteste gefallen (n=10 ältester), neueste erreichbar:
        last = None
        for _ in range(MAX_HISTORY - 1):
            last = hist.undo()
        self.assertEqual(last, {"n": 10})
        self.assertIsNone(hist.undo())


class TestSnapshotImmutability(unittest.TestCase):
    """H) Snapshots gegen Mutation geschützt."""

    def test_push_copies(self):
        snap = {"words": [{"word": "a"}]}
        hist = UndoHistory({"words": []})
        hist.push(snap)
        snap["words"].append({"word": "MUTIERT"})
        hist.undo()  # zurück zur Basis
        self.assertEqual(hist.redo(), {"words": [{"word": "a"}]})

    def test_returned_copies(self):
        hist = UndoHistory({"words": [{"word": "a"}]})
        hist.push({"words": [{"word": "b"}]})
        got = hist.undo()
        got["words"].append({"word": "MUTIERT"})
        self.assertEqual(hist.redo(), {"words": [{"word": "b"}]})


class TestDraftSnapshotRestore(unittest.TestCase):
    """I) Kompletter Draft-State (Text/Wörter/Zeiten/Style/Layout)."""

    def test_full_restore(self):
        draft = _draft()
        before = snapshot_of_draft(draft)
        set_word_timing(draft, 0, 5.0, 5.5)
        split_word(draft, 1, ["We", "lt"])
        apply_text(draft, "ganz anders hier")
        self.assertNotEqual(snapshot_of_draft(draft), before)
        apply_snapshot(draft, before)
        restored = snapshot_of_draft(draft)
        self.assertEqual(restored, before)
        cap = to_caption(draft)
        self.assertEqual(cap.text, "Hallo Welt")
        self.assertEqual([(w.word, w.start, w.end) for w in cap.words],
                         [("Hallo", 5.0, 5.8), ("Welt", 5.9, 7.0)])
        self.assertEqual((cap.start, cap.end), (5.0, 7.0))
        self.assertEqual(dict(cap.style)["pop_scale"], 140)
        self.assertEqual(dict(cap.layout)["play_res_y"], 1920)

    def test_snapshot_survives_draft_mutation(self):
        draft = _draft()
        snap = snapshot_of_draft(draft)
        merge_words(draft, 0)
        draft.style = None
        self.assertEqual(snap["words"][0]["word"], "Hallo")
        self.assertEqual(snap["style"]["pop_scale"], 140)

    def test_merge_undo_restores_two_words(self):
        draft = _draft()
        before = snapshot_of_draft(draft)
        merge_words(draft, 0)
        self.assertEqual(len(draft.words), 1)
        apply_snapshot(draft, before)
        self.assertEqual(len(draft.words), 2)
        self.assertEqual(draft.words[1]["word"], "Welt")


if __name__ == "__main__":
    unittest.main()
