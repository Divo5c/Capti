"""
Modul für Video-Verarbeitung mit ffmpeg.
Audio-Extraktion und hartes Einbetten von Untertiteln.
"""

import os
import subprocess
import logging
import shutil
from pathlib import Path
from typing import Optional

# Logging konfigurieren
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class VideoProcessor:
    """Klasse für Video-Verarbeitung mit ffmpeg."""

    def __init__(self, ffmpeg_path: str = "ffmpeg"):
        """
        Initialisiert den VideoProcessor.

        Args:
            ffmpeg_path: Pfad zur ffmpeg-Executable (Standard: "ffmpeg" im PATH)
        """
        self.ffmpeg_path = ffmpeg_path
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
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 Minuten Timeout
            )

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

    def embed_subtitles(self, video_path: str, srt_path: str, output_path: str = None) -> str:
        """
        Bettet SRT-Untertitel hart in das Video ein (neue MP4-Datei).

        Args:
            video_path: Pfad zur Eingabe-Videodatei
            srt_path: Pfad zur SRT-Untertiteldatei
            output_path: Pfad für die Ausgabe-Videodatei (optional, wird automatisch generiert)

        Returns:
            Pfad zur Ausgabedatei mit eingebetteten Untertiteln
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Videodatei nicht gefunden: {video_path}")
        if not os.path.exists(srt_path):
            raise FileNotFoundError(f"SRT-Datei nicht gefunden: {srt_path}")

        if output_path is None:
            video_stem = Path(video_path).stem
            output_dir = Path(video_path).parent
            output_path = str(output_dir / f"{video_stem}_subtitled.mp4")

        logger.info(f"Bette Untertitel ein: {video_path} + {srt_path} -> {output_path}")

        # SRT-Pfad für ffmpeg escapen (Windows-Pfade mit Backslashes und Doppelpunkten)
        srt_escaped = srt_path.replace("\\", "/").replace(":", "\\:")

        # ffmpeg-Befehl: Video + SRT -> MP4 mit eingebetteten Untertiteln
        # Verwende subtitles-Filter für hartes Einbrennen (burn-in)
        cmd = [
            self.ffmpeg_path,
            "-y",  # Überschreiben ohne Nachfrage
            "-i", video_path,
            "-vf", f"subtitles='{srt_escaped}':force_style='FontSize=24,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,BorderStyle=1,Outline=2,Shadow=1'",
            "-c:v", "libx264",  # H.264 Video-Codec
            "-preset", "medium",  # Encoding-Preset
            "-crf", "23",  # Qualitätsfaktor (18-28, niedriger = besser)
            "-c:a", "aac",  # AAC Audio-Codec
            "-b:a", "128k",  # Audio-Bitrate
            "-movflags", "+faststart",  # Für Web-Streaming optimieren
            output_path
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600  # 10 Minuten Timeout
            )

            if result.returncode != 0:
                logger.error(f"ffmpeg Fehler: {result.stderr}")
                # Fallback: Versuche ohne Styling
                logger.info("Versuche Fallback ohne Styling...")
                return self._embed_subtitles_fallback(video_path, srt_path, output_path)

            if not os.path.exists(output_path):
                raise RuntimeError("Ausgabe-Video wurde nicht erstellt")

            logger.info(f"Untertitel erfolgreich eingebettet: {output_path}")
            return output_path

        except subprocess.TimeoutExpired:
            logger.error("Timeout bei Untertitel-Einbettung")
            raise RuntimeError("Untertitel-Einbettung Timeout (10 Minuten überschritten)")

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

        ass_escaped = ass_path.replace("\\", "/").replace(":", "\\:")

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
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600
            )

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

    def _embed_subtitles_fallback(self, video_path: str, srt_path: str, output_path: str) -> str:
        """
        Fallback-Methode für Untertitel-Einbettung ohne komplexes Styling.

        Args:
            video_path: Pfad zur Eingabe-Videodatei
            srt_path: Pfad zur SRT-Untertiteldatei
            output_path: Pfad für die Ausgabe-Videodatei

        Returns:
            Pfad zur Ausgabedatei
        """
        srt_escaped = srt_path.replace("\\", "/").replace(":", "\\:")

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i", video_path,
            "-vf", f"subtitles='{srt_escaped}'",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            output_path
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600
        )

        if result.returncode != 0:
            logger.error(f"Fallback auch fehlgeschlagen: {result.stderr}")
            raise RuntimeError(f"Untertitel-Einbettung fehlgeschlagen: {result.stderr}")

        if not os.path.exists(output_path):
            raise RuntimeError("Ausgabe-Video wurde nicht erstellt")

        logger.info(f"Untertitel erfolgreich eingebettet (Fallback): {output_path}")
        return output_path

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

        ffprobe_path = self.ffmpeg_path.replace("ffmpeg", "ffprobe")
        if not shutil.which(ffprobe_path):
            ffprobe_path = "ffprobe"

        cmd = [
            ffprobe_path,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            video_path
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
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