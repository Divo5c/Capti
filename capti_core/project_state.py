"""Capti Projektdatei-Persistenz (Block 24): Transkript + Caption-Edits.

Tk-/FFmpeg-freie Core-Komponente. Speichert den Edit-State als normales
UTF-8-JSON (kein Pickle, kein eval, nur primitive Datenstrukturen):

    {
      "schema_version": 1,
      "video_path": "...",
      "model": "small",
      "language": "de",
      "caption_style": {...},
      "segments": [
        {"text": "...", "start": 0.0, "end": 1.5,
         "words": [{"word": "...", "start": 0.0, "end": 0.4}]}
      ]
    }

Regeln:
- Nur bekannte Felder werden gelesen; unbekannte Felder werden ignoriert.
- schema_version != 1 -> ProjectFileError (kein stilles Raten).
- Fehlende Pflichtfelder (schema_version, segments) -> ProjectFileError.
- Ungültige Segmente (fehlende/verkehrte start/end) werden übersprungen,
  fehlende words -> []; das Video selbst wird nie kopiert/geprüft-verschoben:
  ein verschobenes/fehlendes Video löscht NICHT den Transcript-State
  (Aufrufer prüft video_exists() und zeigt Hinweis).
- Speichern erfolgt atomar (same-dir .tmp + os.replace), deterministisch
  (sort_keys, indent=2, UTF-8, ensure_ascii=False).
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from capti_core.project import VALID_MODELS

SCHEMA_VERSION = 1
PROJECT_EXTENSION = ".capti.json"


class ProjectFileError(ValueError):
    """Projektdatei fehlt, ist ungültig oder hat ein unbekanntes Schema."""


@dataclass
class ProjectState:
    """Persistenter Projekt-Stand (Plain-Daten, keine Tk-/Runtime-Objekte)."""

    video_path: str = ""
    model: str = "small"
    language: str | None = None
    caption_style: dict = field(default_factory=dict)
    segments: list = field(default_factory=list)  # Segment-Dicts (s. Modul-Doku)

    def video_exists(self) -> bool:
        """True, wenn das Quellvideo (noch) am gespeicherten Pfad liegt."""
        return bool(self.video_path) and Path(self.video_path).is_file()


def _clean_word(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    word = raw.get("word")
    if word is None:
        return None
    try:
        start = float(raw["start"])
        end = float(raw.get("end", raw["start"]))
    except (KeyError, TypeError, ValueError):
        return None
    if not end > start:
        return None
    if start < 0:
        return None
    return {"word": str(word), "start": start, "end": end}


def _clean_segment(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    try:
        start = float(raw["start"])
        end = float(raw["end"])
    except (KeyError, TypeError, ValueError):
        return None
    if not end > start or start < 0:
        return None
    text = raw.get("text", "")
    words = raw.get("words") or []
    clean_words = []
    if isinstance(words, list):
        for w in words:
            cleaned = _clean_word(w)
            if cleaned is not None:
                clean_words.append(cleaned)
    return {"text": text if isinstance(text, str) else str(text),
            "start": start, "end": end, "words": clean_words}


def _clean_style(raw) -> dict:
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key, value in raw.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            out[str(key)] = value
    return out


def serialize(state: ProjectState) -> dict:
    """ProjectState -> JSON-fähiges Dict (deterministische Struktur)."""
    language = state.language
    if language is not None and not isinstance(language, str):
        language = None
    model = state.model if state.model in VALID_MODELS else "small"
    segments = []
    for raw in state.segments or []:
        cleaned = _clean_segment(raw)
        if cleaned is not None:
            segments.append(cleaned)
    return {
        "schema_version": SCHEMA_VERSION,
        "video_path": str(state.video_path or ""),
        "model": model,
        "language": language,
        "caption_style": _clean_style(state.caption_style),
        "segments": segments,
    }


def deserialize(raw: dict) -> ProjectState:
    """Dict -> ProjectState (strikt bei Schema/Pflichtfeldern, tolerant sonst).

    Raises:
        ProjectFileError: bei unbekannter schema_version, fehlenden
            Pflichtfeldern oder falschen Top-Level-Typen.
    """
    if not isinstance(raw, dict):
        raise ProjectFileError("Projektdatei enthält kein JSON-Objekt.")
    version = raw.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ProjectFileError(
            f"Unbekannte schema_version: {version!r} (erwartet {SCHEMA_VERSION}).")
    segments = raw.get("segments")
    if not isinstance(segments, list):
        raise ProjectFileError("Pflichtfeld 'segments' fehlt oder ist keine Liste.")
    language = raw.get("language")
    if language is not None and not isinstance(language, str):
        language = None
    model = raw.get("model", "small")
    if model not in VALID_MODELS:
        model = "small"
    video = raw.get("video_path", "")
    clean_segments = []
    for item in segments:
        cleaned = _clean_segment(item)
        if cleaned is not None:
            clean_segments.append(cleaned)
    return ProjectState(
        video_path=str(video or ""),
        model=model,
        language=language,
        caption_style=_clean_style(raw.get("caption_style")),
        segments=clean_segments,
    )


def save_project(path, state: ProjectState) -> str:
    """Speichert atomar (.tmp + replace, UTF-8, deterministisch).

    Returns:
        Der verwendete Dateipfad als str.
    """
    target = Path(path)
    data = serialize(state)
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    tmp_path = target.parent / (target.name + ".tmp")
    try:
        tmp_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(text, encoding="utf-8")
        os.replace(tmp_path, target)
    except OSError as exc:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise ProjectFileError(f"Projekt konnte nicht gespeichert werden: {exc}")
    return str(target)


def load_project(path) -> ProjectState:
    """Lädt und validiert eine Projektdatei (lädt State auch bei
    fehlendem Video – Aufrufer prüft video_exists()).

    Raises:
        ProjectFileError: Datei fehlt, kein gültiges JSON oder
            Schema-Verletzung.
    """
    target = Path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except OSError:
        raise ProjectFileError(f"Projektdatei nicht gefunden: {target}")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProjectFileError(f"Ungültiges JSON in Projektdatei: {exc}")
    return deserialize(raw)
