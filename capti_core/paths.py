"""
Capti Core: plattformunabhängige Benutzer-Datenverzeichnisse.

Auflösungsreihenfolge für das Capti-Datenverzeichnis (config.json,
history.json etc.):

1. CAPTI_DATA_DIR   – explizites Override (Tests, mobile Sandboxes)
2. APPDATA          – Windows-Standard (%APPDATA%\\Capti); wird auf allen
                      Plattformen honoriert, damit bestehende Umgebungen
                      und Test-Harnesses unverändert funktionieren
3. Plattform-Default:
   - Windows:       %USERPROFILE%\\Capti  (identisch zum bisherigen
                    Fallback Path.home()/"Capti")
   - macOS:         ~/Library/Application Support/Capti
   - Linux/sonst:   $XDG_DATA_HOME/Capti, sonst ~/.local/share/Capti

Windows-Behavior ist damit byteidentisch zum bisherigen Stand; auf
anderen Plattformen entstehen saubere, plattformkonforme Pfade statt
verstreuter Ordner im Home-Verzeichnis.
"""

import os
import sys
from pathlib import Path

APP_DIR_NAME = "Capti"


def _platform_default_dir() -> Path:
    """Plattformgerechtes Default-Verzeichnis ohne Overrides."""
    if sys.platform == "win32":
        # Bisheriges Verhalten: %APPDATA% (falls vorhanden) oder Home
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / APP_DIR_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    # Linux und alles andere: XDG Base Directory Specification
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / APP_DIR_NAME
    return Path.home() / ".local" / "share" / APP_DIR_NAME


def user_data_dir() -> Path:
    """Gibt das Capti-Benutzerdaten-Verzeichnis zurück (erstellt es NICHT).

    Siehe Moduldocstring für die Auflösungsreihenfolge. Aufrufer sind
    dafür verantwortlich, den Ordner bei Bedarf zu erstellen.
    """
    override = os.environ.get("CAPTI_DATA_DIR")
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / APP_DIR_NAME
    return _platform_default_dir()


def temp_dir() -> Path:
    """Gibt das Capti-Runtime-Temp-Verzeichnis zurück (erstellt es NICHT).

    Liegt bewusst im System-Temp (`tempfile.gettempdir()/Capti`) und NICHT
    neben EXE/Projektordner – dort ist unter z.B. Programme oft nicht
    schreibbar (B5). Funktioniert in Development und Frozen/PyInstaller
    identisch. Aufrufer erstellen den Ordner bei Bedarf (exist_ok=True).
    Nur Zwischendateien (WAV/SRT/ASS) – niemals Benutzerdaten/Outputs.
    """
    import tempfile
    return Path(tempfile.gettempdir()) / APP_DIR_NAME
