"""
Capti DnD-Hilfsmodul: echtes Drag & Drop für Videodateien via tkinterdnd2.

Lädt das tkdnd-Paket (von tkinterdnd2 gebündelt) in den BESTEHENDEN
Tk-Interpreter und registriert Drop-Targets über direkte tk.call-Aufrufe –
ohne zweite Root-Instanz und ohne Widget-Klassen-Ersetzung.

Verwendung:
    from ui.dnd import register_drop_target, parse_dropped_files, pick_first_video
    if register_drop_target(widget):
        widget.bind("<<Drop>>", self._on_drop)
"""

import logging
from pathlib import Path

from ui import i18n

logger = logging.getLogger(__name__)

# Gültige Video-Endungen (identisch zur Validierung im New-Project-Screen)
VALID_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv", ".m4v"}

_tkdnd_loaded = False


def ensure_tkdnd(widget) -> bool:
    """Lädt das tkdnd-Paket in den Tk-Interpreter des Widgets (einmalig).

    tkinterdnd2 liefert die tkdnd-Binaries mit; sie werden über auto_path
    eingebunden. Funktioniert mit jedem Tk-Root (auch ctk.CTk).
    """
    global _tkdnd_loaded
    if _tkdnd_loaded:
        return True
    try:
        import sys as _sys
        import tkinterdnd2
        base = Path(tkinterdnd2.__file__).parent / "tkdnd"
        # Passende Plattform-Variante wählen (64/32-bit, Tcl 8 vs. 9),
        # damit nicht versehentlich eine inkompatible DLL geladen wird.
        arch = "x64" if _sys.maxsize > 2**32 else "x86"
        tcl_major = str(widget.tk.call("info", "patchlevel")).split(".")[0]
        candidates = [base / f"win-{arch}-tcl{tcl_major}", base / f"win-{arch}"]
        for cand in candidates:
            if cand.exists():
                widget.tk.call("lappend", "auto_path", str(cand))
                break
        else:
            widget.tk.call("lappend", "auto_path", str(base))
        widget.tk.call("package", "require", "tkdnd")
        _tkdnd_loaded = True
        return True
    except Exception as e:
        logger.warning(f"tkdnd konnte nicht geladen werden – DnD deaktiviert: {e}")
        return False


def register_drop_target(widget) -> bool:
    """Registriert ein Widget als Drop-Target für Dateien (DND_Files).

    Returns:
        True bei Erfolg, False wenn tkdnd nicht verfügbar ist.
    """
    if not ensure_tkdnd(widget):
        return False
    try:
        widget.tk.call("tkdnd::drop_target", "register", widget._w, "DND_Files")
        return True
    except Exception as e:
        logger.warning(f"Drop-Target-Registrierung fehlgeschlagen: {e}")
        return False


def parse_dropped_files(widget, data) -> list:
    """Parst die rohen Drop-Event-Daten in eine Liste von Pfaden."""
    try:
        return list(widget.tk.splitlist(data))
    except Exception:
        return []


def is_valid_video(path: str) -> bool:
    """Prüft, ob ein Pfad eine unterstützte Video-Endung hat."""
    return Path(path).suffix.lower() in VALID_VIDEO_EXTENSIONS


def pick_first_video(files: list):
    """Wählt die erste gültige Videodatei aus einer Drop-Liste.

    Returns:
        (video_path, error_message) – genau einer der beiden Werte ist None.
    """
    if not files:
        return None, i18n.t("dnd.no_file")
    for f in files:
        if is_valid_video(f):
            return f, None
    return None, i18n.t("dnd.invalid_format")
