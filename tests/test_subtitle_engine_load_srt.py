"""Regressionstests Fix-Block 1 (A1/A2): SubtitleEngine.load_srt.

Prueft den SRT-Edit-Flow der Pipeline (pipeline.py: Untertitel bearbeiten,
danach Segmente aus bearbeiteter SRT neu laden):
- Blocknummern duerfen NIEMALS in die Zeit uebernommen werden
  (Regression: groups()[0:8] machte aus Block 2 -> 2 Stunden).
- Start-/Endzeiten exakt, Umlaute/Sonderzeichen, mehrzeilige Captions.
- Geladene Daten sind direkt im Edit-Flow verwendbar (start/end/text, words=[]).
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle_engine import SubtitleEngine


def _engine_without_model():
    """SubtitleEngine ohne Whisper-Modell (generate_srt braucht keins)."""
    eng = SubtitleEngine.__new__(SubtitleEngine)
    eng.model_size = "small"
    eng.device = "cpu"
    eng.compute_type = "int8"
    eng.model = None
    return eng


def _write_tmp_srt(testcase, content: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".srt")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    testcase.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
    return path


class TestLoadSrtTimings(unittest.TestCase):

    def test_multiple_blocks_exact_times(self):
        path = _write_tmp_srt(self,
            "1\n00:00:01,000 --> 00:00:02,500\nHallo Welt\n\n"
            "2\n00:01:10,250 --> 00:01:12,000\nZweiter Block\n\n"
            "3\n01:02:03,456 --> 01:02:05,000\nDritter Block\n")
        segs = SubtitleEngine.load_srt(path)
        self.assertEqual(len(segs), 3)
        self.assertAlmostEqual(segs[0]["start"], 1.0)
        self.assertAlmostEqual(segs[0]["end"], 2.5)
        self.assertAlmostEqual(segs[1]["start"], 70.25)
        self.assertAlmostEqual(segs[1]["end"], 72.0)
        self.assertAlmostEqual(segs[2]["start"], 3723.456)
        self.assertAlmostEqual(segs[2]["end"], 3725.0)
        self.assertEqual(segs[0]["text"], "Hallo Welt")

    def test_block_index_not_used_as_hour(self):
        # Regression A2: Block "2" begann faelschlicherweise bei 2 Stunden.
        path = _write_tmp_srt(self,
            "1\n00:00:00,500 --> 00:00:01,500\nEins\n\n"
            "2\n00:00:05,000 --> 00:00:06,000\nZwei\n")
        segs = SubtitleEngine.load_srt(path)
        self.assertEqual(len(segs), 2)
        self.assertAlmostEqual(segs[1]["start"], 5.0)
        self.assertAlmostEqual(segs[1]["end"], 6.0)
        self.assertLess(segs[1]["start"], 3600.0)
        self.assertLess(segs[1]["end"], 3600.0)

    def test_umlauts_special_chars(self):
        path = _write_tmp_srt(self,
            "1\n00:00:00,000 --> 00:00:02,000\nGrüße äöü ß € & <tag>\n")
        segs = SubtitleEngine.load_srt(path)
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0]["text"], "Grüße äöü ß € & <tag>")

    def test_multiline_caption_joined(self):
        path = _write_tmp_srt(self,
            "1\n00:00:01,000 --> 00:00:03,000\nErste Zeile\nZweite Zeile\n")
        segs = SubtitleEngine.load_srt(path)
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0]["text"], "Erste Zeile Zweite Zeile")

    def test_malformed_blocks_skipped_no_crash(self):
        path = _write_tmp_srt(self,
            "kein srt inhalt\n\n"
            "1\n00:00:01,000 --> 00:00:02,000\nOk\n\n"
            "2\nkaputte zeitzeile\nText\n")
        segs = SubtitleEngine.load_srt(path)
        self.assertEqual(len(segs), 1)
        self.assertAlmostEqual(segs[0]["start"], 1.0)

    def test_no_word_timestamps_invented(self):
        path = _write_tmp_srt(self,
            "1\n00:00:01,000 --> 00:00:02,000\nText\n")
        segs = SubtitleEngine.load_srt(path)
        self.assertEqual(segs[0]["words"], [])


class TestLoadSrtEditFlow(unittest.TestCase):
    """Der Pipeline-Edit-Flow: generate -> extern bearbeiten -> load."""

    def test_generate_load_roundtrip(self):
        eng = _engine_without_model()
        segments = [
            {"start": 0.5, "end": 2.25, "text": "Hallo schöne Welt", "words": []},
            {"start": 70.25, "end": 72.0, "text": "Zweite Zeile hier", "words": []},
        ]
        fd, path = tempfile.mkstemp(suffix=".srt")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        eng.generate_srt(segments, path)
        loaded = SubtitleEngine.load_srt(path)
        self.assertEqual(len(loaded), 2)
        for orig, back in zip(segments, loaded):
            self.assertAlmostEqual(back["start"], orig["start"], places=2)
            self.assertAlmostEqual(back["end"], orig["end"], places=2)
            self.assertEqual(back["text"], orig["text"])
            self.assertEqual(back["words"], [])

    def test_edited_text_keeps_original_times(self):
        # Simuliert pipeline.py: SRT lesen -> Text aendern -> zurueckschreiben -> load
        eng = _engine_without_model()
        segments = [{"start": 1.0, "end": 2.5, "text": "Original Text", "words": []}]
        fd, path = tempfile.mkstemp(suffix=".srt")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        eng.generate_srt(segments, path)
        with open(path, "r", encoding="utf-8") as f:
            original_content = f.read()
        edited = original_content.replace("Original Text", "Bearbeiteter Grüße-Text")
        self.assertNotEqual(edited, original_content)
        with open(path, "w", encoding="utf-8") as f:
            f.write(edited)
        loaded = SubtitleEngine.load_srt(path)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["text"], "Bearbeiteter Grüße-Text")
        self.assertAlmostEqual(loaded[0]["start"], 1.0)
        self.assertAlmostEqual(loaded[0]["end"], 2.5)


class _FakeWhisperModel:
    """Minimaler Fake für faster-whisper (kein Modell-Download)."""

    def __init__(self, segments, info):
        self._segments = segments
        self._info = info

    def transcribe(self, audio_path, **kwargs):
        return iter(self._segments), self._info


class TestTranscribeAndGenerateSrt(unittest.TestCase):
    """Block 12 (B): transcribe_and_generate_srt als öffentlicher
    Convenience-Einstieg – transkribiert und schreibt SRT in einem Schritt."""

    def _engine_with_fake_model(self):
        from types import SimpleNamespace

        def _word(text, start, end):
            return SimpleNamespace(word=text, start=start, end=end,
                                   probability=0.99)

        segments = [
            SimpleNamespace(
                start=0.0, end=1.5, text="Hallo Welt",
                words=[_word("Hallo", 0.0, 0.7), _word("Welt", 0.8, 1.5)]),
        ]
        info = SimpleNamespace(language="de")
        eng = SubtitleEngine.__new__(SubtitleEngine)
        eng.model_size = "tiny"
        eng.device = "cpu"
        eng.compute_type = "int8"
        eng.model = _FakeWhisperModel(segments, info)
        return eng

    def test_transcribe_and_generate_srt_writes_file(self):
        eng = self._engine_with_fake_model()
        fd, wav_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(wav_path) and os.unlink(wav_path))
        srt_path = wav_path.replace(".wav", ".srt")
        self.addCleanup(lambda: os.path.exists(srt_path) and os.unlink(srt_path))
        result = eng.transcribe_and_generate_srt(wav_path, srt_path, language="de")
        self.assertEqual(result, srt_path)
        with open(srt_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Hallo Welt", content)
        self.assertIn("-->", content)
        # Rücklesbar über load_srt (Edit-Flow-kompatibel)
        loaded = SubtitleEngine.load_srt(srt_path)
        self.assertEqual(len(loaded), 1)
        self.assertAlmostEqual(loaded[0]["start"], 0.0)
        self.assertAlmostEqual(loaded[0]["end"], 1.5)


if __name__ == "__main__":
    unittest.main()
