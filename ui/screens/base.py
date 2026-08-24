"""
Basisklasse für alle Capti-Screens.

Jeder Screen:
- besitzt ein eigenes CTkFrame
- kennt seinen AppController (für Navigation via controller.show_screen)
- kann Theme-/Font-Tokens verwenden
"""

import customtkinter as ctk

from ui.theme import get_theme
from ui.fonts import FontManager


class Screen(ctk.CTkFrame):
    """Gemeinsame Basis für alle Capti-Screens."""

    # Von Unterklassen zu überschreibende Attribute
    screen_name: str = "screen"

    def __init__(self, parent, controller, **kwargs):
        """
        Args:
            parent: Tk/CTk-Parent-Widget
            controller: AppController-Instanz (Navigation, Theme, Fonts)
        """
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.controller = controller
        self.theme = get_theme(controller.current_theme)
        self.build()

    # ------------------------------------------------------------------
    # Von Unterklassen zu implementieren / optional nutzbar
    # ------------------------------------------------------------------

    def build(self):
        """Baut den Screen-Inhalt auf (von Unterklassen überschreiben)."""
        pass

    def on_show(self):
        """Wird vom Controller aufgerufen, wenn der Screen sichtbar wird."""
        pass

    def on_hide(self):
        """Wird vom Controller aufgerufen, wenn der Screen verlassen wird."""
        pass

    # ------------------------------------------------------------------
    # Convenience-Helfer für Theme & Fonts
    # ------------------------------------------------------------------

    def font(self, role: str, size: int):
        """Erzeugt einen Marken-Font über den zentralen FontManager."""
        return FontManager.get(role, size)

    def color(self, token: str) -> str:
        """Gibt einen Theme-Farb-Token zurück."""
        return self.theme.get(token, "#ffffff")

    def navigate(self, screen_name: str):
        """Zentrale Navigation – läuft immer über den Controller."""
        self.controller.show_screen(screen_name)

    def set_content_width(self, width: int):
        """Responsive Breitenanpassung (optional).

        Der AppController ruft dies beim Größenwechsel des Wrappers auf,
        damit Screens feste Inhaltsbreiten an den verfügbaren Platz
        anpassen können. Default: keine Aktion.
        """
        return None