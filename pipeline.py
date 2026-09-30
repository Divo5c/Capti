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
import tempfile
import threading
from pathlib import Path
from typing import Callable, Optional, List

from capti_core.caption_style import (
    CAPTION_STYLE_DEFAULTS,
    resolve_caption_style,   # noqa: F401 (Kompatibilitäts-Reexport)
)
from subtitle_engine import create_subtitle_engine, SubtitleEngine
from video_processor import (
    create_video_processor, VideoProcessor, CancelledError,
)
from caption_renderer import create_caption_renderer, group_caption_segments, CaptionRenderer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------
# Stabile Status-Keys (UI-agnostisch).
# Die Pipeline kennt keine Sprache: on_status erhält ausschließlich
# diese Keys; die UI übersetzt sie (i18n / translations.json).
# Technische Log-Meldungen und Fehler-Texte bleiben frei formuliert.
# ---------------------------------------------------------------------
STATUS_STARTED = "pipeline.started"
STATUS_DOWNLOAD_MODEL = "pipeline.download_model"
STATUS_EXTRACT_AUDIO = "pipeline.extract_audio"
STATUS_TRANSCRIBE = "pipeline.transcribe"
STATUS_EMBED_SUBTITLES = "pipeline.embed_subtitles"
STATUS_COMPLETED = "pipeline.completed"
STATUS_CANCELLED = "pipeline.cancelled"


class PipelineJob:
    """Handle für einen per run_async gestarteten Pipeline-Lauf (B2).

    Erlaubt dem Aufrufer: läuft?-Abfrage, Cancel-Anforderung (idempotent)
    und begrenztes Warten – ohne globale Zustände.
    """

    def __init__(self, pipeline: "CaptiPipeline", thread: threading.Thread):
        self._pipeline = pipeline
        self._thread = thread

    @property
    def thread(self) -> threading.Thread:
        """Der Worker-Thread (Kompatibilität)."""
        return self._thread

    @property
    def is_running(self) -> bool:
        """True, solange der Worker-Thread lebt."""
        try:
            return self._thread.is_alive()
        except Exception:
            return False

    @property
    def cancelled(self) -> bool:
        """True, wenn Cancel angefordert wurde."""
        try:
            return self._pipeline.cancel_requested
        except Exception:
            return False

    def cancel(self) -> None:
        """Fordert Abbruch an (idempotent, nicht blockierend)."""
        try:
            self._pipeline.cancel()
        except Exception:
            pass

    def wait(self, timeout: float = None) -> bool:
        """Wartet begrenzt auf sauberes Ende. True = beendet."""
        try:
            self._thread.join(timeout)
        except Exception:
            pass
        return not self.is_running


def _is_writable_dir(path: Path) -> bool:
    """True, wenn path existiert und beschreibbar ist (kein Crash bei Fehlern)."""
    try:
        return path.exists() and os.access(path, os.W_OK)
    except Exception:
        return False


def resolve_output_path(video_path: str, suffix: str = "_subtitled",
                        ext: str = ".mp4") -> str:
    """Ermittelt einen kollisionsfreien Output-Pfad (B4).

    - Standard: `<videoname>_subtitled.mp4` neben dem Quellvideo.
    - Existiert der Name bereits: `_1`, `_2`, ... anhängen (kein
      stilles Ueberschreiben, keine Zufallsnamen, Unicode-sicher).
    - Ist der Zielordner nicht beschreibbar: Fallback auf
      `<System-Temp>/Capti` (+ WARNING-Log), ebenfalls kollisionsfrei.
    """
    src = Path(video_path)
    target_dir = src.parent if str(src.parent) not in ("", ".") else Path(".")
    if not _is_writable_dir(target_dir):
        fallback = Path(tempfile.gettempdir()) / "Capti"
        try:
            fallback.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass  # weiter unten entscheidet die Existenzpruefung
        logger.warning(
            f"Zielordner nicht beschreibbar ({target_dir}) – "
            f"Output-Fallback: {fallback}")
        target_dir = fallback
    candidate = target_dir / f"{src.stem}{suffix}{ext}"
    counter = 1
    while candidate.exists():
        candidate = target_dir / f"{src.stem}{suffix}_{counter}{ext}"
        counter += 1
    return str(candidate)


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
        on_edit_subtitles: Optional[Callable[[str], str]] = None,
        on_cancelled: Optional[Callable[[str], None]] = None,
    ):
        """
        Args:
            temp_dir: Temp-Ordner für Audio/SRT/ASS-Zwischendateien
            on_status: Callback für Statusmeldungen
            on_progress: Callback für Fortschritt (0..100)
            on_log: Callback für Log-Nachrichten (level, message)
            on_done: Callback bei Erfolg (output_path)
            on_error: Callback bei Fehler (error_message)
            on_edit_subtitles: Callback zur Bearbeitung der SRT-Untertitel.
                Nimmt den SRT-Inhalt als String und gibt den bearbeiteten String zurück.
                Wenn None, wird keine Bearbeitung angeboten.
            on_cancelled: Callback bei Abbruch (message)
        """
        self.temp_dir = Path(temp_dir)
        self._on_status = on_status or (lambda msg: None)
        self._on_progress = on_progress or (lambda pct: None)
        self._on_log = on_log or (lambda level, msg: None)
        self._on_done = on_done or (lambda path: None)
        self._on_error = on_error or (lambda err: None)
        self._on_edit_subtitles = on_edit_subtitles  # may be None
        self._on_cancelled = on_cancelled or (lambda msg: None)

        self.subtitle_engine: Optional[SubtitleEngine] = None
        self.video_processor: Optional[VideoProcessor] = None
        self.caption_renderer = None

        # B2: Cancel-Event (pro Pipeline-Instanz; Instanzen werden pro
        # Verarbeitung neu erzeugt, daher keine Altlasten zwischen Läufen)
        # plus Liste eigener Temp-Dateien für gezieltes Cleanup.
        self._cancel_event = threading.Event()
        self._owned_files: list = []
        # Block 20: letztes Transkript (gruppierte Segmente, exakt der
        # ASS-Input) + Quellvideo; nur bei Erfolg gesetzt, sonst None.
        self.last_segments = None
        self.last_video_path = None

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    @property
    def cancel_requested(self) -> bool:
        """True, wenn Abbruch angefordert wurde."""
        try:
            return self._cancel_event.is_set()
        except Exception:
            return False

    def cancel(self) -> None:
        """Fordert Abbruch an (idempotent, nicht blockierend, B2).

        Setzt das Cancel-Event und beendet ggf. laufenden ffmpeg über
        den VideoProcessor. Mehrfaches Cancel ist unbedenklich.
        """
        try:
            self._cancel_event.set()
        except Exception:
            pass
        try:
            processor = self.video_processor
            if processor is not None and hasattr(processor, "request_cancel"):
                processor.request_cancel()
        except Exception:
            pass

    def run(self, video_path: str, model_size: str = "small", language: str = None,
            caption_style: Optional[dict] = None,
            override_segments: Optional[list] = None) -> str:
        """
        Verarbeitet ein Video komplett (synchron, blockierend).

        Args:
            video_path: Pfad zum Eingangsvideo
            model_size: Whisper-Modellgröße ("tiny", "base", "small", "medium")
            language: Quellsprache ("de", "en", ...) oder None für Auto-Erkennung
            caption_style: Optionale Style-Optionen (Farben als #RRGGBB, Pop etc.)
                           – None bedeutet exakt bisheriges Default-Verhalten
            override_segments: Editierte Segmente (Block 22) statt Neutranskription;
                           None/leer bedeutet exakt bisherigen Whisper-Pfad

        Returns:
            Pfad zum Output-Video mit eingebrannten Untertiteln

        Raises:
            CancelledError: bei Abbruch (wird zusätzlich an on_cancelled gemeldet)
            Exception: bei Fehlern in der Verarbeitung (wird zusätzlich an on_error gemeldet)
        """
        try:
            output_path = self._run(video_path, model_size, language,
                                    caption_style, override_segments)
            self._on_done(output_path)
            return output_path
        except CancelledError as e:
            logger.info(f"Pipeline abgebrochen: {e}")
            self._status(STATUS_CANCELLED)
            self._on_cancelled(str(e) or "Verarbeitung abgebrochen")
            raise
        except Exception as e:
            logger.error(f"Pipeline-Fehler: {e}")
            self._on_error(str(e))
            raise
        finally:
            self._cleanup_owned()

    def run_async(self, video_path: str, model_size: str = "small", language: str = None,
                  caption_style: Optional[dict] = None,
                  override_segments: Optional[list] = None) -> "PipelineJob":
        """Startet run() in einem Daemon-Thread; liefert ein PipelineJob-Handle."""
        thread = threading.Thread(
            target=self.run,
            args=(video_path, model_size, language, caption_style,
                  override_segments),
            daemon=True
        )
        thread.start()
        return PipelineJob(self, thread)

    # ------------------------------------------------------------------
    # Cancel-/Cleanup-Helfer (B2)
    # ------------------------------------------------------------------

    def _check_cancelled(self) -> None:
        """Wirft CancelledError, wenn Abbruch angefordert wurde."""
        try:
            if self._cancel_event.is_set():
                raise CancelledError("Verarbeitung abgebrochen")
        except CancelledError:
            raise
        except Exception:
            pass

    def _own(self, path: str) -> str:
        """Registriert eine jobeigene Temp-Datei für gezieltes Cleanup."""
        try:
            if path and path not in self._owned_files:
                self._owned_files.append(path)
        except Exception:
            pass
        return path

    def _cleanup_owned(self) -> None:
        """Entfernt NUR eigene Temp-Dateien (idempotent, missing-ok, B2).

        Fremde Dateien im geteilten Temp-Ordner bleiben unangetastet.
        """
        try:
            files, self._owned_files = list(self._owned_files), []
        except Exception:
            return
        for path in files:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass

    @staticmethod
    def _remove_partial(path: str) -> None:
        """Entfernt unvollständigen Output (missing-ok, B2)."""
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Interne Verarbeitung (funktional 1:1 aus _process_video übernommen)
    # ------------------------------------------------------------------

    def _run(self, video_path: str, model_size: str, language: Optional[str],
             caption_style: Optional[dict] = None,
             override_segments: Optional[list] = None) -> str:
        self._owned_files = []
        self.last_segments = None
        self.last_video_path = None
        # Block 22: editierte Segmente ersetzen die Neutranskription
        # (bereits gruppiert + editiert); None/leer = bisheriger Pfad.
        use_override = bool(override_segments)
        self._check_cancelled()
        # 1. SubtitleEngine initialisieren (ggf. Erst-Download, C6).
        # faster-whisper meldet keinen Byte-Fortschritt (tqdm deaktiviert),
        # daher ehrlicher Status statt Fake-Prozenten; Progress bleibt bei 5.
        self._status(STATUS_STARTED)
        self._progress(5)
        try:
            cached = SubtitleEngine.is_model_cached(model_size)
        except Exception:
            cached = None
        if cached:
            self._log("INFO", f"Whisper-Modell '{model_size}' bereits vorhanden (Cache).")
        else:
            self._status(STATUS_DOWNLOAD_MODEL)
            self._log("INFO",
                      f"Whisper-Modell '{model_size}' wird geladen "
                      f"(Erst-Download, kann einige Minuten dauern) ...")
        self.subtitle_engine = create_subtitle_engine(model_size=model_size, device="auto")
        self._log("SUCCESS", f"Whisper-Modell '{model_size}' bereit.")
        self._check_cancelled()

        # 2. VideoProcessor initialisieren (falls noch nicht geschehen)
        if self.video_processor is None:
            self.video_processor = create_video_processor()
        try:
            if hasattr(self.video_processor, "bind_cancel"):
                self.video_processor.bind_cancel(self._cancel_event)
        except Exception:
            pass

        # 3. Temp-Ordner erstellen
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        # 4. Audio extrahieren (in _temp)
        self._status(STATUS_EXTRACT_AUDIO, 15)
        video_stem = Path(video_path).stem
        audio_path = str(self.temp_dir / f"{video_stem}_audio.wav")

        audio_path = self.video_processor.extract_audio(video_path, audio_path)
        self._own(audio_path)
        self._check_cancelled()
        self._log("INFO", f"Audio extrahiert: {os.path.basename(audio_path)}")

        # 5. Transkription mit Word-Timestamps.
        # Echter Segment-Fortschritt (C3) wird in den Gesamtfortschritt
        # 30 -> 70 gemappt (danach setzt Embed 70). Ohne belastbare Dauer
        # meldet die Engine nichts – kein Fake-Fortschritt.
        self._status(STATUS_TRANSCRIBE, 30)

        def _tx_progress(frac: float) -> None:
            try:
                frac = max(0.0, min(1.0, float(frac)))
            except (TypeError, ValueError):
                return
            self._progress(30.0 + frac * 40.0)
            self._check_cancelled()

        if use_override:
            # Editierte Segmente (Controller-State) statt Whisper verwenden;
            # Engine-Init bleibt (SRT-Erzeugung braucht sie), Gruppierung
            # entfällt (Segmente sind bereits gruppiert + editiert).
            segments = list(override_segments)
            self._log("INFO", "Editierte Segmente verwendet (keine Neutranskription).")
        else:
            segments = self.subtitle_engine.transcribe(
                audio_path, language,
                on_progress=_tx_progress,
                should_cancel=lambda: self.cancel_requested,
            )
        self._check_cancelled()

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
        if not use_override:
            segments = group_caption_segments(segments, layout)

        # SRT aus den gruppierten Segmenten (identische Textblöcke wie ASS)
        srt_path = str(self.temp_dir / f"{video_stem}.srt")
        self.subtitle_engine.generate_srt(segments, srt_path)
        self._own(srt_path)
        self._log("SUCCESS", f"SRT-Datei erstellt: {os.path.basename(srt_path)}")

        # Optional: Untertitel bearbeiten (SRT-Level)
        if self._on_edit_subtitles is not None:
            self._log("INFO", "Untertitel-Bearbeitung wird angeboten...")
            with open(srt_path, 'r', encoding='utf-8') as f:
                original_srt = f.read()
            edited_srt = self._on_edit_subtitles(original_srt)
            if edited_srt != original_srt:
                with open(srt_path, 'w', encoding='utf-8') as f:
                    f.write(edited_srt)
                self._log("INFO", "Untertitel wurden bearbeitet.")
                # Nach Bearbeitung die Segmente aus der bearbeiteten SRT neu laden (ohne Wort-Level-Info)
                segments = self.subtitle_engine.load_srt(srt_path)
            else:
                self._log("INFO", "Untertitel blieben unverändert.")

        # Block 20: Transkript für die echte Preview sichern (exakt die
        # Segmente, aus denen gleich die ASS erzeugt wird).
        self.last_segments = segments
        self.last_video_path = video_path

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
        self._own(ass_path)
        self._check_cancelled()
        self._log("SUCCESS", f"ASS-Datei erstellt: {os.path.basename(ass_path)}")

        # 6. Untertitel einbetten (Output-Video im Original-Ordner)
        self._status(STATUS_EMBED_SUBTITLES, 70)
        output_path = resolve_output_path(video_path)
        try:
            output_path = self.video_processor.embed_ass(video_path, ass_path, output_path)
        except Exception:
            # Unvollständiger Output darf nicht als Ergebnis zurückbleiben (B2).
            # Der Pfad stammt aus resolve_output_path (garantiert frisch).
            self._remove_partial(output_path)
            raise
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