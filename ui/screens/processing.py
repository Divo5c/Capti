"""
Processing-Screen: moderne Fortschrittsansicht für die CaptiPipeline.

Der Screen besitzt eine saubere API (update_status, update_progress,
add_log, set_step, complete, show_error), über die der AppController
später die echten Pipeline-Callbacks anbindet. Keine Pipeline-Logik hier.
"""

import json
import os
import queue
import sys
from pathlib import Path

import customtkinter as ctk

from history import HistoryManager
from pipeline import CaptiPipeline
from ui import i18n
from ui.screens.base import Screen

# Verarbeitungsschritte (Reihenfolge = Pipeline-Ablauf; i18n-Keys)
STEPS = ["proc.step1", "proc.step2", "proc.step3", "proc.step4", "proc.step5"]

# Progress-Schwellen für die automatische Schritt-Zuordnung
_STEP_THRESHOLDS = [0, 20, 40, 65, 95]


class ProcessingScreen(Screen):
    screen_name = "processing"

    def build(self):
        self.grid_columnconfigure(0, weight=1)

        # Zustand
        self._nav_locked = False
        self._step_states = ["pending"] * len(STEPS)

        # ----------------------------------------------------------
        # 1) Header
        # ----------------------------------------------------------
        title = ctk.CTkLabel(self, text=i18n.t("proc.title"),
                             font=self.font("display", 40),
                             text_color=self.color("text"))
        title.grid(row=0, column=0, pady=(40, 4))

        subtitle = ctk.CTkLabel(self, text=i18n.t("proc.subtitle"),
                                font=self.font("body", 14),
                                text_color=self.color("text_secondary"))
        subtitle.grid(row=1, column=0, pady=(0, 24))

        # ----------------------------------------------------------
        # 2) Aktuelles Video (dezente Card)
        # ----------------------------------------------------------
        self.video_card = ctk.CTkFrame(self, width=560, height=76, corner_radius=12,
                                       fg_color=self.color("surface"),
                                       border_width=1, border_color=self.color("border"))
        self.video_card.grid(row=2, column=0, padx=24, pady=(0, 20))
        self.video_card.grid_propagate(False)
        self.video_card.grid_columnconfigure(0, weight=1)

        self.video_name_label = ctk.CTkLabel(self.video_card, text=i18n.t("proc.no_video"),
                                             font=self.font("body", 14),
                                             anchor="w",
                                             text_color=self.color("text"))
        self.video_name_label.grid(row=0, column=0, sticky="w", padx=20, pady=(10, 0))

        self.video_meta_label = ctk.CTkLabel(self.video_card, text="",
                                             font=self.font("technical", 11),
                                             anchor="w",
                                             text_color=self.color("text_secondary"))
        self.video_meta_label.grid(row=1, column=0, sticky="w", padx=20, pady=(0, 10))

        # ----------------------------------------------------------
        # 3) Fortschritt: große zentrale Anzeige
        # ----------------------------------------------------------
        progress_card = ctk.CTkFrame(self, width=560, corner_radius=16,
                                     fg_color=self.color("surface"),
                                     border_width=1, border_color=self.color("border"))
        progress_card.grid(row=3, column=0, padx=24, pady=(0, 20))
        progress_card.grid_columnconfigure(0, weight=1)

        self.percent_label = ctk.CTkLabel(progress_card, text="0 %",
                                          font=self.font("technical", 40),
                                          text_color=self.color("accent"))
        self.percent_label.grid(row=0, column=0, pady=(24, 8))

        self.progress_bar = ctk.CTkProgressBar(progress_card, height=10, corner_radius=5,
                                               fg_color=self.color("surface_secondary"),
                                               progress_color=self.color("accent"))
        self.progress_bar.grid(row=1, column=0, sticky="ew", padx=32)
        self.progress_bar.set(0)

        self.status_label = ctk.CTkLabel(progress_card, text=i18n.t("proc.preparing"),
                                         font=self.font("body", 13),
                                         text_color=self.color("text_secondary"))
        self.status_label.grid(row=2, column=0, pady=(10, 20))

        # ----------------------------------------------------------
        # 4) Verarbeitungsschritte (vertikale Anzeige)
        # ----------------------------------------------------------
        steps_card = ctk.CTkFrame(self, width=560, corner_radius=12,
                                  fg_color=self.color("surface"),
                                  border_width=1, border_color=self.color("border"))
        steps_card.grid(row=4, column=0, padx=24, pady=(0, 20))
        steps_card.grid_columnconfigure(0, weight=1)

        self._step_labels = []
        for i, step_name in enumerate(STEPS):
            lbl = ctk.CTkLabel(steps_card, text=self._format_step(i),
                               font=self.font("technical", 12),
                               anchor="w",
                               text_color=self.color("text_secondary"))
            lbl.grid(row=i, column=0, sticky="w", padx=24, pady=4)
            self._step_labels.append(lbl)
        # Letzten Schritt etwas mehr Abstand geben
        self._apply_step_colors()

        # ----------------------------------------------------------
        # 5) Log (dezente technische Anzeige)
        # ----------------------------------------------------------
        self.log_box = ctk.CTkTextbox(self, height=110, corner_radius=12,
                                      font=self.font("technical", 11),
                                      fg_color=self.color("surface"),
                                      border_width=1, border_color=self.color("border"),
                                      text_color=self.color("text_secondary"),
                                      wrap="word")
        self.log_box.grid(row=5, column=0, sticky="ew", padx=24, pady=(0, 8))
        self.log_box.configure(state="disabled")

        self.error_label = ctk.CTkLabel(self, text="",
                                        font=self.font("body", 13),
                                        text_color=self.color("error"), wraplength=560)
        self.error_label.grid(row=6, column=0, padx=24, pady=(0, 8))

        # ----------------------------------------------------------
        # 6) Navigation: dezenter Zurück-Button (nur wenn nicht gelockt)
        # ----------------------------------------------------------
        self.btn_back = ctk.CTkButton(
            self, text=i18n.t("common.back"), width=120, height=36,
            font=self.font("body", 13), corner_radius=8,
            fg_color="transparent", border_width=1,
            border_color=self.color("border"),
            text_color=self.color("text"),
            command=self._go_back)
        self.btn_back.grid(row=7, column=0, pady=(8, 24))

    # ------------------------------------------------------------------
    # Öffentliche API (spätere Pipeline-Anbindung)
    # ------------------------------------------------------------------

    def set_video_info(self, filename: str, model: str = "", language: str = ""):
        """Setzt Dateiname und technische Metadaten des aktuellen Videos."""
        self.video_name_label.configure(text=filename)
        meta_parts = [p for p in (model, language) if p]
        self.video_meta_label.configure(text=" · ".join(meta_parts))

    def update_status(self, message: str):
        """Aktualisiert den Status-Text (Pipeline-Callback on_status).

        Die Pipeline ist UI-agnostisch und liefert Status-Keys
        ("pipeline.*"); diese werden hier via i18n übersetzt.
        Freie Texte (z.B. Tests, Fehlerdetails) bleiben unverändert.
        """
        if isinstance(message, str) and message.startswith("pipeline."):
            message = i18n.t(message)
        self.status_label.configure(text=message)

    def update_progress(self, percent: float):
        """Aktualisiert Prozentanzeige, Bar und automatisch die Schritte."""
        percent = max(0.0, min(100.0, float(percent)))
        self.percent_label.configure(text=f"{int(round(percent))} %")
        self.progress_bar.set(percent / 100.0)
        # Automatische Schritt-Zuordnung (feinere Steuerung via set_step)
        if percent >= 100:
            self._step_states = ["completed"] * len(STEPS)
        else:
            active_index = 0
            for i, threshold in enumerate(_STEP_THRESHOLDS):
                if percent > threshold:
                    active_index = i
            for i in range(len(STEPS)):
                if i < active_index:
                    self._step_states[i] = "completed"
                elif i == active_index:
                    self._step_states[i] = "active"
                else:
                    self._step_states[i] = "pending"
        self._apply_step_colors()

    def add_log(self, level: str, message: str):
        """Hängt eine technische Log-Zeile an (Pipeline-Callback on_log)."""
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{level}] {message}" + chr(10))
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def set_step(self, index: int, state: str):
        """Setzt einen Schritt explizit: 'pending', 'active' oder 'completed'."""
        if 0 <= index < len(STEPS) and state in ("pending", "active", "completed"):
            self._step_states[index] = state
            self._apply_step_colors()

    def complete(self, output_path: str = ""):
        """Verarbeitung erfolgreich: alle Schritte fertig, 100 %.

        Navigation zum Result-Screen übernimmt später der AppController.
        """
        self._step_states = ["completed"] * len(STEPS)
        self._apply_step_colors()
        self.update_progress(100)
        self.update_status(i18n.t("proc.done"))
        self._nav_locked = False
        self.btn_back.configure(state="normal")

    def show_error(self, message: str):
        """Zeigt einen Fehler an und gibt die Navigation frei."""
        self.error_label.configure(text=i18n.t("proc.error_prefix", message=message))
        self.update_status(i18n.t("proc.failed"))
        self._nav_locked = False
        self.btn_back.configure(state="normal")

    def show_cancelled(self, message: str = ""):
        """Abbruch (B2): kein Fehlerdialog, nur Status + freie Navigation."""
        self.error_label.configure(text="")
        self.update_status(i18n.t("proc.cancelled"))
        self._nav_locked = False
        self.btn_back.configure(state="normal")

    def reset(self):
        """Setzt den Screen für eine neue Verarbeitung zurück."""
        self.update_progress(0)
        self._step_states = ["pending"] * len(STEPS)
        self._apply_step_colors()
        self.update_status(i18n.t("proc.preparing"))
        self.error_label.configure(text="")
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    # ------------------------------------------------------------------
    # Nav-Lock (aus Phase 3 beibehalten)
    # ------------------------------------------------------------------

    def lock_navigation(self):
        """Sperrt die Zurück-Navigation während eines laufenden Prozesses."""
        self._nav_locked = True
        self.btn_back.configure(state="disabled")

    def unlock_navigation(self):
        self._nav_locked = False
        self.btn_back.configure(state="normal")

    # ------------------------------------------------------------------
    # Pipeline-Integration (Phase 10)
    # ------------------------------------------------------------------

    def set_project(self, video_path: str, model: str = "small", language: str = None,
                    caption_style: dict = None):
        """
        Übernimmt die Projektdaten aus dem New-Project-Screen und startet
        die Verarbeitung automatisch über die bestehende CaptiPipeline.

        Args:
            video_path: Ausgewähltes Video
            model: Whisper-Modell ("tiny", "base", "small", "medium")
            language: Sprachcode ("de", "en") oder None für Auto
            caption_style: Optionaler projekt-spezifischer Caption Style
                           (None -> gespeicherter Style aus der Config)
        """
        self.video_path = video_path
        self.model = model
        self.language = language
        self.project_caption_style = caption_style

        self.reset()
        self.set_video_info(os.path.basename(video_path), model=model,
                            language=language or "Auto")
        self.lock_navigation()
        self.navigate("processing")
        self._start_pipeline()

    def _start_pipeline(self):
        """Startet die bestehende CaptiPipeline (run_async, nicht blockierend).

        Pipeline-Callbacks landen thread-safe in einer Queue; ein UI-Poller
        (self.after) verarbeitet sie im Main-Thread. Keine direkten
        Widget-Updates aus dem Pipeline-Thread.
        """
        self._ui_queue = queue.Queue()
        self._polling = True
        self.after(100, self._drain_ui_queue)

        self._pipeline = CaptiPipeline(
            temp_dir=self._temp_dir(),
            on_status=lambda msg: self._ui_queue.put(("status", msg)),
            on_progress=lambda pct: self._ui_queue.put(("progress", pct)),
            on_log=lambda level, msg: self._ui_queue.put(("log", (level, msg))),
            on_done=lambda path: self._ui_queue.put(("done", path)),
            on_error=lambda err: self._ui_queue.put(("error", err)),
            on_cancelled=lambda msg: self._ui_queue.put(("cancelled", msg)),
        )
        # Startup-/Vorverarbeitungs-Cleanup: Reste aus abgestürzten Läufen
        # entfernen, bevor die Pipeline den Ordner neu anlegt. Nur _temp,
        # niemals Output-Videos (liegen im Video-Ordner).
        self._cleanup_temp()
        # Projekt-spezifischer Style (Workflow) hat Vorrang vor dem
        # global gespeicherten Caption Style aus der Config.
        project_style = getattr(self, "project_caption_style", None)
        # Block 22: editierte Segmente (tiefe Kopie, video-genau) statt
        # Neutranskription. Nur bei vorhandenen Edits übergeben – sonst
        # exakt der bisherige Call (Vertrag mit PipelineJob unchanged).
        edited = self.controller.get_transcript_segments(self.video_path)
        # Block 23: merken, ob dieser Lauf Edits verwendet (Result-Hinweis).
        self._last_run_used_edits = edited is not None
        extra = {"override_segments": edited} if edited is not None else {}
        self._pipeline.run_async(self.video_path, model_size=self.model,
                                 language=self.language,
                                 caption_style=project_style
                                 if project_style else self._load_caption_style(),
                                 **extra)

    @staticmethod
    def _load_caption_style():
        """Lädt `caption_style` aus der Capti-Config (None = Renderer-Defaults).

        Nutzt die zentrale Config-Verwaltung (config.py).
        """
        from config import get_config_value
        style = get_config_value("caption_style")
        return style if isinstance(style, dict) and style else None

    def _drain_ui_queue(self):
        """Verarbeitet Pipeline-Events im Main-Thread (thread-safe)."""
        try:
            while True:
                kind, payload = self._ui_queue.get_nowait()
                if kind == "status":
                    self.update_status(payload)
                elif kind == "progress":
                    self.update_progress(payload)
                elif kind == "log":
                    self.add_log(*payload)
                elif kind == "done":
                    self._polling = False
                    self._on_pipeline_done(payload)
                    return
                elif kind == "error":
                    self._polling = False
                    # Block 22: Edit-State bleibt erhalten (last_transcript wird
                    # nur bei Erfolg geschrieben; Video-Match-Guard verhindert
                    # veraltete Anzeige in anderen Projekten).
                    self.show_error(payload)
                    self._cleanup_temp()
                    return
                elif kind == "cancelled":
                    self._polling = False
                    # Block 22: siehe error-Zweig (Edits überleben Cancel).
                    self.show_cancelled(payload)
                    return
        except queue.Empty:
            pass
        if self._polling:
            self.after(100, self._drain_ui_queue)

    @staticmethod
    def _temp_dir():
        """Temp-Ordner im System-Temp (B5) – Development und Frozen identisch."""
        try:
            from capti_core.paths import temp_dir
            return temp_dir()
        except Exception:
            if getattr(sys, "frozen", False):
                base = Path(os.path.dirname(sys.executable))
            else:
                base = Path(__file__).parent.parent.parent  # Projektordner
            return base / "_temp"

    @staticmethod
    def _cleanup_temp():
        """Löscht den _temp-Ordner (gleiche Logik wie Legacy-UI).

        Erfolgt erst NACH Abschluss der Verarbeitung (done/error) – das
        Output-Video liegt im Video-Ordner und wird nie berührt.
        """
        import shutil
        try:
            temp = ProcessingScreen._temp_dir()
            if temp.exists():
                shutil.rmtree(temp)
        except Exception:
            pass  # Cleanup darf niemals die App zum Absturz bringen

    def _on_pipeline_done(self, output_path: str):
        """Pipeline erfolgreich: History-Eintrag, Result-Screen, Navigation frei."""
        # Block 20: echtes Transkript für die Preview sichern (Main-Thread,
        # nur Plain-Daten; Pipeline hält gruppierte Segmente + Quellvideo).
        try:
            pipe = getattr(self, "_pipeline", None)
            segments = getattr(pipe, "last_segments", None)
            if isinstance(segments, list) and segments:
                self.controller.last_transcript = {
                    "video_path": self.video_path,
                    "segments": segments,
                    "model": self.model,
                    "language": self.language,
                }
            else:
                self.controller.last_transcript = None
        except Exception:
            pass
        # History-Eintrag nur bei Erfolg (HistoryManager schreibt selbst)
        HistoryManager().add_entry(
            video_path=self.video_path,
            output_path=output_path,
            model=self.model,
            language=self.language or "",
        )
        self.complete(output_path)

        result = self.controller.get_screen("result")
        result.set_result(
            output_path,
            filename=os.path.basename(self.video_path),
            model=self.model,
            language=self.language,
            video_path=self.video_path,
            caption_style=getattr(self, "project_caption_style", None),
            with_edits=bool(getattr(self, "_last_run_used_edits", False)),
        )
        self.navigate("result")
        self._cleanup_temp()  # Erfolg: Temp-Dateien (WAV/SRT/ASS) entfernen

    def on_show(self):
        # Nav-Lock bleibt bestehen, bis complete()/show_error() freigibt
        pass

    def on_hide(self):
        pass

    def destroy(self):
        """Fordert bei laufender Verarbeitung Cancel an (B2, nicht blockierend)."""
        try:
            pipe = getattr(self, "_pipeline", None)
            if pipe is not None:
                pipe.cancel()
        except Exception:
            pass
        super().destroy()

    def _go_back(self):
        if not self._nav_locked:
            self.navigate("home")

    # ------------------------------------------------------------------
    # Intern
    # ------------------------------------------------------------------

    def _format_step(self, index: int) -> str:
        state = self._step_states[index]
        symbol = {"pending": "○", "active": "◐", "completed": "●"}[state]
        return f"{symbol}  {index + 1}. {i18n.t(STEPS[index])}"

    def _apply_step_colors(self):
        for i, lbl in enumerate(self._step_labels):
            state = self._step_states[i]
            if state == "completed":
                color = self.color("success")
            elif state == "active":
                color = self.color("accent")
            else:
                color = self.color("text_secondary")
            lbl.configure(text=self._format_step(i), text_color=color)