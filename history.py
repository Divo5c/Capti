"""
Capti History: dauerhafte Speicherung verarbeiteter Videos.

UI-unabhängiger HistoryManager; Daten liegen im plattformgerechten
Capti-Datenverzeichnis (Windows: %APPDATA%/Capti/history.json;
ISO-Zeitstempel, max. 10 Einträge).

Robust gegen fehlende/kaputte Dateien – die App stürzt nie wegen History.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from capti_core.paths import user_data_dir

MAX_ENTRIES = 10


def _history_file() -> Path:
    return user_data_dir() / "history.json"


def _read_history() -> list:
    """Liest die History sicher; fehlend/kaputt/falsches Format -> []."""
    try:
        path = _history_file()
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                # Ungültige Einträge (keine Dicts / ohne Kernfelder) ignorieren
                return [e for e in data
                        if isinstance(e, dict)
                        and any(k in e for k in ("video_path", "output_path", "timestamp"))]
    except Exception:
        pass
    return []


def _write_history(entries: list) -> bool:
    """Schreibt die History sicher; Schreibfehler -> False statt Crash."""
    try:
        path = _history_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
        return True
    except Exception:
        return False


class HistoryManager:
    """Kleine, UI-unabhängige Verwaltung des Verarbeitungverlaufs."""

    def __init__(self, max_entries: int = MAX_ENTRIES):
        self.max_entries = max_entries

    def add_entry(self, video_path: str, output_path: str,
                  model: str = "", language: str = "",
                  duration=None, resolution: str = "") -> dict:
        """
        Fügt einen Eintrag hinzu (neuester steht vorne) und speichert.

        Fehlende optionale Felder sind ok. Gibt den erstellten Eintrag zurück.
        """
        entry = {
            "video_path": str(video_path or ""),
            "output_path": str(output_path or ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": str(model or ""),
            "language": str(language or ""),
        }
        if duration is not None:
            try:
                entry["duration"] = float(duration)
            except (TypeError, ValueError):
                pass
        if resolution:
            entry["resolution"] = str(resolution)

        entries = [entry] + _read_history()
        _write_history(entries[: self.max_entries])
        return entry

    def get_entries(self) -> list:
        """Gibt alle gültigen Einträge zurück (neuester zuerst)."""
        return _read_history()

    def get_recent(self, limit: int = 10) -> list:
        """Gibt die letzten `limit` Einträge zurück."""
        return _read_history()[: max(0, int(limit))]

    def remove_entry(self, index: int) -> bool:
        """Entfernt den Eintrag an der Position `index` (0 = neuester)."""
        entries = _read_history()
        if 0 <= index < len(entries):
            del entries[index]
            _write_history(entries)
            return True
        return False

    def clear(self) -> bool:
        """Löscht die gesamte History."""
        return _write_history([])