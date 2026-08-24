"""
Result-Screen: professionelle Erfolgsansicht nach der Verarbeitung.

Nur UI/API-Vorbereitung – die echte Pipeline-Anbindung kommt später.
Der Screen darf bei fehlenden/ungültigen Daten niemals abstürzen.
"""

import os
import subprocess
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from ui import i18n
from ui.screens.base import Screen


class ResultScreen(Screen):
    screen_name = "result"

    def build(self):
        self.grid_columnconfigure(0, weight=1)

        self.output_path: str = ""

        # ----------------------------------------------------------
        # Header
        # ----------------------------------------------------------
        title = ctk.CTkLabel(self, text=i18n.t("res.title"),
                             font=self.font("display", 44),
                             text_color=self.color("success"))
        title.grid(row=0, column=0, pady=(44, 4))

        subtitle = ctk.CTkLabel(self, text=i18n.t("res.subtitle"),
                                font=self.font("body", 14),
                                text_color=self.color("text_secondary"))
        subtitle.grid(row=1, column=0, pady=(0, 28))

        # ----------------------------------------------------------
        # Zentrale Ergebnis-Card
        # ----------------------------------------------------------
        card = ctk.CTkFrame(self, width=600, corner_radius=16,
                            fg_color=self.color("surface"),
                            border_width=1, border_color=self.color("border"))
        card.grid(row=2, column=0, padx=24, pady=(0, 24))
        card.grid_columnconfigure(0, weight=1)
        self.result_card = card

        # Erfolgs-Badge
        badge = ctk.CTkLabel(card, text=i18n.t("res.badge"),
                             font=self.font("technical", 12),
                             text_color=self.color("success"))
        badge.grid(row=0, column=0, sticky="w", padx=24, pady=(20, 8))

        # Dateiname
        self.filename_label = ctk.CTkLabel(card, text=i18n.t("res.no_result"),
                                           font=self.font("display", 22),
                                           anchor="w",
                                           text_color=self.color("text"))
        self.filename_label.grid(row=1, column=0, sticky="w", padx=24, pady=(0, 4))

        # Pfad (Orbitron-Metadaten)
        self.path_label = ctk.CTkLabel(card, text="",
                                       font=self.font("technical", 11),
                                       anchor="w",
                                       text_color=self.color("text_secondary"), wraplength=540)
        self.path_label.grid(row=2, column=0, sticky="w", padx=24, pady=(0, 10))

        # Technische Informationen (Modell · Sprache · Dauer · Auflösung)
        self.meta_label = ctk.CTkLabel(card, text="",
                                       font=self.font("technical", 11),
                                       anchor="w",
                                       text_color=self.color("text_secondary"))
        self.meta_label.grid(row=3, column=0, sticky="w", padx=24, pady=(0, 8))

        # Fehler-Zeile (falls Output ungültig/nicht vorhanden)
        self.error_label = ctk.CTkLabel(card, text="",
                                        font=self.font("body", 12),
                                        anchor="w",
                                        text_color=self.color("error"), wraplength=540)
        self.error_label.grid(row=4, column=0, sticky="w", padx=24, pady=(0, 16))

        # ----------------------------------------------------------
        # Buttons
        # ----------------------------------------------------------
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=3, column=0, pady=(0, 12))
        actions.grid_columnconfigure(0, weight=1)
        actions.grid_columnconfigure(1, weight=1)

        btn_open = ctk.CTkButton(
            actions, text=i18n.t("res.btn_open"), width=190, height=46,
            font=self.font("body", 14), corner_radius=10,
            fg_color=self.color("accent"), hover_color=self.color("accent_hover"),
            text_color="#1a1a1a",
            command=self.open_video)
        btn_open.grid(row=0, column=0, sticky="e", padx=(0, 10))

        btn_save = ctk.CTkButton(
            actions, text=i18n.t("res.btn_save_as"), width=190, height=46,
            font=self.font("body", 14), corner_radius=10,
            fg_color="transparent", border_width=1,
            border_color=self.color("border"),
            text_color=self.color("text"),
            command=self.save_as)
        btn_save.grid(row=0, column=1, sticky="w", padx=(10, 0))

        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.grid(row=4, column=0, pady=(4, 24))
        nav.grid_columnconfigure(0, weight=1)
        nav.grid_columnconfigure(1, weight=1)

        btn_new = ctk.CTkButton(
            nav, text=i18n.t("res.btn_new_project"), width=170, height=42,
            font=self.font("body", 13), corner_radius=8,
            fg_color="transparent", border_width=1,
            border_color=self.color("border"),
            text_color=self.color("text"),
            command=lambda: self.navigate("new_project"))
        btn_new.grid(row=0, column=0, sticky="e", padx=(0, 10))

        btn_home = ctk.CTkButton(
            nav, text=i18n.t("nav.home"), width=130, height=42,
            font=self.font("body", 13), corner_radius=8,
            fg_color="transparent", border_width=1,
            border_color=self.color("border"),
            text_color=self.color("text"),
            command=lambda: self.navigate("home"))
        btn_home.grid(row=0, column=1, sticky="w", padx=(10, 0))

    # ------------------------------------------------------------------
    # Screen-API
    # ------------------------------------------------------------------

    def set_result(self, output_path: str, filename: str = None,
                   model: str = None, language: str = None,
                   duration: str = None, resolution: str = None):
        """
        Setzt das Verarbeitungsergebnis.

        Alle optionalen Metadaten sind sicher verzichtbar; ein ungültiger
        oder nicht existierender Pfad erzeugt keinen Crash, sondern einen
        sichtbaren Fehlerhinweis im Theme-Farbschema.
        """
        self.output_path = str(output_path) if output_path else ""
        name = filename or (os.path.basename(self.output_path) if self.output_path else "")
        self.filename_label.configure(text=name or i18n.t("res.no_result"))
        self.path_label.configure(text=self.output_path)

        meta_parts = [str(p) for p in (model, language, duration, resolution) if p]
        self.meta_label.configure(text=" · ".join(meta_parts))

        if not self.output_path:
            self.error_label.configure(text=i18n.t("res.no_output"))
        elif not Path(self.output_path).exists():
            self.error_label.configure(text=i18n.t("res.output_missing"))
        else:
            self.error_label.configure(text="")

    def open_video(self):
        """Öffnet das erzeugte Video mit dem System-Standard-Programm.

        Kein Crash, wenn kein Output vorhanden ist oder die Datei fehlt.
        """
        if not self.output_path or not Path(self.output_path).exists():
            return
        try:
            os.startfile(self.output_path)  # Windows
        except AttributeError:
            try:
                subprocess.Popen(["xdg-open", self.output_path])
            except Exception:
                pass
        except Exception:
            pass

    def save_as(self):
        """Speichert das Ergebnis über den bestehenden File-Dialog an einen
        benutzerdefinierten Ort. Kein Crash ohne gültiges Output-Video."""
        if not self.output_path or not Path(self.output_path).exists():
            return
        default_name = os.path.basename(self.output_path)
        save_path = filedialog.asksaveasfilename(
            title=i18n.t("res.save_dialog_title"),
            defaultextension=".mp4",
            initialfile=default_name,
            filetypes=[("MP4 Video", "*.mp4"), ("Alle Dateien", "*.*")],
        )
        if save_path:
            try:
                import shutil
                shutil.copy2(self.output_path, save_path)
                self.error_label.configure(text="")
            except Exception as e:
                # Fehler sichtbar machen (kein stilles Verschlucken)
                self.error_label.configure(
                    text=i18n.t("res.save_failed", error=e))

    def reset(self):
        """Setzt den Screen für das nächste Projekt zurück."""
        self.output_path = ""
        self.filename_label.configure(text=i18n.t("res.no_result"))
        self.path_label.configure(text="")
        self.meta_label.configure(text="")
        self.error_label.configure(text="")