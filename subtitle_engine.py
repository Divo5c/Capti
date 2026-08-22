"""
Modul für Whisper-Transkription und SRT-Generierung.
Verwendet faster-whisper für lokale Spracherkennung ohne Cloud-API.
"""

import os
import logging
from pathlib import Path
from typing import List, Tuple
from faster_whisper import WhisperModel

# Logging konfigurieren
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SubtitleEngine:
    """Klasse für Audio-Transkription und SRT-Datei-Generierung."""

    def __init__(self, model_size: str = "small", device: str = "cpu", compute_type: str = "int8"):
        """
        Initialisiert die Whisper-Engine.

        Args:
            model_size: Whisper-Modellgröße ("tiny", "base", "small", "medium", "large")
            device: "cpu" oder "cuda" für GPU-Beschleunigung
            compute_type: "int8", "int8_float16", "float16", "float32"
        """
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.model = None
        self._load_model()

    def _load_model(self):
        """Lädt das Whisper-Modell."""
        logger.info(f"Lade Whisper-Modell: {self.model_size} auf {self.device} ({self.compute_type})")
        try:
            self.model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type
            )
            logger.info("Modell erfolgreich geladen")
        except Exception as e:
            logger.error(f"Fehler beim Laden des Modells: {e}")
            raise

    def transcribe(self, audio_path: str, language: str = None) -> List[dict]:
        """
        Transkribiert eine Audiodatei.

        Args:
            audio_path: Pfad zur Audiodatei
            language: Sprachcode (z.B. "de", "en") oder None für Auto-Erkennung

        Returns:
            Liste von Segmenten mit start, end, text
        """
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audiodatei nicht gefunden: {audio_path}")

        logger.info(f"Starte Transkription: {audio_path}")
        segments, info = self.model.transcribe(
            audio_path,
            language=language,
            beam_size=5,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500)
        )

        result = []
        for segment in segments:
            result.append({
                "start": segment.start,
                "end": segment.end,
                "text": segment.text.strip()
            })

        logger.info(f"Transkription abgeschlossen: {len(result)} Segmente, Sprache: {info.language}")
        return result

    @staticmethod
    def format_timestamp(seconds: float) -> str:
        """
        Konvertiert Sekunden in SRT-Zeitstempel-Format (HH:MM:SS,mmm).

        Args:
            seconds: Zeit in Sekunden

        Returns:
            Formatierter Zeitstempel als String
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        milliseconds = int((seconds - int(seconds)) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"

    def generate_srt(self, segments: List[dict], output_path: str) -> str:
        """
        Generiert eine SRT-Datei aus Transkriptions-Segmenten.

        Args:
            segments: Liste von Dictionaries mit start, end, text
            output_path: Pfad für die Ausgabedatei

        Returns:
            Pfad zur generierten SRT-Datei
        """
        logger.info(f"Generiere SRT-Datei: {output_path}")

        with open(output_path, "w", encoding="utf-8") as f:
            for i, segment in enumerate(segments, 1):
                start_time = self.format_timestamp(segment["start"])
                end_time = self.format_timestamp(segment["end"])
                text = segment["text"]

                f.write(f"{i}\n")
                f.write(f"{start_time} --> {end_time}\n")
                f.write(f"{text}\n\n")

        logger.info(f"SRT-Datei erfolgreich erstellt: {output_path}")
        return output_path

    def transcribe_and_generate_srt(self, audio_path: str, output_path: str, language: str = None) -> str:
        """
        Führt Transkription und SRT-Generierung in einem Schritt durch.

        Args:
            audio_path: Pfad zur Audiodatei
            output_path: Pfad für die SRT-Ausgabedatei
            language: Sprachcode oder None für Auto-Erkennung

        Returns:
            Pfad zur generierten SRT-Datei
        """
        segments = self.transcribe(audio_path, language)
        return self.generate_srt(segments, output_path)


def create_subtitle_engine(model_size: str = "small", device: str = "auto") -> SubtitleEngine:
    if device == "auto":
        try:
            import torch
            if torch.cuda.is_available():
                device = "cuda"
                logger.info(f"Automatische Gerätewahl: cuda ({torch.cuda.get_device_name(0)})")
            else:
                device = "cpu"
                logger.info("Automatische Gerätewahl: cpu")
        except Exception as e:
            logger.warning(f"torch/GPU-Prüfung fehlgeschlagen: {e}")
            device = "cpu"

    compute_type = "float16" if device == "cuda" else "int8"
    return SubtitleEngine(model_size=model_size, device=device, compute_type=compute_type)