# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller-Spec für Capti (Windows x64, One-Folder).

Build:  uv run pyinstaller Capti.spec --noconfirm
Ergebnis: dist/Capti/Capti.exe
"""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

import imageio_ffmpeg

block_cipher = None

PROJECT_DIR = Path(SPECPATH)

# --- Gebündelte Ressourcen -------------------------------------------------
datas = [
    # UI-Übersetzungen
    (str(PROJECT_DIR / "translations.json"), "."),
]

# Marken-Fonts (B3): ui/fonts.py erwartet sie im Frozen-Modus unter
# sys._MEIPASS/assets/fonts – exakt die 4 Dateien aus assets/fonts/,
# keine unnoetigen Fonts.
_font_dir = PROJECT_DIR / "assets" / "fonts"
for _font_file in sorted(_font_dir.glob("*")):
    if _font_file.is_file():
        datas.append((str(_font_file), "assets/fonts"))

# CustomTkinter bringt Theme-/Asset-Dateien mit, die zur Laufzeit benötigt werden
datas += collect_data_files("customtkinter")

# tkinterdnd2 enthält die tkdnd Tcl-Erweiterung (Drag & Drop)
datas += collect_data_files("tkinterdnd2")

# --- FFmpeg-Binary von imageio-ffmpeg explizit mitliefern -------------------
ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
binaries = [(ffmpeg_exe, "imageio_ffmpeg/binaries")]

# --- ffprobe für portable Builds (A3) ---------------------------------------
# tools/fetch_ffprobe.py lädt es zur Build-Zeit nach third_party/ffprobe/.
# Fehlt es (z.B. Fetch übersprungen), warnt der Build nur – die App fällt
# zur Laufzeit ehrlich auf System-ffprobe bzw. das 720x1280-Fallback zurück.
_ffprobe_exe = PROJECT_DIR / "third_party" / "ffprobe" / "ffprobe.exe"
if _ffprobe_exe.exists():
    binaries.append((str(_ffprobe_exe), "."))
else:
    print("WARNUNG: third_party/ffprobe/ffprobe.exe fehlt – "
          "Build läuft ohne gebündeltes ffprobe (siehe tools/fetch_ffprobe.py).")

# --- Hidden Imports ---------------------------------------------------------
hiddenimports = []
hiddenimports += collect_submodules("customtkinter")
hiddenimports += [
    "tkinterdnd2",
    "faster_whisper",
    "faster_whisper.audio",
    "faster_whisper.feature_extractor",
    "faster_whisper.tokenizer",
    "faster_whisper.transcribe",
    "faster_whisper.vad",
    "ctranslate2",
    "onnxruntime",
    "av",
    "tokenizers",
    "huggingface_hub",
    "imageio_ffmpeg",
]

a = Analysis(
    [str(PROJECT_DIR / "main.py")],
    pathex=[str(PROJECT_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "torch",
        "torchvision",
        "torchaudio",
        "matplotlib",
        "IPython",
        "jupyter",
        "pytest",
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Capti",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # GUI-Anwendung, keine Konsole
    disable_windowed_traceback=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Capti",           # -> dist/Capti/
)