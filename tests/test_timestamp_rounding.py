"""Fix-Block 8 (C7): Timestamp-Rundung SRT (ms) und ASS (cs).

SRT rundet mathematisch auf Millisekunden (keine Truncation mehr),
ASS rundet auf Zentisekunden mit Sekundenuebertrag (kein .99-Clamp mehr).
Beide bleiben in ihrer Aufloesung; der Roundtrip-Test begrenzt nur die
aufloesungsbedingte Differenz.
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from caption_renderer import CaptionRenderer
from subtitle_engine import SubtitleEngine

SRT_RE = re.compile(r"^(\d{2}):(\d{2}):(\d{2}),(\d{3})$")
ASS_RE = re.compile(r"^(\d+):(\d{2}):(\d{2})\.(\d{2})$")


def _parse_srt(ts: str) -> float:
    m = SRT_RE.match(ts)
    assert m is not None, f"ungueltiges SRT-Format: {ts!r}"
    h, mi, s, ms = map(int, m.groups())
    return h * 3600 + mi * 60 + s + ms / 1000.0


def _parse_ass(ts: str) -> float:
    m = ASS_RE.match(ts)
    assert m is not None, f"ungueltiges ASS-Format: {ts!r}"
    h, mi, s, cs = map(int, m.groups())
    return h * 3600 + mi * 60 + s + cs / 100.0


class TestSrtRounding(unittest.TestCase):

    def test_zero(self):
        self.assertEqual(SubtitleEngine.format_timestamp(0), "00:00:00,000")
        self.assertEqual(SubtitleEngine.format_timestamp(0.0), "00:00:00,000")

    def test_exact_milliseconds(self):
        self.assertEqual(SubtitleEngine.format_timestamp(1.234), "00:00:01,234")
        self.assertEqual(SubtitleEngine.format_timestamp(70.25), "00:01:10,250")

    def test_round_down_below_half_ms(self):
        self.assertEqual(SubtitleEngine.format_timestamp(1.2344), "00:00:01,234")

    def test_round_up_from_half_ms(self):
        self.assertEqual(SubtitleEngine.format_timestamp(1.2346), "00:00:01,235")

    def test_no_systematic_truncation_lag(self):
        # Regression C7: Truncation machte aus 1.9999 -> 01,999 (1 ms zu frueh)
        self.assertEqual(SubtitleEngine.format_timestamp(1.9999), "00:00:02,000")

    def test_millisecond_carry_to_second(self):
        self.assertEqual(SubtitleEngine.format_timestamp(59.9999), "00:01:00,000")

    def test_minute_carry_to_hour(self):
        self.assertEqual(SubtitleEngine.format_timestamp(3599.9999), "01:00:00,000")

    def test_hours_range(self):
        self.assertEqual(SubtitleEngine.format_timestamp(3723.456), "01:02:03,456")

    def test_negative_clamped(self):
        self.assertEqual(SubtitleEngine.format_timestamp(-1.0), "00:00:00,000")

    def test_invalid_input_no_crash(self):
        self.assertEqual(SubtitleEngine.format_timestamp(None), "00:00:00,000")


class TestAssRounding(unittest.TestCase):

    def test_zero(self):
        self.assertEqual(CaptionRenderer.format_ass_time(0), "0:00:00.00")

    def test_exact_centiseconds(self):
        self.assertEqual(CaptionRenderer.format_ass_time(0.01), "0:00:00.01")
        self.assertEqual(CaptionRenderer.format_ass_time(1.23), "0:00:01.23")

    def test_round_down_below_half_cs(self):
        self.assertEqual(CaptionRenderer.format_ass_time(0.014), "0:00:00.01")

    def test_round_up_from_half_cs(self):
        self.assertEqual(CaptionRenderer.format_ass_time(0.016), "0:00:00.02")

    def test_centisecond_carry_to_second(self):
        # Regression C7: alter Clamp machte aus 0.999 -> 0.99 (10 ms zu frueh)
        self.assertEqual(CaptionRenderer.format_ass_time(0.999), "0:00:01.00")
        self.assertEqual(CaptionRenderer.format_ass_time(0.995), "0:00:01.00")

    def test_no_invalid_100_cs(self):
        for v in (0.999, 1.999, 59.999, 3599.999):
            ts = CaptionRenderer.format_ass_time(v)
            self.assertNotIn(".100", ts)
            self.assertRegex(ts, r"\.\d{2}$")

    def test_second_carry_to_minute(self):
        self.assertEqual(CaptionRenderer.format_ass_time(59.999), "0:01:00.00")

    def test_minute_carry_to_hour(self):
        self.assertEqual(CaptionRenderer.format_ass_time(3599.999), "1:00:00.00")

    def test_negative_clamped(self):
        self.assertEqual(CaptionRenderer.format_ass_time(-2.5), "0:00:00.00")

    def test_invalid_input_no_crash(self):
        self.assertEqual(CaptionRenderer.format_ass_time(None), "0:00:00.00")


class TestTimestampRelation(unittest.TestCase):
    """Gleiche Zeitpunkte: SRT/ASS duerfen sich nur um die Aufloesung unterscheiden."""

    def test_resolution_bounded_difference(self):
        for t in (0.0, 0.7, 1.55, 2.345, 70.25, 600.5, 3723.456):
            srt = _parse_srt(SubtitleEngine.format_timestamp(t))
            ass = _parse_ass(CaptionRenderer.format_ass_time(t))
            self.assertLessEqual(abs(srt - ass), 0.01 + 1e-9)
            self.assertLessEqual(abs(srt - t), 0.001)
            self.assertLessEqual(abs(ass - t), 0.006)

    def test_no_truncation_lead(self):
        # Truncation waere systematisch zu frueh; Rundung liegt nah am Wert
        t = 1.9999
        srt = _parse_srt(SubtitleEngine.format_timestamp(t))
        self.assertGreaterEqual(srt, t - 0.001)
        self.assertLessEqual(srt, t + 0.001)

    def test_typical_whisper_values_valid(self):
        for t in (0.0, 0.32, 5.678, 123.456, 3600.0):
            _parse_srt(SubtitleEngine.format_timestamp(t))
            _parse_ass(CaptionRenderer.format_ass_time(t))


if __name__ == "__main__":
    unittest.main()
