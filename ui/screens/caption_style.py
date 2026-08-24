"""
Caption-Style-Screen: Konfiguration des Caption-Designs.

Speichert die Einstellungen in der bestehenden Capti-Config unter dem
Key `caption_style` – bestehende Config-Werte bleiben erhalten.

Die Caption-Engine/Renderer bleiben unverändert; dieser Screen bereitet
die Werte vor, die später an den Renderer übergeben werden können.
"""

import json
import os
from pathlib import Path

import customtkinter as ctk

from caption_renderer import CaptionRenderer
from ui import i18n
from ui.screens.base import Screen

# ---------------------------------------------------------------------
# Defaults = aktueller Capti-Look (identisch zu caption_renderer.py)
# Farben als Hex (#RRGGBB) für die UI; Shadow mit Alpha-Anteil
# ---------------------------------------------------------------------
DEFAULT_STYLE = {
    "normal_color": "#FFFFFF",
    "highlight_color": "#FFFF00",
    "outline_color": "#101010",
    "shadow_color": "#000000",
    "shadow_alpha": 128,          # 0..255 (Renderer: &H80...)
    "font_name": "Arial Black",
    "font_size": 68,
    "pop_enabled": True,
    "pop_scale": 112,
    "pop_decay_ms": 150,
}

PRESETS = {
    "Capti Default": {},  # exakt die Defaults
    "Clean": {
        "normal_color": "#FFFFFF", "highlight_color": "#FFFFFF",
        "outline_color": "#000000", "shadow_alpha": 96,
        "pop_enabled": False,
    },
    "Strong": {
        "normal_color": "#FFFFFF", "highlight_color": "#FF3B30",
        "outline_color": "#000000", "shadow_alpha": 180,
        "pop_enabled": True, "pop_scale": 125, "pop_decay_ms": 120,
    },
}

# Robuste Farbauswahl ohne zusätzliche Dependency
COLOR_CHOICES = ["#FFFFFF", "#FFFF00", "#FF3B30", "#4EC9B0", "#FFD60A",
                 "#101010", "#000000", "#5A5A5A"]

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


        self._apply_preview()

        # ----------------------------------------------------------
        # 3) Presets
        # ----------------------------------------------------------
        preset_frame = ctk.CTkFrame(self, fg_color="transparent")
        preset_frame.grid(row=3, column=0, pady=(0, 12))
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
        # 4) Farben
        # ----------------------------------------------------------
        colors_card = self._make_card(4, i18n.t("cs.card_colors"))
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
        # 5) Pop-Effekt
        # ----------------------------------------------------------
        pop_card = self._make_card(5, i18n.t("cs.card_pop"))
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
        # 6) Layout (nur Anzeige – dynamisches Layout bleibt Grundlage)
        # ----------------------------------------------------------
        layout_card = self._make_card(6, i18n.t("cs.card_layout"))
        ctk.CTkLabel(layout_card, text=i18n.t("cs.layout_info"), font=self.font("body", 12), anchor="w",
                     text_color=self.color("text_secondary"), wraplength=520, justify="left").grid(
            row=0, column=0, sticky="w", padx=24, pady=(16, 16))

        # ----------------------------------------------------------
        # 7) Schrift
        # ----------------------------------------------------------
        font_card = self._make_card(7, i18n.t("cs.card_font"))
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
        # 8) Speichern + Erfolgsmeldung
        # ----------------------------------------------------------
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=8, column=0, pady=(16, 4))
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

        # ----------------------------------------------------------
        # 9) Workflow-Steuerung (Projektmodus) + Zurück
        # ----------------------------------------------------------
        self.btn_start = ctk.CTkButton(
            self, text=i18n.t("cs.start_processing"), width=260, height=48,
            font=self.font("display", 15), corner_radius=10,
            fg_color=self.color("accent"), hover_color=self.color("accent_hover"),
            text_color="#1a1a1a",
            command=self._start_project_workflow)
        self.btn_start.grid(row=10, column=0, pady=(4, 8))

        self.btn_back = ctk.CTkButton(
            self, text=i18n.t("common.back"), width=120, height=36,
            font=self.font("body", 13), corner_radius=8,
            fg_color="transparent", border_width=1,
            border_color=self.color("border"),
            text_color=self.color("text"),
            command=lambda: self.navigate(
                "new_project" if getattr(self.controller, "pending_project", None)
                else "home"))
        self.btn_back.grid(row=11, column=0, pady=(8, 24))

        # Gespeicherte Werte laden (nach dem Widget-Aufbau)
        self.load_style()
        self._refresh_workflow_mode()

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

    def _rebuild_preview_layout(self):
        """Berechnet Wortpositionen/-zeiten analog zum echten Renderer."""
        import tkinter.font as tkfont

        W, H = self._preview_size
        VIDEO_W, VIDEO_H = 1080, 1920    # virtuelle Videogröße (Portrait)
        layout = CaptionRenderer.compute_layout(VIDEO_W, VIDEO_H)
        px = max(12, int(round(layout["font_size"] * (H / VIDEO_H))))
        family = self.style.get("font_name") or "Arial Black"
        self._preview_font = tkfont.Font(family=family, size=px, weight="bold")

        words = i18n.t("cs.preview_sentence").split()
        per_line = max(1, layout["max_words_per_line"])   # wie im Renderer
        lines = [words[i:i + per_line]
                 for i in range(0, len(words), per_line)][:2]

        margin_frac = layout["margin_v"] / VIDEO_H        # Safe Area unten
        line_h = px * 1.3
        ys = [H * (1 - margin_frac) - line_h * (len(lines) - 1 - k)
              for k in range(len(lines))]

        f = self._preview_font
        space_w = f.measure(" ")
        self._preview_words = []
        for li, line_words in enumerate(lines):
            widths = [f.measure(word) for word in line_words]
            x = (W - (sum(widths) + space_w * (len(line_words) - 1))) / 2
            y = ys[li]
            for word, wd in zip(line_words, widths):
                self._preview_words.append(
                    {"text": word, "x": x, "y": y, "w": wd})
                x += wd + space_w

        # Zeitplan: Wort ~450 ms gesprochen, danach pop_decay zurück auf 100 %
        timeline = []
        t = 300
        word_ms = 450
        decay = max(1, int(self.style.get("pop_decay_ms", 150)))
        for _ in self._preview_words:
            timeline.append({"start": t, "end": t + word_ms,
                             "decay_end": t + word_ms + decay})
            t += word_ms + 60
        self._preview_timeline = timeline
        self._preview_total_ms = t + decay + 200

    def _current_pop_state(self, t_ms: float):
        """(aktiver Wort-Index|None, Scale-%) – ASS-\\t-Semantik des Renderers.

        Während des Wortes auf pop_scale hochskalieren, danach über
        pop_decay_ms linear zurück auf 100 %. Pop aus -> nur Highlight.
        """
        active, scale = None, 100.0
        if not self.style.get("pop_enabled"):
            for i, slot in enumerate(self._preview_timeline):
                if slot["start"] <= t_ms < slot["end"]:
                    active = i
                    break
            return active, 100.0

        pop_scale = max(100, int(self.style.get("pop_scale", 112)))
        for i, slot in enumerate(self._preview_timeline):
            if slot["start"] <= t_ms < slot["decay_end"]:
                active = i
                if t_ms < slot["end"]:
                    frac = ((t_ms - slot["start"]) /
                            max(1, slot["end"] - slot["start"]))
                    scale = 100 + (pop_scale - 100) * min(1.0, frac * 1.6)
                else:
                    frac = ((t_ms - slot["end"]) /
                            max(1, slot["decay_end"] - slot["end"]))
                    scale = pop_scale - (pop_scale - 100) * min(1.0, frac)
                break
        return active, max(100.0, scale)

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
        """Wendet ein Preset auf die aktuellen Style-Werte an."""
        overrides = PRESETS.get(name, {})
        self.style = {**DEFAULT_STYLE, **overrides}
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

    # ------------------------------------------------------------------
    # Lifecycle (Phase 32): Preview-Timer sauber starten/stoppen
    # ------------------------------------------------------------------

    def on_hide(self):
        """Laufende Preview-Animation stoppen (keine Callback-Leichen)."""
        self._cancel_preview_timer()

    def on_show(self):
        """Preview beim erneuten Anzeigen sauber neu starten."""
        self._refresh_workflow_mode()
        if getattr(self, "_preview_words", None):
            self._restart_preview_animation()

    def destroy(self):
        """Preview-Timer vor der Zerstörung abbrechen (kein bgerror)."""
        self._cancel_preview_timer()
        super().destroy()