"""
Capti-Pipeline: UI-agnostische Orchestrierung der Videoverarbeitung.

Enthält die komplette Verarbeitungskette (Audio-Extraktion, Transkription,
Caption-Gruppierung, SRT/ASS-Erzeugung, Untertitel-Einbettung) – funktional
1:1 aus der bisherigen CaptiApp._process_video() übernommen.

Die UI kommuniziert ausschließlich über Callbacks:
    on_status(message: str)
    on_progress(percent: float)          # 0..100
    on_log(level: str, message: str)     # level: INFO/WARNING/ERROR/SUCCESS
    on_done(output_path: str)
    on_error(error_message: str)

Alle Callbacks sind optional.
"""

import os
import logging
import re
from pathlib import Path
from typing import Callable, Optional

from subtitle_engine import create_subtitle_engine, SubtitleEngine
from video_processor import create_video_processor, VideoProcessor
from caption_renderer import create_caption_renderer, group_caption_segments, CaptionRenderer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------
# Stabile Status-Keys (UI-agnostisch).
# Die Pipeline kennt keine Sprache: on_status erhält ausschließlich
# diese Keys; die UI übersetzt sie (i18n / translations.json).
# Technische Log-Meldungen und Fehler-Texte bleiben frei formuliert.
# ---------------------------------------------------------------------
STATUS_STARTED = "pipeline.started"
STATUS_EXTRACT_AUDIO = "pipeline.extract_audio"
STATUS_TRANSCRIBE = "pipeline.transcribe"
STATUS_EMBED_SUBTITLES = "pipeline.embed_subtitles"
STATUS_COMPLETED = "pipeline.completed"

# Sichere Defaults = aktueller Capti-Look (identisch zu CaptionRenderer)
CAPTION_STYLE_DEFAULTS = {
    "normal_color": "&H00FFFFFF",
    "highlight_color": "&H0000FFFF",
    "outline_color": "&H00101010",
    "shadow_color": "&H80000000",
    "font_name": "Arial Black",
    "font_size": 68,
    "pop_enabled": True,
    "pop_scale": 112,
    "pop_decay_ms": 150,
}

_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _hex_to_ass(hex_color, default: str, alpha: int = 0) -> str:
    """Konvertiert #RRGGBB in ASS &HAABBGGRR; ungültige Werte -> Default."""
    if not isinstance(hex_color, str) or not _HEX_RE.match(hex_color):
        return default
    r, g, b = hex_color[1:3], hex_color[3:5], hex_color[5:7]
    try:
        a = max(0, min(255, int(alpha)))
        return f"&H{a:02X}{b.upper()}{g.upper()}{r.upper()}"
    except (TypeError, ValueError):
        return default


def _int_in_range(value, default: int, lo: int, hi: int) -> int:
    """Ganzzahl in Bereich; ungültige Werte -> Default."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    if v < lo or v > hi:
        return default  # außerhalb des Bereichs -> sicherer Default
    return v


def resolve_caption_style(style: Optional[dict]) -> dict:
    """
    Validiert eine Caption-Style-Konfiguration (z.B. aus config.json).

    Ungültige/fehlende Werte -> sichere Defaults. None/leer -> Defaults.
    Returns:
        Dict mit ASS-Farben und validierten Pop-/Font-Werten.
    """
    result = dict(CAPTION_STYLE_DEFAULTS)
    if not isinstance(style, dict):
        return result

    shadow_alpha = style.get("shadow_alpha", 128)
    try:
        shadow_alpha = int(shadow_alpha)
    except (TypeError, ValueError):
        shadow_alpha = 128

    result["normal_color"] = _hex_to_ass(
        style.get("normal_color"), result["normal_color"])
    result["highlight_color"] = _hex_to_ass(
        style.get("highlight_color"), result["highlight_color"])
    result["outline_color"] = _hex_to_ass(
        style.get("outline_color"), result["outline_color"])
    # Shadow: Alpha-Byte aus shadow_alpha (00=opak .. FF=transparent);
    # ohne gültige Farbe: Default-Look (&H80000000)
    result["shadow_color"] = _hex_to_ass(
        style.get("shadow_color"), result["shadow_color"], alpha=shadow_alpha)

    font_name = style.get("font_name")
    if isinstance(font_name, str) and font_name.strip():
        result["font_name"] = font_name.strip()
    result["font_size"] = _int_in_range(style.get("font_size"), 68, 20, 200)
    result["pop_enabled"] = bool(style.get("pop_enabled", True))
    result["pop_scale"] = _int_in_range(style.get("pop_scale"), 112, 100, 200)
    result["pop_decay_ms"] = _int_in_range(style.get("pop_decay_ms"), 150, 0, 1000)
    return result


class CaptiPipeline:
    """Führt die komplette Capti-Verarbeitung aus (UI-agnostisch)."""

    def __init__(
        self,
        temp_dir: Path,
        on_status: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[[float], None]] = None,
        on_log: Optional[Callable[[str, str], None]] = None,
        on_done: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        """
        Args:
            temp_dir: Temp-Ordner für Audio/SRT/ASS-Zwischendateien
            on_status: Callback für Statusmeldungen
            on_progress: Callback für Fortschritt (0..100)
            on_log: Callback für Log-Nachrichten (level, message)
            on_done: Callback bei Erfolg (output_path)
            on_error: Callback bei Fehler (error_message)
        """
        self.temp_dir = Path(temp_dir)
        self._on_status = on_status or (lambda msg: None)
        self._on_progress = on_progress or (lambda pct: None)
        self._on_log = on_log or (lambda level, msg: None)
        self._on_done = on_done or (lambda path: None)
        self._on_error = on_error or (lambda err: None)

        self.subtitle_engine: Optional[SubtitleEngine] = None
        self.video_processor: Optional[VideoProcessor] = None
        self.caption_renderer = None

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    def run(self, video_path: str, model_size: str = "small", language: str = None,
            caption_style: Optional[dict] = None) -> str:
        """
        Verarbeitet ein Video komplett (synchron, blockierend).

        Args:
            video_path: Pfad zum Eingangsvideo
            model_size: Whisper-Modellgröße ("tiny", "base", "small", "medium")
            language: Quellsprache ("de", "en", ...) oder None für Auto-Erkennung
            caption_style: Optionale Style-Optionen (Farben als #RRGGBB, Pop etc.)
                           – None bedeutet exakt bisheriges Default-Verhalten

        Returns:
            Pfad zum Output-Video mit eingebrannten Untertiteln

        Raises:
            Exception: bei Fehlern in der Verarbeitung (wird zusätzlich an on_error gemeldet)
        """
        try:
            output_path = self._run(video_path, model_size, language, caption_style)
            self._on_done(output_path)
            return output_path
        except Exception as e:
            logger.error(f"Pipeline-Fehler: {e}")
            self._on_error(str(e))
            raise

    def run_async(self, video_path: str, model_size: str = "small", language: str = None,
                  caption_style: Optional[dict] = None):
        """Startet run() in einem Daemon-Thread."""
        import threading
        thread = threading.Thread(
            target=self.run,
            args=(video_path, model_size, language, caption_style),
            daemon=True
        )
        thread.start()
        return thread

    # ------------------------------------------------------------------
    # Interne Verarbeitung (funktional 1:1 aus _process_video übernommen)
    # ------------------------------------------------------------------

    def _run(self, video_path: str, model_size: str, language: Optional[str],
             caption_style: Optional[dict] = None) -> str:
        # 1. SubtitleEngine initialisieren
        self._status(STATUS_STARTED)
        self._progress(5)
        self.subtitle_engine = create_subtitle_engine(model_size=model_size, device="auto")

        # 2. VideoProcessor initialisieren (falls noch nicht geschehen)
        if self.video_processor is None:
            self.video_processor = create_video_processor()

        # 3. Temp-Ordner erstellen
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        # 4. Audio extrahieren (in _temp)
        self._status(STATUS_EXTRACT_AUDIO, 15)
        video_stem = Path(video_path).stem
        audio_path = str(self.temp_dir / f"{video_stem}_audio.wav")

        audio_path = self.video_processor.extract_audio(video_path, audio_path)
        self._log("INFO", f"Audio extrahiert: {os.path.basename(audio_path)}")

        # 5. Transkription mit Word-Timestamps
        self._status(STATUS_TRANSCRIBE, 30)
        segments = self.subtitle_engine.transcribe(audio_path, language)

        # Tatsächliche Videoauflösung ermitteln (Fallback: None -> Standard-Layout)
        video_width, video_height = None, None
        try:
            info = self.video_processor.get_video_info(video_path)
            stream = next((s for s in info.get("streams", []) if s.get("width")), None)
            if stream:
                video_width = int(stream["width"])
                video_height = int(stream["height"])
        except Exception as e:
            self._log("WARNING", f"Videoauflösung nicht ermittelbar ({e}) – verwende Standard-Layout.")

        # Intelligente Caption-Gruppierung (lange Segmente -> kurze Blöcke)
        layout = (
            CaptionRenderer.compute_layout(video_width, video_height)
            if video_width and video_height else None
        )
        segments = group_caption_segments(segments, layout)

        # SRT aus den gruppierten Segmenten (identische Textblöcke wie ASS)
        srt_path = str(self.temp_dir / f"{video_stem}.srt")
        self.subtitle_engine.generate_srt(segments, srt_path)
        self._log("SUCCESS", f"SRT-Datei erstellt: {os.path.basename(srt_path)}")

        # ASS mit Word-by-Word-Highlighting erzeugen (adaptives Layout).
        # Ohne caption_style exakt bisheriges Verhalten (Renderer-Defaults);
        # mit Style werden nur die vorhandenen Renderer-Parameter gesetzt.
        if self.caption_renderer is None:
            if caption_style:
                renderer_kwargs = resolve_caption_style(caption_style)
                self._log("INFO", f"Caption-Style angewendet: {renderer_kwargs}")
                self.caption_renderer = create_caption_renderer(**renderer_kwargs)
            else:
                self.caption_renderer = create_caption_renderer()
        ass_path = str(self.temp_dir / f"{video_stem}.ass")

        self.caption_renderer.generate_ass(
            segments,
            ass_path,
            video_width=video_width,
            video_height=video_height
        )
        self._log("SUCCESS", f"ASS-Datei erstellt: {os.path.basename(ass_path)}")

        # 6. Untertitel einbetten (Output-Video im Original-Ordner)
        self._status(STATUS_EMBED_SUBTITLES, 70)
        video_dir = os.path.dirname(video_path)
        output_path = os.path.join(video_dir, f"{video_stem}_subtitled.mp4")
        output_path = self.video_processor.embed_ass(video_path, ass_path, output_path)
        self._log("SUCCESS", f"Video mit Untertiteln erstellt: {os.path.basename(output_path)}")

        # 7. Fertig
        self._status(STATUS_COMPLETED, 100)
        self._log("SUCCESS", "Verarbeitung erfolgreich abgeschlossen!")
        return output_path

    # ------------------------------------------------------------------
    # Callback-Helper
    # ------------------------------------------------------------------

    def _status(self, message: str, progress: float = None):
        self._on_status(message)
        if progress is not None:
            self._progress(progress)

    def _progress(self, percent: float):
        self._on_progress(max(0.0, min(100.0, percent)))

    def _log(self, level: str, message: str):
        logger.info(f"[{level}] {message}")
        self._on_log(level, message)


def create_pipeline(temp_dir, **callbacks) -> CaptiPipeline:
    """Factory-Funktion zum Erstellen einer CaptiPipeline."""
    return CaptiPipeline(temp_dir=temp_dir, **callbacks)