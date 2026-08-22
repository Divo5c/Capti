#!/usr/bin/env python3
"""
Capti - Lokale Short-Video Untertitel-Generierung
Modernes GUI mit CustomTkinter, Dark/Light Mode, Drag & Drop, Language Switcher.
"""

import os
import sys
import json
import threading
import logging
import shutil
from pathlib import Path
from typing import Optional, Dict, Any

import customtkinter as ctk
from tkinterdnd2 import TkinterDnD, DND_FILES
from tkinter import filedialog, messagebox

# Lokale Module importieren
from subtitle_engine import create_subtitle_engine, SubtitleEngine
from video_processor import create_video_processor, VideoProcessor

# Logging konfigurieren
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def resource_path(relative_name: str) -> Path:
    """Pfad zu einer gebündelten Ressource (Development und PyInstaller One-Folder/One-File)."""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / relative_name
    return Path(__file__).parent / relative_name


def app_base_dir() -> Path:
    """Basisverzeichnis der Anwendung (EXE-Ordner bei PyInstaller, sonst Projektordner)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def app_config_dir() -> Path:
    """Benutzerkonfigurations-Verzeichnis: %APPDATA%\\Capti."""
    config_dir = Path(os.environ.get("APPDATA", str(Path.home()))) / "Capti"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


# Pfade für gebündelte Ressourcen (read-only, im Bundle enthalten)
TRANSLATIONS_FILE = resource_path("translations.json")

# Benutzer-Konfiguration (beschreibbar) im APPDATA-Profil
CONFIG_FILE = app_config_dir() / "config.json"

# Einmalige Migration: Bestehende Konfiguration aus dem Projektordner übernehmen
_legacy_config = Path(__file__).parent / "config.json"
if not CONFIG_FILE.exists() and _legacy_config.exists():
    try:
        shutil.copy2(_legacy_config, CONFIG_FILE)
    except Exception:
        pass  # Fallback: Defaults werden verwendet

# Temp-Ordner Pfad (neben der Anwendung, nicht im schreibgeschützten Bundle)
TEMP_DIR = app_base_dir() / "_temp"


class TranslationManager:
    """Verwaltet Übersetzungen und Spracheinstellungen."""

    def __init__(self):
        self.translations: Dict[str, Dict[str, str]] = {}
        self.current_language: str = "de"
        self._load_translations()

    def _load_translations(self):
        """Lädt Übersetzungen aus JSON-Datei."""
        try:
            with open(TRANSLATIONS_FILE, "r", encoding="utf-8") as f:
                self.translations = json.load(f)
        except Exception as e:
            logger.error(f"Fehler beim Laden der Übersetzungen: {e}")
            # Fallback auf Deutsch
            self.translations = {"de": {}, "en": {}}

    def set_language(self, language: str):
        """Setzt die aktuelle Sprache."""
        if language in self.translations:
            self.current_language = language
            self.save_config()

    def get(self, key: str) -> str:
        """Gibt übersetzten Text für aktuellen Key zurück."""
        return self.translations.get(self.current_language, {}).get(key, key)

    def get_available_languages(self) -> list:
        """Gibt verfügbare Sprachen zurück."""
        return list(self.translations.keys())

    def load_config(self):
        """Lädt Konfiguration aus config.json."""
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    self.current_language = config.get("language", "de")
        except Exception as e:
            logger.warning(f"Fehler beim Laden der Config: {e}")

    def save_config(self):
        """Speichert Konfiguration in config.json."""
        try:
            config = {
                "theme": ctk.get_appearance_mode().lower(),
                "language": self.current_language
            }
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            logger.warning(f"Fehler beim Speichern der Config: {e}")


class ConfigManager:
    """Verwaltet Theme-Einstellungen."""

    def __init__(self):
        self.current_theme: str = "dark"

    def load_config(self):
        """Lädt Theme aus config.json."""
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    self.current_theme = config.get("theme", "dark")
        except Exception as e:
            logger.warning(f"Fehler beim Laden der Theme-Config: {e}")

    def set_theme(self, theme: str):
        """Setzt Theme und speichert es."""
        self.current_theme = theme
        ctk.set_appearance_mode(theme)
        self.save_config()

    def toggle_theme(self):
        """Wechselt zwischen Dark und Light Mode."""
        new_theme = "light" if self.current_theme == "dark" else "dark"
        self.set_theme(new_theme)
        return new_theme

    def save_config(self):
        """Speichert Theme in config.json."""
        try:
            config = {}
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    config = json.load(f)
            config["theme"] = self.current_theme
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            logger.warning(f"Fehler beim Speichern der Theme-Config: {e}")


class CaptiApp:
    """Hauptanwendungsklasse für die Capti GUI mit CustomTkinter."""

    def __init__(self, root: ctk.CTk):
        self.root = root
        self.root.title("Capti")
        self.root.geometry("800x700")
        self.root.minsize(1135, 1160)

        # Temp-Ordner beim Start bereinigen
        self._cleanup_temp_dir()

        # Manager initialisieren
        self.translation_mgr = TranslationManager()
        self.config_mgr = ConfigManager()

        # Config laden
        self.translation_mgr.load_config()
        self.config_mgr.load_config()

        # Theme anwenden
        ctk.set_appearance_mode(self.config_mgr.current_theme)
        ctk.set_default_color_theme("blue")

        # State-Variablen
        self.video_path: str = ""
        self.audio_path: str = ""
        self.srt_path: str = ""
        self.output_video_path: str = ""
        self.is_processing: bool = False

        # Engine-Instanzen
        self.subtitle_engine: Optional[SubtitleEngine] = None
        self.video_processor: Optional[VideoProcessor] = None

        # GUI aufbauen
        self._setup_ui()
        self._check_ffmpeg()
        self._update_ui_texts()

        # Cleanup beim Schließen registrieren
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _setup_ui(self):
        """Erstellt die Benutzeroberfläche mit CustomTkinter."""
        # Haupt-Container
        self.main_frame = ctk.CTkFrame(self.root, corner_radius=0)
        self.main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # Grid-Konfiguration für Responsivität
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(2, weight=1)  # Drop-Zone expandiert
        self.main_frame.grid_rowconfigure(5, weight=1)  # Log expandiert

        # --- Header mit Title, Theme Toggle, Language Switcher ---
        self.header_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.header_frame.grid(row=0, column=0, sticky="ew", pady=(0, 20))
        self.header_frame.grid_columnconfigure(1, weight=1)

        # Title
        self.title_label = ctk.CTkLabel(
            self.header_frame,
            text="",
            font=ctk.CTkFont(size=24, weight="bold")
        )
        self.title_label.grid(row=0, column=0, sticky="w")

        # Subtitle
        self.subtitle_label = ctk.CTkLabel(
            self.header_frame,
            text="",
            font=ctk.CTkFont(size=12),
            text_color="gray"
        )
        self.subtitle_label.grid(row=1, column=0, sticky="w", pady=(2, 0))

        # Right side: Theme + Language
        self.controls_frame = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        self.controls_frame.grid(row=0, column=2, rowspan=2, sticky="e")

        # Theme Toggle
        self.theme_label = ctk.CTkLabel(
            self.controls_frame,
            text="",
            font=ctk.CTkFont(size=12)
        )
        self.theme_label.grid(row=0, column=0, padx=(0, 8), sticky="e")

        self.theme_switch = ctk.CTkSwitch(
            self.controls_frame,
            text="",
            command=self._on_theme_toggle,
            width=50,
            height=24
        )
        self.theme_switch.grid(row=0, column=1, padx=(0, 20), sticky="e")
        # Set initial state
        self.theme_switch.select() if self.config_mgr.current_theme == "dark" else self.theme_switch.deselect()

        # Language Switcher
        self.lang_label = ctk.CTkLabel(
            self.controls_frame,
            text="",
            font=ctk.CTkFont(size=12)
        )
        self.lang_label.grid(row=0, column=2, padx=(0, 8), sticky="e")

        self.lang_var = ctk.StringVar(value=self.translation_mgr.current_language)
        self.lang_combo = ctk.CTkComboBox(
            self.controls_frame,
            variable=self.lang_var,
            values=["de", "en"],
            width=100,
            command=self._on_language_change
        )
        self.lang_combo.grid(row=0, column=3, sticky="e")

        # --- Schritt 1: Video auswählen ---
        self.step1_frame = ctk.CTkFrame(self.main_frame)
        self.step1_frame.grid(row=1, column=0, sticky="ew", pady=(0, 15))
        self.step1_frame.grid_columnconfigure(0, weight=1)

        self.step1_title = ctk.CTkLabel(
            self.step1_frame,
            text="",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.step1_title.grid(row=0, column=0, sticky="w", padx=20, pady=(15, 10))

        # Drop Zone
        self.drop_frame = ctk.CTkFrame(self.step1_frame, fg_color=("gray85", "gray20"), corner_radius=12)
        self.drop_frame.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 15))
        self.drop_frame.grid_columnconfigure(0, weight=1)

        self.drop_label = ctk.CTkLabel(
            self.drop_frame,
            text="",
            font=ctk.CTkFont(size=14),
            text_color=("gray40", "gray60")
        )
        self.drop_label.grid(row=0, column=0, pady=40, padx=20)

        # Drag & Drop registrieren
        self.drop_frame.drop_target_register(DND_FILES)
        self.drop_frame.dnd_bind('<<Drop>>', self._on_drop)
        self.drop_frame.dnd_bind('<<DragEnter>>', self._on_drag_enter)
        self.drop_frame.dnd_bind('<<DragLeave>>', self._on_drag_leave)

        # Auch Label als Drop-Target
        self.drop_label.drop_target_register(DND_FILES)
        self.drop_label.dnd_bind('<<Drop>>', self._on_drop)
        self.drop_label.dnd_bind('<<DragEnter>>', self._on_drag_enter)
        self.drop_label.dnd_bind('<<DragLeave>>', self._on_drag_leave)

        # Klick auf Drop-Zone öffnet Datei-Dialog
        self.drop_frame.bind("<Button-1>", lambda e: self._select_video())
        self.drop_label.bind("<Button-1>", lambda e: self._select_video())

        # Video Path Anzeige
        self.video_path_var = ctk.StringVar()
        self.video_path_entry = ctk.CTkEntry(
            self.step1_frame,
            textvariable=self.video_path_var,
            state="readonly",
            height=36,
            font=ctk.CTkFont(size=12)
        )
        self.video_path_entry.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 15))

        # Select Button
        self.btn_select_video = ctk.CTkButton(
            self.step1_frame,
            text="",
            command=self._select_video,
            height=36,
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self.btn_select_video.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 15))

        # --- Schritt 2: Einstellungen ---
        self.step2_frame = ctk.CTkFrame(self.main_frame)
        self.step2_frame.grid(row=2, column=0, sticky="ew", pady=(0, 15))
        self.step2_frame.grid_columnconfigure(1, weight=1)

        self.step2_title = ctk.CTkLabel(
            self.step2_frame,
            text="",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.step2_title.grid(row=0, column=0, columnspan=2, sticky="w", padx=20, pady=(15, 15))

        # Sprache (Transkription)
        self.trans_lang_label = ctk.CTkLabel(
            self.step2_frame,
            text="",
            font=ctk.CTkFont(size=13)
        )
        self.trans_lang_label.grid(row=1, column=0, sticky="w", padx=20, pady=(0, 10))

        self.trans_lang_var = ctk.StringVar(value="auto")
        self.trans_lang_combo = ctk.CTkComboBox(
            self.step2_frame,
            variable=self.trans_lang_var,
            values=["auto", "de", "en", "fr", "es", "it", "pt", "nl", "pl", "ru", "ja", "ko", "zh"],
            width=120,
            height=32,
            font=ctk.CTkFont(size=12)
        )
        self.trans_lang_combo.grid(row=1, column=1, sticky="w", padx=20, pady=(0, 10))

        # Whisper Modell
        self.model_label = ctk.CTkLabel(
            self.step2_frame,
            text="",
            font=ctk.CTkFont(size=13)
        )
        self.model_label.grid(row=2, column=0, sticky="w", padx=20, pady=(0, 10))

        self.model_var = ctk.StringVar(value="small")
        self.model_combo = ctk.CTkComboBox(
            self.step2_frame,
            variable=self.model_var,
            values=["tiny", "base", "small", "medium"],
            width=120,
            height=32,
            font=ctk.CTkFont(size=12)
        )
        self.model_combo.grid(row=2, column=1, sticky="w", padx=20, pady=(0, 10))

        self.model_hint_label = ctk.CTkLabel(
            self.step2_frame,
            text="",
            font=ctk.CTkFont(size=11),
            text_color="gray"
        )
        self.model_hint_label.grid(row=3, column=0, columnspan=2, sticky="w", padx=20, pady=(0, 15))

        # Übersetzen nach (Ollama-Vorbereitung)
        self.translate_label = ctk.CTkLabel(
            self.step2_frame,
            text="",
            font=ctk.CTkFont(size=13)
        )
        self.translate_label.grid(row=4, column=0, sticky="w", padx=20, pady=(0, 10))

        self.translate_var = ctk.StringVar(value="none")
        self.translate_combo = ctk.CTkComboBox(
            self.step2_frame,
            variable=self.translate_var,
            values=["none", "en", "es", "fr", "it", "pt", "nl", "pl", "ru", "ja", "ko", "zh"],
            width=120,
            height=32,
            font=ctk.CTkFont(size=12)
        )
        self.translate_combo.grid(row=4, column=1, sticky="w", padx=20, pady=(0, 15))

        # --- Schritt 3: Verarbeitung ---
        self.step3_frame = ctk.CTkFrame(self.main_frame)
        self.step3_frame.grid(row=3, column=0, sticky="ew", pady=(0, 15))
        self.step3_frame.grid_columnconfigure(0, weight=1)
        self.step3_frame.grid_columnconfigure(1, weight=1)

        self.step3_title = ctk.CTkLabel(
            self.step3_frame,
            text="",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.step3_title.grid(row=0, column=0, columnspan=2, sticky="w", padx=20, pady=(15, 15))

        self.btn_generate = ctk.CTkButton(
            self.step3_frame,
            text="",
            command=self._start_processing,
            height=44,
            font=ctk.CTkFont(size=14, weight="bold"),
            state="disabled"
        )
        self.btn_generate.grid(row=1, column=0, sticky="ew", padx=(20, 10), pady=(0, 15))

        self.btn_save = ctk.CTkButton(
            self.step3_frame,
            text="",
            command=self._save_output_video,
            height=44,
            font=ctk.CTkFont(size=14, weight="bold"),
            state="disabled",
            fg_color=("gray70", "gray30"),
            hover_color=("gray60", "gray40")
        )
        self.btn_save.grid(row=1, column=1, sticky="ew", padx=(10, 20), pady=(0, 15))

        # --- Fortschrittsanzeige ---
        self.progress_frame = ctk.CTkFrame(self.main_frame)
        self.progress_frame.grid(row=4, column=0, sticky="ew", pady=(0, 15))
        self.progress_frame.grid_columnconfigure(0, weight=1)

        self.progress_title = ctk.CTkLabel(
            self.progress_frame,
            text="",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.progress_title.grid(row=0, column=0, sticky="w", padx=20, pady=(15, 10))

        self.progress_var = ctk.DoubleVar(value=0)
        self.progress_bar = ctk.CTkProgressBar(
            self.progress_frame,
            variable=self.progress_var,
            height=12,
            corner_radius=6
        )
        self.progress_bar.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 10))
        self.progress_bar.set(0)

        self.status_var = ctk.StringVar(value="")
        self.status_label = ctk.CTkLabel(
            self.progress_frame,
            textvariable=self.status_var,
            font=ctk.CTkFont(size=12),
            anchor="w"
        )
        self.status_label.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 15))

        # --- Log-Bereich ---
        self.log_frame = ctk.CTkFrame(self.main_frame)
        self.log_frame.grid(row=5, column=0, sticky="nsew", pady=(0, 0))
        self.log_frame.grid_columnconfigure(0, weight=1)
        self.log_frame.grid_rowconfigure(1, weight=1)

        self.log_title = ctk.CTkLabel(
            self.log_frame,
            text="",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.log_title.grid(row=0, column=0, sticky="w", padx=20, pady=(15, 10))

        self.log_text = ctk.CTkTextbox(
            self.log_frame,
            font=ctk.CTkFont(family="Consolas", size=11),
            corner_radius=8,
            wrap="word"
        )
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 15))
        self.log_text.configure(state="disabled")

    def _check_ffmpeg(self):
        """Prüft beim Start, ob ffmpeg verfügbar ist."""
        try:
            self.video_processor = create_video_processor()
            self._log("INFO", "ffmpeg gefunden und bereit.")
        except FileNotFoundError as e:
            self._log("ERROR", str(e))
            messagebox.showerror(
                self.translation_mgr.get("title"),
                "ffmpeg wurde nicht gefunden!\n\n"
                "Bitte installieren Sie ffmpeg:\n"
                "1. Laden Sie es von https://ffmpeg.org/download.html herunter\n"
                "2. Entpacken Sie es (z.B. nach C:\\ffmpeg)\n"
                "3. Fügen Sie den bin-Ordner zur PATH-Umgebungsvariable hinzu\n"
                "4. Starten Sie die App neu"
            )
            self.btn_select_video.configure(state="disabled")
            self.drop_frame.configure(state="disabled")

    def _on_theme_toggle(self):
        """Handler für Theme-Wechsel."""
        new_theme = self.config_mgr.toggle_theme()
        self.theme_switch.select() if new_theme == "dark" else self.theme_switch.deselect()
        self._log("INFO", f"Theme gewechselt zu: {new_theme}")

    def _on_language_change(self, language: str):
        """Handler für Sprachwechsel."""
        self.translation_mgr.set_language(language)
        self._update_ui_texts()
        self._log("INFO", f"UI-Sprache geändert zu: {language}")

    def _update_ui_texts(self):
        """Aktualisiert alle UI-Texte basierend auf aktueller Sprache."""
        t = self.translation_mgr.get

        # Header
        self.title_label.configure(text=t("title"))
        self.subtitle_label.configure(text=t("subtitle"))
        self.theme_label.configure(text=t("theme"))
        self.lang_label.configure(text=t("ui_language"))

        # Schritt 1
        self.step1_title.configure(text=t("step1"))
        self.drop_label.configure(text=t("drop_zone"))
        self.btn_select_video.configure(text=t("select_video"))

        # Schritt 2
        self.step2_title.configure(text=t("step2"))
        self.trans_lang_label.configure(text=t("language"))
        self.model_label.configure(text=t("model"))
        self.model_hint_label.configure(text=t("model_hint"))
        self.translate_label.configure(text=t("translate_to"))

        # Schritt 3
        self.step3_title.configure(text=t("step3"))
        self.btn_generate.configure(text=t("generate"))
        self.btn_save.configure(text=t("save"))

        # Fortschritt
        self.progress_title.configure(text=t("progress"))
        if not self.is_processing:
            if not self.video_path:
                self.status_var.set(t("status_ready"))
            else:
                self.status_var.set(t("status_video_selected"))

        # Log
        self.log_title.configure(text=t("log"))

    def _on_drag_enter(self, event):
        """Visuelles Feedback beim Drag-Enter."""
        self.drop_frame.configure(fg_color=("gray75", "gray30"))
        self.drop_label.configure(text_color=("gray20", "gray80"))

    def _on_drag_leave(self, event):
        """Visuelles Feedback beim Drag-Leave."""
        self.drop_frame.configure(fg_color=("gray85", "gray20"))
        self.drop_label.configure(text_color=("gray40", "gray60"))

    def _on_drop(self, event):
        """Handler für Datei-Drop."""
        self._on_drag_leave(event)
        files = self.root.tk.splitlist(event.data)
        if files:
            file_path = files[0]
            if self._is_valid_video(file_path):
                self.video_path = file_path
                self._on_video_selected()
            else:
                self._log("WARNING", "Ungültiges Dateiformat. Erlaubt: mp4, mov, avi, mkv, webm")

    def _is_valid_video(self, path: str) -> bool:
        """Prüft ob Datei ein gültiges Videoformat hat."""
        valid_extensions = {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv', '.m4v'}
        return Path(path).suffix.lower() in valid_extensions

    def _select_video(self):
        """Öffnet Datei-Dialog zur Video-Auswahl."""
        filetypes = [
            ("Video-Dateien", "*.mp4 *.mov *.avi *.mkv *.webm *.flv *.wmv *.m4v"),
            ("Alle Dateien", "*.*")
        ]
        path = filedialog.askopenfilename(
            title=self.translation_mgr.get("select_video"),
            filetypes=filetypes
        )

        if path:
            self.video_path = path
            self._on_video_selected()

    def _on_video_selected(self):
        """Wird aufgerufen, wenn ein Video ausgewählt wurde."""
        self.video_path_var.set(self.video_path)
        self._log("INFO", f"Video ausgewählt: {os.path.basename(self.video_path)}")
        self.btn_generate.configure(state="normal")
        self.btn_save.configure(state="disabled")
        self.progress_var.set(0)
        self.status_var.set(self.translation_mgr.get("status_video_selected"))

    def _start_processing(self):
        """Startet die Verarbeitung in einem separaten Thread."""
        if self.is_processing:
            return

        if not self.video_path:
            messagebox.showwarning(
                self.translation_mgr.get("title"),
                self.translation_mgr.get("status_ready")
            )
            return

        # UI aktualisieren
        self.is_processing = True
        self.btn_generate.configure(state="disabled")
        self.btn_select_video.configure(state="disabled")
        self.btn_save.configure(state="disabled")
        self.progress_var.set(0)
        self.status_var.set(self.translation_mgr.get("status_processing"))

        # Thread starten
        thread = threading.Thread(target=self._process_video, daemon=True)
        thread.start()

    def _process_video(self):
        """Hauptverarbeitungslogik (läuft im Hintergrund-Thread)."""
        try:
            # 1. SubtitleEngine initialisieren
            self._update_status(self.translation_mgr.get("status_processing"), 5)
            model_size = self.model_var.get()
            self.subtitle_engine = create_subtitle_engine(model_size=model_size, device="auto")

            # 2. VideoProcessor initialisieren (falls noch nicht geschehen)
            if self.video_processor is None:
                self.video_processor = create_video_processor()

            # 3. Temp-Ordner erstellen
            TEMP_DIR.mkdir(parents=True, exist_ok=True)

            # 4. Audio extrahieren (in _temp)
            self._update_status("Extrahiere Audio...", 15)
            video_stem = Path(self.video_path).stem
            self.audio_path = str(TEMP_DIR / f"{video_stem}_audio.wav")

            self.audio_path = self.video_processor.extract_audio(self.video_path, self.audio_path)
            self._log("INFO", f"Audio extrahiert: {os.path.basename(self.audio_path)}")

            # 5. Transkription (SRT in _temp)
            self._update_status("Transkribiere Audio...", 30)
            language = self.trans_lang_var.get()
            if language == "auto":
                language = None

            self.srt_path = str(TEMP_DIR / f"{video_stem}.srt")
            self.subtitle_engine.transcribe_and_generate_srt(
                self.audio_path,
                self.srt_path,
                language
            )
            self._log("SUCCESS", f"SRT-Datei erstellt: {os.path.basename(self.srt_path)}")

            # 6. Untertitel einbetten (Output-Video im Original-Ordner)
            self._update_status("Bette Untertitel ein...", 70)
            video_dir = os.path.dirname(self.video_path)
            self.output_video_path = os.path.join(video_dir, f"{video_stem}_subtitled.mp4")
            self.output_video_path = self.video_processor.embed_subtitles(
                self.video_path,
                self.srt_path,
                self.output_video_path
            )
            self._log("SUCCESS", f"Video mit Untertiteln erstellt: {os.path.basename(self.output_video_path)}")

            # 7. Fertig
            self._update_status(self.translation_mgr.get("status_done"), 100)
            self._log("SUCCESS", "Verarbeitung erfolgreich abgeschlossen!")

            # UI im Haupt-Thread aktualisieren
            self.root.after(0, self._processing_finished)

        except Exception as e:
            self._log("ERROR", f"Fehler: {str(e)}")
            self.root.after(0, lambda: self._processing_error(str(e)))

    def _processing_finished(self):
        """Wird aufgerufen, wenn die Verarbeitung erfolgreich war."""
        self.is_processing = False
        self.btn_generate.configure(state="normal")
        self.btn_select_video.configure(state="normal")
        self.btn_save.configure(state="normal")
        self.status_var.set(self.translation_mgr.get("status_done"))

    def _processing_error(self, error_msg: str):
        """Wird aufgerufen, wenn ein Fehler aufgetreten ist."""
        self.is_processing = False
        self.btn_generate.configure(state="normal")
        self.btn_select_video.configure(state="normal")
        self.btn_save.configure(state="disabled")
        self.progress_var.set(0)
        self.status_var.set("Fehler aufgetreten.")
        messagebox.showerror("Verarbeitungsfehler", f"Ein Fehler ist aufgetreten:\n\n{error_msg}")

    def _save_output_video(self):
        """Speichert das fertige Video an einem benutzerdefinierten Ort."""
        if not self.output_video_path or not os.path.exists(self.output_video_path):
            messagebox.showwarning("Kein Video", "Es gibt noch kein fertiges Video zum Speichern.")
            return

        filetypes = [("MP4 Video", "*.mp4"), ("Alle Dateien", "*.*")]
        default_name = os.path.basename(self.output_video_path)

        save_path = filedialog.asksaveasfilename(
            title=self.translation_mgr.get("save"),
            defaultextension=".mp4",
            initialfile=default_name,
            filetypes=filetypes
        )

        if save_path:
            try:
                shutil.copy2(self.output_video_path, save_path)
                self._log("SUCCESS", f"Video gespeichert: {save_path}")
                messagebox.showinfo("Gespeichert", f"Video erfolgreich gespeichert:\n{save_path}")
            except Exception as e:
                self._log("ERROR", f"Fehler beim Speichern: {e}")
                messagebox.showerror("Speicherfehler", f"Fehler beim Speichern:\n{e}")

    def _update_status(self, message: str, progress: float):
        """Aktualisiert Status und Fortschrittsbalken (thread-safe)."""
        self.root.after(0, lambda: self._do_update_status(message, progress))

    def _do_update_status(self, message: str, progress: float):
        """Führt das eigentliche UI-Update aus."""
        self.status_var.set(message)
        self.progress_var.set(progress / 100.0)

    def _log(self, level: str, message: str):
        """Fügt eine Log-Nachricht hinzu (thread-safe)."""
        self.root.after(0, lambda: self._do_log(level, message))

    def _do_log(self, level: str, message: str):
        """Führt das eigentliche Log-Update aus."""
        self.log_text.configure(state="normal")
        # Farb-Codes für verschiedene Level
        color_map = {
            "INFO": ("#4ec9b0", "#4ec9b0"),
            "WARNING": ("#dcdcaa", "#dcdcaa"),
            "ERROR": ("#f44747", "#f44747"),
            "SUCCESS": ("#4ec9b0", "#4ec9b0")
        }
        color = color_map.get(level, ("white", "white"))

        self.log_text.insert("end", f"[{level}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _cleanup_temp_dir(self):
        """Löscht den _temp-Ordner rekursiv (stillschweigend)."""
        try:
            if TEMP_DIR.exists():
                shutil.rmtree(TEMP_DIR)
                logger.info(f"Temp-Ordner bereinigt: {TEMP_DIR}")
        except Exception:
            pass  # Stillschweigend ignorieren

    def _on_closing(self):
        """Wird aufgerufen, wenn das Fenster geschlossen wird."""
        self._cleanup_temp_dir()
        self.root.destroy()


def main():
    """Einstiegspunkt der Anwendung."""
    # DPI-Awareness für Windows (scharfe Darstellung)
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    # TkinterDnD Root erstellen (muss vor CustomTkinter sein)
    root = TkinterDnD.Tk()

    # CustomTkinter auf TkinterDnD Root anwenden
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    app = CaptiApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()