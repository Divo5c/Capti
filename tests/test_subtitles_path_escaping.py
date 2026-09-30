"""Fix-Block 5 (C5): SRT/ASS-Pfad-Escaping an der ffmpeg-Filtergrenze.

escape_filter_path() escapet exakt: Backslash->Slash, ':'->'\\:', "'"->"\\'".
Leerzeichen, ()[];, Unicode etc. sind innerhalb subtitles='...' literal.
Zusaetzlich: Die echte -vf-Argumentebene wird mit gemocktem Popen geprueft.
"""

import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from video_processor import VideoProcessor, escape_filter_path


class TestEscapeFilterPath(unittest.TestCase):

    def test_normal_path(self):
        self.assertEqual(
            escape_filter_path("C:/videos/clip.ass"),
            "C\\:/videos/clip.ass")

    def test_spaces(self):
        self.assertEqual(
            escape_filter_path("C:/meine videos/clip one.ass"),
            "C\\:/meine videos/clip one.ass")

    def test_parentheses(self):
        self.assertEqual(
            escape_filter_path("C:/vids/clip (2024).ass"),
            "C\\:/vids/clip (2024).ass")

    def test_brackets(self):
        self.assertEqual(
            escape_filter_path("C:/vids/clip [final].ass"),
            "C\\:/vids/clip [final].ass")

    def test_apostrophe(self):
        self.assertEqual(
            escape_filter_path("C:/vids/Bob's clip.ass"),
            "C\\:/vids/Bob\\'s clip.ass")

    def test_semicolon(self):
        self.assertEqual(
            escape_filter_path("C:/vids/a;b.ass"),
            "C\\:/vids/a;b.ass")

    def test_colon(self):
        self.assertEqual(
            escape_filter_path("D:/x/y.ass"),
            "D\\:/x/y.ass")

    def test_backslashes_windows(self):
        self.assertEqual(
            escape_filter_path("C:\\Users\\x\\clip.ass"),
            "C\\:/Users/x/clip.ass")

    def test_unicode_umlauts(self):
        self.assertEqual(
            escape_filter_path("C:/Videos/Grüße äöü ß €.ass"),
            "C\\:/Videos/Grüße äöü ß €.ass")

    def test_combination(self):
        self.assertEqual(
            escape_filter_path("D:\\Bob's (2024) [final]; v2 äöü.srt"),
            "D\\:/Bob\\'s (2024) [final]; v2 äöü.srt")


class _OkPopen:
    """Gemocktes Popen: sofortiger Erfolg, zeichnet argv auf, erzeugt Output."""

    def __init__(self, *args, **kwargs):
        self.cmd = args[0] if args else kwargs.get("args")
        self.returncode = 0
        # Echte embed_ass-Validierung verlangt eine vorhandene Output-Datei
        try:
            Path(self.cmd[-1]).write_bytes(b"fake-mp4")
        except Exception:
            pass

    def poll(self):
        return 0

    def communicate(self, timeout=None):
        return ("", "")

    def terminate(self):
        pass

    def kill(self):
        pass


def _processor():
    vp = VideoProcessor.__new__(VideoProcessor)
    vp.ffmpeg_path = "ffmpeg"
    vp._cancel_event = None
    vp._current_process = None
    vp._proc_lock = threading.Lock()
    return vp


class TestVfArgumentLevel(unittest.TestCase):

    def _run_embed(self, tmp: Path, name: str):
        video = tmp / "clip.mp4"
        video.write_bytes(b"x")
        ass = tmp / name
        ass.write_text("[Script Info]", encoding="utf-8")
        out = tmp / "out.mp4"
        with patch("video_processor.subprocess.Popen",
                   side_effect=lambda *a, **k: _OkPopen(*a, **k)) as mocked:
            vp = _processor()
            result = vp.embed_ass(str(video), str(ass), str(out))
        self.assertEqual(result, str(out))
        vf = mocked.call_args[0][0]
        idx = vf.index("-vf")
        return vf[idx + 1]

    def test_vf_contains_escaped_ass(self):
        tmp = Path(tempfile.mkdtemp(prefix="capti_esc_"))
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        vf = self._run_embed(tmp, "Bob's (2024).ass")
        self.assertTrue(vf.startswith("subtitles='"), vf)
        self.assertIn("Bob\\'s (2024).ass", vf)
        # keine rohen Backslashes mehr im Filter-String
        self.assertNotIn("\\", vf.replace("\\:", "").replace("\\'", ""))

    def test_vf_windows_drive_escaped(self):
        # Simuliert Windows-Pfad auch auf Linux (reine String-Ebene)
        escaped = escape_filter_path("C:\\Vids\\a;b [x].srt")
        self.assertEqual(escaped, "C\\:/Vids/a;b [x].srt")
        vf_value = f"subtitles='{escaped}'"
        self.assertIn("C\\:/Vids/a;b [x].srt", vf_value)


if __name__ == "__main__":
    unittest.main()
