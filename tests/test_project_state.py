"""Fix-Block 24: Projektdatei-Core (Tk-frei).

1. serialize/deserialize roundtrip
2. save/load roundtrip
3. Unicode
4. word timestamps
5. style roundtrip
6. ordering
7. malformed JSON
8. unsupported schema
9. missing required fields
10. unknown fields
11. missing video
12. moved video
13. empty transcript
+ Sonderzeichen, Segment ohne words, ungültige Segmente, Teilsytyle,
  Determinismus, kein .tmp-Rest.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capti_core.project_state import (
    PROJECT_EXTENSION,
    ProjectFileError,
    ProjectState,
    deserialize,
    load_project,
    save_project,
    serialize,
)


def _segments():
    return [
        {"start": 5.0, "end": 7.0, "text": "Hello \"beautiful\" world\nhier",
         "words": [{"word": "Hello", "start": 5.0, "end": 5.8},
                   {"word": "\"beautiful\"", "start": 5.8, "end": 5.9},
                   {"word": "world\nhier", "start": 5.9, "end": 7.0}]},
        {"start": 8.0, "end": 10.0, "text": "Grüße aus München – 100 %",
         "words": [{"word": "Grüße", "start": 8.0, "end": 8.6},
                   {"word": "aus", "start": 8.7, "end": 9.0},
                   {"word": "München", "start": 9.1, "end": 9.5},
                   {"word": "–", "start": 9.5, "end": 9.7},
                   {"word": "100", "start": 9.7, "end": 9.9},
                   {"word": "%", "start": 9.9, "end": 10.0}]},
    ]


def _state():
    return ProjectState(
        video_path="C:/vids/clip A (1).mp4",
        model="tiny",
        language="de",
        caption_style={"pop_scale": 140, "normal_color": "#FFFFFF",
                       "custom_key": "bleibt"},
        segments=_segments(),
    )


def _tmp(testcase):
    tmp = Path(tempfile.mkdtemp(prefix="capti_ps24_"))
    testcase.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
    return tmp


class TestRoundtrip(unittest.TestCase):
    """1/2/3/4/5/6) Roundtrips."""

    def test_serialize_deserialize(self):
        clone = deserialize(serialize(_state()))
        self.assertEqual(clone.video_path, "C:/vids/clip A (1).mp4")
        self.assertEqual(clone.model, "tiny")
        self.assertEqual(clone.language, "de")
        self.assertEqual(clone.segments, _segments())          # 4/6
        self.assertEqual(clone.caption_style["pop_scale"], 140)  # 5

    def test_save_load_roundtrip(self):
        tmp = _tmp(self)
        path = tmp / ("clip" + PROJECT_EXTENSION)
        saved = save_project(path, _state())
        self.assertEqual(saved, str(path))
        self.assertTrue(path.exists())
        self.assertFalse((tmp / ("clip" + PROJECT_EXTENSION + ".tmp")).exists())
        loaded = load_project(path)
        self.assertEqual(loaded.segments, _segments())
        self.assertEqual(loaded.caption_style, _state().caption_style)
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(raw["schema_version"], 1)

    def test_deterministic_bytes(self):
        tmp = _tmp(self)
        a, b = tmp / "a.json", tmp / "b.json"
        save_project(a, _state())
        save_project(b, _state())
        self.assertEqual(a.read_bytes(), b.read_bytes())

    def test_unicode_and_special_chars(self):
        """3) Umlaute/Sonderzeichen/Quotes/Newlines bleiben exakt."""
        tmp = _tmp(self)
        path = tmp / "u.json"
        save_project(path, _state())
        loaded = load_project(path)
        self.assertEqual(loaded.segments[1]["text"], "Grüße aus München – 100 %")
        self.assertIn("\"beautiful\"", loaded.segments[0]["words"][1]["word"])


class TestValidation(unittest.TestCase):
    """7/8/9/10) Fehlerfälle + Toleranz."""

    def _write(self, tmp, name, text):
        path = tmp / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_missing_file(self):
        with self.assertRaises(ProjectFileError):
            load_project("/definitiv/nicht/da.json")

    def test_malformed_json(self):
        """7) Kaputtes JSON -> klarer Fehler, kein Crash."""
        tmp = _tmp(self)
        path = self._write(tmp, "x.json", "{kein json,,,")
        with self.assertRaises(ProjectFileError):
            load_project(path)

    def test_unsupported_schema(self):
        """8) Unbekannte/fehlende schema_version -> Fehler."""
        for version in (0, 2, 99, "1", None):
            with self.assertRaises(ProjectFileError, msg=f"v={version}"):
                deserialize({"schema_version": version, "segments": []})

    def test_missing_required_fields(self):
        """9) segments fehlt / keine Liste -> Fehler."""
        with self.assertRaises(ProjectFileError):
            deserialize({"schema_version": 1})
        with self.assertRaises(ProjectFileError):
            deserialize({"schema_version": 1, "segments": "nonsense"})
        with self.assertRaises(ProjectFileError):
            deserialize(["kein", "dict"])

    def test_unknown_fields_ignored(self):
        """10) Zukünftige Felder (top/segment/word) werden ignoriert."""
        raw = {"schema_version": 1, "segments": [],
               "future_top": {"x": [1, 2]}, "video_path": "v.mp4"}
        state = deserialize(raw)
        self.assertEqual(state.video_path, "v.mp4")
        raw2 = {"schema_version": 1, "segments": [
            {"start": 1.0, "end": 2.0, "text": "hi",
             "future_seg": 1,
             "words": [{"word": "hi", "start": 1.0, "end": 2.0,
                        "future_word": []}]}]}
        state2 = deserialize(raw2)
        self.assertEqual(state2.segments[0]["words"],
                         [{"word": "hi", "start": 1.0, "end": 2.0}])

    def test_empty_transcript(self):
        """13) Leere Segmente sind gültig (Sample-Modus)."""
        state = deserialize({"schema_version": 1, "segments": []})
        self.assertEqual(state.segments, [])

    def test_segment_without_words(self):
        seg = deserialize({"schema_version": 1, "segments": [
            {"start": 1.0, "end": 2.0, "text": "nur text"}]}).segments[0]
        self.assertEqual(seg["words"], [])
        self.assertEqual(seg["text"], "nur text")

    def test_invalid_segments_skipped(self):
        raw = {"schema_version": 1, "segments": [
            {"start": 5.0, "end": 7.0, "text": "ok",
             "words": [{"word": "ok", "start": 5.0, "end": 7.0}]},
            {"start": 9.0, "end": 8.0, "text": "verkehrt"},
            {"text": "ohne Zeiten"},
            "kein dict",
            {"start": -1.0, "end": 2.0, "text": "negativ"},
        ]}
        state = deserialize(raw)
        self.assertEqual([s["text"] for s in state.segments], ["ok"])

    def test_partial_style(self):
        style = deserialize({"schema_version": 1, "segments": [],
                             "caption_style": {"pop_scale": 140,
                                               "nested": {"a": 1},
                                               "lst": [1]}}).caption_style
        self.assertEqual(style, {"pop_scale": 140})
        self.assertEqual(
            deserialize({"schema_version": 1, "segments": [],
                         "caption_style": "kaputt"}).caption_style, {})

    def test_bad_model_falls_back(self):
        state = deserialize({"schema_version": 1, "segments": [],
                             "model": "xxl"})
        self.assertEqual(state.model, "small")


class TestVideoPresence(unittest.TestCase):
    """11/12) Fehlendes/verschobenes Video löscht nichts."""

    def test_missing_video_keeps_state(self):
        state = deserialize({"schema_version": 1,
                             "video_path": "/nirgendwo/clip.mp4",
                             "segments": _segments()[:1]})
        self.assertFalse(state.video_exists())
        self.assertEqual(len(state.segments), 1)

    def test_moved_video_keeps_state(self):
        tmp = _tmp(self)
        path = tmp / "p.json"
        save_project(path, ProjectState(
            video_path=str(tmp / "weg.mp4"), segments=_segments()[:1]))
        loaded = load_project(path)
        self.assertFalse(loaded.video_exists())
        self.assertEqual(loaded.segments[0]["text"],
                         "Hello \"beautiful\" world\nhier")

    def test_existing_video(self):
        tmp = _tmp(self)
        video = tmp / "clip.mp4"
        video.write_bytes(b"x")
        state = ProjectState(video_path=str(video))
        self.assertTrue(state.video_exists())


if __name__ == "__main__":
    unittest.main()
