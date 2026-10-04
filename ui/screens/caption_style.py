"""
Caption-Style-Screen: Konfiguration des Caption-Designs.

Speichert die Einstellungen in der bestehenden Capti-Config unter dem
Key `caption_style` – bestehende Config-Werte bleiben erhalten.

Die Caption-Engine/Renderer bleiben unverändert; dieser Screen bereitet
die Werte vor, die später an den Renderer übergeben werden können.
"""

import json
import math
import os
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from caption_renderer import CaptionRenderer
from ui import i18n
from ui.screens.base import Screen

# ---------------------------------------------------------------------
# Defaults & Presets: eine einzige kanonische Quelle (capti_core).
# Die Werte entsprechen exakt dem bisherigen Capti-Look.
# ---------------------------------------------------------------------
from capti_core.caption_style import DEFAULT_CAPTION_STYLE as DEFAULT_STYLE
from capti_core.caption_style import PRESETS
from capti_core.render_model import (
    captions_from_segments, pop_state_at, pop_windows,
)
from capti_core.caption_draft import (
    apply_snapshot as _draft_apply_snapshot,
    apply_text as _draft_apply_text,
    draft_from_caption as _draft_from_caption,
    delete_word as _draft_delete_word,
    insert_word as _draft_insert_word,
    merge_words as _draft_merge_words,
    set_caption_timing as _draft_set_caption_timing,
    set_word_timing as _draft_set_word_timing,
    split_word_at as _draft_split_word_at,
    snapshot_of_draft as _draft_snapshot,
    split_word as _draft_split_word,
    to_segment as _draft_to_segment,
)
from capti_core.undo_history import UndoHistory

# Robuste Farbauswahl ohne zusätzliche Dependency
COLOR_CHOICES = ["#FFFFFF", "#FFFF00", "#FF3B30", "#4EC9B0", "#FFD60A",
                 "#101010", "#000000", "#5A5A5A"]


# Timing-Leiste (Block 30): reine Zeit<->Pixel-Abbildung, Tk-frei testbar.
# Die Leiste zeigt immer die ABSOLUTE Caption-Spanne (kein 0-Relativieren).
_TIMELINE_PAD = 10
_TIMELINE_HANDLE_R = 7

# Feinjustierung (Block 31/34): effektive Schrittweite aus EXAKT EINER
# Quelle – der Settings-Config (ui.screens.settings.NUDGE_STEP_KEY).
# Buttons, Keyboard-Nudge und Shortcut-Hinweis lesen sie ausschließlich
# über get_nudge_step() (live, ohne Neustart). Default dort definiert.
from ui.screens.settings import read_nudge_step


def get_nudge_step() -> float:
    """Effektive Nudge-Schrittweite in Sekunden (Single Source)."""
    return read_nudge_step()


def _format_nudge_step() -> str:
    """Schrittweite als Anzeigetext aus get_nudge_step() (DE: Komma)."""
    text = f"{get_nudge_step():.2f}"
    if i18n.get_language() == "de":
        text = text.replace(".", ",")
    return text


def _timeline_x(t, width, cap_start, cap_end, pad=_TIMELINE_PAD):
    """Absolute Zeit -> Canvas-X (geklemmt, deterministisch)."""
    span = float(cap_end) - float(cap_start)
    if not span > 0 or width <= 2 * pad:
        return float(pad)
    frac = (float(t) - float(cap_start)) / span
    return pad + min(1.0, max(0.0, frac)) * (width - 2 * pad)


def _timeline_t(x, width, cap_start, cap_end, pad=_TIMELINE_PAD):
    """Canvas-X -> absolute Zeit (geklemmt, deterministisch)."""
    span = float(cap_end) - float(cap_start)
    if not span > 0 or width <= 2 * pad:
        return float(cap_start)
    frac = (float(x) - pad) / (width - 2 * pad)
    return float(cap_start) + min(1.0, max(0.0, frac)) * span


def _finite_or_none(word, key):
    """Finite Float-Zeit aus Dict/Objekt oder None (Block 40, Draw-Guard).

    Schützt Canvas-Zeichnung vor TclError bei kaputten Wortzeiten;
    Validierung bleibt in set_word_timing()/set_caption_timing().
    """
    try:
        if isinstance(word, dict):
            value = word[key]
        else:
            value = getattr(word, key)
        number = float(value)
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _snap_marker_x(time, width, dom_start, dom_end, pad=_TIMELINE_PAD):
    """Snap-Zeit -> Canvas-X, UNGEKLEMMT (Block 40).

    Selbe lineare Abbildung wie Drag-Mapping (frozen Domain), damit
    der Marker exakt auf dem Snap-Zeitpunkt liegt – auch bei
    Erweiterung über die alte Caption-Grenze hinaus.
    """
    span = float(dom_end) - float(dom_start)
    if not span > 0 or width <= 2 * pad:
        return float(pad)
    return pad + (float(time) - float(dom_start)) / span * (width - 2 * pad)


# Snap-Toleranz (Block 38/41): Pixelabstand, ab dem ein Handle
# magnetisch an eine Wortgrenze springt. Skaliert automatisch über
# Pixel/Sekunde der eingefrorenen Drag-Domain mit. Einzige Quelle der
# Wahrheit ist die Settings-Config (ui.screens.settings.SNAP_TOLERANCE_KEY),
# gelesen live über get_snap_tolerance_px() – keine harte Konstante hier.
from ui.screens.settings import read_snap_tolerance


def get_snap_tolerance_px() -> float:
    """Effektive Snap-Toleranz in px (Single Source: Settings)."""
    return read_snap_tolerance()


def _raw_time(word, key):
    """Finite, nicht-negative Zeit aus Dict/Objekt oder None (Block 39).

    Nie Crash bei kaputten Daten; gemeinsame Basis für alle Snap-
    Kandidaten (Caption- wie Wort-Handles).
    """
    try:
        if isinstance(word, dict):
            value = word[key]
        else:
            value = getattr(word, key)
        moment = float(value)
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    if not math.isfinite(moment) or moment < 0:
        return None
    return moment


def _snap_candidates(words, which):
    """Gültige Snap-Zeiten: Wort-Starts (Start-Handle) / Wort-Enden.

    Nur finite, nicht-negative Zeiten aus parsebaren Wörtern (Dicts
    oder RenderWord-Objekte); Rest wird ignoriert, nie gecrasht.
    """
    key = "start" if which == "start" else "end"
    points = []
    for word in words or []:
        moment = _raw_time(word, key)
        if moment is not None:
            points.append(moment)
    return points


def _word_snap_candidates(cap, words, widx, which):
    """Snap-Ziele für Wort-Handles (Block 39): nur direkte Nachbarn.

    Start: [Caption-Start, vorheriges Wort-Ende]; Ende: [nächstes
    Wort-Start, Caption-Ende]. Reihenfolge = Priorität (deterministisch).
    Niemals das eigene andere Ende, niemals ferne Wörter.
    """
    points = []
    if which == "start":
        points.append(cap.start)
        if widx > 0 and widx - 1 < len(words):
            prev_end = _raw_time(words[widx - 1], "end")
            if prev_end is not None:
                points.append(prev_end)
    else:
        if 0 <= widx < len(words) - 1:
            next_start = _raw_time(words[widx + 1], "start")
            if next_start is not None:
                points.append(next_start)
        points.append(cap.end)
    return points


def _snap_time(moment, candidates, tolerance_px, px_per_sec):
    """Nächster Kandidat innerhalb Toleranz oder None (Block 38).

    Distanz in Pixeln (skalierungsabhängig); bei gleichem Abstand
    gewinnt der erste Kandidat in Wortreihenfolge (deterministisch).
    """
    if px_per_sec is None or not px_per_sec > 0:
        return None
    best = None
    best_dist = None
    for candidate in candidates:
        dist = abs((candidate - moment) * px_per_sec)
        if dist <= tolerance_px and (best is None or dist < best_dist):
            best, best_dist = candidate, dist
    return best


LAYOUT_INFO = ("Dynamisches Layout: Portrait/Landscape werden automatisch "
               "berechnet · max. 2 Zeilen · Safe Area unten")


# Zentrale Config-Verwaltung (Single Source of Truth).
# _config_file bleibt als dünner Alias patchbar (Tests); Lese/Schreib-
# Logik liegt vollständig in config.py.
from config import load_config, save_config, config_file as _config_file


def _read_config() -> dict:
    return load_config(_config_file())


def _write_config(config: dict) -> bool:
    return save_config(config, _config_file())


class CaptionStyleScreen(Screen):
    screen_name = "caption_style"

    def build(self):
        self.grid_columnconfigure(0, weight=1)

        self.style = dict(DEFAULT_STYLE)

        # ----------------------------------------------------------
        # 1) Header
        # ----------------------------------------------------------
        ctk.CTkLabel(self, text=i18n.t("cs.title"),
                     font=self.font("display", 40),
                     text_color=self.color("text")).grid(row=0, column=0, pady=(40, 4))
        ctk.CTkLabel(self, text=i18n.t("cs.subtitle"),
                     font=self.font("body", 14),
                     text_color=self.color("text_secondary")).grid(row=1, column=0, pady=(0, 24))

        # ----------------------------------------------------------
        # 2) Preview-Card: video-ähnliche animierte Caption-Vorschau
        #    (Portrait 1080x1920 maßstäblich, echte Renderer-Werte)
        # ----------------------------------------------------------
        preview_card = ctk.CTkFrame(self, width=620, height=420, corner_radius=16,
                                    fg_color=self.color("surface"),
                                    border_width=1, border_color=self.style["outline_color"])
        preview_card.grid(row=2, column=0, padx=24, pady=(0, 16))
        preview_card.grid_columnconfigure((0, 1), weight=1)
        self._preview_card = preview_card

        ctk.CTkLabel(preview_card, text=i18n.t("cs.preview"),
                     font=self.font("technical", 10),
                     text_color=self.color("text_secondary")).grid(
            row=0, column=0, pady=(14, 6))

        # Replay-Button (klein, rechts) – startet die Pop-Animation neu
        self.btn_replay = ctk.CTkButton(
            preview_card, text=i18n.t("cs.preview_replay"), width=34, height=34,
            corner_radius=17, font=self.font("body", 14),
            fg_color=self.color("surface_secondary"),
            hover_color=self.color("accent_hover"),
            text_color=self.color("text"),
            command=self._restart_preview_animation)
        self.btn_replay.grid(row=0, column=1, padx=(0, 16), pady=(10, 0), sticky="e")

        # Video-artige Vorschaufläche (schwarz wie ein Video, Portrait-Seite)
        import tkinter as _tk
        PREVIEW_W, PREVIEW_H = 336, 480   # entspricht 9:16 (skaliertes Video)
        self._preview_size = (PREVIEW_W, PREVIEW_H)
        self.preview_canvas = _tk.Canvas(
            preview_card, width=PREVIEW_W, height=PREVIEW_H,
            bg="#000000", highlightthickness=1,
            highlightbackground=self.color("border"))
        self.preview_canvas.grid(row=1, column=0, columnspan=2, pady=(4, 18))

        # Animationszustand
        self._preview_after_id = None
        self._preview_words = []       # [(word, x, y)] Pixelpositionen
        self._preview_font = None      # tkfont.Font Instanz
        self._preview_timeline = []    # [(start_ms, end_ms, word_index)]
        self._preview_t0 = 0           # Startzeit der aktuellen Animation
        self._preview_caption = None   # RenderCaption (Quelle der Wahrheit)
        self._preview_mode = "sample"    # "sample" | "transcript"
        self._transcript_segments = []   # rohe Transkript-Segmente (nur transcript)
        self._transcript_captions = ()   # RenderCaption-Tupel (nur transcript)


        self._apply_preview()

        # ----------------------------------------------------------
        # 3) Caption-Editor (Block 21, Transkript-Modus)
        # ----------------------------------------------------------
        self._build_editor_card()

        # ----------------------------------------------------------
        # 4) Presets
        # ----------------------------------------------------------
        preset_frame = ctk.CTkFrame(self, fg_color="transparent")
        preset_frame.grid(row=4, column=0, pady=(0, 12))
        for i, name in enumerate(PRESETS):
            btn = ctk.CTkButton(
                preset_frame, text=name, width=150, height=36,
                font=self.font("body", 13), corner_radius=8,
                fg_color="transparent", border_width=1,
                border_color=self.color("border"),
                text_color=self.color("text"),
                command=lambda n=name: self.apply_preset(n))
            btn.grid(row=0, column=i, padx=6)

        # ----------------------------------------------------------
        # 5) Farben
        # ----------------------------------------------------------
        colors_card = self._make_card(5, i18n.t("cs.card_colors"))
        self._color_vars = {}
        rows = [(i18n.t("cs.color.normal"), "normal_color"),
                (i18n.t("cs.color.highlight"), "highlight_color"),
                (i18n.t("cs.color.outline"), "outline_color"),
                (i18n.t("cs.color.shadow"), "shadow_color")]
        for r, (label, key) in enumerate(rows):
            ctk.CTkLabel(colors_card, text=label, font=self.font("body", 13), anchor="w",
                         text_color=self.color("text")).grid(
                row=r, column=0, sticky="w", padx=24, pady=6)
            var = ctk.StringVar(value=self.style[key])
            self._color_vars[key] = var
            combo = ctk.CTkComboBox(
                colors_card, variable=var, values=COLOR_CHOICES, width=140, height=32,
                corner_radius=8, font=self.font("technical", 12),
                fg_color=self.color("surface_secondary"),
                button_color=self.color("border"),
                button_hover_color=self.color("accent_hover"),
                border_color=self.color("border"),
                text_color=self.color("text"),
                command=lambda _c, k=key: self._on_color_change(k))
            combo.grid(row=r, column=1, sticky="w", padx=20, pady=6)
            swatch = ctk.CTkLabel(colors_card, text="", width=40, height=24, corner_radius=6,
                                   fg_color=self.style[key])
            swatch.grid(row=r, column=2, padx=(0, 24))
            self._color_swatches = getattr(self, "_color_swatches", {})
            self._color_swatches[key] = swatch

        # ----------------------------------------------------------
        # 6) Pop-Effekt
        # ----------------------------------------------------------
        pop_card = self._make_card(6, i18n.t("cs.card_pop"))
        self.pop_switch_var = ctk.BooleanVar(value=self.style["pop_enabled"])
        ctk.CTkSwitch(pop_card, text=i18n.t("cs.pop_enabled"), variable=self.pop_switch_var,
                      font=self.font("body", 13), progress_color=self.color("accent"),
                      text_color=self.color("text")).grid(
            row=0, column=0, sticky="w", padx=24, pady=(16, 8))

        ctk.CTkLabel(pop_card, text=i18n.t("cs.pop_scale"), font=self.font("body", 13), anchor="w",
                     text_color=self.color("text")).grid(row=1, column=0, sticky="w", padx=24, pady=4)
        self.pop_scale_slider = ctk.CTkSlider(pop_card, from_=100, to=150, width=220,
                                              progress_color=self.color("accent"),
                                              command=lambda v: self._on_pop_change())
        self.pop_scale_slider.set(self.style["pop_scale"])
        self.pop_scale_slider.grid(row=2, column=0, sticky="w", padx=24, pady=4)
        self.pop_scale_value = ctk.CTkLabel(pop_card, text=str(int(self.style["pop_scale"])),
                                            font=self.font("technical", 12),
                                            text_color=self.color("text_secondary"))
        self.pop_scale_value.grid(row=2, column=1, padx=12)

        ctk.CTkLabel(pop_card, text=i18n.t("cs.pop_decay"), font=self.font("body", 13), anchor="w",
                     text_color=self.color("text")).grid(row=3, column=0, sticky="w", padx=24, pady=4)
        self.pop_decay_slider = ctk.CTkSlider(pop_card, from_=50, to=400, width=220,
                                              progress_color=self.color("accent"),
                                              command=lambda v: self._on_pop_change())
        self.pop_decay_slider.set(self.style["pop_decay_ms"])
        self.pop_decay_slider.grid(row=4, column=0, sticky="w", padx=24, pady=(4, 16))
        self.pop_decay_value = ctk.CTkLabel(pop_card, text=str(int(self.style["pop_decay_ms"])),
                                            font=self.font("technical", 12),
                                            text_color=self.color("text_secondary"))
        self.pop_decay_value.grid(row=4, column=1, padx=12)

        # ----------------------------------------------------------
        # 7) Layout (nur Anzeige – dynamisches Layout bleibt Grundlage)
        # ----------------------------------------------------------
        layout_card = self._make_card(7, i18n.t("cs.card_layout"))
        ctk.CTkLabel(layout_card, text=i18n.t("cs.layout_info"), font=self.font("body", 12), anchor="w",
                     text_color=self.color("text_secondary"), wraplength=520, justify="left").grid(
            row=0, column=0, sticky="w", padx=24, pady=(16, 16))

        # ----------------------------------------------------------
        # 8) Schrift
        # ----------------------------------------------------------
        font_card = self._make_card(8, i18n.t("cs.card_font"))
        ctk.CTkLabel(font_card, text=i18n.t("cs.font_current"),
                      font=self.font("body", 13), anchor="w",
                      text_color=self.color("text")).grid(
            row=0, column=0, sticky="w", padx=24, pady=(16, 2))
        ctk.CTkLabel(font_card, text=i18n.t("cs.font_value", name=self.style["font_name"],
                                            size=self.style["font_size"]),
                     font=self.font("technical", 13), anchor="w",
                     text_color=self.color("accent")).grid(
            row=1, column=0, sticky="w", padx=24, pady=(0, 16))

        # ----------------------------------------------------------
        # 9) Speichern + Erfolgsmeldung
        # ----------------------------------------------------------
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=9, column=0, pady=(16, 4))
        ctk.CTkButton(footer, text=i18n.t("set.btn_save"), width=220, height=46,
                      font=self.font("display", 14), corner_radius=10,
                      fg_color=self.color("accent"), hover_color=self.color("accent_hover"),
                      text_color="#1a1a1a",
                      command=self.save_style).grid(row=0, column=0)
        self.success_label = ctk.CTkLabel(footer, text="", font=self.font("body", 12),
                                          text_color=self.color("success"))
        self.success_label.grid(row=1, column=0, pady=(10, 0))

        ctk.CTkLabel(footer, text=i18n.t("cs.footer_note"),
                     font=self.font("technical", 10),
                     text_color=self.color("text_secondary")).grid(row=2, column=0, pady=(6, 0))
        ctk.CTkButton(footer, text=i18n.t("cs.project_save"), width=220, height=40,
                      font=self.font("body", 13), corner_radius=10,
                      fg_color="transparent", border_width=1,
                      border_color=self.color("border"),
                      text_color=self.color("text"),
                      command=self.save_project_file).grid(row=3, column=0, pady=(10, 0))

        # ----------------------------------------------------------
        # 10) Workflow-Steuerung (Projektmodus) + Zurück
        # ----------------------------------------------------------
        self.btn_start = ctk.CTkButton(
            self, text=i18n.t("cs.start_processing"), width=260, height=48,
            font=self.font("display", 15), corner_radius=10,
            fg_color=self.color("accent"), hover_color=self.color("accent_hover"),
            text_color="#1a1a1a",
            command=self._start_project_workflow)
        self.btn_start.grid(row=11, column=0, pady=(4, 8))

        self.btn_back = ctk.CTkButton(
            self, text=i18n.t("common.back"), width=120, height=36,
            font=self.font("body", 13), corner_radius=8,
            fg_color="transparent", border_width=1,
            border_color=self.color("border"),
            text_color=self.color("text"),
            command=lambda: self.navigate(
                "new_project" if getattr(self.controller, "pending_project", None)
                else "home"))
        self.btn_back.grid(row=12, column=0, pady=(8, 24))

        # Gespeicherte Werte laden (nach dem Widget-Aufbau)
        self.load_style()
        self._refresh_workflow_mode()
        self._refresh_editor()

    def _workflow_active(self) -> bool:
        """True, wenn der Screen als Projekt-Schritt (New Project) läuft."""
        return bool(getattr(self.controller, "pending_project", None))

    def _refresh_workflow_mode(self):
        """Passt Start-/Zurück-Buttons an den aktuellen Modus an."""
        workflow = self._workflow_active()
        if workflow:
            self.btn_start.grid()
            self.btn_back.configure(text=i18n.t("cs.back_to_project"))
        else:
            self.btn_start.grid_remove()
            self.btn_back.configure(text=i18n.t("common.back"))

    def on_show(self):
        """Modus kann sich seit dem letzten Besuch geändert haben."""
        self._refresh_workflow_mode()

    def _start_project_workflow(self):
        """Übergibt das vorbereitete Projekt inkl. Style an Processing.

        Der aktuell im Screen gewählte Style (Preset/Anpassungen) wird
        merge-sicher in die Config gespeichert und projekt-spezifisch an
        die Pipeline übergeben.
        """
        project = getattr(self.controller, "pending_project", None)
        if not project:
            return  # Normaler Modus (globale Style-Verwaltung): nichts tun
        style_for_project = dict(self.style)
        self.save_style()  # merge-sicher persistieren (letzte Auswahl)
        self.controller.pending_project = None
        processing = self.controller.get_screen("processing")
        processing.set_project(project["video_path"],
                               model=project["model"],
                               language=project["language"],
                               caption_style=style_for_project)

    # ------------------------------------------------------------------
    # Helfer
    # ------------------------------------------------------------------

    def _make_card(self, row: int, title: str) -> ctk.CTkFrame:
        card = ctk.CTkFrame(self, width=620, corner_radius=12,
                            fg_color=self.color("surface"),
                            border_width=1, border_color=self.color("border"))
        card.grid(row=row, column=0, padx=24, pady=(0, 12))
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text=title, font=self.font("body", 15), anchor="w",
                     text_color=self.color("text")).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=24, pady=(16, 8))
        return card

    def _apply_preview(self):
        """Aktualisiert die animierte Vorschau aus dem aktuellen Style.

        Verwendet dieselbe Style-Semantik wie der echte Renderer
        (Layout via CaptionRenderer.compute_layout, pop_scale/pop_decay).
        """
        self._preview_card.configure(border_color=self.style["outline_color"])
        self._rebuild_preview_layout()
        self._restart_preview_animation()

    def _cancel_preview_timer(self):
        if getattr(self, "_preview_after_id", None) is not None:
            try:
                self.after_cancel(self._preview_after_id)
            except Exception:
                pass
            self._preview_after_id = None

    def _restart_preview_animation(self):
        """Startet die Karaoke-/Pop-Animation von vorn."""
        import time
        self._cancel_preview_timer()
        self._rebuild_preview_layout()
        self._preview_epoch = time.monotonic()
        self._draw_preview_frame(0)
        self._schedule_preview_tick(33)

    def _schedule_preview_tick(self, delay_ms: int):
        self._preview_after_id = self.after(delay_ms, self._preview_tick)

    def _preview_tick(self):
        """Ein Animationsschritt (~30 fps) über den Tk-Main-Loop."""
        import time
        try:
            if not bool(self.winfo_exists()):
                return
        except Exception:
            return
        try:
            t_ms = int((time.monotonic() - self._preview_epoch) * 1000)
            if t_ms > self._preview_total_ms + 1200:
                self._restart_preview_animation()   # Loop mit kurzer Pause
                return
            self._draw_preview_frame(t_ms)
            self._schedule_preview_tick(33)
        except Exception:
            # Widget bereits zerstört (z.B. Screen-Wechsel im Test/Close)
            self._cancel_preview_timer()

    # Synthetischer Sample-Zeitplan der Preview (Sample-Daten, keine Logik):
    # Wort ~450 ms gesprochen + 60 ms Pause ab t=300 ms (wie bisher).
    _PREVIEW_WORD_MS = 450.0
    _PREVIEW_GAP_MS = 60.0
    _PREVIEW_T0_MS = 300.0

    def _build_sample_caption(self, words, layout):
        """Synthetische Sample-Caption (NUR Sample-Daten: 450/60/300).

        Darf NIEMALS für echte Transkript-Daten verwendet werden (dafür
        set_transcript()). Gibt None zurück, wenn keine Wörter vorhanden.
        """
        synth = [{
            "word": word,
            "start": (self._PREVIEW_T0_MS + i * (self._PREVIEW_WORD_MS + self._PREVIEW_GAP_MS)) / 1000.0,
            "end": (self._PREVIEW_T0_MS + i * (self._PREVIEW_WORD_MS + self._PREVIEW_GAP_MS)
                    + self._PREVIEW_WORD_MS) / 1000.0,
        } for i, word in enumerate(words)]
        if not synth:
            return None
        # Caption-Spanne ab 0.0: pop_windows() rechnet relativ zu
        # cap.start – so bleiben die Fenster absolut (wie Legacy-Slots).
        segment = {
            "start": 0.0,
            "end": synth[-1]["end"],
            "text": " ".join(words),
            "words": synth,
        }
        (caption,) = captions_from_segments(
            [segment], dict(self.style), dict(layout))
        return caption

    def set_transcript(self, segments):
        """Übernimmt echte Transkript-Segmente (TRANSCRIPT-Modus, Block 19).

        Die Segmente (Whisper-Format: start/end/text/words) werden 1:1 über
        captions_from_segments() ins Render-Modell überführt – echte
        Word-Timestamps, keine synthetischen Zeiten. Leere Eingabe schaltet
        zurück in den Sample-Modus.
        """
        self._transcript_segments = list(segments or [])
        self._preview_mode = "transcript" if self._transcript_segments else "sample"
        self._transcript_captions = ()
        self._clear_histories()  # Block 27: neues Transkript, neue History
        self._rebuild_preview_layout()
        self._restart_preview_animation()

    def clear_transcript(self):
        """Zurück zum Sample-Modus."""
        self._transcript_segments = []
        self._transcript_captions = ()
        self._preview_mode = "sample"
        self._clear_histories()  # Block 27: kein Transkript, keine History
        self._rebuild_preview_layout()
        self._restart_preview_animation()

    def _display_caption(self, caption, total_ms):
        """Zeigt eine Caption an (gemeinsamer Adapter-Pfad, Block 19).

        Timeline, Total-Anzeige und Pixel-Einträge werden aus der Caption
        abgeleitet – unabhängig davon, ob sie synthetisch oder echt ist.
        Die Timeline-Slots sind absolute ms-Fenster pro Wort (wie Legacy)
        und existieren unabhängig vom pop_enabled-Flag (Highlight nutzt
        pop_state_at, ebenfalls aus dem Modell).
        """
        self._preview_caption = caption
        if caption is None:
            self._preview_words = []
            self._preview_timeline = []
        else:
            try:
                decay = max(1, int(caption.style.get("pop_decay_ms", 150)))
            except (TypeError, ValueError):
                decay = 150
            # Kaputte Wortzeiten (NaN/Inf) überspringen statt crashen
            # (Block 40); Timeline dient nur als Existenz-Indikator.
            self._preview_timeline = [
                {"start": round(w.start * 1000),
                 "end": round(w.end * 1000),
                 "decay_end": round(w.end * 1000) + decay}
                for w in caption.words
                if _finite_or_none(w, "start") is not None
                and _finite_or_none(w, "end") is not None
            ]
            self._preview_words = self._layout_caption_entries(caption)
        self._preview_total_ms = total_ms

    def _layout_caption_entries(self, caption):
        """Tk-Pixelpositionen für eine Caption (reiner UI-Adapter).

        Zeilen und Wörter stammen aus dem Modell; nur Messung und
        Zentrierung sind Tk-spezifisch.
        """
        W, H = self._preview_size
        margin_v = caption.layout.get("margin_v", 384)
        play_res_y = caption.layout.get("play_res_y", 1920) or 1920
        px = int(self._preview_font.cget("size"))
        line_groups = [
            [caption.words[i].word for i in idxs]
            for idxs in caption.lines
        ][:2]
        margin_frac = margin_v / play_res_y              # Safe Area unten
        line_h = px * 1.3
        ys = [H * (1 - margin_frac) - line_h * (len(line_groups) - 1 - k)
              for k in range(len(line_groups))]
        f = self._preview_font
        space_w = f.measure(" ")
        entries = []
        for li, line_words in enumerate(line_groups):
            widths = [f.measure(word) for word in line_words]
            x = (W - (sum(widths) + space_w * (len(line_words) - 1))) / 2
            y = ys[li]
            for word, wd in zip(line_words, widths):
                entries.append({"text": word, "x": x, "y": y, "w": wd})
                x += wd + space_w
        return entries

    def _select_transcript_caption(self, t_ms):
        """Wählt die Caption für t_ms auf absoluter Timeline (Block 19).

        Policy: Caption mit start <= t < end; sonst nächste kommende,
        sonst letzte. Keine implizite Rücksetzung auf 0.
        """
        caps = self._transcript_captions
        if not caps:
            if self._preview_caption is not None or self._preview_words \
                    or self._preview_timeline:
                self._display_caption(None, self._preview_total_ms)
            return None
        selected = None
        for cap in caps:
            if cap.start * 1000 <= t_ms < cap.end * 1000:
                selected = cap
                break
        if selected is None:
            upcoming = [c for c in caps if c.start * 1000 > t_ms]
            selected = upcoming[0] if upcoming else caps[-1]
        if selected is not self._preview_caption:
            self._display_caption(selected, self._preview_total_ms)
        return selected

    def _rebuild_preview_layout(self):
        """Baut Sample- ODER Transkript-Caption und zeigt sie an.

        Quelle der Wahrheit ist immer eine RenderCaption; Pixelmessung und
        Timeline-Ableitung laufen über den gemeinsamen Adapter-Pfad.
        """
        import tkinter.font as tkfont

        _, H = self._preview_size
        VIDEO_W, VIDEO_H = 1080, 1920    # virtuelle Videogröße (Portrait)
        layout = CaptionRenderer.compute_layout(VIDEO_W, VIDEO_H)
        px = max(12, int(round(layout["font_size"] * (H / VIDEO_H))))
        family = self.style.get("font_name") or "Arial Black"
        self._preview_font = tkfont.Font(family=family, size=px, weight="bold")

        decay = max(1, int(self.style.get("pop_decay_ms", 150)))
        if self._preview_mode == "transcript" and self._transcript_segments:
            self._transcript_captions = captions_from_segments(
                self._transcript_segments, dict(self.style), dict(layout))
            if self._transcript_captions:
                last_end = self._transcript_captions[-1].end
                self._display_caption(self._transcript_captions[0],
                                      last_end * 1000 + 1200)
            else:
                self._display_caption(None, 0)
        else:
            self._preview_mode = "sample"
            words = i18n.t("cs.preview_sentence").split()
            caption = self._build_sample_caption(words, layout)
            if caption is None or not caption.words:
                self._display_caption(None, self._PREVIEW_T0_MS + decay + 200)
                return
            last_start = round(caption.words[-1].start * 1000)
            self._display_caption(
                caption,
                last_start + self._PREVIEW_WORD_MS + self._PREVIEW_GAP_MS
                + decay + 200)

    def _current_pop_state(self, t_ms: float):
        """(aktiver Wort-Index|None, Scale-%) – delegiert an Render-Modell.

        Identische ASS-\\t-Semantik wie bisher (jetzt zentral in
        capti_core.render_model.pop_state_at); diese Methode bleibt als
        dünner Adapter für API-Stabilität bestehen.
        """
        caption = getattr(self, "_preview_caption", None)
        if caption is None:
            return None, 100.0
        try:
            return pop_state_at(caption, t_ms)
        except (TypeError, ValueError, OverflowError):
            # Kaputte Wortzeiten (NaN/Inf): kein Highlight, kein Crash
            # (Block 40). Core-Semantik bleibt unangetastet.
            return None, 100.0

    def _ass_or_hex_color(self, value: str, fallback: str) -> str:
        """ASS-&HBBGGRR(FR)-Farben -> Tk-Hex; Hex wird durchgereicht."""
        value = (value or "").strip()
        if value.startswith("#") and len(value) == 7:
            return value.upper()
        if value.upper().startswith("&H"):
            hexpart = value[2:]
            if len(hexpart) == 8:            # Alpha-Byte vorne abschneiden
                hexpart = hexpart[2:]
            if len(hexpart) == 6:
                bb, gg, rr = hexpart[0:2], hexpart[2:4], hexpart[4:6]
                return f"#{rr}{gg}{bb}".upper()
        return fallback

    def _shadow_rgb(self):
        """Shadow-Alpha über Schwarz mischen (Tk kennt kein Alpha)."""
        try:
            alpha = max(0, min(255, int(self.style.get("shadow_alpha", 128))))
        except (TypeError, ValueError):
            alpha = 128
        level = int(255 * (255 - alpha) / 255)
        return f"#{level:02x}{level:02x}{level:02x}"

    def _draw_preview_frame(self, t_ms: float):
        """Zeichnet einen Vorschau-Rahmen (Wörter, Farben, Pop-Scale)."""
        import tkinter.font as tkfont
        if self._preview_mode == "transcript":
            self._select_transcript_caption(t_ms)
        canvas = self.preview_canvas
        canvas.delete("all")
        active, scale = self._current_pop_state(t_ms)
        normal = self._ass_or_hex_color(self.style.get("normal_color"), "#FFFFFF")
        highlight = self._ass_or_hex_color(
            self.style.get("highlight_color"), "#FFFF00")
        outline = self._ass_or_hex_color(
            self.style.get("outline_color"), "#101010")
        shadow = (self._shadow_rgb()
                  if int(self.style.get("shadow_alpha", 128) or 0) > 0 else None)
        base_font = self._preview_font

        for i, entry in enumerate(self._preview_words):
            is_active = (i == active)
            size_scale = (scale / 100.0) if is_active else 1.0
            color = highlight if is_active else normal
            if size_scale != 1.0:
                cx = entry["x"] + entry["w"] / 2
                anchor_x = cx - (entry["w"] * size_scale) / 2
                f = tkfont.Font(root=canvas,
                                family=base_font.actual("family"),
                                size=max(8, int(base_font.cget("size")
                                                * size_scale)),
                                weight="bold")
            else:
                anchor_x = entry["x"]
                f = base_font

            if shadow:
                canvas.create_text(anchor_x + 3, entry["y"] + 3,
                                   text=entry["text"], fill=shadow,
                                   font=f, anchor="w")
            for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2),
                           (-2, -2), (2, -2), (-2, 2), (2, 2)):
                canvas.create_text(anchor_x + dx, entry["y"] + dy,
                                   text=entry["text"], fill=outline,
                                   font=f, anchor="w")
            canvas.create_text(anchor_x, entry["y"], text=entry["text"],
                               fill=color, font=f, anchor="w")

    def _on_color_change(self, key: str):
        value = self._color_vars[key].get().strip()
        if not value.startswith("#") or len(value) != 7:
            return
        try:
            int(value[1:], 16)
        except ValueError:
            return
        self.style[key] = value.upper()
        self._color_swatches[key].configure(fg_color=value.upper())
        self._apply_preview()

    def _on_pop_change(self):
        self.style["pop_enabled"] = bool(self.pop_switch_var.get())
        self.style["pop_scale"] = int(self.pop_scale_slider.get())
        self.style["pop_decay_ms"] = int(self.pop_decay_slider.get())
        self.pop_scale_value.configure(text=str(self.style["pop_scale"]))
        self.pop_decay_value.configure(text=str(self.style["pop_decay_ms"]))
        self._apply_preview()  # Phase 32: Pop-Änderungen sofort animieren

    # ------------------------------------------------------------------
    # Screen-API
    # ------------------------------------------------------------------

    def apply_preset(self, name: str):
        """Wendet ein Preset auf den AKTUELLEN Style an (Merge, C2).

        Nur die Preset-Felder werden aktualisiert; alle anderen Felder –
        inkl. custom/zukünftiger Keys – bleiben erhalten. Styles sind flach
        (keine verschachtelten Strukturen), daher genügt ein flacher Merge.
        "Capti Default" enthält keine Overrides und ändert folglich nichts.
        """
        overrides = PRESETS.get(name, {})
        self.style = {**self.style, **overrides}
        self._sync_ui_from_style()
        self.success_label.configure(text=i18n.t("cs.preset_applied", name=name))

    def _sync_ui_from_style(self):
        for key, var in self._color_vars.items():
            var.set(self.style[key])
            self._color_swatches[key].configure(fg_color=self.style[key])
        self.pop_switch_var.set(bool(self.style["pop_enabled"]))
        self.pop_scale_slider.set(self.style["pop_scale"])
        self.pop_decay_slider.set(self.style["pop_decay_ms"])
        self.pop_scale_value.configure(text=str(int(self.style["pop_scale"])))
        self.pop_decay_value.configure(text=str(int(self.style["pop_decay_ms"])))
        self._apply_preview()

    def load_style(self):
        """Lädt `caption_style` aus der bestehenden Config (mit Defaults)."""
        saved = _read_config().get("caption_style", {})
        if isinstance(saved, dict):
            self.style = {**DEFAULT_STYLE, **saved}
        else:
            self.style = dict(DEFAULT_STYLE)
        self._sync_ui_from_style()

    def save_style(self):
        """Speichert `caption_style` in der bestehenden Config.

        Bestehende andere Keys bleiben erhalten; kaputte Config ist sicher.
        """
        self._on_pop_change()  # Slider-Stände übernehmen
        config = _read_config()
        config["caption_style"] = dict(self.style)
        if _write_config(config):
            self.success_label.configure(text=i18n.t("set.saved"))
        else:
            self.success_label.configure(text=i18n.t("set.save_failed"))

    def reset(self):
        """Setzt UI und Style auf gespeicherte bzw. Default-Werte zurück."""
        self.success_label.configure(text="")
        self.load_style()

    def save_project_file(self):
        """Speichert Transkript + Edits + Style als Projektdatei (Block 24).

        Kurzes Status-Feedback im Erfolgs-Label; kein Popup-Spam.
        Fehler werden sichtbar gemacht, crashen aber nie.
        """
        from capti_core.project_state import PROJECT_EXTENSION, ProjectFileError
        video = ""
        try:
            project = getattr(self.controller, "pending_project", None)
            if isinstance(project, dict):
                video = project.get("video_path") or ""
        except Exception:
            video = ""
        initialdir, initialfile = None, None
        if video:
            try:
                parent = os.path.dirname(os.path.abspath(video))
                if os.path.isdir(parent):
                    initialdir = parent
                stem = os.path.splitext(os.path.basename(video))[0]
                if stem:
                    initialfile = stem + PROJECT_EXTENSION
            except Exception:
                pass
        save_path = filedialog.asksaveasfilename(
            title=i18n.t("cs.project_save"),
            defaultextension=PROJECT_EXTENSION,
            initialdir=initialdir,
            initialfile=initialfile,
            filetypes=[("Capti-Projekt", "*" + PROJECT_EXTENSION),
                       ("JSON", "*.json"), ("Alle Dateien", "*.*")],
        )
        if not save_path:
            return
        try:
            saved = self.controller.save_project_state(save_path)
            self.success_label.configure(
                text=i18n.t("cs.project_saved",
                            name=os.path.basename(saved)))
        except ProjectFileError as exc:
            self.success_label.configure(
                text=i18n.t("cs.project_save_failed", error=exc))
        except Exception as exc:
            self.success_label.configure(
                text=i18n.t("cs.project_save_failed", error=exc))

    # ------------------------------------------------------------------
    # Caption-Editor (Block 21): Draft -> RenderCaption -> Preview
    # ------------------------------------------------------------------

    def _build_editor_card(self):
        """Baut die minimale Editor-Sektion (Transkript-Modus)."""
        self._editor_index = None
        card = self._make_card(3, i18n.t("cs.editor_title"))
        card.grid_columnconfigure(1, weight=1)
        self._editor_card = card
        ctk.CTkLabel(card, text=i18n.t("cs.editor_caption"),
                     font=self.font("body", 13), anchor="w",
                     text_color=self.color("text")).grid(
            row=1, column=0, sticky="w", padx=24, pady=6)
        self._editor_option = ctk.CTkOptionMenu(
            card, values=["–"], width=420, height=32, corner_radius=8,
            font=self.font("body", 13),
            fg_color=self.color("surface_secondary"),
            button_color=self.color("border"),
            button_hover_color=self.color("accent_hover"),
            text_color=self.color("text"),
            command=self._on_editor_select)
        self._editor_option.grid(row=1, column=1, sticky="ew",
                                 padx=(0, 24), pady=6)
        ctk.CTkLabel(card, text=i18n.t("cs.editor_text"),
                     font=self.font("body", 13), anchor="w",
                     text_color=self.color("text")).grid(
            row=2, column=0, sticky="w", padx=24, pady=6)
        self._editor_entry = ctk.CTkEntry(
            card, width=420, height=36, corner_radius=8,
            font=self.font("body", 13),
            fg_color=self.color("surface_secondary"),
            border_color=self.color("border"),
            text_color=self.color("text"))
        self._editor_entry.grid(row=2, column=1, sticky="ew",
                                padx=(0, 24), pady=6)
        self._editor_time_label = ctk.CTkLabel(
            card, text="", font=self.font("technical", 12), anchor="w",
            text_color=self.color("text_secondary"))
        self._editor_time_label.grid(row=3, column=1, sticky="w",
                                     padx=(0, 24), pady=(0, 2))
        # --- Caption-Grenzen-Nudge (Block 36): Start/Ende der Caption
        # mit derselben nudge_step wie Word-Timings verschieben.
        ctk.CTkLabel(card, text=i18n.t("cs.caption_nudge_start"),
                     font=self.font("body", 13), anchor="w",
                     text_color=self.color("text")).grid(
            row=4, column=0, sticky="w", padx=24, pady=6)
        cap_start_row = ctk.CTkFrame(card, fg_color="transparent")
        cap_start_row.grid(row=4, column=1, sticky="ew",
                           padx=(0, 24), pady=6)
        # Exakte Start-Eingabe (Block 52): wie Word-Zeiten, Übernehmen
        # läuft über den bestehenden Apply-Pfad (atomar, eine History).
        self._cap_start_entry = ctk.CTkEntry(
            cap_start_row, width=110, height=32, corner_radius=8,
            font=self.font("technical", 12),
            fg_color=self.color("surface_secondary"),
            border_color=self.color("border"),
            text_color=self.color("text"))
        self._cap_start_entry.grid(row=0, column=0, padx=(0, 8))
        self._cap_start_minus_btn = ctk.CTkButton(
            cap_start_row, text=i18n.t("cs.editor_timing_minus"),
            width=51, height=32,
            font=self.font("technical", 11), corner_radius=8,
            fg_color="transparent", border_width=1,
            border_color=self.color("border"),
            text_color=self.color("text"),
            command=lambda: self._on_caption_nudge("start", -get_nudge_step()))
        self._cap_start_minus_btn.grid(row=0, column=1, padx=(0, 8))
        self._cap_start_plus_btn = ctk.CTkButton(
            cap_start_row, text=i18n.t("cs.editor_timing_plus"),
            width=51, height=32,
            font=self.font("technical", 11), corner_radius=8,
            fg_color="transparent", border_width=1,
            border_color=self.color("border"),
            text_color=self.color("text"),
            command=lambda: self._on_caption_nudge("start", get_nudge_step()))
        self._cap_start_plus_btn.grid(row=0, column=2)
        ctk.CTkLabel(card, text=i18n.t("cs.caption_nudge_end"),
                     font=self.font("body", 13), anchor="w",
                     text_color=self.color("text")).grid(
            row=5, column=0, sticky="w", padx=24, pady=6)
        cap_end_row = ctk.CTkFrame(card, fg_color="transparent")
        cap_end_row.grid(row=5, column=1, sticky="ew",
                         padx=(0, 24), pady=6)
        self._cap_end_entry = ctk.CTkEntry(
            cap_end_row, width=110, height=32, corner_radius=8,
            font=self.font("technical", 12),
            fg_color=self.color("surface_secondary"),
            border_color=self.color("border"),
            text_color=self.color("text"))
        self._cap_end_entry.grid(row=0, column=0, padx=(0, 8))
        self._cap_end_minus_btn = ctk.CTkButton(
            cap_end_row, text=i18n.t("cs.editor_timing_minus"),
            width=51, height=32,
            font=self.font("technical", 11), corner_radius=8,
            fg_color="transparent", border_width=1,
            border_color=self.color("border"),
            text_color=self.color("text"),
            command=lambda: self._on_caption_nudge("end", -get_nudge_step()))
        self._cap_end_minus_btn.grid(row=0, column=1, padx=(0, 8))
        self._cap_end_plus_btn = ctk.CTkButton(
            cap_end_row, text=i18n.t("cs.editor_timing_plus"),
            width=51, height=32,
            font=self.font("technical", 11), corner_radius=8,
            fg_color="transparent", border_width=1,
            border_color=self.color("border"),
            text_color=self.color("text"),
            command=lambda: self._on_caption_nudge("end", get_nudge_step()))
        self._cap_end_plus_btn.grid(row=0, column=2)
        # Caption-Keyboard-Hinweis (Block 50): kompakt unter den
        # Caption-Nudge-Buttons, Schrittwert live aus get_nudge_step().
        self._cap_key_hint_label = ctk.CTkLabel(
            card, text="", font=self.font("technical", 11), anchor="w",
            text_color=self.color("text_secondary"))
        self._cap_key_hint_label.grid(row=6, column=0, columnspan=2,
                                      sticky="w", padx=24, pady=(0, 2))
        ctk.CTkLabel(card, text=i18n.t("cs.editor_words"),
                     font=self.font("body", 13), anchor="w",
                     text_color=self.color("text")).grid(
            row=7, column=0, sticky="nw", padx=24, pady=6)
        self._editor_words_box = ctk.CTkTextbox(
            card, width=420, height=84, corner_radius=8,
            font=self.font("technical", 12),
            fg_color=self.color("surface_secondary"),
            border_color=self.color("border"),
            text_color=self.color("text"))
        self._editor_words_box.grid(row=7, column=1, sticky="ew",
                                    padx=(0, 24), pady=6)
        self._editor_apply = ctk.CTkButton(
            card, text=i18n.t("cs.editor_apply"), width=160, height=36,
            font=self.font("body", 13), corner_radius=8,
            fg_color=self.color("accent"),
            hover_color=self.color("accent_hover"),
            text_color="#1a1a1a",
            command=self._on_editor_apply)
        self._editor_apply.grid(row=8, column=1, sticky="e",
                                padx=(0, 24), pady=(6, 4))
        self._editor_hint = ctk.CTkLabel(
            card, text="", font=self.font("body", 12), anchor="w",
            text_color=self.color("text_secondary"), wraplength=520,
            justify="left")
        self._editor_hint.grid(row=9, column=0, columnspan=2, sticky="w",
                               padx=24, pady=(0, 8))
        # --- Word-Zeile (Block 25): Auswahl + Timing-Edit + Split/Merge ---
        self._word_index = None
        ctk.CTkLabel(card, text=i18n.t("cs.word_label"),
                     font=self.font("body", 13), anchor="w",
                     text_color=self.color("text")).grid(
            row=10, column=0, sticky="w", padx=24, pady=6)
        self._word_option = ctk.CTkOptionMenu(
            card, values=["–"], width=420, height=32, corner_radius=8,
            font=self.font("body", 13),
            fg_color=self.color("surface_secondary"),
            button_color=self.color("border"),
            button_hover_color=self.color("accent_hover"),
            text_color=self.color("text"),
            command=self._on_word_select)
        self._word_option.grid(row=10, column=1, sticky="ew",
                               padx=(0, 24), pady=6)
        ctk.CTkLabel(card, text=i18n.t("cs.word_times"),
                     font=self.font("body", 13), anchor="w",
                     text_color=self.color("text")).grid(
            row=11, column=0, sticky="w", padx=24, pady=6)
        time_row = ctk.CTkFrame(card, fg_color="transparent")
        time_row.grid(row=11, column=1, sticky="ew", padx=(0, 24), pady=6)
        self._word_start_entry = ctk.CTkEntry(
            time_row, width=110, height=32, corner_radius=8,
            font=self.font("technical", 12),
            fg_color=self.color("surface_secondary"),
            border_color=self.color("border"),
            text_color=self.color("text"),
            placeholder_text="start")
        self._word_start_entry.grid(row=0, column=0, padx=(0, 8))
        self._word_end_entry = ctk.CTkEntry(
            time_row, width=110, height=32, corner_radius=8,
            font=self.font("technical", 12),
            fg_color=self.color("surface_secondary"),
            border_color=self.color("border"),
            text_color=self.color("text"),
            placeholder_text="end")
        self._word_end_entry.grid(row=0, column=1, padx=(0, 8))
        self._word_set_btn = ctk.CTkButton(
            time_row, text=i18n.t("cs.word_set"), width=100, height=32,
            font=self.font("body", 12), corner_radius=8,
            fg_color="transparent", border_width=1,
            border_color=self.color("border"),
            text_color=self.color("text"),
            command=self._on_word_set)
        self._word_set_btn.grid(row=0, column=2)
        # --- Feinjustierung ±0,05 s (Block 31): je zwei Buttons unter
        # Start-/End-Entry, selbe Core-Validierung wie alle Timing-Wege.
        start_nudge = ctk.CTkFrame(time_row, fg_color="transparent")
        start_nudge.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self._start_minus_btn = ctk.CTkButton(
            start_nudge, text=i18n.t("cs.editor_timing_minus"),
            width=51, height=28,
            font=self.font("technical", 11), corner_radius=8,
            fg_color="transparent", border_width=1,
            border_color=self.color("border"),
            text_color=self.color("text"),
            command=lambda: self._on_nudge("start", -get_nudge_step()))
        self._start_minus_btn.grid(row=0, column=0, padx=(0, 8))
        self._start_plus_btn = ctk.CTkButton(
            start_nudge, text=i18n.t("cs.editor_timing_plus"),
            width=51, height=28,
            font=self.font("technical", 11), corner_radius=8,
            fg_color="transparent", border_width=1,
            border_color=self.color("border"),
            text_color=self.color("text"),
            command=lambda: self._on_nudge("start", get_nudge_step()))
        self._start_plus_btn.grid(row=0, column=1)
        end_nudge = ctk.CTkFrame(time_row, fg_color="transparent")
        end_nudge.grid(row=1, column=1, sticky="w", pady=(4, 0))
        self._end_minus_btn = ctk.CTkButton(
            end_nudge, text=i18n.t("cs.editor_timing_minus"),
            width=51, height=28,
            font=self.font("technical", 11), corner_radius=8,
            fg_color="transparent", border_width=1,
            border_color=self.color("border"),
            text_color=self.color("text"),
            command=lambda: self._on_nudge("end", -get_nudge_step()))
        self._end_minus_btn.grid(row=0, column=0, padx=(0, 8))
        self._end_plus_btn = ctk.CTkButton(
            end_nudge, text=i18n.t("cs.editor_timing_plus"),
            width=51, height=28,
            font=self.font("technical", 11), corner_radius=8,
            fg_color="transparent", border_width=1,
            border_color=self.color("border"),
            text_color=self.color("text"),
            command=lambda: self._on_nudge("end", get_nudge_step()))
        self._end_plus_btn.grid(row=0, column=1)
        # Shortcut-Hinweis (Block 33): kompakt unter den Nudge-Buttons,
        # Schrittwert aus get_nudge_step() (Single Source).
        self._nudge_hint_label = ctk.CTkLabel(
            time_row, text="", font=self.font("technical", 11), anchor="w",
            text_color=self.color("text_secondary"))
        self._nudge_hint_label.grid(row=2, column=0, columnspan=3,
                                    sticky="w", pady=(2, 0))
        self._refresh_nudge_hint()
        # --- Timing-Leiste (Block 30): Caption-Spanne mit ziehbaren
        # Start-/Ende-Markern des ausgewählten Worts (absolute Zeiten).
        import tkinter as _tl_tk
        self._timeline_w = 420
        self._timeline_h = 56
        self._timeline = _tl_tk.Canvas(
            card, width=self._timeline_w, height=self._timeline_h,
            bg=self.color("surface_secondary"), highlightthickness=1,
            highlightbackground=self.color("border"))
        self._timeline.grid(row=12, column=0, columnspan=2,
                            padx=24, pady=(2, 6), sticky="ew")
        self._timeline.bind("<Button-1>", self._on_timeline_press)
        self._timeline.bind("<B1-Motion>", self._on_timeline_move)
        self._timeline.bind("<ButtonRelease-1>", self._on_timeline_release)
        self._timeline_drag = None
        op_row = ctk.CTkFrame(card, fg_color="transparent")
        op_row.grid(row=13, column=1, sticky="ew", padx=(0, 24), pady=(0, 4))
        self._word_split_btn = ctk.CTkButton(
            op_row, text=i18n.t("cs.word_split"), width=130, height=32,
            font=self.font("body", 12), corner_radius=8,
            fg_color="transparent", border_width=1,
            border_color=self.color("border"),
            text_color=self.color("text"),
            command=self._on_word_split)
        self._word_split_btn.grid(row=0, column=0, padx=(0, 8))
        self._word_merge_btn = ctk.CTkButton(
            op_row, text=i18n.t("cs.word_merge"), width=130, height=32,
            font=self.font("body", 12), corner_radius=8,
            fg_color="transparent", border_width=1,
            border_color=self.color("border"),
            text_color=self.color("text"),
            command=self._on_word_merge)
        self._word_merge_btn.grid(row=0, column=1)
        self._word_info_label = ctk.CTkLabel(
            card, text="", font=self.font("technical", 12), anchor="w",
            text_color=self.color("text_secondary"))
        self._word_info_label.grid(row=14, column=1, sticky="w",
                                   padx=(0, 24), pady=(0, 4))
        # --- Manuelle Wort-Ops (Block 28): Split-Punkt/Insert/Delete ---
        split_row = ctk.CTkFrame(card, fg_color="transparent")
        split_row.grid(row=16, column=1, sticky="ew",
                       padx=(0, 24), pady=(6, 4))
        self._split_index_entry = ctk.CTkEntry(
            split_row, width=70, height=32, corner_radius=8,
            font=self.font("technical", 12),
            fg_color=self.color("surface_secondary"),
            border_color=self.color("border"),
            text_color=self.color("text"),
            placeholder_text=i18n.t("cs.word_split_index"))
        self._split_index_entry.grid(row=0, column=0, padx=(0, 8))
        self._word_split_at_btn = ctk.CTkButton(
            split_row, text=i18n.t("cs.word_split_at"), width=130, height=32,
            font=self.font("body", 12), corner_radius=8,
            fg_color="transparent", border_width=1,
            border_color=self.color("border"),
            text_color=self.color("text"),
            command=self._on_word_split_at)
        self._word_split_at_btn.grid(row=0, column=1, padx=(0, 8))
        self._word_delete_btn = ctk.CTkButton(
            split_row, text=i18n.t("cs.word_delete"), width=130, height=32,
            font=self.font("body", 12), corner_radius=8,
            fg_color="transparent", border_width=1,
            border_color=self.color("border"),
            text_color=self.color("text"),
            command=self._on_word_delete)
        self._word_delete_btn.grid(row=0, column=2)
        insert_row = ctk.CTkFrame(card, fg_color="transparent")
        insert_row.grid(row=17, column=1, sticky="ew",
                        padx=(0, 24), pady=(0, 4))
        self._insert_word_entry = ctk.CTkEntry(
            insert_row, width=150, height=32, corner_radius=8,
            font=self.font("body", 13),
            fg_color=self.color("surface_secondary"),
            border_color=self.color("border"),
            text_color=self.color("text"),
            placeholder_text=i18n.t("cs.word_insert_text"))
        self._insert_word_entry.grid(row=0, column=0, padx=(0, 8))
        self._word_insert_before_btn = ctk.CTkButton(
            insert_row, text=i18n.t("cs.word_insert_before"),
            width=100, height=32,
            font=self.font("body", 12), corner_radius=8,
            fg_color="transparent", border_width=1,
            border_color=self.color("border"),
            text_color=self.color("text"),
            command=self._on_word_insert_before)
        self._word_insert_before_btn.grid(row=0, column=1, padx=(0, 8))
        self._word_insert_after_btn = ctk.CTkButton(
            insert_row, text=i18n.t("cs.word_insert_after"),
            width=100, height=32,
            font=self.font("body", 12), corner_radius=8,
            fg_color="transparent", border_width=1,
            border_color=self.color("border"),
            text_color=self.color("text"),
            command=self._on_word_insert_after)
        self._word_insert_after_btn.grid(row=0, column=2)
        # --- Undo/Redo (Block 27) ---
        self._undo_histories = {}
        self._history_key = None
        undo_row = ctk.CTkFrame(card, fg_color="transparent")
        undo_row.grid(row=15, column=1, sticky="ew",
                      padx=(0, 24), pady=(0, 16))
        self._undo_btn = ctk.CTkButton(
            undo_row, text=i18n.t("cs.editor_undo"), width=130, height=32,
            font=self.font("body", 12), corner_radius=8,
            fg_color="transparent", border_width=1,
            border_color=self.color("border"),
            text_color=self.color("text"),
            command=self._on_undo)
        self._undo_btn.grid(row=0, column=0, padx=(0, 8))
        self._redo_btn = ctk.CTkButton(
            undo_row, text=i18n.t("cs.editor_redo"), width=130, height=32,
            font=self.font("body", 12), corner_radius=8,
            fg_color="transparent", border_width=1,
            border_color=self.color("border"),
            text_color=self.color("text"),
            command=self._on_redo)
        self._redo_btn.grid(row=0, column=1)
        self._undo_btn.configure(state="disabled")
        self._redo_btn.configure(state="disabled")
        # Shortcuts aufs Fenster (nicht App-global): CustomTkinter
        # verbietet bind_all; der Fokus-Guard grenzt auf den Editor ein.
        self._undo_key_ids = []
        try:
            top = self.winfo_toplevel()
            self._undo_key_ids = [
                ("<Control-z>", top.bind("<Control-z>",
                                         self._on_undo_key, add="+")),
                ("<Control-y>", top.bind("<Control-y>",
                                         self._on_redo_key, add="+")),
                ("<Control-Z>", top.bind("<Control-Z>",
                                         self._on_redo_key, add="+")),
                ("<Left>", top.bind("<Left>",
                                    self._on_nudge_key, add="+")),
                ("<Right>", top.bind("<Right>",
                                     self._on_nudge_key, add="+")),
            ]
        except Exception:
            self._undo_key_ids = []

    def _editor_labels(self):
        """Dropdown-Einträge für die Transkript-Captions."""
        labels = []
        for i, cap in enumerate(getattr(self, "_transcript_captions", None) or ()):
            labels.append(f"{i + 1} · {cap.start:.1f}s–{cap.end:.1f}s · {cap.text[:32]}")
        return labels

    def _refresh_editor(self):
        """Synchronisiert die Editor-Sektion mit den Transkript-Captions.

        Nur im Transkript-Modus aktiv; sonst deaktiviert mit Hinweis.
        Erhält die Auswahl, solange der Index noch gültig ist.
        """
        caps = list(getattr(self, "_transcript_captions", None) or ())
        active = self._preview_mode == "transcript" and bool(caps)
        if not active:
            self._editor_index = None
            self._editor_option.configure(values=["–"])
            self._editor_option.set("–")
            self._editor_entry.delete(0, "end")
            self._editor_entry.configure(state="disabled")
            self._cap_start_entry.delete(0, "end")
            self._cap_start_entry.configure(state="disabled")
            self._cap_end_entry.delete(0, "end")
            self._cap_end_entry.configure(state="disabled")
            self._editor_apply.configure(state="disabled")
            self._editor_time_label.configure(text="")
            self._editor_words_box.configure(state="normal")
            self._editor_words_box.delete("1.0", "end")
            self._editor_words_box.configure(state="disabled")
            self._editor_hint.configure(text=i18n.t("cs.editor_hint_sample"))
            self._refresh_word_row()
            self._update_undo_buttons()
            return
        self._editor_entry.configure(state="normal")
        self._cap_start_entry.configure(state="normal")
        self._cap_end_entry.configure(state="normal")
        self._editor_apply.configure(state="normal")
        self._editor_words_box.configure(state="normal")
        labels = self._editor_labels()
        self._editor_option.configure(values=labels)
        idx = self._editor_index
        if idx is None or not 0 <= idx < len(caps):
            idx = 0
        self._editor_index = idx
        self._editor_option.set(labels[idx])
        self._load_editor_caption(idx)
        # Verschobenes/fehlendes Video: State bleibt, Hinweis zeigen.
        missing = False
        try:
            project = getattr(self.controller, "pending_project", None)
            video = project.get("video_path") if isinstance(project, dict) else ""
            missing = bool(video) and not os.path.isfile(video)
        except Exception:
            missing = False
        self._editor_hint.configure(
            text=i18n.t("cs.editor_video_missing") if missing else "")
        self._update_undo_buttons()

    def _load_editor_caption(self, idx: int):
        """Lädt Caption idx in Entry/Zeit-/Wort-Anzeige (Draft-Ansicht)."""
        caps = list(getattr(self, "_transcript_captions", None) or ())
        if not 0 <= idx < len(caps):
            return
        cap = caps[idx]
        self._editor_entry.delete(0, "end")
        self._editor_entry.insert(0, cap.text)
        self._cap_start_entry.delete(0, "end")
        self._cap_start_entry.insert(0, f"{cap.start:.3f}")
        self._cap_end_entry.delete(0, "end")
        self._cap_end_entry.insert(0, f"{cap.end:.3f}")
        self._editor_time_label.configure(
            text=f"{i18n.t('cs.editor_start', value=f'{cap.start:.2f}')} · "
                 f"{i18n.t('cs.editor_end', value=f'{cap.end:.2f}')}")
        self._editor_words_box.delete("1.0", "end")
        for w in cap.words:
            self._editor_words_box.insert(
                "end", f"{w.word}  [{w.start:.2f}–{w.end:.2f}]\n")
        # Auswahl erhalten, falls noch gültig (Block 30, §6);
        # _refresh_word_row klemmt ungültige/leere Auswahl auf 0/None.
        self._refresh_word_row()

    def _on_editor_select(self, _choice: str):
        """Dropdown-Auswahl -> Caption in den Editor laden."""
        try:
            idx = list(self._editor_option.cget("values")).index(
                self._editor_option.get())
        except ValueError:
            return
        self._editor_index = idx
        self._load_editor_caption(idx)
        self._update_undo_buttons()

    # --- Word-Edit (Block 25) ------------------------------------

    def _word_labels(self, cap):
        """Dropdown-Einträge für die Wörter einer Caption."""
        return [f"{i + 1} · {w.word} [{w.start:.2f}–{w.end:.2f}]"
                for i, w in enumerate(cap.words)]

    def _set_word_widgets_state(self, state: str):
        """Aktiviert/deaktiviert alle Word-Widgets (inkl. Entries)."""
        for widget in (self._word_option, self._word_start_entry,
                       self._word_end_entry, self._word_set_btn,
                       self._start_minus_btn, self._start_plus_btn,
                       self._end_minus_btn, self._end_plus_btn,
                       self._cap_start_minus_btn, self._cap_start_plus_btn,
                       self._cap_end_minus_btn, self._cap_end_plus_btn,
                       self._word_split_btn, self._word_merge_btn,
                       self._split_index_entry, self._word_split_at_btn,
                       self._word_delete_btn, self._insert_word_entry,
                       self._word_insert_before_btn,
                       self._word_insert_after_btn):
            try:
                widget.configure(state=state)
            except Exception:
                pass

    def _refresh_word_row(self):
        """Synchronisiert Word-Auswahl/Info mit der Editor-Caption."""
        caps = list(getattr(self, "_transcript_captions", None) or ())
        idx = self._editor_index
        cap = caps[idx] if idx is not None and 0 <= idx < len(caps) else None
        words = list(cap.words) if cap is not None else []
        if not words:
            self._word_index = None
            self._word_option.configure(values=["–"])
            self._word_option.set("–")
            self._word_start_entry.delete(0, "end")
            self._word_end_entry.delete(0, "end")
            self._word_info_label.configure(text="")
            self._set_word_widgets_state("disabled")
            self._clear_timeline()
            self._nudge_hint_label.grid_remove()
            return
        self._set_word_widgets_state("normal")
        labels = self._word_labels(cap)
        self._word_option.configure(values=labels)
        widx = self._word_index
        if widx is None or not 0 <= widx < len(words):
            widx = 0
        self._word_index = widx
        self._word_option.set(labels[widx])
        self._fill_word_entries(words[widx])
        self._draw_timeline()
        self._refresh_nudge_hint()
        self._nudge_hint_label.grid()

    def _refresh_nudge_hint(self):
        """Shortcut-Hinweise aus get_nudge_step() neu setzen."""
        try:
            self._nudge_hint_label.configure(
                text=i18n.t("cs.timing_hint", step=_format_nudge_step()))
        except Exception:
            pass
        self._refresh_cap_key_hint()

    def _refresh_cap_key_hint(self):
        """Caption-Keyboard-Hinweis aus get_nudge_step() neu setzen."""
        try:
            self._cap_key_hint_label.configure(
                text=i18n.t("cs.caption_key_hint",
                            step=_format_nudge_step()))
        except Exception:
            pass

    def _fill_word_entries(self, word):
        """Start/Ende-Einträge + Dauer-Info für ein RenderWord."""
        self._word_start_entry.delete(0, "end")
        self._word_start_entry.insert(0, f"{word.start:.3f}")
        self._word_end_entry.delete(0, "end")
        self._word_end_entry.insert(0, f"{word.end:.3f}")
        self._word_info_label.configure(
            text=i18n.t("cs.word_info",
                        value=f"{max(0.0, word.end - word.start):.3f}"))

    # --- Timing-Leiste (Block 30): Drag auf absoluter Caption-Spanne --

    def _timeline_state(self):
        """(Caption, Wort, Wort-Index) für die Leiste oder Nones."""
        caps = list(getattr(self, "_transcript_captions", None) or ())
        idx = self._editor_index
        cap = caps[idx] if idx is not None and 0 <= idx < len(caps) else None
        if cap is None or not cap.end > cap.start:
            return None, None, None
        words = list(cap.words)
        widx = getattr(self, "_word_index", None)
        if widx is None or not 0 <= widx < len(words):
            return None, None, None
        return cap, words[widx], widx

    def _timeline_handles(self):
        """(x_start, x_end) der Marker in Canvas-Pixeln oder None."""
        cap, word, _widx = self._timeline_state()
        if cap is None:
            return None
        width = getattr(self, "_timeline_w", 0)
        return (_timeline_x(word.start, width, cap.start, cap.end),
                _timeline_x(word.end, width, cap.start, cap.end))

    def _timeline_caption(self):
        """Aktuelle Caption für Caption-Drag oder None (ohne Wort nötig)."""
        caps = list(getattr(self, "_transcript_captions", None) or ())
        idx = self._editor_index
        cap = caps[idx] if idx is not None and 0 <= idx < len(caps) else None
        if cap is None or not cap.end > cap.start:
            return None
        return cap

    def _timeline_caption_handles(self):
        """(x_start, x_end) der Caption-Grenzen oder None.

        Liegen immer an den Track-Enden (Mapping-Domain); räumlich
        deckungsgleich mit Wort-Markern bei berührenden Wörtern –
        Press priorisiert Wort-Handles (bestehendes Verhalten).
        """
        cap = self._timeline_caption()
        if cap is None:
            return None
        width = getattr(self, "_timeline_w", 0)
        return (_timeline_x(cap.start, width, cap.start, cap.end),
                _timeline_x(cap.end, width, cap.start, cap.end))

    def _clear_timeline(self):
        """Leiste leeren (keine Auswahl / kein Transkript)."""
        import contextlib
        self._timeline_drag = None
        with contextlib.suppress(Exception):
            self._timeline.delete("all")

    def _draw_timeline(self, temp=None, cap_temp=None, snap=None):
        """Zeichnet Track + Nachbarn + Wortspanne + Marker.

        Args:
            temp: optionale (start, end)-Wort-Drag-Vorschau (nur Anzeige,
                absolute Zeiten; rot bei start >= end).
            cap_temp: optionale (start, end)-Caption-Drag-Vorschau als
                Outline-Overlay (Modell bleibt unverändert).
            snap: optional {"time", "which", "kind", "domain"} aus dem
                Move-Handler (bereits berechnet, keine zweite Suche):
                vertikale Snap-Markierung + Highlight des aktiven
                Handles. None = kein Indikator.
        """
        import contextlib
        cv = getattr(self, "_timeline", None)
        if cv is None:
            return
        with contextlib.suppress(Exception):
            cv.delete("all")
        cap = self._timeline_caption()
        if cap is None:
            return
        _, word, widx = self._timeline_state()
        width = self._timeline_w
        height = self._timeline_h
        pad = _TIMELINE_PAD
        y0, y1 = 20, 32
        words = list(cap.words)
        track_fill = self.color("surface")
        muted = self.color("text_secondary")
        accent = self.color("accent")
        bad = self.color("error")
        marker = self.color("text")
        label_color = self.color("text_secondary")
        edge = self.color("border")
        cv.create_rectangle(pad, y0, width - pad, y1,
                            fill=track_fill, outline=edge)
        for i, other in enumerate(words):
            if widx is not None and i == widx:
                continue
            if _finite_or_none(other, "start") is None \
                    or _finite_or_none(other, "end") is None:
                continue  # kaputte Zeiten: kein Crash, kein Marker
            cv.create_rectangle(
                _timeline_x(other.start, width, cap.start, cap.end), y0 + 2,
                _timeline_x(other.end, width, cap.start, cap.end), y1 - 2,
                fill=muted, outline="")
        span_times = None
        if word is not None:
            if temp is not None:
                span_times = temp
            elif _finite_or_none(word, "start") is not None \
                    and _finite_or_none(word, "end") is not None:
                span_times = (word.start, word.end)
            # Kaputte Modell-Zeiten: Spanne/Handles auslassen (kein Crash).
        if span_times is not None:
            start, end = span_times
            fill = accent if end > start else bad
            x0 = _timeline_x(start, width, cap.start, cap.end)
            x1 = _timeline_x(end, width, cap.start, cap.end)
            cv.create_rectangle(x0, y0 - 2, x1, y1 + 2, fill=fill, outline="")
            for handle_x in (x0, x1):
                cv.create_rectangle(handle_x - 3, y0 - 7, handle_x + 3, y1 + 7,
                                    fill=marker, outline=edge)
            if snap is not None and snap.get("kind") == "word":
                hx = x0 if snap.get("which") == "start" else x1
                self._draw_snap_indicator(cv, snap, hx, width,
                                          y0, y1, accent)
        # Caption-Grenzen: höhere Balken, eigene Trefferzone (Press
        # priorisiert Wort-Handles, damit Word-Drag unverändert bleibt).
        for cap_x in (_timeline_x(cap.start, width, cap.start, cap.end),
                      _timeline_x(cap.end, width, cap.start, cap.end)):
            cv.create_rectangle(cap_x - 2, y0 - 12, cap_x + 2, y1 + 12,
                                fill=marker, outline=edge)
        if cap_temp is not None:
            cs, ce = cap_temp
            xs0 = _timeline_x(cs, width, cap.start, cap.end)
            xs1 = _timeline_x(ce, width, cap.start, cap.end)
            cv.create_rectangle(xs0, y0 - 4, xs1, y1 + 4, fill="",
                                outline=accent if ce > cs else bad, width=2)
            if snap is not None and snap.get("kind") == "caption":
                hx = xs0 if snap.get("which") == "start" else xs1
                self._draw_snap_indicator(cv, snap, hx, width,
                                          y0, y1, accent)
        cv.create_text(pad, height - 8, text=f"{cap.start:.2f}s",
                       anchor="w", fill=label_color)
        cv.create_text(width - pad, height - 8, text=f"{cap.end:.2f}s",
                       anchor="e", fill=label_color)

    def _draw_snap_indicator(self, cv, snap, active_x, width, y0, y1,
                             accent):
        """Snap-Markierung + Highlight des aktiven Handles (Block 40).

        Nutzt ausschließlich den übergebenen Snap-State (keine zweite
        Suche/Toleranz/Mathematik): Marker exakt auf snap["time"] via
        snap["domain"], aktiver Handle mit Accent-Outline. Tags "snap"
        bzw. "snap_handle" für Tests und sauberes Neuzeichnen.
        """
        try:
            domain = snap.get("domain") or (None, None)
            marker_x = _snap_marker_x(snap["time"], width,
                                      domain[0], domain[1])
        except (KeyError, TypeError, ValueError):
            return
        cv.create_line(marker_x, y0 - 14, marker_x, y1 + 14,
                       fill=accent, width=2, tags=("snap",))
        cv.create_rectangle(active_x - 3, y0 - 7, active_x + 3, y1 + 7,
                            fill="", outline=accent, width=2,
                            tags=("snap", "snap_handle"))

    def _on_timeline_press(self, event):
        """Drag-Start: Marker treffen -> temporäres Timing beginnen.

        Priorität: Wort-Handles zuerst (bestehendes Verhalten bleibt),
        dann Caption-Grenzen. Noch KEIN Draft-Commit beim Press.
        """
        self._timeline_drag = None
        try:
            pos_x = float(event.x)
        except (AttributeError, TypeError, ValueError):
            return
        handles = self._timeline_handles()
        if handles is not None:
            x0, x1 = handles
            if abs(pos_x - x0) <= _TIMELINE_HANDLE_R:
                which = "start"
            elif abs(pos_x - x1) <= _TIMELINE_HANDLE_R:
                which = "end"
            else:
                which = None
            if which is not None:
                cap, _word, widx = self._timeline_state()
                self._timeline_drag = {
                    "kind": "word",
                    "which": which,
                    "widx": widx,
                    "idx": self._editor_index,
                    "before": _draft_snapshot(_draft_from_caption(cap)),
                    "temp": None,
                    "snapped": None,
                }
                return
        cap_handles = self._timeline_caption_handles()
        cap = self._timeline_caption()
        if cap_handles is None or cap is None:
            return
        cx0, cx1 = cap_handles
        if abs(pos_x - cx0) <= _TIMELINE_HANDLE_R:
            which = "start"
        elif abs(pos_x - cx1) <= _TIMELINE_HANDLE_R:
            which = "end"
        else:
            return
        self._timeline_drag = {
            "kind": "caption",
            "which": which,
            "widx": None,
            "idx": self._editor_index,
            "before": _draft_snapshot(_draft_from_caption(cap)),
            "temp": None,
            "snapped": None,
            # Eingefrorene Mapping-Domain (Original-Spanne), damit der
            # Marker beim Ziehen über die alte Grenze hinaus nicht springt.
            "map_start": cap.start,
            "map_end": cap.end,
        }

    def _on_timeline_move(self, event):
        """Drag-Vorschau: nur Anzeige (Entries + Leiste), kein Commit."""
        drag = getattr(self, "_timeline_drag", None)
        if not drag:
            return
        if drag.get("kind", "word") == "caption":
            self._on_caption_move(event, drag)
            return
        cap, word, widx = self._timeline_state()
        if cap is None or widx != drag["widx"] \
                or self._editor_index != drag["idx"]:
            self._timeline_drag = None
            return
        try:
            moment = _timeline_t(float(event.x), self._timeline_w,
                                 cap.start, cap.end)
        except (AttributeError, TypeError, ValueError):
            return
        moment = min(cap.end, max(cap.start, moment))
        words = list(cap.words)
        span = cap.end - cap.start
        width = self._timeline_w
        px_per_sec = (width - 2 * _TIMELINE_PAD) / span if span > 0 else 0
        points = _word_snap_candidates(cap, words, widx, drag["which"])
        snapped = _snap_time(moment, points,
                             get_snap_tolerance_px(), px_per_sec)
        drag["snapped"] = ({"time": snapped, "which": drag["which"],
                            "kind": "word",
                            "domain": (cap.start, cap.end)}
                           if snapped is not None else None)
        if snapped is None:
            snapped = moment
        if drag["which"] == "start":
            start, end = snapped, word.end
        else:
            start, end = word.start, snapped
        drag["temp"] = (start, end)
        self._word_start_entry.delete(0, "end")
        self._word_start_entry.insert(0, f"{start:.3f}")
        self._word_end_entry.delete(0, "end")
        self._word_end_entry.insert(0, f"{end:.3f}")
        self._word_info_label.configure(
            text=i18n.t("cs.word_info",
                        value=f"{max(0.0, end - start):.3f}"))
        self._draw_timeline(temp=(start, end), snap=drag["snapped"])

    def _on_caption_move(self, event, drag):
        """Caption-Drag-Vorschau: temporäre Grenzen, kein Commit.

        Mapping über die beim Press eingefrorene Domain (lineare
        Erweiterung, keine Klemmung an alter Grenze); harte Untergrenze
        0 für den Start. Modell/History/Controller bleiben unberührt.
        """
        cap = self._timeline_caption()
        if cap is None or self._editor_index != drag.get("idx"):
            self._timeline_drag = None
            return
        try:
            pos_x = float(event.x)
        except (AttributeError, TypeError, ValueError):
            return
        width = self._timeline_w
        span = drag["map_end"] - drag["map_start"]
        if not span > 0 or width <= 0:
            return
        moment = drag["map_start"] + (pos_x - _TIMELINE_PAD) \
            / max(1, (width - 2 * _TIMELINE_PAD)) * span
        # Snap (Block 38): nur temporäre Position, validiert erst Release.
        # Snap-State (Block 40) für den Indikator: exakt dieser Wert.
        px_per_sec = (width - 2 * _TIMELINE_PAD) / span
        domain = (drag["map_start"], drag["map_end"])
        if drag["which"] == "start":
            candidates = [t for t in _snap_candidates(cap.words, "start")
                          if t <= cap.end]
            snapped = _snap_time(moment, candidates,
                                 get_snap_tolerance_px(), px_per_sec)
            start = snapped if snapped is not None else moment
            start, end = max(0.0, start), cap.end
        else:
            candidates = [t for t in _snap_candidates(cap.words, "end")
                          if t >= cap.start]
            snapped = _snap_time(moment, candidates,
                                 get_snap_tolerance_px(), px_per_sec)
            end = snapped if snapped is not None else moment
            start = cap.start
        drag["temp"] = (start, end)
        # Kandidaten sind stets >= 0, daher ist max(0.0, .) bei Snap
        # ein No-Op und der Indikator zeigt exakt den Snap-Wert.
        drag["snapped"] = ({"time": snapped, "which": drag["which"],
                            "kind": "caption", "domain": domain}
                           if snapped is not None else None)
        self._editor_time_label.configure(
            text=f"{i18n.t('cs.editor_start', value=f'{start:.2f}')} · "
                 f"{i18n.t('cs.editor_end', value=f'{end:.2f}')}")
        self._draw_timeline(cap_temp=(start, end), snap=drag["snapped"])

    def _on_timeline_release(self, _event=None):
        """Drag-Ende: genau ein Commit (oder saubere Ablehnung)."""
        drag = getattr(self, "_timeline_drag", None)
        self._timeline_drag = None
        if not drag:
            return
        if drag.get("kind", "word") == "caption":
            self._on_caption_release(drag)
            return
        temp = drag.get("temp")
        caps = list(getattr(self, "_transcript_captions", None) or ())
        idx = drag.get("idx")
        if temp is None or self._editor_index != idx \
                or idx is None or not 0 <= idx < len(caps):
            self._refresh_word_row()
            return
        draft = _draft_from_caption(caps[idx])
        widx = drag.get("widx")
        if widx is None or not 0 <= widx < len(draft.words) \
                or not _draft_set_word_timing(draft, widx,
                                              temp[0], temp[1]):
            self._reject_word_edit()
            self._refresh_word_row()
            return
        self._push_history(idx, drag.get("before"), draft)
        self._commit_draft(idx, draft)
        self._editor_hint.configure(
            text=i18n.t("cs.editor_applied", index=idx + 1))

    def _on_caption_release(self, drag):
        """Caption-Drag-Ende: validiert via set_caption_timing().

        Genau ein Commit + ein History-Step bei Erfolg; bei Ablehnung
        Anzeige auf Modellstand zurücksetzen, kein State-Wechsel.
        """
        temp = drag.get("temp")
        caps = list(getattr(self, "_transcript_captions", None) or ())
        idx = drag.get("idx")
        if temp is None or self._editor_index != idx \
                or idx is None or not 0 <= idx < len(caps):
            self._refresh_editor()
            return
        draft = _draft_from_caption(caps[idx])
        if not _draft_set_caption_timing(draft, temp[0], temp[1]):
            self._reject_word_edit()
            self._refresh_editor()
            return
        self._push_history(idx, drag.get("before"), draft)
        self._commit_draft(idx, draft)
        self._editor_hint.configure(
            text=i18n.t("cs.editor_applied", index=idx + 1))

    def _on_word_select(self, _choice: str):
        """Word-Dropdown -> Einträge + Info laden."""
        try:
            widx = list(self._word_option.cget("values")).index(
                self._word_option.get())
        except ValueError:
            return
        self._word_index = widx
        caps = list(getattr(self, "_transcript_captions", None) or ())
        idx = self._editor_index
        if idx is not None and 0 <= idx < len(caps):
            words = list(caps[idx].words)
            if 0 <= widx < len(words):
                self._fill_word_entries(words[widx])
                self._draw_timeline()

    @staticmethod
    def _parse_time(text: str):
        """Sekunden parsen (Komma/Punkt, Whitespace-tolerant) oder None."""
        try:
            return float(str(text).strip().replace(",", "."))
        except (TypeError, ValueError):
            return None

    def _current_draft(self):
        """(idx, Draft) der Editor-Caption oder (None, None)."""
        caps = list(getattr(self, "_transcript_captions", None) or ())
        idx = self._editor_index
        if self._preview_mode != "transcript" or idx is None \
                or not 0 <= idx < len(caps):
            return None, None
        return idx, _draft_from_caption(caps[idx])

    def _reject_word_edit(self):
        """Ungültige Word-Eingabe: Hinweis, kein State-Wechsel."""
        self._editor_hint.configure(text=i18n.t("cs.word_invalid"))

    def _on_word_set(self):
        """Start/Ende übernehmen (validiert, sonst Ablehnung)."""
        idx, draft = self._current_draft()
        if draft is None:
            return
        before = _draft_snapshot(draft)
        widx = self._word_index
        start = self._parse_time(self._word_start_entry.get())
        end = self._parse_time(self._word_end_entry.get())
        if start is None or end is None or not _draft_set_word_timing(
                draft, widx if widx is not None else -1, start, end):
            self._reject_word_edit()
            return
        self._push_history(idx, before, draft)
        self._commit_draft(idx, draft)
        self._editor_hint.configure(
            text=i18n.t("cs.editor_applied", index=idx + 1))

    def _on_nudge(self, which: str, delta: float):
        """Start/Ende um ±0,05 s verschieben (Block 31).

        Rechnet vom committeten Modell-Wert (nicht vom Entry-Text),
        validiert ausschließlich über set_word_timing(); bei Erfolg
        genau ein History-Step + Standard-Commit, sonst Ablehnung
        ohne State-Wechsel.
        """
        idx, draft = self._current_draft()
        if draft is None:
            return
        widx = self._word_index
        if widx is None or not 0 <= widx < len(draft.words):
            self._reject_word_edit()
            return
        try:
            cur_start = float(draft.words[widx]["start"])
            cur_end = float(draft.words[widx]["end"])
        except (KeyError, TypeError, ValueError):
            self._reject_word_edit()
            return
        if which == "start":
            new_start, new_end = cur_start + delta, cur_end
        elif which == "end":
            new_start, new_end = cur_start, cur_end + delta
        else:
            self._reject_word_edit()
            return
        before = _draft_snapshot(draft)
        if not _draft_set_word_timing(draft, widx, new_start, new_end):
            self._reject_word_edit()
            return
        self._push_history(idx, before, draft)
        self._commit_draft(idx, draft)
        self._editor_hint.configure(
            text=i18n.t("cs.editor_applied", index=idx + 1))

    def _on_caption_nudge(self, which: str, delta: float):
        """Caption-Grenze um ±nudge_step verschieben (Block 36).

        Rechnet vom committeten Modell-Wert, validiert ausschließlich
        über set_caption_timing() (Wörter bleiben unverändert und
        innerhalb); bei Erfolg genau ein History-Step + Standard-Commit,
        sonst Ablehnung ohne State-Wechsel.
        """
        idx, draft = self._current_draft()
        if draft is None:
            return
        try:
            cur_start = float(draft.start)
            cur_end = float(draft.end)
        except (TypeError, ValueError):
            self._reject_word_edit()
            return
        if which == "start":
            new_start, new_end = cur_start + delta, cur_end
        elif which == "end":
            new_start, new_end = cur_start, cur_end + delta
        else:
            self._reject_word_edit()
            return
        before = _draft_snapshot(draft)
        if not _draft_set_caption_timing(draft, new_start, new_end):
            self._reject_word_edit()
            return
        self._push_history(idx, before, draft)
        self._commit_draft(idx, draft)
        self._editor_hint.configure(
            text=i18n.t("cs.editor_applied", index=idx + 1))

    def _on_word_split(self):
        """Wort splitten (Auto-Split, sonst Ablehnung)."""
        idx, draft = self._current_draft()
        if draft is None:
            return
        before = _draft_snapshot(draft)
        widx = self._word_index
        if widx is None or not _draft_split_word(draft, widx):
            self._reject_word_edit()
            return
        self._push_history(idx, before, draft)
        self._commit_draft(idx, draft)
        self._editor_hint.configure(
            text=i18n.t("cs.editor_applied", index=idx + 1))

    def _on_word_merge(self):
        """Wort mit Nachfolger mergen (sonst Ablehnung)."""
        idx, draft = self._current_draft()
        if draft is None:
            return
        before = _draft_snapshot(draft)
        widx = self._word_index
        if widx is None or not _draft_merge_words(draft, widx):
            self._reject_word_edit()
            return
        self._push_history(idx, before, draft)
        self._commit_draft(idx, draft)
        self._editor_hint.configure(
            text=i18n.t("cs.editor_applied", index=idx + 1))

    @staticmethod
    def _parse_split_index(text: str):
        """Zeichenindex parsen (strikt int) oder None."""
        try:
            return int(str(text).strip())
        except (TypeError, ValueError):
            return None

    def _on_word_split_at(self):
        """Wort am Zeichenindex teilen (validiert, sonst Ablehnung)."""
        idx, draft = self._current_draft()
        if draft is None:
            return
        before = _draft_snapshot(draft)
        widx = self._word_index
        char_index = self._parse_split_index(
            self._split_index_entry.get())
        if char_index is None or widx is None \
                or not _draft_split_word_at(draft, widx, char_index):
            self._reject_word_edit()
            return
        self._push_history(idx, before, draft)
        self._commit_draft(idx, draft)
        self._editor_hint.configure(
            text=i18n.t("cs.editor_applied", index=idx + 1))

    def _on_word_insert(self, before_selected: bool):
        """Wort vor/nach Auswahl einfügen (validiert, sonst Ablehnung)."""
        idx, draft = self._current_draft()
        if draft is None:
            return
        before = _draft_snapshot(draft)
        widx = self._word_index
        words = draft.words
        if widx is None or not 0 <= widx < len(words):
            # Einfügen in leere Caption an Position 0.
            pos = 0 if not words else None
            if pos is None:
                self._reject_word_edit()
                return
        else:
            pos = widx if before_selected else widx + 1
        word = self._insert_word_entry.get()
        if not _draft_insert_word(draft, pos, word):
            self._reject_word_edit()
            return
        self._push_history(idx, before, draft)
        self._commit_draft(idx, draft)
        self._editor_hint.configure(
            text=i18n.t("cs.editor_applied", index=idx + 1))

    def _on_word_insert_before(self):
        """Wort vor dem ausgewählten Wort einfügen."""
        self._on_word_insert(True)

    def _on_word_insert_after(self):
        """Wort nach dem ausgewählten Wort einfügen."""
        self._on_word_insert(False)

    def _on_word_delete(self):
        """Ausgewähltes Wort löschen (validiert, sonst Ablehnung)."""
        idx, draft = self._current_draft()
        if draft is None:
            return
        before = _draft_snapshot(draft)
        widx = self._word_index
        if widx is None or not _draft_delete_word(draft, widx):
            self._reject_word_edit()
            return
        self._push_history(idx, before, draft)
        self._commit_draft(idx, draft)
        self._editor_hint.configure(
            text=i18n.t("cs.editor_applied", index=idx + 1))

    def _on_editor_apply(self):
        """Übernimmt den Edit: Text + exakte Zeiten (Block 52).

        Leere Zeitfelder -> reiner Text-Edit (bisheriges Verhalten).
        Ausgefüllte Felder -> atomar Text + Timing, validiert
        ausschließlich über set_caption_timing() (Wörter unverändert
        und innerhalb); bei Erfolg genau ein History-Step +
        Standard-Commit, sonst Ablehnung ohne State-Wechsel.
        """
        caps = list(getattr(self, "_transcript_captions", None) or ())
        idx = self._editor_index
        if self._preview_mode != "transcript" or idx is None \
                or not 0 <= idx < len(caps):
            return
        new_text = self._editor_entry.get()
        raw_start = self._cap_start_entry.get().strip()
        raw_end = self._cap_end_entry.get().strip()
        draft = _draft_from_caption(caps[idx])
        before = _draft_snapshot(draft)
        _draft_apply_text(draft, new_text)
        if raw_start or raw_end:
            new_start = self._parse_time(raw_start) \
                if raw_start else float(draft.start)
            new_end = self._parse_time(raw_end) \
                if raw_end else float(draft.end)
            if new_start is None or new_end is None:
                self._reject_word_edit()
                return
            if not _draft_set_caption_timing(draft, new_start, new_end):
                self._reject_word_edit()
                return
        self._push_history(idx, before, draft)
        self._commit_draft(idx, draft)
        self._editor_hint.configure(
            text=i18n.t("cs.editor_applied", index=idx + 1))

    def _commit_draft(self, idx: int, draft):
        """Schreibt einen Draft zurück: Segment -> Rebuild -> Preview.

        Gemeinsamer Commit-Pfad für Text-, Timing-, Split- und Merge-Edits:
        Transkript-Segmente (Screen + Controller-Sync), Preview-Rebuild und
        sofortige Anzeige. Die geänderte Caption wird sofort dargestellt;
        Lines/Pop/Layout werden aus dem Render-Modell neu abgeleitet.
        """
        segment = _draft_to_segment(draft)
        self._transcript_segments[idx] = segment
        # Controller-Kopie synchron halten (gleiche Länge, gleiches Video).
        last = getattr(self.controller, "last_transcript", None)
        segs = last.get("segments") if isinstance(last, dict) else None
        if isinstance(segs, list) and len(segs) == len(self._transcript_segments) \
                and 0 <= idx < len(segs):
            segs[idx] = dict(segment)
        self._rebuild_preview_layout()
        self._restart_preview_animation()
        # Geänderte Caption sofort darstellen (statt erst bei ihrer Zeit).
        # Primär Start-Match; Fallback End-Match für Caption-Start-Nudge,
        # dessen Start sich geändert hat (Reihenfolge bleibt 1:1).
        shown = False
        for cap in self._transcript_captions:
            if abs(cap.start - draft.start) < 1e-9:
                self._display_caption(cap, self._preview_total_ms)
                shown = True
                break
        if not shown:
            for cap in self._transcript_captions:
                if abs(cap.end - draft.end) < 1e-9:
                    self._display_caption(cap, self._preview_total_ms)
                    break
        self._refresh_editor()

    # --- Undo/Redo (Block 27, pro Caption, Tk-frei im Core) -------

    def _clear_histories(self):
        """Vergisst alle Undo/Redo-Schritte (Transkript-/Projektwechsel)."""
        try:
            for hist in getattr(self, "_undo_histories", {}).values():
                hist.clear()
        except Exception:
            pass
        self._undo_histories = {}
        self._history_key = None

    def _histories_valid(self) -> bool:
        """True, wenn Histories zum aktuellen Transkript gehören."""
        return getattr(self, "_history_key", None) == id(
            getattr(self, "_transcript_segments", None))

    def _history_for(self, idx: int, seed: dict):
        """History für Caption idx (mit Ausgangs-Snapshot seeden)."""
        if not self._histories_valid():
            self._clear_histories()
            self._history_key = id(self._transcript_segments)
        hist = self._undo_histories.get(idx)
        if hist is None:
            hist = UndoHistory()
            hist.push(seed)
            self._undo_histories[idx] = hist
        return hist

    def _push_history(self, idx: int, before: dict, draft):
        """Genau ein History-Schritt pro abgeschlossener Aktion."""
        hist = self._history_for(idx, before)
        hist.push(_draft_snapshot(draft))
        self._update_undo_buttons()

    def _update_undo_buttons(self):
        """Button-Zustand spiegelt can_undo/can_redo (Block 27)."""
        can_undo = can_redo = False
        try:
            idx = self._editor_index
            hist = None
            if self._histories_valid():
                hist = self._undo_histories.get(idx)
            if hist is not None:
                can_undo, can_redo = hist.can_undo, hist.can_redo
        except Exception:
            can_undo = can_redo = False
        try:
            self._undo_btn.configure(
                state="normal" if can_undo else "disabled")
            self._redo_btn.configure(
                state="normal" if can_redo else "disabled")
        except Exception:
            pass

    def _restore_snapshot(self, idx: int, snap: dict):
        """Snapshot -> Draft -> Standard-Commit (Preview/Export/State)."""
        caps = list(getattr(self, "_transcript_captions", None) or ())
        if not 0 <= idx < len(caps):
            return
        draft = _draft_from_caption(caps[idx])
        _draft_apply_snapshot(draft, snap)
        self._commit_draft(idx, draft)

    def _on_undo(self):
        """Stellt den vorherigen Caption-Stand wieder her."""
        try:
            idx = self._editor_index
            hist = self._undo_histories.get(idx) \
                if self._histories_valid() else None
            snap = hist.undo() if hist is not None else None
        except Exception:
            snap = None
        if snap is None:
            return
        self._restore_snapshot(idx, snap)
        self._update_undo_buttons()

    def _on_redo(self):
        """Stellt den nächsten Caption-Stand wieder her."""
        try:
            idx = self._editor_index
            hist = self._undo_histories.get(idx) \
                if self._histories_valid() else None
            snap = hist.redo() if hist is not None else None
        except Exception:
            snap = None
        if snap is None:
            return
        self._restore_snapshot(idx, snap)
        self._update_undo_buttons()

    def _editor_key_guard(self) -> bool:
        """True, wenn der Fokus im Caption-Editor liegt (kein Hijacking)."""
        try:
            if not bool(self.winfo_exists()):
                return False
            focus = self.focus_get()
            card = getattr(self, "_editor_card", None)
            if focus is None or card is None:
                return False
            return str(focus).startswith(str(card))
        except Exception:
            return False

    def _on_undo_key(self, _event=None):
        if self._editor_key_guard():
            self._on_undo()
            return "break"
        return None

    def _on_redo_key(self, _event=None):
        if self._editor_key_guard():
            self._on_redo()
            return "break"
        return None

    def _nudge_key_guard(self) -> bool:
        """True, wenn Keyboard-Nudge feuern darf (Block 32).

        Fokus im Editor, aber NICHT in einem Text-/Auswahl-Widget:
        Entries, Textbox und Dropdown behalten ihr natives Verhalten
        (Cursor, Selektion, Auswahl). Kein bind_all().
        """
        try:
            if not self._editor_key_guard():
                return False
            focus = self.focus_get()
            if focus is None:
                return False
            return not isinstance(
                focus, (ctk.CTkEntry, ctk.CTkTextbox, ctk.CTkOptionMenu))
        except Exception:
            return False

    def _on_nudge_key(self, event=None):
        """Pfeil links/rechts -> Start ±Step, Shift+Pfeil -> Ende ±Step.

        Priorität WORD > CAPTION > NOTHING (Block 48): Bei gültigem
        Word-Kontext exakt der bisherige Word-Pfad (_on_nudge ->
        set_word_timing -> _commit_draft -> History); sonst, bei
        aktiver Caption, derselbe Pfad wie die Caption-Buttons
        (_on_caption_nudge -> set_caption_timing). Step immer live
        über get_nudge_step(). Ctrl/Alt-Kombis und andere Tasten
        bleiben unberührt (None = keine Aktion).
        """
        try:
            keysym = getattr(event, "keysym", "")
            state = int(getattr(event, "state", 0) or 0)
        except (TypeError, ValueError):
            return None
        if state & 0x000C:  # Ctrl/Alt behalten ihr Verhalten
            return None
        if keysym == "Left":
            delta = -get_nudge_step()
        elif keysym == "Right":
            delta = get_nudge_step()
        else:
            return None
        if not self._nudge_key_guard():
            return None
        which = "end" if (state & 0x0001) else "start"
        _idx, draft = self._current_draft()
        if draft is None:
            return "break"
        widx = self._word_index
        if widx is not None and 0 <= widx < len(draft.words):
            self._on_nudge(which, delta)
        else:
            self._on_caption_nudge(which, delta)
        return "break"

    # ------------------------------------------------------------------
    # Lifecycle (Phase 32): Preview-Timer sauber starten/stoppen
    # ------------------------------------------------------------------

    def on_hide(self):
        """Laufende Preview-Animation stoppen (keine Callback-Leichen)."""
        self._cancel_preview_timer()

    def on_show(self):
        """Preview beim erneuten Anzeigen sauber neu starten."""
        self._refresh_workflow_mode()
        self._sync_transcript_preview()
        self._refresh_editor()
        if getattr(self, "_preview_words", None):
            self._restart_preview_animation()

    def _sync_transcript_preview(self):
        """Zieht ggf. echtes Transkript (Block 20) oder fällt auf Sample zurück.

        Nur bei passendem Projektvideo (pending_project); sonst Sample.
        Idempotent: bereits angezeigtes Transkript wird nicht neu aufgebaut.
        """
        try:
            project = getattr(self.controller, "pending_project", None)
            video = project.get("video_path") if isinstance(project, dict) else None
            last = getattr(self.controller, "last_transcript", None)
        except Exception:
            video, last = None, None
        if (isinstance(last, dict) and video
                and last.get("video_path") == video
                and isinstance(last.get("segments"), list)
                and last["segments"]):
            if self._preview_mode != "transcript" \
                    or list(self._transcript_segments) != list(last["segments"]):
                self.set_transcript(last["segments"])
        elif self._preview_mode == "transcript":
            self.clear_transcript()

    def destroy(self):
        """Preview-Timer vor der Zerstörung abbrechen (kein bgerror)."""
        self._cancel_preview_timer()
        try:
            top = self.winfo_toplevel()
            for seq, funcid in getattr(self, "_undo_key_ids", []) or []:
                try:
                    if funcid:
                        top.unbind(seq, funcid)
                except Exception:
                    pass
        except Exception:
            pass
        super().destroy()

