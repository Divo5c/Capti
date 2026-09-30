"""
Modul für Video-Verarbeitung mit ffmpeg.
Audio-Extraktion und hartes Einbetten von Untertiteln.
"""

import os
import subprocess
import logging
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Optional

# Logging konfigurieren
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CancelledError(Exception):
    """Abbruch angefordert (Cancel-Event gesetzt, B2)."""


# Timeout für terminate() -> kill()-Fallback bei Cancel (Sekunden)
_CANCEL_KILL_TIMEOUT = 5.0
# Poll-Intervall für Cancel/Timeout-Überwachung (Sekunden)
_POLL_INTERVAL = 0.2


def resolve_ffprobe_exe(ffmpeg_path: str = "ffmpeg", project_root: Optional[Path] = None) -> Optional[str]:
    """Loest den ffprobe-Pfad portabel auf (Development + Frozen).

    Reihenfolge (erste vorhandene Datei gewinnt):
    1. CAPTI_FFPROBE (Env-Override, Tests/manuelle Pfade)
    2. Frozen: sys._MEIPASS/ffprobe(.exe) (PyInstaller-Bundle, A3)
    3. Dev: <project>/third_party/ffprobe/ffprobe(.exe) (Build-Time-Fetch)
    4. Neben der imageio-ffmpeg-Binary (zukunftssicher, falls dort mal ffprobe liegt)
    5. System-PATH ("ffprobe") – nur sinnvoller Fallback, keine angenommene Runtime-Abhängigkeit

    Returns:
        Pfad als String oder None, wenn nirgends ein ffprobe gefunden wurde.
    """
    override = os.environ.get("CAPTI_FFPROBE")
    if override and Path(override).exists():
        return str(Path(override))

    exe_names = ("ffprobe.exe", "ffprobe")

    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            for name in exe_names:
                cand = Path(meipass) / name
                if cand.exists():
                    return str(cand)

    root = Path(project_root) if project_root is not None else Path(__file__).resolve().parent
    for name in exe_names:
        cand = root / "third_party" / "ffprobe" / name
        if cand.exists():
            return str(cand)

    try:
        import imageio_ffmpeg
        sibling_dir = Path(imageio_ffmpeg.get_ffmpeg_exe()).parent
        for name in exe_names:
            cand = sibling_dir / name
            if cand.exists():
                return str(cand)
    except Exception:
        pass  # imageio-ffmpeg optional – weiter zum PATH-Fallback

    found = shutil.which("ffprobe")
    if found:
        return found
    return None


def escape_filter_path(path: str) -> str:
    """Escapet einen Dateipfad für den ffmpeg-subtitles-Filter (C5).

    Exakte Grenze: Python -> Filtergraph-String in `subtitles='...'`:
    - Backslash -> Slash (Windows-Trenner neutralisieren, ZUERST)
    - ':' -> '\\:' (Laufwerks-Doppelpunkt ist Filter-Trenner)
    - "'" -> "\\'" (einziges Zeichen, das Single-Quoting bricht)
    Leerzeichen, ()[];, Unicode/Umlaute etc. sind innerhalb '...' literal
    und werden bewusst NICHT escapet.
    """
    text = str(path).replace("\\", "/")
    text = text.replace(":", "\\:")
    text = text.replace("'", "\\'")
    return text


class VideoProcessor:
    """Klasse für Video-Verarbeitung mit ffmpeg."""

    def __init__(self, ffmpeg_path: str = "ffmpeg", cancel_event=None):
        """
        Initialisiert den VideoProcessor.

        Args:
            ffmpeg_path: Pfad zur ffmpeg-Executable (Standard: "ffmpeg" im PATH)
            cancel_event: Optionales threading.Event für Abbruch (B2, sonst None)
        """
        self.ffmpeg_path = ffmpeg_path
        self._cancel_event = cancel_event
        self._current_process = None
        self._proc_lock = threading.Lock()
        # Fallback: Wenn ffmpeg nicht im PATH gefunden wird, verwende die
        # mit imageio-ffmpeg gebündelte Binary (projektlokal, keine Systeminstallation nötig).
        if shutil.which(ffmpeg_path) is None:
            try:
                import imageio_ffmpeg
                self.ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
                logger.info(f"ffmpeg nicht im PATH gefunden – verwende imageio-ffmpeg-Binary: {self.ffmpeg_path}")
            except ImportError:
                logger.info("imageio-ffmpeg nicht verfügbar – bleibe bei Standard-Pfadsuche.")
        self._verify_ffmpeg()

    def _verify_ffmpeg(self) -> bool:
        """
        Prüft, ob ffmpeg verfügbar ist.

        Returns:
            True wenn ffmpeg gefunden wurde

        Raises:
            FileNotFoundError: Wenn ffmpeg nicht gefunden wird
        """
        try:
            result = subprocess.run(
                [self.ffmpeg_path, "-version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                logger.info(f"ffmpeg gefunden: {self.ffmpeg_path}")
                return True
            else:
                raise FileNotFoundError("ffmpeg nicht funktionsfähig")
        except FileNotFoundError:
            logger.error(f"ffmpeg nicht gefunden unter: {self.ffmpeg_path}")
            raise FileNotFoundError(
                f"ffmpeg nicht gefunden. Bitte installieren Sie ffmpeg und fügen Sie es zum PATH hinzu. "
                f"Oder geben Sie den vollständigen Pfad zur ffmpeg.exe an."
            )
        except subprocess.TimeoutExpired:
            logger.error("ffmpeg Timeout beim Versionscheck")
            raise FileNotFoundError("ffmpeg antwortet nicht (Timeout)")

    def bind_cancel(self, cancel_event) -> None:
        """Verdrahtet ein Cancel-Event der Pipeline (B2, idempotent)."""
        try:
            self._cancel_event = cancel_event
        except Exception:
            pass

    def request_cancel(self) -> None:
        """Fordert Abbruch an und beendet ggf. laufenden ffmpeg (idempotent)."""
        try:
            if self._cancel_event is None:
                import threading as _t
                self._cancel_event = _t.Event()
            self._cancel_event.set()
        except Exception:
            pass
        proc = None
        try:
            with self._proc_lock:
                proc = self._current_process
        except Exception:
            proc = None
        if proc is not None:
            try:
                if proc.poll() is None:
                    proc.terminate()
            except Exception:
                pass

    def _run_cmd(self, cmd, timeout):
        """Wie subprocess.run(capture_output, text, timeout), aber abbrechbar (B2).

        - Cancel-Event gesetzt -> terminate(), nach kurzem Timeout kill(),
          danach CancelledError (kein Zombie, kein Deadlock: Pipes werden
          via communicate() drainiert).
        - Timeout-Ueberschreitung -> subprocess.TimeoutExpired (wie bisher).
        """
        deadline = time.monotonic() + timeout if timeout else None
        # FileNotFoundError (Binary fehlt) propagiert unverändert wie bisher.
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            with self._proc_lock:
                self._current_process = proc
        except Exception:
            pass
        try:
            while True:
                cancelled = False
                try:
                    cancelled = bool(self._cancel_event is not None
                                    and self._cancel_event.is_set())
                except Exception:
                    cancelled = False
                if cancelled:
                    raise CancelledError("Verarbeitung abgebrochen")
                remaining = None
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                        try:
                            proc.communicate(timeout=_CANCEL_KILL_TIMEOUT)
                        except Exception:
                            pass
                        raise subprocess.TimeoutExpired(cmd, timeout)
                try:
                    step = _POLL_INTERVAL
                    if remaining is not None and remaining < step:
                        step = max(0.01, remaining)
                    out, err = proc.communicate(timeout=step)
                    return subprocess.CompletedProcess(
                        cmd, proc.returncode, out, err)
                except subprocess.TimeoutExpired:
                    continue  # erneut Cancel/Deadline pruefen
        except CancelledError:
            try:
                if proc.poll() is None:
                    proc.terminate()
            except Exception:
                pass
            try:
                proc.communicate(timeout=_CANCEL_KILL_TIMEOUT)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except Exception:
                    pass
                try:
                    proc.communicate(timeout=_CANCEL_KILL_TIMEOUT)
                except Exception:
                    pass
            except Exception:
                pass
            raise
        finally:
            try:
                with self._proc_lock:
                    if self._current_process is proc:
                        self._current_process = None
            except Exception:
                pass

    def extract_audio(self, video_path: str, output_path: str = None) -> str:
        """
        Extrahiert Audio aus einer Videodatei als WAV (16kHz, mono) für Whisper.

        Args:
            video_path: Pfad zur Eingabe-Videodatei
            output_path: Pfad für die Ausgabe-Audiodatei (optional, wird automatisch generiert)

        Returns:
            Pfad zur extrahierten Audiodatei
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Videodatei nicht gefunden: {video_path}")

        if output_path is None:
            video_stem = Path(video_path).stem
            output_dir = Path(video_path).parent
            output_path = str(output_dir / f"{video_stem}_audio.wav")

        logger.info(f"Extrahiere Audio aus: {video_path} -> {output_path}")

        # ffmpeg-Befehl: Video -> WAV (16kHz, mono, 16-bit) für optimale Whisper-Erkennung
        cmd = [
            self.ffmpeg_path,
            "-y",  # Überschreiben ohne Nachfrage
            "-i", video_path,
            "-vn",  # Kein Video
            "-acodec", "pcm_s16le",  # 16-bit PCM
            "-ar", "16000",  # 16kHz Sample-Rate (Whisper Standard)
            "-ac", "1",  # Mono
            output_path
        ]

        try:
            result = self._run_cmd(cmd, timeout=300)  # 5 Minuten Timeout

            if result.returncode != 0:
                logger.error(f"ffmpeg Fehler: {result.stderr}")
                raise RuntimeError(f"Audio-Extraktion fehlgeschlagen: {result.stderr}")

            if not os.path.exists(output_path):
                raise RuntimeError("Audio-Datei wurde nicht erstellt")

            logger.info(f"Audio erfolgreich extrahiert: {output_path}")
            return output_path

        except subprocess.TimeoutExpired:
            logger.error("Timeout bei Audio-Extraktion")
            raise RuntimeError("Audio-Extraktion Timeout (5 Minuten überschritten)")

    def embed_ass(self, video_path: str, ass_path: str, output_path: str = None) -> str:
        """
        Bettet ASS-Untertitel hart in das Video ein (neue MP4-Datei).
        Verwendet die Styles aus der ASS-Datei (kein force_style-Override),
        damit Karaoke-Highlighting erhalten bleibt.

        Args:
            video_path: Pfad zur Eingabe-Videodatei
            ass_path: Pfad zur ASS-Untertiteldatei
            output_path: Pfad für die Ausgabe-Videodatei (optional)

        Returns:
            Pfad zur Ausgabedatei mit eingebetteten Untertiteln
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Videodatei nicht gefunden: {video_path}")
        if not os.path.exists(ass_path):
            raise FileNotFoundError(f"ASS-Datei nicht gefunden: {ass_path}")

        if output_path is None:
            video_stem = Path(video_path).stem
            output_dir = Path(video_path).parent
            output_path = str(output_dir / f"{video_stem}_subtitled.mp4")

        logger.info(f"Bette ASS-Untertitel ein: {video_path} + {ass_path} -> {output_path}")

        ass_escaped = escape_filter_path(ass_path)

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i", video_path,
            "-vf", f"subtitles='{ass_escaped}'",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            output_path
        ]

        try:
            result = self._run_cmd(cmd, timeout=600)

            if result.returncode != 0:
                logger.error(f"ffmpeg Fehler: {result.stderr}")
                raise RuntimeError(f"ASS-Einbettung fehlgeschlagen: {result.stderr}")

            if not os.path.exists(output_path):
                raise RuntimeError("Ausgabe-Video wurde nicht erstellt")

            logger.info(f"ASS-Untertitel erfolgreich eingebettet: {output_path}")
            return output_path

        except subprocess.TimeoutExpired:
            logger.error("Timeout bei ASS-Einbettung")
            raise RuntimeError("ASS-Einbettung Timeout (10 Minuten überschritten)")

    def get_video_info(self, video_path: str) -> dict:
        """
        Ermittelt Video-Informationen mit ffprobe.

        Args:
            video_path: Pfad zur Videodatei

        Returns:
            Dictionary mit Video-Informationen (duration, width, height, fps, etc.)
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Videodatei nicht gefunden: {video_path}")

        ffprobe_path = resolve_ffprobe_exe(self.ffmpeg_path)
        if ffprobe_path is None:
            logger.warning(
                "ffprobe nicht gefunden (weder gebuendelt noch im PATH) – "
                "Videoinformationen nicht verfuegbar. Das ASS-Layout faellt "
                "auf 720x1280 zurueck.")
            return {}

        cmd = [
            ffprobe_path,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            video_path
        ]

        try:
            result = self._run_cmd(cmd, timeout=30)
            if result.returncode != 0:
                logger.warning(f"ffprobe Fehler: {result.stderr}")
                return {}

            import json
            info = json.loads(result.stdout)
            return info
        except Exception as e:
            logger.warning(f"Fehler beim Auslesen der Video-Info: {e}")
            return {}


def create_video_processor(ffmpeg_path: str = "ffmpeg") -> VideoProcessor:
    """
    Factory-Funktion zum Erstellen einer VideoProcessor-Instanz.

    Args:
        ffmpeg_path: Pfad zur ffmpeg-Executable

    Returns:
        VideoProcessor-Instanz
    """
    return VideoProcessor(ffmpeg_path=ffmpeg_path)