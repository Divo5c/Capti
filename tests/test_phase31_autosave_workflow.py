"""
Regressionstests Phase 31: Settings Auto-Save + Caption-Style-Workflow.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import customtkinter as ctk

from config import load_config, set_config_value
from ui import i18n
from ui.screens.settings import _language_label


class Phase31Base(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        ctk.set_appearance_mode("dark")
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()
        i18n.set_language("de")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg_path = os.path.join(self.tmp.name, "config.json")
        self._old = os.environ.get("CAPTI_CONFIG_FILE")
        os.environ["CAPTI_CONFIG_FILE"] = self.cfg_path
        i18n.set_language("de")

    def tearDown(self):
        if self._old is None:
            os.environ.pop("CAPTI_CONFIG_FILE", None)
        else:
            os.environ["CAPTI_CONFIG_FILE"] = self._old
        i18n.set_language("de")
        self.tmp.cleanup()

    def _controller(self):
        from ui.app_controller import AppController
        return AppController(self.root)

    def _settings(self):
        controller = self._controller()
        screen = controller.get_screen("settings")
        self.root.update()
        return controller, screen


class TestSettingsAutoSave(Phase31Base):
    """1-10: Settings werden sofort angewendet und gespeichert."""

    def test_theme_change_applies_and_saves_immediately(self):  # 1+2+7
        controller, screen = self._settings()
        from ui.theme import get_theme
        self.assertEqual(screen.color("background"),
                         get_theme("dark")["background"])
        screen._on_theme_selected(i18n.t("set.theme.light"))
        self.root.update()
        self.assertEqual(load_config()["theme"], "light")
        new_screen = controller.get_screen("settings")
        self.assertEqual(new_screen.color("background"),
                         get_theme("light")["background"])

    def test_yellow_stays_yellow(self):
        controller, screen = self._settings()
        screen._on_theme_selected(i18n.t("set.theme.yellow"))
        self.root.update()
        self.assertEqual(load_config()["theme"], "yellow")
        self.assertEqual(controller.get_screen("settings").color("accent"),
                         "#ffd60a")

    def test_language_change_applies_and_saves_immediately(self):  # 3+4+8
        controller, screen = self._settings()
        screen._on_language_selected(_language_label("en"))
        self.root.update()
        self.assertEqual(load_config()["language"], "en")
        self.assertEqual(i18n.get_language(), "en")
        self.assertEqual(controller._nav_buttons["new_project"].cget("text"),
                         "New Project")

    def test_name_persists_without_save_button(self):  # 5
        _, screen = self._settings()
        screen.name_entry.delete(0, "end")
        screen.name_entry.insert(0, "TestUser")
        screen._save_name()  # FocusOut/Enter-Handler
        self.assertEqual(load_config()["name"], "TestUser")

    def test_model_persists_immediately(self):
        _, screen = self._settings()
        screen._on_model_selected("medium")
        self.assertEqual(load_config()["model"], "medium")

    def test_unknown_keys_survive_autosave(self):  # 6
        set_config_value("custom_key", {"a": 1})
        _, screen = self._settings()
        screen.name_entry.insert(0, "X")
        screen._save_name()
        screen._on_model_selected("base")
        cfg = load_config()
        self.assertEqual(cfg["custom_key"], {"a": 1})
        self.assertEqual(cfg["name"], "X")
        self.assertEqual(cfg["model"], "base")

    def test_no_save_button_in_ui(self):  # 10
        def _collect(w, out):
            if isinstance(w, ctk.CTkButton):
                out.append(w.cget("text"))
            for ch in w.winfo_children():
                _collect(ch, out)

        _, screen = self._settings()
        texts: list = []
        _collect(screen, texts)
        self.assertNotIn(i18n.t("set.btn_save"), texts)

    def test_live_language_switch_still_works(self):  # 9
        controller, _ = self._settings()
        controller.set_language("en")
        self.root.update()
        self.assertEqual(controller._nav_buttons["home"].cget("text"), "Home")
        self.assertEqual(load_config()["language"], "en")


class TestCaptionStyleWorkflow(Phase31Base):
    """11-22: New Project -> Caption Style -> Processing."""

    def _project_screen(self):
        controller = self._controller()
        controller.show_screen("new_project")
        self.root.update()
        return controller, controller.get_screen("new_project")

    def _fill_project(self, screen):
        screen.set_video("C:/videos/clip.mp4")
        screen.lang_var.set("np.lang.en")
        screen.model_var.set("tiny")

    def _buttons(self, widget):
        out = []
        if isinstance(widget, ctk.CTkButton):
            out.append(widget)
        for ch in widget.winfo_children():
            out.extend(self._buttons(ch))
        return out

    def test_continue_button_text_is_next(self):  # 11
        _, screen = self._project_screen()
        self.assertIn(i18n.t("np.continue"),
                      [b.cget("text") for b in self._buttons(screen)])

    def test_continue_starts_no_pipeline(self):  # 12+21
        with patch("ui.screens.processing.CaptiPipeline"):
            controller, screen = self._project_screen()
            self._fill_project(screen)
            screen._on_continue()
        processing = controller.get_screen("processing")
        self.assertIsNone(getattr(processing, "_pipeline", None))

    def test_project_data_kept_and_caption_step_shown(self):  # 13-16
        controller, screen = self._project_screen()
        self._fill_project(screen)
        screen._on_continue()
        self.assertEqual(controller.current_screen, "caption_style")
        project = controller.pending_project
        self.assertEqual(project["video_path"], "C:/videos/clip.mp4")
        self.assertEqual(project["model"], "tiny")
        self.assertEqual(project["language"], "en")


    def test_style_selection_reaches_processing(self):  # 17+18+20
        controller, screen = self._project_screen()
        self._fill_project(screen)
        screen._on_continue()
        cs = controller.get_screen("caption_style")
        self.assertTrue(cs._workflow_active())
        cs.apply_preset("Strong")
        with patch("ui.screens.processing.CaptiPipeline") as mock_pipeline:
            cs._start_project_workflow()
            self.root.update()
            kwargs = (mock_pipeline.return_value.run_async.call_args.kwargs)
            self.assertEqual(kwargs["caption_style"]["highlight_color"],
                             "#FF3B30")
            self.assertEqual(kwargs["caption_style"]["pop_scale"], 125)
            processing = controller.get_screen("processing")
            self.assertEqual(processing.video_path, "C:/videos/clip.mp4")
            self.assertEqual(processing.model, "tiny")
            self.assertEqual(processing.language, "en")
        self.assertIsNone(controller.pending_project)

    def test_back_from_caption_style_preserves_selection(self):  # 19
        controller, screen = self._project_screen()
        self._fill_project(screen)
        screen._on_continue()
        cs = controller.get_screen("caption_style")
        cs.btn_back.invoke()
        self.assertEqual(controller.current_screen, "new_project")
        self.assertIsNotNone(controller.pending_project)

    def test_normal_mode_has_no_start_button(self):
        controller = self._controller()
        cs = controller.get_screen("caption_style")
        self.assertFalse(cs._workflow_active())
        self.assertEqual(str(cs.btn_start.winfo_manager()), "")

    def test_i18n_keys_complete_de_en(self):  # 22
        for lang in ("de", "en"):
            for key in ("np.continue", "cs.start_processing",
                        "cs.back_to_project", "cs.workflow_hint"):
                self.assertIn(key, i18n.TRANSLATIONS[lang], f"{lang}:{key}")
                self.assertFalse(
                    i18n.TRANSLATIONS[lang][key].startswith(("np.", "cs.")),
                    f"Roh-Key in {lang}: {key}")


if __name__ == "__main__":
    unittest.main()
