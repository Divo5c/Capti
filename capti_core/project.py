"""
Capti Core: Projektmodell, Workflow-Zustandsmaschine und Validierung.

Bildet den Capti-Workflow plattformunabhängig ab:

    NEW_PROJECT -> CAPTION_STYLE -> PROCESSING -> RESULT

Die Zustandsmaschine ist reine Geschäftslogik (keine UI-Abhängigkeit)
und definiert die erlaubten Übergänge exakt so, wie der Desktop- sie
umsetzt:

- New Project: Video + Sprache + Modell wählen (KEIN Verarbeitungsstart)
- Caption Style: Style wählen/anpassen, dann Verarbeitung starten
- Processing: läuft; Abbruch/Fehler führt zurück zu CAPTION_STYLE
- Result: Ergebnis speichern/öffnen, dann neues Projekt oder Home

Eine zukünftige mobile App implementiert genau diese Übergänge und
erhält Validierung/Serialisierung geschenkt.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional

# Identisch zur Desktop-Validierung (ui/screens/new_project.py)
VALID_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv",
                          ".webm", ".flv", ".wmv", ".m4v"}

# Unterstützte Whisper-Modelle (Desktop-Parität)
VALID_MODELS = ("tiny", "base", "small", "medium")


class WorkflowState(Enum):
    """Zustände des Capti-Projekt-Workflows."""
    HOME = "home"
    NEW_PROJECT = "new_project"
    CAPTION_STYLE = "caption_style"
    PROCESSING = "processing"
    RESULT = "result"


# Erlaubte Übergänge: state -> mögliche Folgezustände
TRANSITIONS = {
    WorkflowState.HOME: {WorkflowState.NEW_PROJECT},
    WorkflowState.NEW_PROJECT: {WorkflowState.HOME, WorkflowState.CAPTION_STYLE},
    WorkflowState.CAPTION_STYLE: {
        WorkflowState.NEW_PROJECT,      # Zurück zum Projektschritt
        WorkflowState.PROCESSING,       # Verarbeitung starten
        WorkflowState.HOME,
    },
    WorkflowState.PROCESSING: {
        WorkflowState.RESULT,           # Erfolg
        WorkflowState.CAPTION_STYLE,    # Fehler-/Abbruchpfad
        WorkflowState.HOME,
    },
    WorkflowState.RESULT: {
        WorkflowState.NEW_PROJECT,      # Weiteres Projekt
        WorkflowState.HOME,
    },
}


class InvalidTransitionError(ValueError):
    """Wird bei unzulässigen Workflow-Übergängen ausgelöst."""


@dataclass
class CaptiProject:
    """Ein Capti-Projekt (Auswahlzustand über den gesamten Workflow)."""

    video_path: str = ""
    language: Optional[str] = None          # None = Auto-Erkennung
    model: str = "small"
    caption_style: dict = field(default_factory=dict)

    # ---------------- Serialisierung ----------------

    def to_dict(self) -> dict:
        """Serialisierbare Repräsentation (nur persistenzwürdige Daten)."""
        return {
            "video_path": self.video_path,
            "language": self.language,
            "model": self.model,
            "caption_style": dict(self.caption_style),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "CaptiProject":
        """Robustes Deserialisieren; kaputte Werte -> sichere Defaults."""
        raw = raw if isinstance(raw, dict) else {}
        language = raw.get("language")
        if language is not None and not isinstance(language, str):
            language = None
        model = raw.get("model")
        if model not in VALID_MODELS:
            model = "small"
        style = raw.get("caption_style")
        return cls(
            video_path=str(raw.get("video_path") or ""),
            language=language,
            model=model,
            caption_style=dict(style) if isinstance(style, dict) else {},
        )

    # ---------------- Validierung ----------------

    def validation_errors(self) -> List[str]:
        """Liste von Problemen; leer bedeutet: verarbeitungsbereit.

        Stabile Maschinen-Codes (nicht lokalisierte Texte), damit UIs
        sie selbst übersetzen können.
        """
        errors: List[str] = []
        if not self.video_path:
            errors.append("error.no_video")
        elif not is_valid_video_path(self.video_path):
            errors.append("error.invalid_format")
        if not Path(self.video_path or "").exists():
            errors.append("error.video_missing")
        if self.model not in VALID_MODELS:
            errors.append("error.invalid_model")
        return errors


def is_valid_video_path(path: str) -> bool:
    """True, wenn die Endung ein unterstütztes Videoformat ist."""
    return Path(path or "").suffix.lower() in VALID_VIDEO_EXTENSIONS


class ProjectWorkflow:
    """Kleine explizite Zustandsmaschine für den Projekt-Workflow."""

    def __init__(self, project: CaptiProject = None,
                 initial_state: WorkflowState = WorkflowState.HOME):
        self.project = project or CaptiProject()
        self.state = initial_state

    def can_transition(self, target: WorkflowState) -> bool:
        """True, wenn der Übergang laut Workflow erlaubt ist."""
        return target in TRANSITIONS[self.state]

    def transition(self, target: WorkflowState) -> WorkflowState:
        """Führt einen erlaubten Übergang aus (sonst InvalidTransitionError)."""
        if not self.can_transition(target):
            raise InvalidTransitionError(
                f"Übergang {self.state.value} -> {target.value} nicht erlaubt")
        self.state = target
        return self.state

    def can_start_processing(self) -> bool:
        """Verarbeitung nur starten, wenn im Style-Schritt und Projekt valide."""
        return (self.state == WorkflowState.CAPTION_STYLE
                and not self.project.validation_errors())
