"""
Capti Theme-System: zentrale Design-Tokens für Dark / Light / Yellow.

Alle zukünftigen UI-Dateien beziehen Farben ausschließlich aus hier –
keine verstreuten Hardcoded-Farben.

Verwendung:
    from ui.theme import get_theme
    colors = get_theme("dark")
    colors["background"]  # "#1a1a1a"
"""

from typing import Dict

# Verfügbare Themes
AVAILABLE_THEMES = ["dark", "light", "yellow"]

# Token-Schlüssel (Dokumentation der verpflichtenden Keys)
TOKEN_KEYS = [
    "background",
    "surface",
    "surface_secondary",
    "text",
    "text_secondary",
    "accent",
    "accent_hover",
    "border",
    "success",
    "error",
]

THEMES: Dict[str, Dict[str, str]] = {
    "dark": {
        "background":        "#1a1a1a",
        "surface":           "#242424",
        "surface_secondary": "#2e2e2e",
        "text":              "#ffffff",
        "text_secondary":    "#9e9e9e",
        "accent":            "#ffd60a",   # Capti Yellow
        "accent_hover":      "#e6c200",
        "border":            "#3a3a3a",
        "success":           "#4ec9b0",
        "error":             "#f44747",
    },
    "light": {
        "background":        "#fafafa",
        "surface":           "#ffffff",
        "surface_secondary": "#f0f0f0",
        "text":              "#1a1a1a",
        "text_secondary":    "#6b6b6b",
        "accent":            "#f5c400",
        "accent_hover":      "#ddb000",
        "border":            "#dcdcdc",
        "success":           "#2e8b6e",
        "error":             "#d13438",
    },
    "yellow": {
        # Yellow-Theme: gelbe Akzentfläche als Grundstimmung
        "background":        "#1c1a10",
        "surface":           "#2a2617",
        "surface_secondary": "#38331d",
        "text":              "#fff8dc",
        "text_secondary":    "#c9bd8a",
        "accent":            "#ffd60a",
        "accent_hover":      "#ffe45c",
        "border":            "#4a4325",
        "success":           "#8fd694",
        "error":             "#ff6b6b",
    },
}

DEFAULT_THEME = "dark"


def get_theme(name: str = None) -> Dict[str, str]:
    """
    Gibt die Design-Tokens eines Themes zurück.

    Args:
        name: "dark", "light" oder "yellow"; None/ungültig -> Default (dark)

    Returns:
        Dict mit allen Token-Keys
    """
    return dict(THEMES.get(name or DEFAULT_THEME, THEMES[DEFAULT_THEME]))


def is_valid_theme(name: str) -> bool:
    """Prüft, ob ein Theme-Name unterstützt wird."""
    return name in AVAILABLE_THEMES