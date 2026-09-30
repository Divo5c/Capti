"""Fix-Block 2: Frozen-Assets (B3) + portable ffprobe-Aufloesung (A3).

B3: ui/fonts.py muss gebuendelte Fonts im Frozen-Modus unter
    sys._MEIPASS/assets/fonts finden (Capti.spec Datas).
A3: video_processor.resolve_ffprobe_exe() muss portabel aufloesen
    (Env -> Frozen -> third_party -> imageio-Sibling -> PATH -> None)
    und get_video_info() muss damit echte Breite/Hoehe liefern,
    ohne System-ffprobe vorauszusetzen.
"""

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui.fonts import FONT_ROLES, FontManager, _assets_dir
from video_processor import VideoProcessor, resolve_ffprobe_exe

REPO_ROOT = Path(__file__).resolve().parent.parent


def _make_tmpdir(testcase):
    tmp = tempfile.mkdtemp(prefix="capti_frozen_")
    testcase.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
    return Path(tmp)


class TestFrozenFontAssets(unittest.TestCase):

    def test_all_role_fonts_exist_in_repo(self):
        """Alle 4 Rollen-Fonts liegen exakt in assets/fonts/ (nicht mehr, nicht weniger)."""
        fonts_dir = REPO_ROOT / "assets" / "fonts"
        for role, info in FONT_ROLES.items():
            with self.subTest(role=role):
                self.assertTrue((fonts_dir / info["file"]).is_file(),
                                f"Font fehlt: assets/fonts/{info['file']}")
        bundled = sorted(p.name for p in fonts_dir.iterdir() if p.is_file())
        expected = sorted(info["file"] for info in FONT_ROLES.values())
        self.assertEqual(bundled, expected)

    def test_dev_assets_dir_is_repo(self):
        """Development: _assets_dir() zeigt auf Repo-assets/fonts (kein _MEIPASS)."""
        had = hasattr(sys, "_MEIPASS")
        old = getattr(sys, "_MEIPASS", None)
        if had:
            delattr(sys, "_MEIPASS")
        self.addCleanup(lambda: setattr(sys, "_MEIPASS", old) if had else None)
        self.assertEqual(_assets_dir(), REPO_ROOT / "assets" / "fonts")

    def test_frozen_assets_dir_resolution(self):
        """Frozen: _assets_dir() nutzt sys._MEIPASS/assets/fonts."""
        tmp = _make_tmpdir(self)
        (tmp / "assets" / "fonts").mkdir(parents=True)
        (tmp / "assets" / "fonts" / "Nevera-Regular.otf").write_bytes(b"fakefont")
        old = getattr(sys, "_MEIPASS", None)
        had = hasattr(sys, "_MEIPASS")
        sys._MEIPASS = str(tmp)
        self.addCleanup(lambda: (setattr(sys, "_MEIPASS", old) if had else delattr(sys, "_MEIPASS")))
        self.assertEqual(_assets_dir(), tmp / "assets" / "fonts")
        self.assertTrue((_assets_dir() / "Nevera-Regular.otf").is_file())

    def test_fontmanager_fallback_without_crash(self):
        """Leeres Font-Verzeichnis -> Fallbacks, kein Crash (Linux: kein GDI)."""
        tmp = _make_tmpdir(self)
        FontManager.reset()
        self.addCleanup(FontManager.reset)
        ok = FontManager.initialize(assets_dir=tmp)
        self.assertTrue(ok)
        for role, info in FONT_ROLES.items():
            self.assertEqual(FontManager.get_family(role), info["fallback"])


class TestFfprobeResolution(unittest.TestCase):

    def test_env_override_wins(self):
        tmp = _make_tmpdir(self)
        fake = tmp / "myffprobe"
        fake.write_bytes(b"x")
        with mock.patch.dict(os.environ, {"CAPTI_FFPROBE": str(fake)}):
            self.assertEqual(resolve_ffprobe_exe(), str(fake))

    def test_env_override_missing_falls_through(self):
        tmp = _make_tmpdir(self)
        with mock.patch.dict(os.environ, {"CAPTI_FFPROBE": str(tmp / "nope"),
                                           "PATH": str(tmp)}):
            # kein third_party im Repo-Tmp, kein PATH-ffprobe -> None
            self.assertIsNone(resolve_ffprobe_exe(project_root=tmp))

    def test_frozen_meipass_resolution(self):
        tmp = _make_tmpdir(self)
        exe = tmp / "ffprobe.exe"
        exe.write_bytes(b"MZ")
        old_frozen = getattr(sys, "frozen", None)
        had_frozen = hasattr(sys, "frozen")
        old_meipass = getattr(sys, "_MEIPASS", None)
        had_meipass = hasattr(sys, "_MEIPASS")
        sys.frozen = True
        sys._MEIPASS = str(tmp)
        def _restore():
            if had_frozen:
                sys.frozen = old_frozen
            else:
                delattr(sys, "frozen")
            if had_meipass:
                sys._MEIPASS = old_meipass
            else:
                delattr(sys, "_MEIPASS")
        self.addCleanup(_restore)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CAPTI_FFPROBE", None)
            self.assertEqual(resolve_ffprobe_exe(), str(exe))

    def test_dev_third_party_resolution(self):
        tmp = _make_tmpdir(self)
        exe = tmp / "third_party" / "ffprobe" / "ffprobe.exe"
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"MZ")
        with mock.patch.dict(os.environ, {"PATH": str(tmp), "CAPTI_FFPROBE": ""}):
            os.environ.pop("CAPTI_FFPROBE", None)
            self.assertEqual(resolve_ffprobe_exe(project_root=tmp), str(exe))

    def test_none_when_absent(self):
        tmp = _make_tmpdir(self)
        with mock.patch.dict(os.environ, {"PATH": str(tmp)}):
            os.environ.pop("CAPTI_FFPROBE", None)
            # imageio-Sibling enthaelt kein ffprobe (verifiziert) -> None
            self.assertIsNone(resolve_ffprobe_exe(project_root=tmp))


def _write_fake_ffprobe(path: Path, width: int, height: int):
    """Schreibt ein ausfuehrbares Fake-ffprobe (JSON wie ffprobe -show_streams)."""
    script = (
        "#!/bin/sh\n"
        f'echo \'{{"streams": [{{"width": {width}, "height": {height}, '
        f'"codec_type": "video"}}], "format": {{"duration": "10.0"}}}}\'\n'
    )
    path.write_text(script, encoding="utf-8", newline="\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class TestGetVideoInfoPortable(unittest.TestCase):

    def _video(self, tmp: Path) -> str:
        vid = tmp / "clip.mp4"
        vid.write_bytes(b"fakevideo")
        return str(vid)

    def _processor(self) -> VideoProcessor:
        """VideoProcessor ohne ffmpeg-Check (B2-Attribute wie __init__ setzen)."""
        import threading
        vp = VideoProcessor.__new__(VideoProcessor)
        vp.ffmpeg_path = "ffmpeg"
        vp._cancel_event = None
        vp._current_process = None
        vp._proc_lock = threading.Lock()
        return vp

    def test_portrait_9_16_width_height(self):
        tmp = _make_tmpdir(self)
        fake = tmp / "ffprobe"
        _write_fake_ffprobe(fake, 1080, 1920)
        with mock.patch.dict(os.environ, {"CAPTI_FFPROBE": str(fake)}):
            vp = self._processor()
            info = vp.get_video_info(self._video(tmp))
        streams = [s for s in info.get("streams", []) if s.get("width")]
        self.assertTrue(streams)
        self.assertEqual(int(streams[0]["width"]), 1080)
        self.assertEqual(int(streams[0]["height"]), 1920)

    def test_landscape_16_9_width_height(self):
        tmp = _make_tmpdir(self)
        fake = tmp / "ffprobe"
        _write_fake_ffprobe(fake, 1920, 1080)
        with mock.patch.dict(os.environ, {"CAPTI_FFPROBE": str(fake)}):
            vp = self._processor()
            info = vp.get_video_info(self._video(tmp))
        streams = [s for s in info.get("streams", []) if s.get("width")]
        self.assertTrue(streams)
        self.assertEqual(int(streams[0]["width"]), 1920)
        self.assertEqual(int(streams[0]["height"]), 1080)

    def test_missing_binary_returns_empty_without_crash(self):
        """Ohne gebuendeltes und ohne System-ffprobe: {} statt Crash."""
        tmp = _make_tmpdir(self)
        vid = self._video(tmp)
        with mock.patch.dict(os.environ, {"PATH": str(tmp)}):
            os.environ.pop("CAPTI_FFPROBE", None)
            vp = self._processor()
            self.assertEqual(vp.get_video_info(vid), {})


if __name__ == "__main__":
    unittest.main()
