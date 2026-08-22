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

# CustomTkinter bringt Theme-/Asset-Dateien mit, die zur Laufzeit benötigt werden
datas += collect_data_files("customtkinter")

# tkinterdnd2 enthält die tkdnd Tcl-Erweiterung (Drag & Drop)
datas += collect_data_files("tkinterdnd2")

# --- FFmpeg-Binary von imageio-ffmpeg explizit mitliefern -------------------
# (imageio-ffmpeg liefert KEIN ffprobe – get_video_info() bleibt optional)
ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
binaries = [(ffmpeg_exe, "imageio_ffmpeg/binaries")]

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