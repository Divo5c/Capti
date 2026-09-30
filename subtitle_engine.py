"""
Modul für Whisper-Transkription und SRT-Generierung.
Verwendet faster-whisper für lokale Spracherkennung ohne Cloud-API.
"""

import os
import logging
import wave
from pathlib import Path
from typing import Callable, List, Optional, Tuple
from faster_whisper import WhisperModel

from video_processor import CancelledError

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

    @staticmethod
    def is_model_cached(model_size: str):
        """Prüft OHNE Netzwerk, ob das Modell im HF-Cache liegt (C6).

        Nutzt faster-whisper.utils.download_model(local_files_only=True):
        gecacht -> True; fehlend (LocalEntryNotFoundError) -> False;
        sonstige Fehler (z.B. ungültige Größe) -> None (unbekannt,
        sichere Seite: Download-Status anzeigen, Loader meldet Details).

        Returns:
            True/False/None (unbekannt). Niemals Exception.
        """
        try:
            from faster_whisper.utils import download_model
            download_model(model_size, local_files_only=True)
            return True
        except Exception as e:
            if e.__class__.__name__ == "LocalEntryNotFoundError":
                return False
            return None

    def _load_model(self):
        """Lädt das Whisper-Modell (ggf. Erst-Download via HuggingFace-Hub).

        Der Hub lädt atomar (Temp-Datei + Rename) und validiert den Cache;
        unvollständige/beschädigte Downloads werden automatisch erneut
        geladen – es entsteht nie eine halbfertige Modelldatei im Cache.
        """
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
            raise RuntimeError(
                f"Whisper-Modell '{self.model_size}' konnte nicht geladen "
                f"werden: {e}. Prüfe Internetverbindung (Erst-Download) "
                f"und freien Speicherplatz."
            ) from e

    def transcribe(self, audio_path: str, language: str = None,
                   on_progress: Optional[Callable[[float], None]] = None,
                   should_cancel: Optional[Callable[[], bool]] = None) -> List[dict]:
        """
        Transkribiert eine Audiodatei.

        Args:
            audio_path: Pfad zur Audiodatei
            language: Sprachcode (z.B. "de", "en") oder None für Auto-Erkennung
            on_progress: Optionaler Callback mit Bruchteil 0..1 (C3).
                Basiert auf echten Segment-Endzeiten relativ zur Audio-Dauer
                (faster-whisper liefert Segmente lazy + info.duration sofort).
                Bei unbekannter Dauer wird nichts gemeldet (ehrlich, kein Fake).
                Monoton nicht-fallend, immer in [0, 1].
            should_cancel: Optionales Callable -> True bei Abbruchwunsch (B2).
                Wird pro Segment geprüft und wirft dann CancelledError.

        Returns:
            Liste von Segmenten mit start, end, text und words
            (words: Liste von Dicts mit word, start, end, probability)
        """
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audiodatei nicht gefunden: {audio_path}")

        logger.info(f"Starte Transkription: {audio_path}")
        segments, info = self.model.transcribe(
            audio_path,
            language=language,
            beam_size=5,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
            word_timestamps=True
        )

        duration = self._audio_duration(info, audio_path)

        result = []
        last_frac = 0.0
        for segment in segments:
            if should_cancel is not None:
                cancelled = False
                try:
                    cancelled = bool(should_cancel())
                except Exception:
                    cancelled = False
                if cancelled:
                    raise CancelledError("Verarbeitung abgebrochen")
            # Wort-Timestamps erfassen (Grundlage für Word-by-Word-Highlighting)
            words = []
            if segment.words:
                for w in segment.words:
                    words.append({
                        "word": w.word.strip(),
                        "start": w.start,
                        "end": w.end,
                        "probability": w.probability
                    })

            result.append({
                "start": segment.start,
                "end": segment.end,
                "text": segment.text.strip(),
                "words": words
            })
            if on_progress is not None and duration:
                try:
                    frac = max(0.0, min(1.0, float(segment.end) / duration))
                except (TypeError, ValueError):
                    continue
                if frac >= last_frac:
                    last_frac = frac
                    try:
                        on_progress(frac)
                    except CancelledError:
                        raise  # Abbruch aus Progress-Callback (B2) weitergeben
                    except Exception:
                        pass  # sonstiges Progress-Problem darf nie abbrechen

        logger.info(f"Transkription abgeschlossen: {len(result)} Segmente, Sprache: {info.language}")
        return result

    @staticmethod
    def _audio_duration(info, audio_path: str) -> Optional[float]:
        """Audio-Gesamtdauer in Sekunden (info.duration, Fallback WAV-Header).

        None, wenn nicht belastbar ermittelbar – dann kein Fortschritt.
        """
        try:
            duration = float(getattr(info, "duration", None) or 0)
            if duration > 0:
                return duration
        except (TypeError, ValueError):
            pass
        try:
            with wave.open(audio_path, "rb") as wf:
                rate = wf.getframerate() or 0
                if rate > 0:
                    duration = wf.getnframes() / float(rate)
                    return duration if duration > 0 else None
        except Exception:
            pass
        return None

    @staticmethod
    def format_timestamp(seconds: float) -> str:
        """
        Konvertiert Sekunden in SRT-Zeitstempel-Format (HH:MM:SS,mmm).

        Rundet mathematisch korrekt auf Millisekunden (C7 – zuvor wurde
        systematisch trunkiert, d.h. bis zu knapp 1 ms zu früh). Überläufe
        werden weitergetragen (999.x ms -> nächste Sekunde etc.).
        Negative/ungültige Eingaben -> 00:00:00,000 (niemals Crash).

        Args:
            seconds: Zeit in Sekunden

        Returns:
            Formatierter Zeitstempel als String
        """
        try:
            total_ms = round(max(0.0, float(seconds)) * 1000)
        except (TypeError, ValueError):
            total_ms = 0
        hours, rem = divmod(total_ms, 3600000)
        minutes, rem = divmod(rem, 60000)
        secs, millis = divmod(rem, 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

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


    @staticmethod
    def load_srt(srt_path: str) -> List[dict]:
        """Load SRT file and return list of segment dicts with start, end, text.
        Each dict: {'start': float, 'end': float, 'text': str, 'words': []}
        """
        import re
        # Nur die reine Zeitzeile matchen (Blocknummer und Text stehen in
        # eigenen Zeilen und werden separat behandelt – idx darf nie als
        # Stunde interpretiert werden).
        pattern = re.compile(r'(\d{2}):(\d{2}):(\d{2}),(\d{3})\s+-->\s+(\d{2}):(\d{2}):(\d{2}),(\d{3})')
        segments = []
        with open(srt_path, 'r', encoding='utf-8') as f:
            content = f.read()
        # split by blank lines
        blocks = re.split(r'\r?\n\r?\n', content.strip())
        for block in blocks:
            if not block.strip():
                continue
            lines = block.splitlines()
            if len(lines) < 3:
                continue
            # first line: index (ignore)
            # second line: timestamps
            # third line+: text (may be multiple lines)
            time_line = lines[1]
            text_lines = lines[2:]
            text = ' '.join(text_lines)
            m = pattern.match(time_line)
            if not m:
                continue
            h1, m1, s1, ms1, h2, m2, s2, ms2 = m.groups()
            start = int(h1)*3600 + int(m1)*60 + int(s1) + int(ms1)/1000.0
            end = int(h2)*3600 + int(m2)*60 + int(s2) + int(ms2)/1000.0
            segments.append({
                'start': start,
                'end': end,
                'text': text.strip(),
                'words': []  # no word-level info after edit
            })
        return segments

def create_subtitle_engine(model_size: str = "small", device: str = "auto") -> SubtitleEngine:
    if device == "auto":
        try:
            # torch ist optional: nur für GPU-Erkennung; Capti läuft ohne PyTorch
            # (faster-whisper nutzt ctranslate2). Pylance-Warnung bewusst unterdrückt.
            import torch  # type: ignore[import-not-found]
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