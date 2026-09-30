"""
Capti Core: plattformunabhängige Geschäftslogik (geteilt zwischen
Desktop-UI und zukünftigen Plattformen).

Enthält bewusst KEINE UI-/Tkinter-Abhängigkeiten:

- paths          -> plattformgerechte Benutzer-Datenverzeichnisse
- caption_style  -> ein einziges, serialisierbares Caption-Style-Modell
                    inkl. Konvertierung in Renderer-(ASS-)Parameter
- project        -> Projektmodell + Workflow-Zustandsmaschine + Validierung
"""

from capti_core.paths import user_data_dir
from capti_core.caption_style import (
    CaptionStyle,
    DEFAULT_CAPTION_STYLE,
    PRESETS as CAPTION_PRESETS,
    resolve_caption_style,
)
from capti_core.project import (
    CaptiProject,
    InvalidTransitionError,
    ProjectWorkflow,
    WorkflowState,
    is_valid_video_path,
)

__all__ = [
    "user_data_dir",
    "CaptionStyle",
    "DEFAULT_CAPTION_STYLE",
    "CAPTION_PRESETS",
    "resolve_caption_style",
    "CaptiProject",
    "InvalidTransitionError",
    "ProjectWorkflow",
    "WorkflowState",
    "is_valid_video_path",
]
