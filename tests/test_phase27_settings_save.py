"""
Regressionstests Phase 27: Settings-Save-Korrektheit & UX-Reparatur.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import customtkinter as ctk

from config import load_config, save_config, set_config_value
from ui import i18n
from ui.screens.settings import _theme_label, _language_label


class Phase27Base(unittest.TestCase):
    """Temp-Config + gemeinsames (verstecktes) CTk-Root."""

    @classmethod
    def setUpClass(cls):
        ctk.set_appearance_mode("dark")
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg_path = os.path.join(self.tmp.name, "config.json")
        self._old_cfg_env = os.environ.get("CAPTI_CONFIG_FILE")
        os.environ["CAPTI_CONFIG_FILE"] = self.cfg_path
        i18n.set_language("de")

    def tearDown(self):
        if self._old_cfg_env is None:
            os.environ.pop("CAPTI_CONFIG_FILE", None)
        else:
            os.environ["CAPTI_CONFIG_FILE"] = self._old_cfg_env
        i18n.set_language("de")
        self.tmp.cleanup()

    def _controller(self):
        from ui.app_controller import AppController
        return AppController(self.root)

    def _settings_screen(self, theme=None, language=None):
        if theme is not None:
            set_config_value("theme", theme)
        if language is not None:
            set_config_value("language", language)
        controller = self._controller()
        screen = controller.get_screen("settings")
        self.root.update()
        return controller, screen


class TestSettingsSaveWithoutChange(Phase27Base):
    """Speichern ohne Änderung darf nichts zurücksetzen."""

    def test_no_change_preserves_values(self):  # alle 6 Kombinationen
        for theme in ("dark", "light", "yellow"):
            for language in ("de", "en"):
                with self.subTest(theme=theme, language=language):
                    _, screen = self._settings_screen(theme, language)
                    screen.save_settings()
                    cfg = load_config()
                    self.assertEqual(cfg["theme"], theme)
                    self.assertEqual(cfg["language"], language)

    def test_labels_are_never_raw_keys(self):
        """Sichtbare Werte enthalten keine rohen set.*-Keys."""
        for lang_ui in ("de", "en"):
            i18n.set_language(lang_ui)
            _, screen = self._settings_screen("yellow", "en")
            self.assertNotIn("set.", screen.theme_var.get())
            self.assertNotIn("set.", screen.language_var.get())
            for value in screen.theme_segmented.cget("values"):
                self.assertFalse(str(value).startswith("set."),
                                 f"Roh-Key sichtbar: {value}")
            for value in screen.language_combo.cget("values"):
                self.assertFalse(str(value).startswith("set."),
                                 f"Roh-Key sichtbar: {value}")

    def test_theme_change_persists(self):
        _, screen = self._settings_screen("dark", "de")
        screen.theme_var.set(_theme_label("yellow"))
        screen.save_settings()
        self.assertEqual(load_config()["theme"], "yellow")

    def test_language_change_persists(self):
        _, screen = self._settings_screen("dark", "de")
        screen.language_var.set(_language_label("en"))
        screen.save_settings()
        self.assertEqual(load_config()["language"], "en")

    def test_theme_and_language_changed_together(self):
        _, screen = self._settings_screen("dark", "de")
        screen.theme_var.set(_theme_label("light"))
        screen.language_var.set(_language_label("en"))
        screen.save_settings()
        cfg = load_config()
        self.assertEqual(cfg["theme"], "light")
        self.assertEqual(cfg["language"], "en")

    def test_yellow_survives_save_in_english_ui(self):
        i18n.set_language("en")
        _, screen = self._settings_screen("yellow", "en")
        screen.name_entry.insert(0, "Tester")  # einzige Änderung: Name
        screen.save_settings()
        cfg = load_config()
        self.assertEqual(cfg["theme"], "yellow")
        self.assertEqual(cfg["language"], "en")
        self.assertEqual(cfg["name"], "Tester")


class TestLiveLanguageSwitchKeepsCodes(Phase27Base):

    def test_labels_update_codes_stay(self):
        controller, screen = self._settings_screen("yellow", "de")
        # Live-Sprachwechsel über den Controller (baut Screens neu auf)
        controller.set_language("en")
        screen2 = controller.get_screen("settings")
        self.root.update()
        # Label entspricht der EN-Übersetzung, kein Roh-Key
        self.assertEqual(screen2.theme_var.get(),
                         i18n.TRANSLATIONS["en"]["set.theme.yellow"])
        self.assertEqual(screen2.language_var.get(),
                         i18n.TRANSLATIONS["en"]["set.lang.en"])
        self.assertNotIn("set.", screen2.theme_var.get())
        screen2.save_settings()
        cfg = load_config()
        self.assertEqual(cfg["theme"], "yellow")
        self.assertEqual(cfg["language"], "en")


class TestResultSaveAs(unittest.TestCase):
    """save_as(): Erfolg funktioniert weiter, Fehler wird sichtbar."""

    @classmethod
    def setUpClass(cls):
        ctk.set_appearance_mode("dark")
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg_path = os.path.join(self.tmp.name, "config.json")
        self._old = os.environ.get("CAPTI_CONFIG_FILE")
        os.environ["CAPTI_CONFIG_FILE"] = self.cfg_path

    def tearDown(self):
        if self._old is None:
            os.environ.pop("CAPTI_CONFIG_FILE", None)
        else:
            os.environ["CAPTI_CONFIG_FILE"] = self._old
        self.tmp.cleanup()

    def _screen_with_output(self):
        from ui.app_controller import AppController
        controller = AppController(self.root)
        screen = controller.get_screen("result")
        src = os.path.join(self.tmp.name, "out.mp4")
        with open(src, "w", encoding="utf-8") as f:
            f.write("x")
        screen.set_result(src)
        return screen, src

    def test_successful_save_clears_error(self):
        screen, src = self._screen_with_output()
        dest = os.path.join(self.tmp.name, "copy.mp4")
        with patch("ui.screens.result.filedialog.asksaveasfilename",
                   return_value=dest):
            screen.save_as()
        self.assertTrue(os.path.exists(dest))
        self.assertEqual(screen.error_label.cget("text"), "")

    def test_failed_save_shows_visible_error(self):
        i18n.set_language("de")
        screen, src = self._screen_with_output()
        # Ziel in nicht existierendes Verzeichnis -> shutil.copy2 schlägt fehl
        dest = os.path.join(self.tmp.name, "nope", "x.mp4")
        with patch("ui.screens.result.filedialog.asksaveasfilename",
                   return_value=dest):
            screen.save_as()
        text = screen.error_label.cget("text")
        prefix = i18n.TRANSLATIONS["de"]["res.save_failed"].split(":")[0]
        self.assertTrue(text.startswith(prefix),
                        f"Keine sichtbare Fehlermeldung: {text!r}")
        self.assertNotIn("res.save_failed", text)  # Key nie roh sichtbar


class TestStartupTempCleanup(unittest.TestCase):
    """Vorverarbeitungs-Cleanup: entfernt _temp-Reste, sonst nichts."""

    def test_cleanup_removes_temp_and_keeps_output(self):
        from ui.screens.processing import ProcessingScreen
        tmp = tempfile.TemporaryDirectory()
        try:
            base = Path(tmp.name)
            temp_dir = base / "_temp"
            temp_dir.mkdir()
            (temp_dir / "clip_audio.wav").write_text("x", encoding="utf-8")
            output = base / "clip_subtitled.mp4"
            output.write_text("video", encoding="utf-8")

            with patch.object(ProcessingScreen, "_temp_dir",
                              return_value=temp_dir):
                ProcessingScreen._cleanup_temp()

            self.assertFalse(temp_dir.exists())      # _temp entfernt
            self.assertTrue(output.exists())          # Output unberührt
            # Zweiter Aufruf ohne _temp: kein Fehler
            with patch.object(ProcessingScreen, "_temp_dir",
                              return_value=temp_dir):
                ProcessingScreen._cleanup_temp()
        finally:
            tmp.cleanup()


class TestCentralizedConfigReaders(Phase27Base):

    def test_home_and_new_project_use_central_config(self):
        import ui.screens.home as home_mod
        import ui.screens.new_project as np_mod
        save_config({"name": "Diraj", "model": "medium"})
        self.assertEqual(home_mod._load_user_name(), "Diraj")
        self.assertEqual(np_mod._load_default_model(), "medium")
        # Kaputte Config -> sichere Defaults, kein Crash
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            f.write("{broken")
        self.assertEqual(home_mod._load_user_name(), "")
        self.assertEqual(np_mod._load_default_model(), "small")


class TestNudgeStepSettings(Phase27Base):
    """Block 34: Nudge-Schrittweite (Parse, Read, UI, Persistenz)."""

    def test_default(self):
        from ui.screens.settings import NUDGE_STEP_DEFAULT, read_nudge_step
        self.assertEqual(NUDGE_STEP_DEFAULT, 0.05)
        self.assertEqual(read_nudge_step({}), 0.05)
        self.assertEqual(read_nudge_step(), 0.05)

    def test_parse_valid(self):
        from ui.screens.settings import parse_nudge_step
        self.assertEqual(parse_nudge_step("0.05"), 0.05)
        self.assertEqual(parse_nudge_step("0,05"), 0.05)
        self.assertEqual(parse_nudge_step("  0.1  "), 0.1)
        self.assertEqual(parse_nudge_step(0.2), 0.2)
        self.assertEqual(parse_nudge_step("0.001"), 0.001)

    def test_parse_invalid(self):
        from ui.screens.settings import parse_nudge_step
        for bad in ("", "0", "0.0", "-0.05", "abc", "1..2",
                    "nan", "NaN", "inf", "-inf", None, [], {}):
            self.assertIsNone(parse_nudge_step(bad), msg=repr(bad))

    def test_read_fallback(self):
        from ui.screens.settings import read_nudge_step
        self.assertEqual(read_nudge_step({"nudge_step": "kaputt"}), 0.05)
        self.assertEqual(read_nudge_step({"nudge_step": -1}), 0.05)
        self.assertEqual(read_nudge_step({"nudge_step": 0}), 0.05)
        self.assertEqual(read_nudge_step({"nudge_step": "inf"}), 0.05)
        self.assertEqual(read_nudge_step({"nudge_step": 0.25}), 0.25)

    def test_ui_valid_applies_and_persists(self):
        from ui.screens.settings import NUDGE_STEP_KEY, read_nudge_step
        _, screen = self._settings_screen()
        screen.nudge_entry.delete(0, "end")
        screen.nudge_entry.insert(0, "0,10")
        screen._save_nudge_step()
        self.assertEqual(load_config()[NUDGE_STEP_KEY], 0.10)
        self.assertEqual(read_nudge_step(), 0.10)
        self.assertEqual(screen.nudge_status_label.cget("text"), "")
        # Neuaufbau liest denselben Wert (Persistenz):
        _, screen2 = self._settings_screen()
        self.assertEqual(screen2.nudge_entry.get(), "0.1")

    def test_ui_invalid_reverts(self):
        from ui.screens.settings import NUDGE_STEP_KEY, read_nudge_step
        _, screen = self._settings_screen()
        set_config_value(NUDGE_STEP_KEY, 0.05)
        for bad in ("", "0", "-2", "abc", "nan"):
            screen.nudge_entry.delete(0, "end")
            screen.nudge_entry.insert(0, bad)
            screen._save_nudge_step()
            self.assertEqual(load_config()[NUDGE_STEP_KEY], 0.05)
            self.assertEqual(screen.nudge_entry.get(), "0.05")
            self.assertTrue(screen.nudge_status_label.cget("text"))
        self.assertEqual(read_nudge_step(), 0.05)

    def test_save_settings_includes_nudge(self):
        from ui.screens.settings import NUDGE_STEP_KEY
        _, screen = self._settings_screen()
        screen.nudge_entry.delete(0, "end")
        screen.nudge_entry.insert(0, "0.2")
        screen.save_settings()
        self.assertEqual(load_config()[NUDGE_STEP_KEY], 0.2)

    def test_de_en_labels(self):
        for lang, title, desc in (
                ("de", "Timing-Schrittweite", "Schrittweite"),
                ("en", "Timing step", "Step size")):
            i18n.set_language(lang)
            self.assertEqual(i18n.t("set.nudge_title"), title)
            self.assertIn(desc, i18n.t("set.nudge_desc"))
            self.assertTrue(i18n.t("set.nudge_invalid"))


class TestNudgePresets(Phase27Base):
    """Block 35: Preset-Auswahl steuert nur den Settings-Wert."""

    def test_preset_list(self):
        from ui.screens.settings import NUDGE_STEP_PRESETS
        self.assertEqual(tuple(NUDGE_STEP_PRESETS), (0.01, 0.05, 0.10, 0.50))

    def test_each_preset_saves_value(self):
        from ui.screens.settings import NUDGE_STEP_KEY, read_nudge_step
        for preset in (0.01, 0.05, 0.10, 0.50):
            _, screen = self._settings_screen()
            screen._on_preset_selected(preset)
            self.assertEqual(load_config()[NUDGE_STEP_KEY], preset)
            self.assertEqual(read_nudge_step(), preset)
            self.assertEqual(screen.nudge_entry.get(), f"{preset:g}")

    def test_preset_uses_save_path(self):
        """Preset-Klick schreibt merge-sicher (andere Keys bleiben)."""
        from ui.screens.settings import NUDGE_STEP_KEY
        set_config_value("theme", "light")
        _, screen = self._settings_screen()
        screen._on_preset_selected(0.10)
        cfg = load_config()
        self.assertEqual(cfg[NUDGE_STEP_KEY], 0.10)
        self.assertEqual(cfg["theme"], "light")

    def test_restart_loads_preset(self):
        from ui.screens.settings import read_nudge_step
        _, screen = self._settings_screen()
        screen._on_preset_selected(0.50)
        _, screen2 = self._settings_screen()
        self.assertEqual(read_nudge_step(), 0.50)
        self.assertEqual(screen2.nudge_entry.get(), "0.5")
        active = [p for p, b in screen2._preset_buttons.items()
                  if b.cget("fg_color") != "transparent"]
        self.assertEqual(active, [0.50])

    def test_free_value_marks_no_preset(self):
        from ui.screens import settings as settings_mod
        _, screen = self._settings_screen()
        screen.nudge_entry.delete(0, "end")
        screen.nudge_entry.insert(0, "0,15")
        screen._save_nudge_step()
        self.assertEqual(load_config()["nudge_step"], 0.15)
        active = [p for p, b in screen._preset_buttons.items()
                  if b.cget("fg_color") != "transparent"]
        self.assertEqual(active, [])
        # ... und bleibt nach Neustart ohne Markierung:
        _, screen2 = self._settings_screen()
        active2 = [p for p, b in screen2._preset_buttons.items()
                   if b.cget("fg_color") != "transparent"]
        self.assertEqual(active2, [])
        self.assertEqual(settings_mod.read_nudge_step(), 0.15)

    def test_preset_format_de_en(self):
        from ui.screens.settings import format_nudge_preset
        i18n.set_language("de")
        self.assertEqual(
            [format_nudge_preset(p) for p in (0.01, 0.05, 0.10, 0.50)],
            ["0,01 s", "0,05 s", "0,10 s", "0,50 s"])
        i18n.set_language("en")
        self.assertEqual(
            [format_nudge_preset(p) for p in (0.01, 0.05, 0.10, 0.50)],
            ["0.01 s", "0.05 s", "0.10 s", "0.50 s"])

    def test_single_source_no_second_step(self):
        """Editor liest Settings (kein direktes PRESETS-Reading)."""
        import ui.screens.caption_style as cs_mod
        from ui.screens import settings as settings_mod
        set_config_value(settings_mod.NUDGE_STEP_KEY, 0.10)
        self.assertEqual(cs_mod.get_nudge_step(), 0.10)
        self.assertEqual(settings_mod.read_nudge_step(), 0.10)
        with open(cs_mod.__file__, encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("NUDGE_STEP_PRESETS", source)
        self.assertNotIn("_NUDGE_STEP =", source)


class TestSnapToleranceSettings(Phase27Base):
    """Block 41: Snap-Toleranz (Default, Parse, Read, UI, Persistenz)."""

    def test_default(self):
        from ui.screens.settings import SNAP_TOLERANCE_DEFAULT, read_snap_tolerance
        self.assertEqual(SNAP_TOLERANCE_DEFAULT, 8.0)
        self.assertEqual(read_snap_tolerance({}), 8.0)
        self.assertEqual(read_snap_tolerance(), 8.0)

    def test_read_valid(self):
        from ui.screens.settings import read_snap_tolerance
        self.assertEqual(read_snap_tolerance({"snap_tolerance_px": 2}), 2.0)
        self.assertEqual(read_snap_tolerance({"snap_tolerance_px": 16.5}), 16.5)
        self.assertEqual(read_snap_tolerance({"snap_tolerance_px": "12"}), 12.0)

    def test_read_invalid_falls_back(self):
        from ui.screens.settings import read_snap_tolerance
        for bad in ("", "0", 0, -3, "abc", "nan", "inf", None, [], {},
                    "1..2"):
            self.assertEqual(read_snap_tolerance(
                {"snap_tolerance_px": bad}), 8.0, msg=repr(bad))

    def test_ui_valid_applies_and_persists(self):
        from ui.screens.settings import SNAP_TOLERANCE_KEY, read_snap_tolerance
        _, screen = self._settings_screen()
        screen.snap_entry.delete(0, "end")
        screen.snap_entry.insert(0, "16")
        screen._save_snap_tolerance()
        self.assertEqual(load_config()[SNAP_TOLERANCE_KEY], 16.0)
        self.assertEqual(read_snap_tolerance(), 16.0)
        self.assertEqual(screen.snap_status_label.cget("text"), "")
        # Neuaufbau liest denselben Wert (Persistenz):
        _, screen2 = self._settings_screen()
        self.assertEqual(screen2.snap_entry.get(), "16")

    def test_ui_invalid_reverts(self):
        from ui.screens.settings import SNAP_TOLERANCE_KEY, read_snap_tolerance
        _, screen = self._settings_screen()
        set_config_value(SNAP_TOLERANCE_KEY, 8.0)
        for bad in ("", "0", "-2", "abc", "nan", "inf"):
            screen.snap_entry.delete(0, "end")
            screen.snap_entry.insert(0, bad)
            screen._save_snap_tolerance()
            self.assertEqual(load_config()[SNAP_TOLERANCE_KEY], 8.0)
            self.assertEqual(screen.snap_entry.get(), "8")
            self.assertTrue(screen.snap_status_label.cget("text"))
        self.assertEqual(read_snap_tolerance(), 8.0)

    def test_ui_comma_and_whitespace(self):
        from ui.screens.settings import read_snap_tolerance
        _, screen = self._settings_screen()
        screen.snap_entry.delete(0, "end")
        screen.snap_entry.insert(0, "  2,5  ")
        screen._save_snap_tolerance()
        self.assertEqual(read_snap_tolerance(), 2.5)

    def test_de_en_labels(self):
        for lang, title in (("de", "Snap-Toleranz"), ("en", "Snap tolerance")):
            controller, _screen = self._settings_screen()
            controller.set_language(lang)
            screen = controller.get_screen("settings")
            found = " ".join(
                w.cget("text") for w in screen.snap_entry.master.winfo_children()
                if "Label" in type(w).__name__)
            self.assertIn(title, found)


class TestSnapPresetSettings(Phase27Base):
    """Block 42: Snap-Presets (Konstante, Auswahl, Persistenz, freie Werte)."""

    def test_preset_constant(self):
        from ui.screens.settings import SNAP_TOLERANCE_PRESETS
        self.assertEqual(SNAP_TOLERANCE_PRESETS, (2.0, 4.0, 8.0, 16.0))

    def test_no_duplicate_in_caption_style(self):
        import ui.screens.caption_style as cs_mod
        src = open(cs_mod.__file__, encoding="utf-8").read()
        self.assertNotIn("SNAP_TOLERANCE_PRESETS", src)
        self.assertNotIn("(2.0, 4.0, 8.0, 16.0)", src)

    def test_preset_format(self):
        from ui.screens.settings import format_snap_preset
        self.assertEqual(format_snap_preset(2.0), "2 px")
        self.assertEqual(format_snap_preset(4.0), "4 px")
        self.assertEqual(format_snap_preset(8.0), "8 px")
        self.assertEqual(format_snap_preset(16.0), "16 px")

    def test_preset_click_writes_config(self):
        from ui.screens.settings import SNAP_TOLERANCE_KEY, read_snap_tolerance
        _, screen = self._settings_screen()
        for preset in (2.0, 4.0, 8.0, 16.0):
            screen._on_preset_selected_snap(preset)
            self.assertEqual(load_config()[SNAP_TOLERANCE_KEY], preset)
            self.assertEqual(read_snap_tolerance(), preset)

    def test_preset_active_marking(self):
        _, screen = self._settings_screen()
        accent = screen.color("accent")
        screen._on_preset_selected_snap(16.0)
        active = [p for p, b in screen._preset_buttons_snap.items()
                  if str(b.cget("fg_color")) == str(accent)]
        self.assertEqual(active, [16.0])
        screen._on_preset_selected_snap(4.0)
        active = [p for p, b in screen._preset_buttons_snap.items()
                  if str(b.cget("fg_color")) == str(accent)]
        self.assertEqual(active, [4.0])

    def test_preset_persist_reload(self):
        from ui.screens.settings import SNAP_TOLERANCE_KEY, read_snap_tolerance
        _, screen = self._settings_screen()
        screen._on_preset_selected_snap(16.0)
        self.assertEqual(load_config()[SNAP_TOLERANCE_KEY], 16.0)
        _, screen2 = self._settings_screen()
        accent = screen2.color("accent")
        self.assertEqual(read_snap_tolerance(), 16.0)
        active = [p for p, b in screen2._preset_buttons_snap.items()
                  if str(b.cget("fg_color")) == str(accent)]
        self.assertEqual(active, [16.0])

    def test_free_value_no_preset(self):
        from ui.screens.settings import read_snap_tolerance
        _, screen = self._settings_screen()
        accent = screen.color("accent")
        for free in ("6", "12.5"):
            screen.snap_entry.delete(0, "end")
            screen.snap_entry.insert(0, free)
            screen._save_snap_tolerance()
            self.assertEqual(read_snap_tolerance(), float(free))
            active = [p for p, b in screen._preset_buttons_snap.items()
                      if str(b.cget("fg_color")) == str(accent)]
            self.assertEqual(active, [])
        # danach Preset -> korrekt markiert:
        screen._on_preset_selected_snap(8.0)
        active = [p for p, b in screen._preset_buttons_snap.items()
                  if str(b.cget("fg_color")) == str(accent)]
        self.assertEqual(active, [8.0])


if __name__ == "__main__":
    unittest.main()



