"""
Capti AppController: zentrale Screen-Verwaltung und Navigation.

- Verwaltet alle Screens (lazy erstellt, immer nur einer sichtbar)
- show_screen(name) als einziger Navigationsweg
- Nutzt Theme-Tokens (ui/theme.py) und FontManager (ui/fonts.py)
- Einfache Sidebar-Hauptnavigation (Home, New Project, Caption Style, Settings)

Screens navigieren nie direkt untereinander – nur über den Controller.
"""

import copy
import json
import logging
import os
from pathlib import Path

from capti_core.project_state import (
    ProjectState,
    load_project,
    save_project,
)

import customtkinter as ctk

from ui import i18n
from ui.theme import get_theme
from ui.fonts import FontManager
from ui.screens.home import HomeScreen
from ui.screens.new_project import NewProjectScreen
from ui.screens.caption_style import CaptionStyleScreen
from ui.screens.processing import ProcessingScreen
from ui.screens.result import ResultScreen
from ui.screens.settings import SettingsScreen

logger = logging.getLogger(__name__)

# Registrierte Screens: name -> Screen-Klasse
SCREEN_REGISTRY = {
    "home": HomeScreen,
    "new_project": NewProjectScreen,
    "caption_style": CaptionStyleScreen,
    "processing": ProcessingScreen,
    "result": ResultScreen,
    "settings": SettingsScreen,
}

# Einträge der Hauptnavigation (Sidebar)
MAIN_NAV = ["home", "new_project", "caption_style", "settings"]

DEFAULT_SCREEN = "home"

# Fallback-Labels (Deutsch); zur Laufzeit wird i18n verwendet
NAV_LABELS = {
    "home": "Home",
    "new_project": "Neues Projekt",
    "caption_style": "Caption Style",
    "processing": "Verarbeitung",
    "result": "Ergebnis",
    "settings": "Einstellungen",
}


# Zentrale Config-Verwaltung (Single Source of Truth).
# Lese/Schreib-Logik liegt vollständig in config.py; der Pfad wird über
# den Settings-Screen aufgelöst (bleibt dort patchbar für Tests).
from config import load_config, save_config


def _config_file():
    from ui.screens import settings as _settings_mod
    return _settings_mod._config_file()


def _read_config() -> dict:
    return load_config(_config_file())


def _set_config_value(key: str, value) -> bool:
    """Merge-sicher einen einzelnen Wert setzen (alle anderen Keys bleiben)."""
    cfg = _read_config()
    cfg[key] = value
    return save_config(cfg, _config_file())


class AppController:
    """Zentrale Steuerung von Screens, Navigation und Design-System."""

    def __init__(self, root: ctk.CTk, theme_name: str = "dark"):
        """
        Args:
            root: Tkinter/CTk-Root-Fenster
            theme_name: Start-Theme ("dark", "light", "yellow")
        """
        self.root = root
        self.current_theme = theme_name if theme_name in ("dark", "light", "yellow") else "dark"
        self.current_screen: str = None

        # UI-Sprache aus der Config laden (ungültig/fehlend -> de)
        i18n.set_language(_read_config().get("language", "de"))

        self._screens = {}       # name -> Screen-Instanz (lazy)
        self._wrappers = {}      # name -> ScrollableFrame-Wrapper (lazy)
        self._nav_buttons = {}   # name -> CTkButton
        # Projekt in Vorbereitung (New Project -> Caption Style -> Processing)
        self.pending_project: dict | None = None
        # Letztes Transkript (Block 20): {"video_path": str, "segments": [...]}
        # aus erfolgreichem Processing-Lauf; Caption Style zeigt es an, wenn
        # es zum aktuellen Projekt gehört. Nur Plain-Daten, keine Tk-Refs.
        # Block 22: trägt zusätzlich Caption-Edits (Editor-Apply schreibt
        # hierher); Export (Pipeline-Override) liest hierher.
        self.last_transcript: dict | None = None
        # Block 24: zuletzt geladener/gespeicherter Projektdatei-Stand
        # (Plain-Daten, keine Tk-Refs).
        self.current_project_state: ProjectState | None = None



        FontManager.initialize()
        self._build_layout()
        self.show_screen(DEFAULT_SCREEN)

    def get_transcript_segments(self, video_path: str):
        """Editierte Transkript-Segmente für video_path (tiefe Kopie).

        Gibt None zurück bei fehlendem Transkript, Video-Mismatch oder
        leerer Segmentliste – dann läuft der bisherige Whisper-Pfad.
        Die Kopie entkoppelt Pipeline/Export vom Session-State (keine
        Aliase, keine Tk-Objekte).
        """
        last = self.last_transcript
        if not isinstance(last, dict):
            return None
        if last.get("video_path") != video_path:
            return None
        segments = last.get("segments")
        if not isinstance(segments, list) or not segments:
            return None
        return copy.deepcopy(segments)

    # ------------------------------------------------------------------
    # Layout: Sidebar + Screen-Container
    # ------------------------------------------------------------------

    def _build_layout(self):
        theme = get_theme(self.current_theme)

        self.root.configure(fg_color=theme["background"])
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        # --- Sidebar (Hauptnavigation) ---
        self.sidebar = ctk.CTkFrame(self.root, width=200, corner_radius=0,
                                    fg_color=theme["surface"])
        self.sidebar.grid(row=0, column=0, sticky="nsw")
        self.sidebar.grid_propagate(False)
        # Abstandhalter-Zeile drückt die Signatur nach unten
        self.sidebar.grid_rowconfigure(len(MAIN_NAV) + 1, weight=1)

        logo = ctk.CTkLabel(self.sidebar, text="Capti",
                            font=FontManager.get("display", 28),
                            text_color=theme["accent"])
        logo.grid(row=0, column=0, padx=20, pady=(24, 32), sticky="w")

        for i, name in enumerate(MAIN_NAV, start=1):
            btn = ctk.CTkButton(
                self.sidebar, text=i18n.t(f"nav.{name}"),
                height=40, corner_radius=8, anchor="w",
                font=FontManager.get("body", 14),
                fg_color="transparent",
                hover_color=theme["surface_secondary"],
                text_color=theme["text"],
                command=lambda n=name: self.show_screen(n))
            btn.grid(row=i, column=0, padx=12, pady=4, sticky="ew")
            self._nav_buttons[name] = btn

        # Signatur unten in der Sidebar
        signature = ctk.CTkLabel(self.sidebar, text="Erstellt von Diraj Voruganti",
                                 font=FontManager.get("signature", 14),
                                 text_color=theme["text_secondary"], wraplength=170)
        signature.grid(row=len(MAIN_NAV) + 2, column=0, padx=16, pady=(24, 16), sticky="s")

        # --- Screen-Container ---
        self.container = ctk.CTkFrame(self.root, corner_radius=0,
                                      fg_color=theme["background"])
        self.container.grid(row=0, column=1, sticky="nsew")
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def show_screen(self, name: str):
        """
        Zeigt den angeforderten Screen an (zentraler Navigationsweg).

        Ungültige Namen werden abgefangen: es wird zum Default-Screen
        (home) navigiert und eine Warnung geloggt.
        """
        if name not in SCREEN_REGISTRY:
            logger.warning(f"Unbekannter Screen '{name}' – navigiere zu '{DEFAULT_SCREEN}'")
            name = DEFAULT_SCREEN

        # Alten Screen ausblenden
        if self.current_screen is not None and self.current_screen in self._screens:
            old = self._screens[self.current_screen]
            old.on_hide()
            old.master.grid_forget()

        # Neuen Screen lazy erstellen und anzeigen (in Scroll-Wrapper)
        if name not in self._screens:
            self._create_screen(name)
        screen = self._screens[name]
        wrapper = self._wrappers[name]
        wrapper.grid(row=0, column=0, sticky="nsew")
        screen.on_show()

        self.current_screen = name

        self._update_nav_highlight()

    def _create_screen(self, name: str):
        """Erstellt einen Screen in einem vertikalen Scroll-Wrapper.

        CTkScrollableFrame bietet Mausrad-/Touchpad-Scrolling, damit alle
        Inhalte auch bei kleiner Fensterhöhe erreichbar bleiben.
        """
        theme = get_theme(self.current_theme)
        wrapper = ctk.CTkScrollableFrame(self.container,
                                         fg_color=theme["background"])
        # Horizontale Zentrierung: Streck-Spalten links/rechts, Inhalt
        # mittig mit natürlicher Breite (bei schmalen Fenstern schrumpft
        # die Mittelspalte; keine horizontale Scrollpflicht).
        wrapper.grid_columnconfigure(0, weight=1)
        wrapper.grid_columnconfigure(1, weight=0)
        wrapper.grid_columnconfigure(2, weight=1)
        screen = SCREEN_REGISTRY[name](wrapper, self)
        # Screen explizit IM Wrapper platzieren (sonst bleibt der
        # Scrollbereich leer und kollabiert auf 1 px Höhe).
        screen.grid(row=0, column=1, sticky="n")
        # Responsive Breite: Screens mit festen Inhaltsbreiten an den
        # verfügbaren Platz anpassen (Phase 34), Obergrenze 672 px.
        wrapper.bind("<Configure>", lambda event, s=screen:
                     s.set_content_width(max(360, min(672, event.width - 16))),
                     add="+")
        self._wrappers[name] = wrapper
        self._screens[name] = screen

    def set_language(self, language: str):
        """Ändert die UI-Sprache zur Laufzeit (ohne Neustart).

        - i18n-Sprache setzen
        - Sprache merge-sicher in der Config speichern (alle anderen
          Keys bleiben erhalten)
        - Sidebar-Labels aktualisieren
        - bereits erzeugte Screens neu aufbauen (aktuelle Texte)
        """
        i18n.set_language(language)

        # Merge-sicher speichern (alle anderen Keys bleiben erhalten)
        _set_config_value("language", i18n.get_language())

        # Sidebar-Labels aktualisieren
        for name, btn in self._nav_buttons.items():
            btn.configure(text=i18n.t(f"nav.{name}"))

        # Bereits erzeugte Screens neu aufbauen (frische Texte).
        # Der Processing-Screen bleibt unangetastet, solange eine
        # Verarbeitung läuft (Pipeline würde sonst abgerissen).
        processing = self._screens.get("processing")
        processing_busy = (processing is not None
                           and getattr(processing, "_polling", False))
        for name, screen in list(self._screens.items()):
            if name == "processing" and processing_busy:
                continue
            screen.destroy()
            self._wrappers[name].destroy()
            del self._screens[name]
            del self._wrappers[name]

        # Aktuellen Screen neu erstellen und anzeigen
        current = self.current_screen or DEFAULT_SCREEN
        self.current_screen = None
        self.show_screen(current)

    def apply_theme(self, theme_name: str):
        """Wendet ein Theme zur Laufzeit an (Sidebar, Container, Nav-Buttons).

        Screens lesen ihre Farben über self.color(...) beim nächsten
        Zugriff – der Controller färbt die Rahmen-Elemente neu.
        """
        if theme_name not in ("dark", "light", "yellow"):
            return
        self.current_theme = theme_name
        ctk.set_appearance_mode(theme_name)
        theme = get_theme(theme_name)

        self.root.configure(fg_color=theme["background"])
        self.sidebar.configure(fg_color=theme["surface"])
        self.container.configure(fg_color=theme["background"])
        for btn in self._nav_buttons.values():
            btn.configure(hover_color=theme["surface_secondary"])
        # Bereits erzeugte Screens neu aufbauen, damit ALLE Inhalte die
        # neuen Theme-Farben bekommen (Screen-Inhalte cachen ihre Farben).
        # Laufende Verarbeitung bleibt unangetastet.
        processing = self._screens.get("processing")
        processing_busy = (processing is not None
                           and getattr(processing, "_polling", False))
        for name, screen in list(self._screens.items()):
            if name == "processing" and processing_busy:
                continue
            screen.destroy()
            self._wrappers[name].destroy()
            del self._screens[name]
            del self._wrappers[name]
        # Aktuellen Screen mit neuem Theme neu anzeigen
        if self.current_screen is not None and self.current_screen not in self._screens:
            current = self.current_screen
            self.current_screen = None
            self.show_screen(current)
        self._update_nav_highlight()

    def _update_nav_highlight(self):
        """Hebt den aktiven Nav-Eintrag hervor."""
        theme = get_theme(self.current_theme)
        for nav_name, btn in self._nav_buttons.items():
            active = (nav_name == self.current_screen)
            btn.configure(
                fg_color=theme["accent"] if active else "transparent",
                text_color="#1a1a1a" if active else theme["text"],
            )

    # ------------------------------------------------------------------
    # Zugriff für spätere Phasen
    # ------------------------------------------------------------------

    @property
    def screen_names(self):
        return list(SCREEN_REGISTRY.keys())

    def get_screen(self, name: str):
        """Gibt die Screen-Instanz zurück (erstellt sie bei Bedarf)."""
        if name not in SCREEN_REGISTRY:
            return None
        if name not in self._screens:
            self._create_screen(name)
        return self._screens[name]

    # ------------------------------------------------------------------
    # Projektdatei-Persistenz (Block 24): Transkript + Caption-Edits
    # ------------------------------------------------------------------

    def collect_project_state(self) -> ProjectState:
        """Sammelt den aktuellen Edit-State als ProjectState (Plain-Daten).

        Quelle: last_transcript (Video + editierte Segmente),
        pending_project/last_transcript (Modell/Sprache),
        Caption-Style-Screen (aktueller Style inkl. ungesicherter Edits).
        """
        last = self.last_transcript if isinstance(
            self.last_transcript, dict) else {}
        pending = self.pending_project if isinstance(
            self.pending_project, dict) else {}
        segments = last.get("segments")
        if not isinstance(segments, list):
            segments = []
        try:
            style_screen = self.get_screen("caption_style")
            style = dict(getattr(style_screen, "style", {}) or {})
        except Exception:
            style = {}
        model = pending.get("model") or last.get("model") or "small"
        language = pending.get("language", last.get("language"))
        return ProjectState(
            video_path=str(last.get("video_path")
                           or pending.get("video_path") or ""),
            model=model,
            language=language,
            caption_style=style,
            segments=copy.deepcopy(segments),
        )

    def save_project_state(self, path) -> str:
        """Speichert den aktuellen State als Projektdatei (atomar)."""
        state = self.collect_project_state()
        saved = save_project(path, state)
        self.current_project_state = state
        return saved

    def load_project_state(self, path) -> ProjectState:
        """Lädt eine Projektdatei und übernimmt sie in den Session-State.

        Setzt last_transcript (Video-Key-Isolation bleibt), pending_project
        (passende Preview) und den Caption-Style-Screen. Lädt auch bei
        fehlendem Video (Aufrufer prüft state.video_exists()).
        """
        state = load_project(path)
        self.current_project_state = state
        if state.segments:
            self.last_transcript = {
                "video_path": state.video_path,
                "segments": copy.deepcopy(state.segments),
                "model": state.model,
                "language": state.language,
            }
        else:
            self.last_transcript = None
        if state.video_path:
            self.pending_project = {
                "video_path": state.video_path,
                "model": state.model,
                "language": state.language,
            }
        try:
            from capti_core.caption_style import (
                DEFAULT_CAPTION_STYLE as _DEFAULT_STYLE)
            style_screen = self.get_screen("caption_style")
            style_screen.style = {**_DEFAULT_STYLE, **state.caption_style}
            style_screen._sync_ui_from_style()
        except Exception:
            pass
        return state