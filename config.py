"""
Capti zentrale Config-Verwaltung (UI-unabhängig).

Alle Lese-/Schreibzugriffe auf die Capti-config.json laufen über
dieses Modul. Der Pfad wird plattformunabhängig über capti_core.paths
aufgelöst (Windows: %APPDATA%/Capti – unverändert; andere Plattformen:
plattformgerechte Datenverzeichnisse). Garantien:

- Fehlende Datei -> sichere Defaults (leeres Dict)
- Kaputtes JSON / kein Dict -> leeres Dict statt Crash
- Merge-Sicherheit: save_config() erhält ALLE bestehenden Keys,
  auch unbekannte (custom_key etc.)
- Keine Abhängigkeit von UI/i18n

Tests können den Pfad per Umgebungsvariable CAPTI_CONFIG_FILE umleiten.
"""

import json
import os
from pathlib import Path
from typing import Any, Optional

from capti_core.paths import user_data_dir


def config_file() -> Path:
    """Pfad zur Capti-Config (Test-Override: CAPTI_CONFIG_FILE)."""
    override = os.environ.get("CAPTI_CONFIG_FILE")
    if override:
        return Path(override)
    return user_data_dir() / "config.json"


def load_config(path: Path = None) -> dict:
    """Lädt die Config sicher.

    Fehlende Datei, kaputtes JSON oder Nicht-Dict -> {} (sichere Defaults).
    Optionaler Pfad-Override (für Tests/UI-Wrapper).
    """
    try:
        path = path or config_file()
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass  # niemals crashen – Defaults verwenden
    return {}


def save_config(config: dict, path: Path = None) -> bool:
    """Speichert die Config merge-sicher.

    Erwartet ein vollständiges Config-Dict (z.B. aus load_config() +
    Änderungen). Ordner wird bei Bedarf erstellt. Schreibfehler -> False.
    Optionaler Pfad-Override (für Tests/UI-Wrapper).
    """
    try:
        if not isinstance(config, dict):
            return False
        path = path or config_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        return True
    except Exception:
        return False


def get_config_value(key: str, default: Optional[Any] = None) -> Any:
    """Liest einen einzelnen Config-Wert (fehlend/kaputt -> default)."""
    return load_config().get(key, default)


def set_config_value(key: str, value: Any) -> bool:
    """Setzt einen einzelnen Wert merge-sicher (alle anderen Keys bleiben)."""
    config = load_config()
    config[key] = value
    return save_config(config)


# ---------------------------------------------------------------------
# Fensterzustand (Phase 30): Größe/Position/Maximiert, merge-sicher.
# ---------------------------------------------------------------------

MIN_WINDOW_WIDTH = 820
MIN_WINDOW_HEIGHT = 560

_GEOMETRY_RE = None  # lazy importfrei halten


def sanitize_geometry(geometry: str) -> Optional[str]:
    """Validiert eine Tk-Geometry "BxH+X+Y" und clamp auf Mindestgröße.

    Rückgabe: normalisierter String oder None bei ungültiger Eingabe.
    """
    if not isinstance(geometry, str):
        return None
    import re
    m = re.match(r"^(\d+)x(\d+)([+-]\d+)([+-]\d+)$", geometry.strip())
    if not m:
        return None
    try:
        w = max(MIN_WINDOW_WIDTH, int(m.group(1)))
        h = max(MIN_WINDOW_HEIGHT, int(m.group(2)))
        x, y = int(m.group(3)), int(m.group(4))
    except ValueError:
        return None
    return f"{w}x{h}{x:+d}{y:+d}"


def load_window_state() -> dict:
    """Liest window_geometry/window_maximized sicher (Defaults bei Problemen)."""
    return {
        "geometry": sanitize_geometry(get_config_value("window_geometry", "")),
        "maximized": bool(get_config_value("window_maximized", False)),
    }


def save_window_state(geometry: str, maximized: bool) -> bool:
    """Speichert den Fensterzustand merge-sicher (nur die beiden Keys)."""
    ok1 = set_config_value("window_geometry",
                           sanitize_geometry(geometry) or "")
    ok2 = set_config_value("window_maximized", bool(maximized))
    return ok1 and ok2