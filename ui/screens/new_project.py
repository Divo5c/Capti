"""
New-Project-Screen: Video-Auswahl + Verarbeitungsoptionen.

Nur Auswahl & Optionen – keine Verarbeitung, keine Übersetzung,
keine History. Navigation ausschließlich über den AppController.
"""

import json
import os
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from ui import i18n
from ui.dnd import parse_dropped_files, pick_first_video, register_drop_target
from ui.screens.base import Screen

VALID_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv", ".m4v"}

# Transkriptionssprache (bewusst getrennt von der UI-Sprache!)
LANGUAGE_KEYS = ["np.lang.auto", "np.lang.de", "np.lang.en"]
LANGUAGE_CODES = {"np.lang.auto": None, "np.lang.de": "de", "np.lang.en": "en"}

MODEL_OPTIONS = ["tiny", "base", "small", "medium"]

# i18n-Keys fuer die Modell-Hinweise (Werte in ui/i18n.py)
MODEL_HINT_KEYS = {
    "tiny": "np.model_hint.tiny",
    "base": "np.model_hint.base",
    "small": "np.model_hint.small",
    "medium": "np.model_hint.medium",
}

# Technische Hinweise pro Modell (Orbitron-Metadaten)
MODEL_HINTS = {
    "tiny": "schnell · geringer Speicher",
    "base": "schnell · kleiner Speicher",
    "small": "ausgewogen · Standard",
    "medium": "genauer · mehr Zeit & Speicher",
}


def _load_default_model() -> str:
    """Liest das Standard-Modell über die zentrale Config (Fallback: 'small')."""
    from config import get_config_value
    model = get_config_value("model", "small")
    return model if model in MODEL_OPTIONS else "small"


def resolve_language_code(label: str):
    """Löst Anzeige-Label ODER rohen Key in den stabilen Sprachcode auf (C1).

    - Rohe Keys ("np.lang.de") funktionieren weiterhin (Tests/Kompatibilität).
    - Sichtbare Labels werden in ALLEN Sprachen erkannt (robust gegen
      Live-Sprachwechsel): "Deutsch"/"German" -> "de" etc.
    - Unbekannt/leer -> None (= Auto). Es wird nie ein Anzeigetext als
      interner Code gespeichert.
    """
    if label in LANGUAGE_CODES:
        return LANGUAGE_CODES[label]
    for key, code in LANGUAGE_CODES.items():
        for lang in i18n.TRANSLATIONS:
            if i18n.TRANSLATIONS[lang].get(key) == label:
                return code
    return None


class NewProjectScreen(Screen):
    screen_name = "new_project"

    def build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)  # Optionsbereich expandiert

        # ----------------------------------------------------------
        # 1) Header
        # ----------------------------------------------------------
        title = ctk.CTkLabel(self, text=i18n.t("np.title"),
                             font=self.font("display", 40),
                             text_color=self.color("text"))
        title.grid(row=0, column=0, pady=(40, 4))

        subtitle = ctk.CTkLabel(self, text=i18n.t("np.subtitle"),
                                font=self.font("body", 14),
                                text_color=self.color("text_secondary"))
        subtitle.grid(row=1, column=0, pady=(0, 28))

        # ----------------------------------------------------------
        # 2) Video-Auswahl: große Drop-Zone-Card
        # ----------------------------------------------------------
        self.drop_card = ctk.CTkFrame(
            self, width=620, height=170, corner_radius=16,
            fg_color=self.color("surface"),
            border_width=2, border_color=self.color("border"),
            cursor="hand2")
        self.drop_card.grid(row=2, column=0, sticky="ew", padx=24, pady=(0, 8))
        self.drop_card.grid_propagate(False)
        self.drop_card.grid_columnconfigure(0, weight=1)

        self.drop_text = ctk.CTkLabel(self.drop_card, text=i18n.t("np.drop_text"),
                                 font=self.font("display", 20),
                                 text_color=self.color("text"),
                                 cursor="hand2")
        self.drop_text.grid(row=0, column=0, pady=(28, 4))

        self.or_text = ctk.CTkLabel(self.drop_card, text=i18n.t("np.or_text"),
                               font=self.font("body", 13),
                               text_color=self.color("text_secondary"),
                               cursor="hand2")
        self.or_text.grid(row=1, column=0, pady=(0, 12))

        btn_select = ctk.CTkButton(
            self.drop_card, text=i18n.t("np.btn_select"), width=180, height=38,
            font=self.font("body", 13), corner_radius=8,
            fg_color=self.color("accent"), hover_color=self.color("accent_hover"),
            text_color="#1a1a1a",
            command=self._select_video)
        btn_select.grid(row=2, column=0, pady=(0, 20))

        # Ausgewählter Dateiname (Orbitron-Metadaten)
        self.file_label = ctk.CTkLabel(self, text="",
                                       font=self.font("technical", 12),
                                       text_color=self.color("accent"))
        self.file_label.grid(row=3, column=0, pady=(4, 16))

        # Klick auf Drop-Zone öffnet ebenfalls den File-Dialog
        for widget in (self.drop_card, self.drop_text, self.or_text):
            widget.bind("<Button-1>", lambda e: self._select_video())
        self.drop_card.bind("<Enter>", lambda e: self.drop_card.configure(
            border_color=self.color("accent")))
        self.drop_card.bind("<Leave>", lambda e: self.drop_card.configure(
            border_color=self.color("border")))

        # Echtes Drag & Drop (tkinterdnd2) – Drop-Zone + Texte als Targets
        for widget in (self.drop_card, self.drop_text, self.or_text):
            if register_drop_target(widget):
                widget.bind("<<Drop>>", self._on_drop)
                widget.bind("<<DragEnter>>", self._on_drag_enter)
                widget.bind("<<DragLeave>>", self._on_drag_leave)

        # ----------------------------------------------------------
        # 3) Optionen: Sprache / Übersetzung (Info) / Modell
        # ----------------------------------------------------------
        options = ctk.CTkFrame(self, fg_color="transparent")
        options.grid(row=4, column=0, sticky="new", padx=24, pady=(8, 0))
        options.grid_columnconfigure(0, weight=1)
        options.grid_columnconfigure(1, weight=1)

        # --- Sprache ---
        lang_card = ctk.CTkFrame(options, corner_radius=12,
                                 fg_color=self.color("surface"),
                                 border_width=1, border_color=self.color("border"))
        lang_card.grid(row=0, column=0, sticky="new", padx=(0, 8), pady=8)
        ctk.CTkLabel(lang_card, text=i18n.t("np.lang_title"),
                     font=self.font("body", 15),
                     text_color=self.color("text")).grid(
            row=0, column=0, sticky="w", padx=20, pady=(16, 4))
        ctk.CTkLabel(lang_card, text=i18n.t("np.lang_desc"),
                     font=self.font("body", 11),
                     text_color=self.color("text_secondary")).grid(
            row=1, column=0, sticky="w", padx=20, pady=(0, 8))
        self.lang_var = ctk.StringVar(value=i18n.t("np.lang.auto"))
        self.lang_combo = ctk.CTkComboBox(
            lang_card, variable=self.lang_var,
            values=[i18n.t(key) for key in LANGUAGE_KEYS],
            width=180, height=34, corner_radius=8,
            font=self.font("body", 13),
            fg_color=self.color("surface_secondary"),
            button_color=self.color("border"),
            button_hover_color=self.color("accent_hover"),
            border_color=self.color("border"),
            text_color=self.color("text"), state="readonly")
        self.lang_combo.grid(row=2, column=0, sticky="w", padx=20, pady=(0, 16))

        # --- Übersetzung: dezente Info-Card (KEINE funktionale Auswahl) ---
        trans_card = ctk.CTkFrame(options, corner_radius=12,
                                  fg_color=self.color("surface"),
                                  border_width=1, border_color=self.color("border"))
        trans_card.grid(row=0, column=1, sticky="new", padx=(8, 0), pady=8)
        ctk.CTkLabel(trans_card, text=i18n.t("np.trans_title"),
                     font=self.font("body", 15),
                     text_color=self.color("text")).grid(
            row=0, column=0, sticky="w", padx=20, pady=(16, 4))
        ctk.CTkLabel(trans_card, text=i18n.t("np.trans_desc"),
                     font=self.font("body", 11),
                     text_color=self.color("text_secondary")).grid(
            row=1, column=0, sticky="w", padx=20, pady=(0, 8))
        ctk.CTkLabel(trans_card, text="COMING SOON",
                     font=self.font("technical", 10),
                     text_color=self.color("accent")).grid(
            row=2, column=0, sticky="w", padx=20, pady=(0, 16))

        # --- Whisper-Modell ---
        model_card = ctk.CTkFrame(options, corner_radius=12,
                                  fg_color=self.color("surface"),
                                  border_width=1, border_color=self.color("border"))
        model_card.grid(row=1, column=0, columnspan=2, sticky="ew", pady=8)
        model_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(model_card, text=i18n.t("np.model_title"),
                     font=self.font("body", 15),
                     text_color=self.color("text")).grid(
            row=0, column=0, sticky="w", padx=20, pady=(16, 4))

        self.model_var = ctk.StringVar(value=_load_default_model())
        self.model_hint = ctk.CTkLabel(
            model_card, text=i18n.t(MODEL_HINT_KEYS[self.model_var.get()]),
            font=self.font("technical", 11),
            text_color=self.color("text_secondary"))
        self.model_hint.grid(row=1, column=0, sticky="w", padx=20, pady=(0, 8))

        self.model_combo = ctk.CTkComboBox(
            model_card, variable=self.model_var, values=MODEL_OPTIONS,
            width=180, height=34, corner_radius=8,
            font=self.font("technical", 13),
            fg_color=self.color("surface_secondary"),
            button_color=self.color("border"),
            button_hover_color=self.color("accent_hover"),
            border_color=self.color("border"),
            text_color=self.color("text"),
            command=self._on_model_change)
        self.model_combo.grid(row=2, column=0, sticky="w", padx=20, pady=(0, 6))

        ctk.CTkLabel(model_card, text=i18n.t("np.model_note"),
                     font=self.font("body", 11),
                     text_color=self.color("text_secondary")).grid(
            row=3, column=0, sticky="w", padx=20, pady=(0, 16))

        # ----------------------------------------------------------
        # 6) Weiter-Button + Hinweis
        # ----------------------------------------------------------
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=5, column=0, pady=(16, 8))
        footer.grid_columnconfigure(0, weight=1)

        self.warning_label = ctk.CTkLabel(footer, text="",
                                          font=self.font("body", 12),
                                          text_color=self.color("error"))
        self.warning_label.grid(row=0, column=0, pady=(0, 8))

        btn_continue = ctk.CTkButton(
            footer, text=i18n.t("np.continue"), width=240, height=48,
            font=self.font("display", 15), corner_radius=10,
            fg_color=self.color("accent"), hover_color=self.color("accent_hover"),
            text_color="#1a1a1a",
            command=self._on_continue)
        btn_continue.grid(row=1, column=0, pady=(0, 8))

        # ----------------------------------------------------------
        # 7) Zurück
        # ----------------------------------------------------------
        btn_back = ctk.CTkButton(
            self, text=i18n.t("common.back"), width=120, height=36,
            font=self.font("body", 13), corner_radius=8,
            fg_color="transparent", border_width=1,
            border_color=self.color("border"),
            text_color=self.color("text"),
            command=lambda: self.navigate("home"))
        btn_back.grid(row=6, column=0, pady=(8, 24))

    # ------------------------------------------------------------------
    # Aktionen
    # ------------------------------------------------------------------

    def _select_video(self):
        """Öffnet den bestehenden File-Dialog und übernimmt den Dateinamen."""
        filetypes = [
            ("Video-Dateien", "*.mp4 *.mov *.avi *.mkv *.webm *.flv *.wmv *.m4v"),
            ("Alle Dateien", "*.*"),
        ]
        path = filedialog.askopenfilename(title=i18n.t("np.select_dialog_title"),
                                          filetypes=filetypes)
        if path:
            self.set_video(path)

    def set_video(self, path: str):
        """Übernimmt ein ausgewähltes Video (File-Dialog UND Drag & Drop)."""
        self.video_path = path
        self.file_label.configure(text=os.path.basename(path))
        self.warning_label.configure(text="")

    def _on_drop(self, event):
        """Echte Datei wurde auf die Drop-Zone gezogen."""
        files = parse_dropped_files(self, event.data)
        video, error = pick_first_video(files)
        if video:
            self.set_video(video)
        else:
            self.warning_label.configure(text=error or i18n.t("np.invalid_file"))

    def _on_drag_enter(self, event=None):
        """Dezente Hervorhebung der Drop-Zone während des Drags (Theme-Tokens)."""
        self.drop_card.configure(border_color=self.color("accent"),
                                 fg_color=self.color("surface_secondary"))

    def _on_drag_leave(self, event=None):
        """Drop-Zone nach Verlassen wieder in den Normalzustand zurücksetzen."""
        self.drop_card.configure(border_color=self.color("border"),
                                 fg_color=self.color("surface"))

    def _on_model_change(self, choice: str):
        """Aktualisiert den technischen Modell-Hinweis."""
        self.model_hint.configure(text=i18n.t(MODEL_HINT_KEYS.get(choice, "")))

    def set_content_width(self, width: int):
        """Phase 34: feste Kartenbreiten responsiv anpassen."""
        self.drop_card.configure(width=width)

    def _on_continue(self):
        """Prüft die Daten und übergibt sie an den Processing-Screen.

        Die Verarbeitung startet dort automatisch über die CaptiPipeline.
        """
        if not getattr(self, "video_path", None):
            self.warning_label.configure(text=i18n.t("np.warn_no_video"))
            return
        if Path(self.video_path).suffix.lower() not in VALID_VIDEO_EXTENSIONS:
            self.warning_label.configure(text=i18n.t("np.warn_invalid"))
            return
        self.warning_label.configure(text="")

        # Phase 31: Projekt zwischenspeichern und zum Caption-Style-Schritt
        # navigieren – KEINE Verarbeitung hier (Pipeline startet erst nach
        # der Style-Auswahl über den Processing-Screen).
        self.controller.pending_project = {
            "video_path": self.video_path,
            "model": self.model_var.get(),
            "language": resolve_language_code(self.lang_var.get()),
        }
        self.navigate("caption_style")
