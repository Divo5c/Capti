"""
Capti Font-System: zentrale Verwaltung der Marken-Fonts.

Fonts werden als private Fonts aus assets/fonts/ geladen (AddFontResourceEx
mit FR_PRIVATE) – sie werden NICHT dauerhaft in Windows installiert und sind
nur für den aktuellen Prozess sichtbar.

Font-Rollen:
    display   -> Nevera              (Titel / große Überschriften)
    technical -> Orbitron Medium     (technische Elemente, Zeiten, Zahlen)
    body      -> Prociono            (normaler UI-Text)
    signature -> Electroharmonix     ("Erstellt von Diraj Voruganti")

Verwendung:
    from ui.fonts import FontManager
    FontManager.initialize()
    font = FontManager.get("display", 32)
"""

import ctypes
import logging
import sys
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)

# Assets-Ordner (funktioniert im Dev-Modus und in PyInstaller-Bundles)
def _assets_dir() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "assets" / "fonts"
    return Path(__file__).parent.parent / "assets" / "fonts"

FR_PRIVATE = 0x10  # AddFontResourceEx: nur für diesen Prozess sichtbar

# Rolle -> (Dateiname, GDI-Familienname nach Registrierung)
FONT_ROLES: Dict[str, Dict[str, str]] = {
    "display": {
        "file": "Nevera-Regular.otf",
        "family": "Nevera",
        "fallback": "Segoe UI",
    },
    "technical": {
        # Hinweis: Asset liegt als "Orbitron Medium.otf" vor (kein Light-Weight verfügbar)
        "file": "Orbitron Medium.otf",
        "family": "Orbitron Medium",
        "fallback": "Consolas",
    },
    "body": {
        "file": "Prociono-Regular.ttf",
        "family": "Prociono",
        "fallback": "Segoe UI",
    },
    "signature": {
        "file": "Electroharmonix.otf",
        "family": "Electroharmonix",
        "fallback": "Segoe Script",
    },
}


class FontManager:
    """Zentraler Zugriff auf die Capti-Marken-Fonts."""

    _initialized = False
    _loaded_families: Dict[str, str] = {}  # role -> tatsächlich nutzbarer Familienname

    @classmethod
    def initialize(cls, assets_dir: Path = None) -> bool:
        """
        Registriert alle Fonts als private Prozess-Fonts.

        Args:
            assets_dir: Optional abweichender Font-Ordner (für Tests)

        Returns:
            True, wenn mindestens ein Font registriert wurde
        """
        if cls._initialized and not assets_dir:
            return bool(cls._loaded_families)

        fonts_dir = Path(assets_dir) if assets_dir else _assets_dir()
        cls._loaded_families = {}

        try:
            gdi32 = ctypes.windll.gdi32
            for role, info in FONT_ROLES.items():
                font_path = fonts_dir / info["file"]
                if not font_path.exists():
                    logger.warning(f"Font-Datei nicht gefunden: {font_path} – nutze Fallback")
                    cls._loaded_families[role] = info["fallback"]
                    continue
                # FR_PRIVATE: Font nur für diesen Prozess laden (keine Systeminstallation)
                result = gdi32.AddFontResourceExW(str(font_path), FR_PRIVATE, 0)
                if result > 0:
                    cls._loaded_families[role] = info["family"]
                    logger.info(f"Font registriert: {info['family']} ({info['file']})")
                else:
                    logger.warning(f"Font-Registrierung fehlgeschlagen: {info['file']} – nutze Fallback")
                    cls._loaded_families[role] = info["fallback"]
            cls._initialized = True
        except Exception as e:
            # Sichere Lösung: komplett auf System-Fallbacks ausweichen
            logger.error(f"Font-Registrierung nicht möglich ({e}) – nutze System-Fallbacks")
            cls._loaded_families = {r: i["fallback"] for r, i in FONT_ROLES.items()}
            cls._initialized = True

        return bool(cls._loaded_families)

    @classmethod
    def get_family(cls, role: str) -> str:
        """
        Gibt den nutzbaren Familiennamen für eine Font-Rolle zurück.

        Args:
            role: "display", "technical", "body" oder "signature"

        Returns:
            Familienname (Marken-Font oder Fallback)
        """
        if not cls._initialized:
            cls.initialize()
        return cls._loaded_families.get(role, FONT_ROLES.get(role, {}).get("fallback", "Segoe UI"))

    @classmethod
    def get(cls, role: str, size: int):
        """
        Erzeugt einen CustomTkinter-Font für eine Rolle.

        Args:
            role: Font-Rolle ("display", "technical", "body", "signature")
            size: Schriftgröße in Pixeln

        Returns:
            ctk.CTkFont-Instanz
        """
        import customtkinter as ctk
        return ctk.CTkFont(family=cls.get_family(role), size=size)

    @classmethod
    def reset(cls):
        """Setzt den Initialisierungs-Zustand zurück (für Tests)."""
        cls._initialized = False
        cls._loaded_families = {}