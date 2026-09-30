"""
Home-Screen: professioneller Einstieg mit Begrüßung, Haupt-CTA,
Verlauf-Mockup und Signatur-Footer.

Nur visuelles Gerüst – keine History-Logik, keine Videoverarbeitung.
"""

import json
import os
import random
from datetime import datetime
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from history import HistoryManager
from ui import i18n
from ui.screens.base import Screen

# Kontrastfarbe für Text auf dem gelben Accent-Button (kein Theme-Token nötig,
# da der Accent in allen Themes gelb ist)
_ON_ACCENT_TEXT = "#1a1a1a"

# Atmosphäre-Text-Keys (statisch, nicht interaktiv; via i18n übersetzt)
ATMOSPHERE_KEYS = ["home.atmosphere.1", "home.atmosphere.2",
                   "home.atmosphere.3", "home.atmosphere.4"]

LANGUAGE_LABELS = {"de": "Deutsch", "en": "English"}


def _load_user_name() -> str:
    """Liest den Namen über die zentrale Config-Verwaltung (config.py).

    Sichere Fallbacks: fehlender Key, kaputte Datei oder leerer Name -> "".
    """
    from config import get_config_value
    return str(get_config_value("name", "") or "").strip()


class HomeScreen(Screen):
    screen_name = "home"

    def build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)  # Verlauf-Bereich expandiert

        # ----------------------------------------------------------
        # 1) Header: großer Capti-Titel
        # ----------------------------------------------------------
        title = ctk.CTkLabel(self, text="Capti",
                             font=self.font("display", 56),
                             text_color=self.color("text"))
        title.grid(row=0, column=0, pady=(48, 4))

        tagline = ctk.CTkLabel(self, text=i18n.t("home.tagline"),
                               font=self.font("body", 14),
                               text_color=self.color("text_secondary"))
        tagline.grid(row=1, column=0, pady=(0, 36))

        # ----------------------------------------------------------
        # 2) Begrüßung
        # ----------------------------------------------------------
        name = _load_user_name()
        greeting = (i18n.t("home.greeting", name=name) if name
                    else i18n.t("home.greeting_no_name"))
        greeting_label = ctk.CTkLabel(self, text=greeting,
                                      font=self.font("display", 30),
                                      text_color=self.color("text"))
        greeting_label.grid(row=2, column=0, pady=(0, 6))

        atmosphere = i18n.t(random.choice(ATMOSPHERE_KEYS))
        self.atmosphere_label = ctk.CTkLabel(self, text=atmosphere,
                                             font=self.font("body", 14),
                                             text_color=self.color("text_secondary"))
        self.atmosphere_label.grid(row=3, column=0, pady=(0, 40))

        # ----------------------------------------------------------
        # 3) Haupt-CTA: große Card / Drop-Zone
        # ----------------------------------------------------------
        self.cta_card = ctk.CTkFrame(
            self, width=560, height=180, corner_radius=16,
            fg_color=self.color("surface"),
            border_width=2, border_color=self.color("border"),
            cursor="hand2")
        self.cta_card.grid(row=4, column=0, padx=24, pady=(0, 8))
        self.cta_card.grid_propagate(False)
        self.cta_card.grid_columnconfigure(0, weight=1)

        plus = ctk.CTkLabel(self.cta_card, text=i18n.t("home.cta_new"),
                            font=self.font("display", 24),
                            text_color=self.color("accent"),
                            cursor="hand2")
        plus.grid(row=0, column=0, pady=(44, 8))
        hint = ctk.CTkLabel(self.cta_card, text=i18n.t("home.cta_hint"),
                            font=self.font("body", 13),
                            text_color=self.color("text_secondary"),
                            cursor="hand2")
        hint.grid(row=1, column=0, pady=(0, 32))

        # Klick auf die gesamte Card navigiert zu new_project
        for widget in (self.cta_card, plus, hint):
            widget.bind("<Button-1>", lambda e: self.navigate("new_project"))
        self.cta_card.bind("<Enter>", lambda e: self.cta_card.configure(
            border_color=self.color("accent")))
        self.cta_card.bind("<Leave>", lambda e: self.cta_card.configure(
            border_color=self.color("border")))

        # ----------------------------------------------------------
        # 3b) Projekt öffnen (Block 24: Transkript + Edits laden)
        # ----------------------------------------------------------
        open_row = ctk.CTkFrame(self, fg_color="transparent")
        open_row.grid(row=5, column=0, pady=(0, 8))
        ctk.CTkButton(open_row, text=i18n.t("home.open_project"), width=220,
                      height=40, font=self.font("body", 13), corner_radius=10,
                      fg_color="transparent", border_width=1,
                      border_color=self.color("border"),
                      text_color=self.color("text"),
                      command=self.open_project_file).grid(row=0, column=0)
        self.open_status_label = ctk.CTkLabel(
            open_row, text="", font=self.font("body", 12),
            text_color=self.color("text_secondary"))
        self.open_status_label.grid(row=1, column=0, pady=(6, 0))

        # ----------------------------------------------------------
        # 4) Verlauf – echte History (HistoryManager)
        # ----------------------------------------------------------
        history_title = ctk.CTkLabel(self, text=i18n.t("home.history_title"),
                                     font=self.font("body", 15),
                                     text_color=self.color("text"))
        history_title.grid(row=6, column=0, sticky="w", padx=64, pady=(28, 10))

        self._history_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._history_frame.grid(row=7, column=0, sticky="new", padx=48, pady=(0, 12))
        self._history_frame.grid_columnconfigure(0, weight=1)

        self._build_history_entries()

        # ----------------------------------------------------------
        # 5) Footer: Signatur
        # ----------------------------------------------------------
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=8, column=0, pady=(16, 20))
        ctk.CTkLabel(footer, text=i18n.t("footer.created_by"),
                     font=self.font("body", 11),
                     text_color=self.color("text_secondary")).grid(row=0, column=0)
        ctk.CTkLabel(footer, text="Diraj Voruganti",
                     font=self.font("signature", 18),
                     text_color=self.color("accent")).grid(row=1, column=0, pady=(2, 0))

    def _build_history_entries(self):
        """Baut die History-Einträge (oder den Empty State) auf."""
        for child in self._history_frame.winfo_children():
            child.destroy()

        entries = HistoryManager().get_recent(10)

        if not entries:
            empty = ctk.CTkFrame(self._history_frame, height=90, corner_radius=12,
                                 fg_color=self.color("surface"),
                                 border_width=1, border_color=self.color("border"))
            empty.grid(row=0, column=0, sticky="ew", pady=4, padx=16)
            empty.grid_propagate(False)
            empty.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(empty, text=i18n.t("history.empty_title"),
                          font=self.font("body", 14),
                          text_color=self.color("text")).grid(row=0, column=0, pady=(18, 2))
            ctk.CTkLabel(empty, text=i18n.t("history.empty_hint"),
                         font=self.font("body", 12),
                         text_color=self.color("text_secondary")).grid(row=1, column=0, pady=(0, 16))
            return

        for i, entry in enumerate(entries):
            card = ctk.CTkFrame(self._history_frame, height=64, corner_radius=12,
                                fg_color=self.color("surface"),
                                border_width=1, border_color=self.color("border"),
                                cursor="hand2")
            card.grid(row=i, column=0, sticky="ew", pady=4, padx=16)
            card.grid_propagate(False)
            card.grid_columnconfigure(0, weight=1)

            filename = os.path.basename(entry.get("video_path", "")) or i18n.t("history.unknown_video")
            name_label = ctk.CTkLabel(card, text=filename,
                                      font=self.font("body", 14),
                                      anchor="w",
                                      text_color=self.color("text"), cursor="hand2")
            name_label.grid(row=0, column=0, sticky="w", padx=20, pady=(10, 0))

            meta = self._format_history_meta(entry)
            meta_label = ctk.CTkLabel(card, text=meta,
                                      font=self.font("technical", 11),
                                      anchor="w",
                                      text_color=self.color("text_secondary"), cursor="hand2")
            meta_label.grid(row=1, column=0, sticky="w", padx=20, pady=(0, 10))

            # Klick öffnet den Result-Screen mit den gespeicherten Metadaten
            for widget in (card, name_label, meta_label):
                widget.bind("<Button-1>", lambda e, en=entry: self._open_history_entry(en))

    @staticmethod
    def _format_history_meta(entry: dict) -> str:
        """Formatiert Datum · Modell · Sprache für einen History-Eintrag."""
        try:
            ts = datetime.fromisoformat(entry.get("timestamp", ""))
            date_str = ts.strftime("%d.%m.%Y %H:%M")
        except Exception:
            date_str = ""
        model = entry.get("model", "")
        language = LANGUAGE_LABELS.get(entry.get("language", ""), entry.get("language", ""))
        parts = [p for p in (date_str, model, language) if p]
        return " · ".join(parts)

    def _open_history_entry(self, entry: dict):
        """Öffnet den Result-Screen mit dem gespeicherten Output + Metadaten.

        Fehlende Output-Datei nutzt das bestehende Fehlerverhalten des
        Result-Screens. KEINE Pipeline-Anbindung.
        """
        result = self.controller.get_screen("result")
        result.set_result(
            entry.get("output_path", ""),
            filename=os.path.basename(entry.get("video_path", "")) or None,
            model=entry.get("model") or None,
            language=LANGUAGE_LABELS.get(entry.get("language", ""), entry.get("language") or None),
            duration=entry.get("duration"),
            resolution=entry.get("resolution") or None,
        )
        self.navigate("result")

    def open_project_file(self, path: str | None = None):
        """Lädt eine Projektdatei (Block 24) und öffnet den Caption-Editor.

        Ohne Pfad wird der Datei-Dialog gezeigt. Fehler werden in der
        Status-Zeile angezeigt (kein Popup-Spam, kein Crash).
        """
        from capti_core.project_state import (
            PROJECT_EXTENSION, ProjectFileError)
        if path is None:
            path = filedialog.askopenfilename(
                title=i18n.t("home.open_project"),
                defaultextension=PROJECT_EXTENSION,
                filetypes=[("Capti-Projekt", "*" + PROJECT_EXTENSION),
                           ("JSON", "*.json"), ("Alle Dateien", "*.*")],
            )
        if not path:
            return
        try:
            self.controller.load_project_state(path)
        except ProjectFileError as exc:
            self.open_status_label.configure(
                text=i18n.t("home.open_failed", error=exc))
            return
        except Exception as exc:
            self.open_status_label.configure(
                text=i18n.t("home.open_failed", error=exc))
            return
        # State lebt im Controller (last_transcript/pending_project/Style)
        self.open_status_label.configure(text="")
        self.navigate("caption_style")

    def set_content_width(self, width: int):
        """Phase 34: CTA-Card responsiv anpassen."""
        self.cta_card.configure(width=width)

    def on_show(self):
        """History beim Anzeigen aktualisieren (z.B. nach neuer Verarbeitung)."""
        self._build_history_entries()
