"""
Regressionstests Phase 18: Drag & Drop (Logik getrennt von der OS-Eventquelle).
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Hermetisch: echte Nutzer-Config niemals lesen/schreiben (Phase 30)
import tempfile as _tmp
if "CAPTI_CONFIG_FILE" not in os.environ:
    os.environ["APPDATA"] = _tmp.mkdtemp(prefix="capti_test_appdata_")

from ui.dnd import is_valid_video, parse_dropped_files, pick_first_video


class FakeEvent:
    def __init__(self, data):
        self.data = data


class TestDndLogic(unittest.TestCase):
    """DnD-Logik ohne OS-Drag-Eventquelle (tk.splitlist gemockt)."""

    def test_valid_video_accepted(self):
        video, err = pick_first_video([r"C:\vids\clip.mp4"])
        self.assertEqual(video, r"C:\vids\clip.mp4")
        self.assertIsNone(err)

    def test_invalid_file_rejected(self):
        video, err = pick_first_video([r"C:\docs\notes.txt"])
        self.assertIsNone(video)
        self.assertIn("Ungültig", err)

    def test_multiple_files_first_valid_wins(self):
        files = [r"C:\a\readme.txt", r"C:\b\movie.mkv", r"C:\c\other.mp4"]
        video, err = pick_first_video(files)
        self.assertEqual(video, r"C:\b\movie.mkv")
        self.assertIsNone(err)

    def test_empty_drop_no_crash(self):
        video, err = pick_first_video([])
        self.assertIsNone(video)
        self.assertTrue(err)

    def test_parse_dropped_files_uses_splitlist(self):
        widget = MagicMock()
        widget.tk.splitlist.return_value = ("C:\\x\\a.mp4", "C:\\x\\b.txt")
        result = parse_dropped_files(widget, "{C:\\x\\a.mp4} {C:\\x\\b.txt}")
        self.assertEqual(result, ["C:\\x\\a.mp4", "C:\\x\\b.txt"])

    def test_parse_dropped_files_bad_data_no_crash(self):
        widget = MagicMock()
        widget.tk.splitlist.side_effect = Exception("bad")
        self.assertEqual(parse_dropped_files(widget, "???"), [])

    def test_is_valid_video_extensions(self):
        for ext in (".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv", ".m4v"):
            self.assertTrue(is_valid_video(f"x{ext}".upper()))
        self.assertFalse(is_valid_video("x.gif"))
        self.assertFalse(is_valid_video("noext"))


class TestNewProjectDropHandler(unittest.TestCase):
    """Drop-Handler des Screens mit simuliertem Drop-Event."""

    def _make_screen(self):
        from ui.screens.new_project import NewProjectScreen
        screen = NewProjectScreen.__new__(NewProjectScreen)
        screen.file_label = MagicMock()
        screen.warning_label = MagicMock()
        return screen

    def test_on_drop_sets_video(self):
        screen = self._make_screen()
        with patch("ui.screens.new_project.parse_dropped_files",
                   return_value=[r"C:\v\clip.mp4"]):
            screen._on_drop(FakeEvent("{C:\\v\\clip.mp4}"))
        self.assertEqual(screen.video_path, r"C:\v\clip.mp4")
        screen.file_label.configure.assert_called_once()
        screen.warning_label.configure.assert_called_with(text="")

    def test_on_drop_invalid_shows_warning(self):
        screen = self._make_screen()
        with patch("ui.screens.new_project.parse_dropped_files",
                   return_value=[r"C:\x\file.exe"]):
            screen._on_drop(FakeEvent("data"))
        self.assertFalse(hasattr(screen, "video_path"))
        args = screen.warning_label.configure.call_args
        self.assertIn("Ungültig", args.kwargs["text"])

    def test_drag_feedback_toggle(self):
        screen = self._make_screen()
        screen.drop_card = MagicMock()
        screen.theme = {"accent": "#ffd60a", "border": "#3a3a3a",
                        "surface": "#242424", "surface_secondary": "#2e2e2e"}
        screen.color = lambda token: screen.theme.get(token, "#ffffff")
        screen._on_drag_enter()
        cfg = screen.drop_card.configure.call_args.kwargs
        self.assertEqual(cfg["border_color"], "#ffd60a")
        screen.drop_card.reset_mock()
        screen._on_drag_leave()
        cfg = screen.drop_card.configure.call_args.kwargs
        self.assertEqual(cfg["border_color"], "#3a3a3a")
        self.assertEqual(cfg["fg_color"], "#242424")


class TestDndAllThemes(unittest.TestCase):
    """Drag-Feedback-Farben existieren in allen drei Themes."""

    def test_theme_tokens_present(self):
        from ui.theme import THEMES
        for name in ("dark", "light", "yellow"):
            theme = THEMES[name]
            for token in ("accent", "border", "surface", "surface_secondary"):
                self.assertIn(token, theme)


if __name__ == "__main__":
    unittest.main()

