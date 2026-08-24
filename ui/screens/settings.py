"""
Settings-Screen: Name, Darstellung, Sprache, Standardmodell.

Speichert ausschließlich in der bestehenden Capti-Config
(%APPDATA%/Capti/config.json) – bestehende Keys bleiben erhalten.
Robust gegen fehlende/kaputte Config und ungültige Werte.
"""

import json
import os
from pathlib import Path

import customtkinter as ctk

from history import HistoryManager
from ui import i18n
from ui.screens.base import Screen

# Theme-Optionen werden zur Laufzeit via i18n-Keys aufgebaut
MODEL_OPTIONS = ["tiny", "base", "small", "medium"]

DEFAULTS = {"name": "", "theme": "dark", "language": "de", "model": "small"}

THEME_CODES = ["dark", "light", "yellow"]
LANGUAGE_CODES = ["de", "en"]


def _theme_label(code: str) -> str:
    """Übersetztes Label für einen Theme-Code (Fallback: Code)."""
    key = f"set.theme.{code}"
    return i18n.t(key) if code in THEME_CODES else code


def _language_label(code: str) -> str:
    """Übersetztes Label für einen Sprach-Code (Fallback: Code)."""
    key = f"set.lang.{code}"
    return i18n.t(key) if code in LANGUAGE_CODES else code


def _resolve_code(label: str, prefix: str, codes: list) -> str | None:
    """Löst ein sichtbares Label zurück in den stabilen Code.

    Robust gegen Live-Sprachwechsel: Es werden ALLE Sprach-Varianten
    geprüft (nicht nur die aktuell angezeigte), damit das Mapping nie
    kaputtgeht. Rohe Codes werden ebenfalls erkannt.
    """
    for code in codes:
        if label == code:
            return code
        for lang in i18n.TRANSLATIONS:
            if i18n.TRANSLATIONS[lang].get(f"{prefix}.{code}") == label:
                return code
    return None




# Zentrale Config-Verwaltung (Single Source of Truth).
# _config_file bleibt als dünner Alias patchbar (Tests); Lese/Schreib-
# Logik liegt vollständig in config.py.
from config import (
    load_config, save_config, set_config_value, config_file as _config_file,
)


def _read_config() -> dict:
    return load_config(_config_file())


def _write_config(config: dict) -> bool:
    return save_config(config, _config_file())


class SettingsScreen(Screen):
    screen_name = "settings"

    def build(self):
        self.grid_columnconfigure(0, weight=1)

        # ----------------------------------------------------------
        # Header
        # ----------------------------------------------------------
        title = ctk.CTkLabel(self, text=i18n.t("set.title"),
                             font=self.font("display", 40),
                             text_color=self.color("text"))
        title.grid(row=0, column=0, pady=(40, 4))

        subtitle = ctk.CTkLabel(self, text=i18n.t("set.subtitle"),
                                font=self.font("body", 14),
                                text_color=self.color("text_secondary"))
        subtitle.grid(row=1, column=0, pady=(0, 28))

        # ----------------------------------------------------------
        # Card 1 – Dein Name
        # ----------------------------------------------------------
        name_card = ctk.CTkFrame(self, width=600, corner_radius=12,
                                 fg_color=self.color("surface"),
                                 border_width=1, border_color=self.color("border"))
        name_card.grid(row=2, column=0, padx=24, pady=(0, 12))
        name_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(name_card, text=i18n.t("set.name_title"),
                      font=self.font("body", 15), anchor="w",
                      text_color=self.color("text")).grid(
            row=0, column=0, sticky="w", padx=24, pady=(16, 2))
        ctk.CTkLabel(name_card, text=i18n.t("set.name_desc"),
                     font=self.font("body", 11), anchor="w",
                     text_color=self.color("text_secondary")).grid(
            row=1, column=0, sticky="w", padx=24, pady=(0, 8))

        self.name_entry = ctk.CTkEntry(name_card, width=280, height=36,
                                       corner_radius=8,
                                       font=self.font("body", 13),
                                       fg_color=self.color("surface_secondary"),
                                       border_color=self.color("border"),
                                       text_color=self.color("text"))
        self.name_entry.grid(row=2, column=0, sticky="w", padx=24, pady=(0, 16))
        # Auto-Save: Name wird bei Enter oder beim Verlassen gespeichert
        self.name_entry.bind("<Return>", lambda _e: self._save_name())
        self.name_entry.bind("<FocusOut>", lambda _e: self._save_name())

        # ----------------------------------------------------------
        # Card 2 – Darstellung
        # ----------------------------------------------------------
        theme_card = ctk.CTkFrame(self, width=600, corner_radius=12,
                                  fg_color=self.color("surface"),
                                  border_width=1, border_color=self.color("border"))
        theme_card.grid(row=3, column=0, padx=24, pady=(0, 12))
        theme_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(theme_card, text=i18n.t("set.theme_title"),
                      font=self.font("body", 15), anchor="w",
                      text_color=self.color("text")).grid(
            row=0, column=0, sticky="w", padx=24, pady=(16, 2))
        ctk.CTkLabel(theme_card, text=i18n.t("set.theme_desc"),
                      font=self.font("body", 11), anchor="w",
                      text_color=self.color("text_secondary")).grid(
            row=1, column=0, sticky="w", padx=24, pady=(0, 8))

        self.theme_var = ctk.StringVar(value=_theme_label("dark"))
        self.theme_segmented = ctk.CTkSegmentedButton(
            theme_card, values=[_theme_label(c) for c in THEME_CODES],
            variable=self.theme_var,
            command=self._on_theme_selected,

            font=self.font("body", 13),
            selected_color=self.color("accent"),
            selected_hover_color=self.color("accent_hover"),
            unselected_color=self.color("surface_secondary"),
            unselected_hover_color=self.color("surface_secondary"),
            text_color=self.color("text"))
        self.theme_segmented.grid(row=2, column=0, sticky="w", padx=24, pady=(0, 16))

        # ----------------------------------------------------------
        # Card 3 – Sprache (UI-Sprache)
        # ----------------------------------------------------------
        lang_card = ctk.CTkFrame(self, width=600, corner_radius=12,
                                 fg_color=self.color("surface"),
                                 border_width=1, border_color=self.color("border"))
        lang_card.grid(row=4, column=0, padx=24, pady=(0, 12))
        lang_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(lang_card, text=i18n.t("set.lang_title"),
                      font=self.font("body", 15), anchor="w",
                      text_color=self.color("text")).grid(
            row=0, column=0, sticky="w", padx=24, pady=(16, 2))
        ctk.CTkLabel(lang_card, text=i18n.t("set.lang_desc"),
                      font=self.font("body", 11), anchor="w",
                      text_color=self.color("text_secondary")).grid(
            row=1, column=0, sticky="w", padx=24, pady=(0, 8))

        self.language_var = ctk.StringVar(value=_language_label("de"))
        self.language_combo = ctk.CTkComboBox(
            lang_card, variable=self.language_var,
            values=[_language_label(c) for c in LANGUAGE_CODES],
            command=self._on_language_selected,

            width=180, height=34, corner_radius=8,
            font=self.font("body", 13),
            fg_color=self.color("surface_secondary"),
            button_color=self.color("border"),
            button_hover_color=self.color("accent_hover"),
            border_color=self.color("border"),
            text_color=self.color("text"), state="readonly")
        self.language_combo.grid(row=2, column=0, sticky="w", padx=24, pady=(0, 16))

        # ----------------------------------------------------------
        # Card 4 – Standardmodell
        # ----------------------------------------------------------
        model_card = ctk.CTkFrame(self, width=600, corner_radius=12,
                                  fg_color=self.color("surface"),
                                  border_width=1, border_color=self.color("border"))
        model_card.grid(row=5, column=0, padx=24, pady=(0, 12))
        model_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(model_card, text=i18n.t("set.model_title"),
                      font=self.font("body", 15), anchor="w",
                      text_color=self.color("text")).grid(
            row=0, column=0, sticky="w", padx=24, pady=(16, 2))
        ctk.CTkLabel(model_card, text=i18n.t("set.model_desc"),
                     font=self.font("body", 11), anchor="w",
                     text_color=self.color("text_secondary")).grid(
            row=1, column=0, sticky="w", padx=24, pady=(0, 8))

        self.model_var = ctk.StringVar(value="small")
        self.model_combo = ctk.CTkComboBox(
            model_card, variable=self.model_var, values=MODEL_OPTIONS,
            command=self._on_model_selected,
            width=180, height=34, corner_radius=8,
            font=self.font("technical", 13),
            fg_color=self.color("surface_secondary"),
            button_color=self.color("border"),
            button_hover_color=self.color("accent_hover"),
            border_color=self.color("border"),
            text_color=self.color("text"), state="readonly")
        self.model_combo.grid(row=2, column=0, sticky="w", padx=24, pady=(0, 16))

        # ----------------------------------------------------------
        # Card 5 – Verlauf
        # ----------------------------------------------------------
        history_card = ctk.CTkFrame(self, width=600, corner_radius=12,
                                    fg_color=self.color("surface"),
                                    border_width=1, border_color=self.color("border"))
        history_card.grid(row=6, column=0, padx=24, pady=(0, 12))
        history_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(history_card, text=i18n.t("set.history_title"),
                      font=self.font("body", 15), anchor="w",
                      text_color=self.color("text")).grid(
            row=0, column=0, sticky="w", padx=24, pady=(16, 2))
        ctk.CTkLabel(history_card, text=i18n.t("set.history_desc"),
                      font=self.font("body", 11), anchor="w",
                      text_color=self.color("text_secondary")).grid(
            row=1, column=0, sticky="w", padx=24, pady=(0, 8))

        btn_clear_history = ctk.CTkButton(
            history_card, text=i18n.t("set.clear_history"), width=170, height=36,
            font=self.font("body", 13), corner_radius=8,
            fg_color="transparent", border_width=1,
            border_color=self.color("error"),
            text_color=self.color("error"),
            hover_color=self.color("surface_secondary"),
            command=self._clear_history)
        btn_clear_history.grid(row=2, column=0, sticky="w", padx=24, pady=(0, 16))

        self.history_status_label = ctk.CTkLabel(history_card, text="",
                                                 font=self.font("body", 12),
                                                 anchor="w",
                                                 text_color=self.color("success"))
        self.history_status_label.grid(row=3, column=0, sticky="w", padx=24, pady=(0, 16))

        # ----------------------------------------------------------
        # Zurück (Auto-Save: kein separater Speichern-Button nötig)
        # ----------------------------------------------------------
        btn_back = ctk.CTkButton(
            self, text=i18n.t("common.back"), width=120, height=36,
            font=self.font("body", 13), corner_radius=8,
            fg_color="transparent", border_width=1,
            border_color=self.color("border"),
            text_color=self.color("text"),
            command=lambda: self.navigate("home"))
        btn_back.grid(row=7, column=0, pady=(16, 24))

        self.load_settings()

    # ------------------------------------------------------------------
    # Screen-API
    # ------------------------------------------------------------------

    def load_settings(self):
        """Lädt die Einstellungen aus der bestehenden Config (mit Defaults)."""
        config = {**DEFAULTS, **_read_config()}

        # Name (leer ist erlaubt)
        self.name_entry.delete(0, "end")
        self.name_entry.insert(0, str(config.get("name", "")))

        # Theme (ungültig -> dark)
        # Theme (ungueltig -> dark): Label anzeigen, Code bleibt massgeblich
        theme = config.get("theme", "dark")
        if theme not in THEME_CODES:
            theme = "dark"
        self.theme_var.set(_theme_label(theme))

        # Sprache (ungueltig -> de)
        language = config.get("language", "de")
        if language not in LANGUAGE_CODES:
            language = "de"
        self.language_var.set(_language_label(language))

        # Modell (ungültig -> small)
        model = config.get("model", "small")
        self.model_var.set(model if model in MODEL_OPTIONS else "small")

    # ------------------------------------------------------------------
    # Auto-Save-Handler (sofortige Anwendung + merge-sicheres Speichern)
    # ------------------------------------------------------------------

    def _set_value(self, key: str, value) -> bool:
        """Einzelnen Wert merge-sicher über den zentralen Pfad schreiben."""
        cfg = _read_config()
        cfg[key] = value
        return _write_config(cfg)

    def _on_theme_selected(self, label: str):
        """Theme sofort anwenden und speichern (kein Save-Klick nötig)."""
        code = _resolve_code(label, "set.theme", THEME_CODES)
        if not code:
            return
        self._set_value("theme", code)
        # apply_theme baut die Screens neu auf (inkl. dieser Instanz)
        self.controller.apply_theme(code)

    def _on_language_selected(self, label: str):
        """Sprache sofort anwenden und speichern (Live-Wechsel)."""
        code = _resolve_code(label, "set.lang", LANGUAGE_CODES)
        if not code:
            return
        # set_language persistiert merge-sicher und baut die Screens neu
        self.controller.set_language(code)

    def _on_model_selected(self, choice: str):
        """Standardmodell sofort speichern."""
        if choice in MODEL_OPTIONS:
            self._set_value("model", choice)

    def _save_name(self):
        """Name merge-sicher speichern (Enter/FocusOut, kein Button)."""
        self._set_value("name", self.name_entry.get().strip())

    def save_settings(self):
        """Speichert alle sichtbaren Einstellungen merge-sicher.

        Wird von den Auto-Save-Callbacks nicht mehr benötigt (die
        speichern gezielt einzelne Keys), bleibt aber als Sammel-Routine
        für Tests und programmatische Nutzung erhalten. Bestehende
        unbekannte Keys bleiben erhalten.
        """
        config = _read_config()
        config["name"] = self.name_entry.get().strip()
        theme = _resolve_code(self.theme_var.get(), "set.theme", THEME_CODES)
        config["theme"] = theme if theme else config.get("theme", "dark")
        language = _resolve_code(self.language_var.get(), "set.lang", LANGUAGE_CODES)
        config["language"] = language if language else config.get("language", "de")
        model = self.model_var.get()
        config["model"] = model if model in MODEL_OPTIONS else "small"
        _write_config(config)

    def _clear_history(self):
        """Löscht die gesamte History (dezente Meldung, keine Messagebox)."""
        ok = HistoryManager().clear()
        self.history_status_label.configure(
            text=i18n.t("set.history_cleared") if ok else i18n.t("set.history_clear_failed"))

    def reset(self):
        """Setzt die UI-Felder auf die gespeicherten Werte zurück."""
        self.load_settings()