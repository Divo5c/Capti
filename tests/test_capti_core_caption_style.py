"""
Tests für capti_core.caption_style: das eine Caption-Style-Modell.

Abgedeckt:
- Defaults/Preset-Werte (kanonische Form)
- Feldweise Validierung (kaputte Werte -> sichere Defaults, kein Crash)
- Serialisierungs-Roundtrip
- ASS-Konvertierung an der Render-Grenze (inkl. Alpha-Byte)
- Kompatibilität mit pipeline.resolve_caption_style / CAPTION_STYLE_DEFAULTS
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capti_core.caption_style import (
    CAPTION_STYLE_DEFAULTS,
    DEFAULT_CAPTION_STYLE,
    PRESETS,
    CaptionStyle,
    resolve_caption_style,
)
import pipeline as pipeline_mod


class TestDefaults(unittest.TestCase):

    def test_canonical_defaults_match_documented_look(self):  # 1
        self.assertEqual(DEFAULT_CAPTION_STYLE["normal_color"], "#FFFFFF")
        self.assertEqual(DEFAULT_CAPTION_STYLE["highlight_color"], "#FFFF00")
        self.assertEqual(DEFAULT_CAPTION_STYLE["outline_color"], "#101010")
        self.assertEqual(DEFAULT_CAPTION_STYLE["shadow_alpha"], 128)
        self.assertEqual(DEFAULT_CAPTION_STYLE["font_name"], "Arial Black")
        self.assertEqual(DEFAULT_CAPTION_STYLE["font_size"], 68)
        self.assertTrue(DEFAULT_CAPTION_STYLE["pop_enabled"])
        self.assertEqual(DEFAULT_CAPTION_STYLE["pop_scale"], 112)
        self.assertEqual(DEFAULT_CAPTION_STYLE["pop_decay_ms"], 150)

    def test_ass_defaults_unchanged_for_renderer(self):  # 2
        # Render-Seite muss exakt den bisherigen Capti-Look behalten
        self.assertEqual(CAPTION_STYLE_DEFAULTS["normal_color"], "&H00FFFFFF")
        self.assertEqual(CAPTION_STYLE_DEFAULTS["highlight_color"], "&H0000FFFF")
        self.assertEqual(CAPTION_STYLE_DEFAULTS["outline_color"], "&H00101010")
        self.assertEqual(CAPTION_STYLE_DEFAULTS["shadow_color"], "&H80000000")

    def test_pipeline_reexports_core_symbols(self):  # 3
        self.assertIs(pipeline_mod.resolve_caption_style, resolve_caption_style)
        self.assertIs(pipeline_mod.CAPTION_STYLE_DEFAULTS, CAPTION_STYLE_DEFAULTS)


class TestResolveCompatibility(unittest.TestCase):
    """resolve_caption_style liefert identische Ergebnisse wie bisher."""

    def test_none_gives_ass_defaults(self):  # 4
        self.assertEqual(resolve_caption_style(None), CAPTION_STYLE_DEFAULTS)

    def test_empty_dict_gives_ass_defaults(self):  # 5
        self.assertEqual(resolve_caption_style({}), CAPTION_STYLE_DEFAULTS)

    def test_valid_hex_colors_converted(self):  # 6
        result = resolve_caption_style({
            "normal_color": "#FF8800",
            "highlight_color": "#00ff88",   # lowercase ok
            "outline_color": "#000000",
            "shadow_color": "#202020",
            "shadow_alpha": 200,
        })
        self.assertEqual(result["normal_color"], "&H000088FF")     # BGR!
        self.assertEqual(result["highlight_color"], "&H0088FF00")
        self.assertEqual(result["outline_color"], "&H00000000")
        self.assertEqual(result["shadow_color"], "&HC8202020")     # C8=200

    def test_invalid_values_fall_back_to_defaults(self):  # 7
        result = resolve_caption_style({
            "normal_color": "rot",
            "highlight_color": 12345,
            "font_size": "riesig",
            "pop_scale": 9999,          # außerhalb 100..200 -> Default
            "pop_decay_ms": -5,         # außerhalb 0..1000 -> Default
        })
        self.assertEqual(result["normal_color"],
                         CAPTION_STYLE_DEFAULTS["normal_color"])
        self.assertEqual(result["highlight_color"],
                         CAPTION_STYLE_DEFAULTS["highlight_color"])
        self.assertEqual(result["font_size"], 68)
        self.assertEqual(result["pop_scale"], 112)
        self.assertEqual(result["pop_decay_ms"], 150)

    def test_font_name_stripped_and_applied(self):  # 8
        result = resolve_caption_style({"font_name": "  Impact  "})
        self.assertEqual(result["font_name"], "Impact")

    def test_shadow_alpha_out_of_range_is_clamped_in_color(self):  # 9
        result = resolve_caption_style({"shadow_color": "#000000",
                                        "shadow_alpha": 999})
        self.assertEqual(result["shadow_color"], "&HFF000000")  # FF=255

    def test_shadow_alpha_without_explicit_color_is_ignored_legacy(self):  # 9b
        # Legacy-Regel: ohne gültige shadow_color gilt der klassische
        # Look &H80000000 – shadow_alpha bleibt bewusst wirkungslos.
        self.assertEqual(
            resolve_caption_style({"shadow_alpha": 64})["shadow_color"],
            "&H80000000")
        self.assertEqual(
            resolve_caption_style({"shadow_color": "kaputt",
                                   "shadow_alpha": 200})["shadow_color"],
            "&H80000000")

    def test_explicit_default_black_gets_alpha_applied(self):  # 9c
        # Explizit gesetztes Schwarz (Wert zufällig = Default) MUSS das
        # Alpha erhalten – Entscheidend ist die Explizitheit, nicht der Wert.
        self.assertEqual(
            resolve_caption_style({"shadow_color": "#000000",
                                   "shadow_alpha": 200})["shadow_color"],
            "&HC8000000")

    def test_pop_enabled_coercion_like_legacy(self):  # 10
        self.assertTrue(resolve_caption_style(
            {"pop_enabled": "wahr"})["pop_enabled"])       # truthy String -> True


class TestCaptionStyleModel(unittest.TestCase):

    def test_roundtrip_to_dict_from_dict(self):  # 11
        style = CaptionStyle(highlight_color="#FF3B30", pop_scale=125)
        clone = CaptionStyle.from_dict(style.to_dict())
        self.assertEqual(clone, style)

    def test_from_dict_garbage_does_not_crash(self):  # 12
        self.assertEqual(CaptionStyle.from_dict(None).to_dict(),
                         CaptionStyle().to_dict())
        self.assertEqual(CaptionStyle.from_dict("kaputt").to_dict(),
                         CaptionStyle().to_dict())

    def test_shadow_color_explicitness_semantics(self):  # 12b
        # Aus config geladen ohne Farbe -> nicht explizit
        self.assertFalse(CaptionStyle.from_dict({}).shadow_color_explicit)
        # Explizit gesetzte (gültige) Farbe -> explizit
        self.assertTrue(CaptionStyle.from_dict(
            {"shadow_color": "#101010"}).shadow_color_explicit)
        # Direkt konstruierter Style gilt als explizit
        self.assertTrue(CaptionStyle().shadow_color_explicit)

    def test_unknown_keys_are_ignored(self):  # 13
        style = CaptionStyle.from_dict({"future_param": 42})
        self.assertFalse(hasattr(style, "future_param"))
        self.assertEqual(style.pop_scale, 112)

    def test_load_with_saved_config_value(self):  # 14
        style = CaptionStyle.load({"pop_enabled": False, "font_size": 90})
        self.assertFalse(style.pop_enabled)
        self.assertEqual(style.font_size, 90)

    def test_load_with_none_or_empty_gives_defaults(self):  # 15
        self.assertEqual(CaptionStyle.load(None), CaptionStyle())
        self.assertEqual(CaptionStyle.load({}), CaptionStyle())
        self.assertEqual(CaptionStyle.load(""), CaptionStyle())

    def test_merged_with_preset_strong(self):  # 16
        base = CaptionStyle()
        merged = base.merged_with_preset("Strong")
        self.assertEqual(merged.highlight_color, "#FF3B30")
        self.assertEqual(merged.pop_scale, 125)
        self.assertEqual(merged.pop_decay_ms, 120)
        self.assertEqual(merged.shadow_alpha, 180)
        # Basis bleibt unverändert
        self.assertEqual(base.highlight_color, "#FFFF00")

    def test_merged_with_unknown_preset_is_noop(self):  # 17
        base = CaptionStyle(pop_scale=130)
        merged = base.merged_with_preset("Existiert nicht")
        self.assertEqual(merged.pop_scale, 130)

    def test_presets_contain_capti_default_empty_overrides(self):  # 18
        self.assertEqual(PRESETS["Capti Default"], {})

    def test_to_renderer_kwargs_matches_resolve(self):  # 19
        raw = {"normal_color": "#112233", "shadow_alpha": 64}
        via_model = CaptionStyle.from_dict(raw).to_renderer_kwargs()
        self.assertEqual(via_model, resolve_caption_style(raw))

    def test_renderer_kwargs_are_accepted_by_real_renderer(self):  # 20
        from caption_renderer import create_caption_renderer
        kwargs = CaptionStyle.from_dict({}).to_renderer_kwargs()
        renderer = create_caption_renderer(**kwargs)   # darf nicht crashen
        self.assertEqual(renderer.font_size, 68)
        self.assertEqual(renderer.pop_scale, 112)
        self.assertTrue(renderer.pop_enabled)

    def test_position_not_a_style_parameter_by_design(self):  # 21
        # Position/Wörter pro Zeile werden aus der Videoauflösung abgeleitet
        # und sind bewusst KEINE Style-Felder (Explizitheit lt. Architektur).
        self.assertNotIn("position", DEFAULT_CAPTION_STYLE)
        self.assertNotIn("max_words_per_line", DEFAULT_CAPTION_STYLE)


if __name__ == "__main__":
    unittest.main()
