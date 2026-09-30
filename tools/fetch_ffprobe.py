"""Build-time Bezug eines portablen Windows-ffprobe.exe (A3).

Quelle (geprueft 2026-09-14):
  URL:     https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip
  Version: 9.0.1 (siehe .ver-Datei, "9.0.1")
  SHA256:  fec81ae03971d9dd4be3ebe02e263bd2ec1d789483f931bdba5f5715e65da2e9
           (stimmt mit .../ffmpeg-release-essentials.zip.sha256 ueberein)
  Inhalt:  ffmpeg-9.0.1-essentials_build/bin/ffprobe.exe (102652416 Bytes, MZ ok)
  Lizenz:  GPL (Binary enthaelt GPL-Hinweise; wie das bereits gebuendelte
           imageio-ffmpeg-ffmpeg – keine neue Lizenzlage, aber dokumentiert).
  Warum Gyan: stabile URL, publizierte .sha256/.ver, enthaelt ffprobe.exe.
  Alternative: BtbN FFmpeg-Builds (Rolling-Namen, daher nicht gepinnt).

Ablauf: ZIP laden -> SHA256 pruefen -> NUR bin/ffprobe.exe nach
  third_party/ffprobe/ffprobe.exe extrahieren (+ SOURCE.txt mit Provenienz).
  third_party/ ist gitignored – das ~100-MB-Binary landet NIE im Repo.
  Capti.spec buendelt es (falls vorhanden), sonst warnt der Build und die
  App faellt zur Laufzeit auf System-ffprobe zurueck.

Aufruf:  uv run python tools/fetch_ffprobe.py [--force]
Nur Stdlib (urllib/hashlib/zipfile) – keine neuen Dependencies.
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
import zipfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEST_DIR = PROJECT_DIR / "third_party" / "ffprobe"
DEST_EXE = DEST_DIR / "ffprobe.exe"
SOURCE_TXT = DEST_DIR / "SOURCE.txt"

FFPROBE_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
FFPROBE_SHA256 = "fec81ae03971d9dd4be3ebe02e263bd2ec1d789483f931bdba5f5715e65da2e9"
FFPROBE_VERSION = "9.0.1"
FFPROBE_ZIP_MEMBER = "ffmpeg-9.0.1-essentials_build/bin/ffprobe.exe"
MIN_EXE_SIZE = 10 * 1024 * 1024  # unvollstaendige Downloads abfangen


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _exe_looks_valid(path: Path) -> bool:
    """Plausibilitaet: vorhanden, gross genug, MZ-Header (Windows-PE)."""
    try:
        if not path.is_file() or path.stat().st_size < MIN_EXE_SIZE:
            return False
        with open(path, "rb") as f:
            return f.read(2) == b"MZ"
    except OSError:
        return False


def fetch_ffprobe(force: bool = False) -> Path:
    """Laedt/entpackt ffprobe.exe bei Bedarf; gibt den Pfad zurueck."""
    if DEST_EXE.exists() and not force:
        if _exe_looks_valid(DEST_EXE):
            print(f"ffprobe bereits vorhanden: {DEST_EXE}")
            return DEST_EXE
        print(f"ffprobe ungueltig ({DEST_EXE.stat().st_size} Bytes) – lade neu ...")
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    tmp_zip = DEST_DIR / "_download.zip"
    print(f"Lade {FFPROBE_URL} ... (~110 MB)")
    urllib.request.urlretrieve(FFPROBE_URL, tmp_zip)
    try:
        digest = _sha256_file(tmp_zip)
        if digest != FFPROBE_SHA256:
            raise RuntimeError(
                f"SHA256 mismatch: erwartet {FFPROBE_SHA256}, erhalten {digest} "
                "(Upstream hat das Rolling-Archiv aktualisiert – URL/Hash in "
                "tools/fetch_ffprobe.py aktualisieren)")
        print("SHA256 ok.")
        with zipfile.ZipFile(tmp_zip) as zf:
            try:
                member = zf.getinfo(FFPROBE_ZIP_MEMBER)
            except KeyError:
                names = [n for n in zf.namelist() if n.lower().endswith("bin/ffprobe.exe")]
                if not names:
                    raise RuntimeError("ffprobe.exe nicht im Archiv gefunden")
                member = zf.getinfo(min(names))
                print(f"Hinweis: Member-Pfad abweichend ({member.filename}) – trotzdem ok.")
            with zf.open(member) as src, open(DEST_EXE, "wb") as dst:
                while True:
                    chunk = src.read(1 << 20)
                    if not chunk:
                        break
                    dst.write(chunk)
        if not _exe_looks_valid(DEST_EXE):
            raise RuntimeError("ffprobe.exe nach Entpacken ungueltig (Groesse/MZ-Header)")
        SOURCE_TXT.write_text(
            f"Quelle: {FFPROBE_URL}\nVersion: {FFPROBE_VERSION}\n"
            f"SHA256: {FFPROBE_SHA256}\nLizenz: GPL (siehe Gyan-Build-README)\n",
            encoding="utf-8",
        )
        size_mb = DEST_EXE.stat().st_size / (1024 * 1024)
        print(f"Fertig: {DEST_EXE} ({size_mb:.1f} MB)")
        return DEST_EXE
    finally:
        try:
            tmp_zip.unlink(missing_ok=True)
        except OSError:
            pass


def main(argv=None) -> int:
    force = "--force" in (argv or sys.argv[1:])
    try:
        fetch_ffprobe(force=force)
    except Exception as e:  # noqa: BLE001 – Build-Fehler lesbar melden
        print(f"FEHLER: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
