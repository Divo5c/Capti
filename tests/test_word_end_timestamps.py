"""
Regressionstests Phase 20: fehlende Word-End-Timestamps robust behandeln.
"""

import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from caption_renderer import (
    CaptionRenderer, MIN_WORD_DURATION,
    group_caption_segments, normalize_word_timestamps,
)


def _word(word, start, end=None):
    w = {"word": word, "start": start}
    if end is not None:
        w["end"] = end
    return w


def _parse_ass_time(ts: str) -> float:
    h, m, rest = ts.split(":")
    s, cs = rest.split(".")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(cs) / 100.0


class TestNormalizeWordTimestamps(unittest.TestCase):

    def test_next_word_start_used_as_end(self):
        words = [_word("Hallo", 1.20), _word("Welt", 1.55, 1.90)]
        out = normalize_word_timestamps(words)
        self.assertEqual(out[0]["end"], 1.55)
        self.assertEqual(out[1]["end"], 1.90)

    def test_last_word_uses_segment_end(self):
        words = [_word("Hallo", 1.20, 1.50), _word("Welt", 1.55)]
        out = normalize_word_timestamps(words, fallback_end=2.00)
        self.assertEqual(out[1]["end"], 2.00)

    def test_no_info_safe_fallback(self):
        words = [_word("Solo", 5.00)]
        out = normalize_word_timestamps(words, fallback_end=None)
        self.assertGreater(out[0]["end"], out[0]["start"])
        self.assertLessEqual(out[0]["end"] - out[0]["start"], MIN_WORD_DURATION + 1e-9)

    def test_valid_ends_unchanged(self):
        words = [_word("a", 1.0, 1.3), _word("b", 1.4, 1.9), _word("c", 2.0, 2.5)]
        out = normalize_word_timestamps(words, fallback_end=3.0)
        self.assertEqual([w["end"] for w in out], [1.3, 1.9, 2.5])
        self.assertEqual([w["start"] for w in out], [1.0, 1.4, 2.0])

    def test_multiple_consecutive_missing_ends(self):
        words = [_word("a", 1.0), _word("b", 1.2), _word("c", 1.5, 1.8)]
        out = normalize_word_timestamps(words)
        self.assertEqual(out[0]["end"], 1.2)
        self.assertEqual(out[1]["end"], 1.5)
        self.assertEqual(out[2]["end"], 1.8)

    def test_invalid_end_value_replaced(self):
        words = [_word("a", 1.0, 0.5), _word("b", 1.4, 1.8)]  # end < start
        out = normalize_word_timestamps(words)
        self.assertGreater(out[0]["end"], out[0]["start"])
        self.assertEqual(out[0]["end"], 1.4)

    def test_input_dicts_not_mutated(self):
        words = [_word("a", 1.0), _word("b", 1.3, 1.6)]
        normalize_word_timestamps(words)
        self.assertNotIn("end", words[0])

    def test_broken_words_do_not_crash(self):
        words = [{"word": "x"}, {"word": "y", "start": "abc"}, _word("z", 2.0, 2.4)]
        out = normalize_word_timestamps(words)
        self.assertEqual(len(out), 3)


class TestGroupingWithMissingEnds(unittest.TestCase):

    def test_group_end_greater_than_start(self):
        segment = {
            "start": 1.0, "end": 3.0, "text": "Hallo Welt",
            "words": [_word("Hallo", 1.0), _word("Welt", 1.5)],
        }
        groups = group_caption_segments([segment])
        for g in groups:
            self.assertGreater(g["end"], g["start"])

    def test_missing_ends_inside_group_resolved(self):
        segment = {
            "start": 1.0, "end": 2.0, "text": "a b c",
            "words": [_word("a", 1.0), _word("b", 1.2), _word("c", 1.4)],
        }
        groups = group_caption_segments([segment])
        self.assertEqual(len(groups), 1)
        # c ist letztes Word ohne end -> Segment-Ende 2.0
        self.assertEqual(groups[0]["end"], 2.0)

    def test_normal_data_unchanged(self):
        segment = {
            "start": 1.0, "end": 2.0, "text": "a b",
            "words": [_word("a", 1.0, 1.2), _word("b", 1.3, 1.9)],
        }
        groups = group_caption_segments([segment])
        self.assertEqual(groups[0]["start"], 1.0)
        self.assertEqual(groups[0]["end"], 1.9)
        self.assertEqual(groups[0]["words"][0]["end"], 1.2)


class TestAssOutput(unittest.TestCase):

    def setUp(self):
        self.renderer = CaptionRenderer(pop_enabled=True)
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _ass_path(self):
        return os.path.join(self.tmp.name, "out.ass")

    @staticmethod
    def _dialogues(path):
        with open(path, "r", encoding="utf-8-sig") as f:
            for line in f:
                if line.startswith("Dialogue:"):
                    yield line

    def test_missing_ends_produce_valid_dialogues(self):
        segments = [{
            "start": 1.0, "end": 3.0, "text": "Hallo Welt",
            "words": [_word("Hallo", 1.0), _word("Welt", 1.5)],
        }]
        path = self.renderer.generate_ass(segments, self._ass_path())
        for line in self._dialogues(path):
            m = re.match(r"Dialogue: 0,([^,]+),([^,]+),", line)
            start = _parse_ass_time(m.group(1))
            end = _parse_ass_time(m.group(2))
            self.assertGreater(end, start)

    def test_segment_with_end_le_start_clamped(self):
        segments = [{"start": 5.0, "end": 5.0, "text": "x",
                     "words": [_word("x", 5.0)]}]
        path = self.renderer.generate_ass(segments, self._ass_path())
        lines = list(self._dialogues(path))
        self.assertEqual(len(lines), 1)
        m = re.match(r"Dialogue: 0,([^,]+),([^,]+),", lines[0])
        self.assertGreater(_parse_ass_time(m.group(2)), _parse_ass_time(m.group(1)))

    def test_broken_segments_do_not_crash(self):
        segments = [
            {"text": "no times"},
            {"start": "bad", "end": 1.0, "text": "bad start"},
            {"start": 1.0, "end": 2.0, "text": "", "words": []},
            {"start": 2.0, "end": 3.0, "text": "ok", "words": [_word("ok", 2.0, 2.5)]},
        ]
        path = self.renderer.generate_ass(segments, self._ass_path())
        lines = list(self._dialogues(path))
        self.assertEqual(len(lines), 1)  # nur das gültige Segment

    def test_karaoke_durations_positive(self):
        segments = [{
            "start": 1.0, "end": 3.0, "text": "a b",
            "words": [_word("a", 1.0), _word("b", 1.0)],  # gleicher Start
        }]
        path = self.renderer.generate_ass(segments, self._ass_path())
        for line in self._dialogues(path):
            for k in re.findall(r"\\k(\d+)", line):
                self.assertGreater(int(k), 0)


class TestSrtFromGroupedSegments(unittest.TestCase):
    """SRT wird aus den gruppierten Segmenten erzeugt – Zeiten müssen gültig sein."""

    def test_grouped_segments_valid_for_srt(self):
        from subtitle_engine import SubtitleEngine
        segment = {
            "start": 1.0, "end": 3.0, "text": "Hallo Welt",
            "words": [_word("Hallo", 1.0), _word("Welt", 1.5)],
        }
        groups = group_caption_segments([segment])
        tmp = tempfile.TemporaryDirectory()
        try:
            srt_path = os.path.join(tmp.name, "out.srt")
            SubtitleEngine().generate_srt(groups, srt_path)
            nl = chr(10)
            content = open(srt_path, "r", encoding="utf-8").read().strip()
            blocks = [b for b in re.split(nl + r"\s*" + nl, content) if b.strip()]
            self.assertTrue(blocks)
            for block in blocks:
                timing = block.splitlines()[1]
                start_s, end_s = timing.split(" --> ")
                def to_sec(ts):
                    h, m, rest = ts.split(":")
                    s, ms = rest.split(",")
                    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
                self.assertGreater(to_sec(end_s), to_sec(start_s))
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()