"""
Capti Core: ein einziges, serialisierbares Caption-Style-Modell.

Kanonisches Speicherformat (config.json: Key "caption_style"):
    - Farben als Hex-Strings "#RRGGBB" (plattformunabhängig, UI-tauglich)
    - shadow_alpha als 0..255 (0 = opak .. 255 = transparent); wirkt nur
      zusammen mit einer explizit gesetzten shadow_color (Legacy-Regel:
      ohne Farbe gilt der klassische Look &H80000000)
    - font_name / font_size / pop_enabled / pop_scale / pop_decay_ms

Nur an der Render-Grenze (ASS-Untertitel) werden die Farben in das
ASS-Format &HAABBGGRR konvertiert – to_renderer_kwargs() ist die EINZIGE
Konvertierungsstelle. Die Werte entsprechen exakt dem bisherigen
Capti-Look (caption_renderer.py Defaults).

Position und max_words_per_line sind bewusst KEINE Style-Parameter:
sie werden beim Rendern aus der Videoauflösung abgeleitet
(CaptionRenderer.compute_layout). Das Modell dokumentiert diese
Explizitheit statt sie stillschweigend zu ändern.
"""

import re
from dataclasses import dataclass, fields

# ---------------------------------------------------------------------
# Kanonische Defaults = aktueller Capti-Look
# ---------------------------------------------------------------------

DEFAULT_CAPTION_STYLE = {
    "normal_color": "#FFFFFF",
    "highlight_color": "#FFFF00",
    "outline_color": "#101010",
    "shadow_color": "#000000",
    "shadow_alpha": 128,
    "font_name": "Arial Black",
    "font_size": 68,
    "pop_enabled": True,
    "pop_scale": 112,
    "pop_decay_ms": 150,
}

# Presets in kanonischer Form ("Capti Default" = exakt die Defaults)
PRESETS = {
    "Capti Default": {},
    "Clean": {
        "normal_color": "#FFFFFF", "highlight_color": "#FFFFFF",
        "outline_color": "#000000", "shadow_alpha": 96,
        "pop_enabled": False,
    },
    "Strong": {
        "normal_color": "#FFFFFF", "highlight_color": "#FF3B30",
        "outline_color": "#000000", "shadow_alpha": 180,
        "pop_enabled": True, "pop_scale": 125, "pop_decay_ms": 120,
    },
}

# ASS-Defaults (Render-Seite); entspricht pipeline.CAPTION_STYLE_DEFAULTS
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
    """Ganzzahl in Bereich; ungültige/out-of-range Werte -> Default."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    if v < lo or v > hi:
        return default
    return v


def _clamp_int(value, default: int, lo: int, hi: int) -> int:
    """Ganzzahl in [lo, hi] clampen; ungültige Werte -> Default."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


@dataclass
class CaptionStyle:
    """Plattformunabhängiges Caption-Style-Modell (kanonische Form)."""

    normal_color: str = DEFAULT_CAPTION_STYLE["normal_color"]
    highlight_color: str = DEFAULT_CAPTION_STYLE["highlight_color"]
    outline_color: str = DEFAULT_CAPTION_STYLE["outline_color"]
    shadow_color: str = DEFAULT_CAPTION_STYLE["shadow_color"]
    shadow_alpha: int = DEFAULT_CAPTION_STYLE["shadow_alpha"]
    font_name: str = DEFAULT_CAPTION_STYLE["font_name"]
    font_size: int = DEFAULT_CAPTION_STYLE["font_size"]
    pop_enabled: bool = DEFAULT_CAPTION_STYLE["pop_enabled"]
    pop_scale: int = DEFAULT_CAPTION_STYLE["pop_scale"]
    pop_decay_ms: int = DEFAULT_CAPTION_STYLE["pop_decay_ms"]
    # Legacy-Regel: shadow_alpha wirkt nur, wenn eine explizit gültige
    # shadow_color konfiguriert wurde; sonst gilt der klassische Look
    # (&H80000000) unabhängig vom Alpha-Wert. Direkt konstruierte
    # Styles gelten als explizit.
    shadow_color_explicit: bool = True

    # ---------------- Serialisierung ----------------

    def to_dict(self) -> dict:
        """Kanonisches Dict (z.B. für config.json); interne Flags ausgenommen."""
        return {f.name: getattr(self, f.name) for f in fields(self)
                if f.name != "shadow_color_explicit"}

    @classmethod
    def from_dict(cls, raw: dict) -> "CaptionStyle":
        """Erzeugt einen validierten Style aus einem rohen Dict.

        Ungültige/fehlende Felder -> sicherer Default pro Feld;
        unbekannte Keys werden ignoriert. Nichts kann crashen.
        shadow_alpha wird legacy-konform geclampt (nicht verworfen).
        """
        raw = raw if isinstance(raw, dict) else {}
        raw_shadow = raw.get("shadow_color")
        shadow_explicit = (isinstance(raw_shadow, str)
                           and bool(_HEX_RE.match(raw_shadow)))
        return cls(
            normal_color=_valid_hex(raw.get("normal_color"),
                                    DEFAULT_CAPTION_STYLE["normal_color"]),
            highlight_color=_valid_hex(raw.get("highlight_color"),
                                       DEFAULT_CAPTION_STYLE["highlight_color"]),
            outline_color=_valid_hex(raw.get("outline_color"),
                                     DEFAULT_CAPTION_STYLE["outline_color"]),
            shadow_color=_valid_hex(raw_shadow,
                                    DEFAULT_CAPTION_STYLE["shadow_color"]),
            shadow_color_explicit=shadow_explicit,
            shadow_alpha=_clamp_int(raw.get("shadow_alpha"), 128, 0, 255),
            font_name=_valid_font_name(raw.get("font_name"),
                                       DEFAULT_CAPTION_STYLE["font_name"]),
            font_size=_int_in_range(raw.get("font_size"), 68, 20, 200),
            pop_enabled=bool(raw.get("pop_enabled", True)),
            pop_scale=_int_in_range(raw.get("pop_scale"), 112, 100, 200),
            pop_decay_ms=_int_in_range(raw.get("pop_decay_ms"), 150, 0, 1000),
        )

    @classmethod
    def load(cls, config_value) -> "CaptionStyle":
        """Liest den Style aus einem config.json-Wert (None/leer -> Defaults)."""
        if isinstance(config_value, dict) and config_value:
            return cls.from_dict(config_value)
        return cls()

    def merged_with_preset(self, preset_name: str) -> "CaptionStyle":
        """Wendet ein Preset auf eine Kopie dieses Styles an."""
        overrides = PRESETS.get(preset_name)
        if not overrides:
            return self
        data = self.to_dict()
        data.update(overrides)
        return CaptionStyle.from_dict(data)

    # ---------------- Render-Grenze (ASS) ----------------

    def to_renderer_kwargs(self) -> dict:
        """Konvertiert in Renderer-kwargs (ASS-Farben) – EINZIGE Konvertierungsstelle."""
        if self.shadow_color_explicit:
            # Alpha-Byte: 00=opak .. FF=transparent (ASS-Semantik)
            shadow = _hex_to_ass(
                self.shadow_color, CAPTION_STYLE_DEFAULTS["shadow_color"],
                alpha=self.shadow_alpha)
        else:
            # Legacy-Regel: ohne explizite Farbe klassischer Look,
            # shadow_alpha bleibt wirkungslos
            shadow = CAPTION_STYLE_DEFAULTS["shadow_color"]
        return {
            "normal_color": _hex_to_ass(
                self.normal_color, CAPTION_STYLE_DEFAULTS["normal_color"]),
            "highlight_color": _hex_to_ass(
                self.highlight_color, CAPTION_STYLE_DEFAULTS["highlight_color"]),
            "outline_color": _hex_to_ass(
                self.outline_color, CAPTION_STYLE_DEFAULTS["outline_color"]),
            "shadow_color": shadow,
            "font_name": self.font_name,
            "font_size": self.font_size,
            "pop_enabled": self.pop_enabled,
            "pop_scale": self.pop_scale,
            "pop_decay_ms": self.pop_decay_ms,
        }


def _valid_hex(value, default: str) -> str:
    """Hex-Farbe "#RRGGBB" oder Default."""
    if isinstance(value, str) and _HEX_RE.match(value):
        return value.upper()
    return default


def _valid_font_name(value, default: str) -> str:
    """Nicht-leerer Fontname oder Default."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def resolve_caption_style(style) -> dict:
    """Validiert ein Caption-Style-Dict und liefert Renderer-(ASS-)kwargs.

    Kompatibilitäts-API mit identischer Semantik wie die frühere
    pipeline.resolve_caption_style(); None/kaputt -> sichere Defaults.
    shadow_alpha wird legacy-konform in 0..255 geclampt (nicht verworfen).
    """
    if not isinstance(style, dict):
        return dict(CAPTION_STYLE_DEFAULTS)
    return CaptionStyle.from_dict(style).to_renderer_kwargs()
