#!/usr/bin/env python3
"""
Reproduzierbarer Release-Build für Capti (Windows x64).

Ablauf:
1. Alte Build-Artefakte entfernen (build/, dist/, Capti-v*-Windows.zip)
2. uv-Umgebung synchronisieren
3. PyInstaller ausführen (Capti.spec, One-Folder)
4. README.txt in die Distribution kopieren
5. ZIP erstellen: Capti-v<version>-Windows.zip

Ausführen:  uv run python build.py
"""

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
DIST_DIR = PROJECT_DIR / "dist"
APP_DIR = DIST_DIR / "Capti"
BUILD_DIR = PROJECT_DIR / "build"


def get_version() -> str:
    """Liest die Version aus pyproject.toml."""
    for line in (PROJECT_DIR / "pyproject.toml").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("version"):
            return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError("Version nicht in pyproject.toml gefunden")


def run(cmd: list) -> None:
    print(f"> {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=PROJECT_DIR)


def main() -> None:
    version = get_version()
    zip_name = f"Capti-v{version}-Windows.zip"
    zip_path = PROJECT_DIR / zip_name

    # 1. Alte Artefakte entfernen
    for path in (BUILD_DIR, APP_DIR, zip_path):
        if path.exists():
            print(f"Entferne {path}")
            shutil.rmtree(path) if path.is_dir() else path.unlink()

    # 2. uv-Umgebung synchronisieren
    run(["uv", "sync"])

    # 3. PyInstaller-Build (One-Folder)
    run(["uv", "run", "pyinstaller", "Capti.spec", "--noconfirm"])

    if not (APP_DIR / "Capti.exe").exists():
        raise RuntimeError("Build fehlgeschlagen: Capti.exe nicht gefunden")

    # 4. README.txt in die Distribution kopieren
    readme_src = PROJECT_DIR / "README.txt"
    if readme_src.exists():
        shutil.copy2(readme_src, APP_DIR / "README.txt")

    # 5. ZIP erstellen
    print(f"Erstelle {zip_name} ...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for file in sorted(APP_DIR.rglob("*")):
            if file.is_file():
                zf.write(file, Path("Capti") / file.relative_to(APP_DIR))

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"\nFertig: {zip_name} ({size_mb:.1f} MB)")
    print(f"Distribution: {APP_DIR}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.exit(f"Build fehlgeschlagen (Exit-Code {e.returncode})")