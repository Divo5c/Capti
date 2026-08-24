"""
Regressionstests Phase 28: Fenster/Scroll, Theme-Korrektheit, Name,
Caption-Style-Kette.

1. Screens liegen in einem vertikalen Scroll-Wrapper (kleine Fenster).
2. Startup nutzt das gespeicherte Theme; apply_theme baut Screens neu
   auf, sodass alle Inhalte die neuen Farben tragen.
3. Name + andere Werte bleiben nach Speichern und Controller-Neustart.
4. Config caption_style -> Processing -> Renderer -> ASS enthält Style.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import customtkinter as ctk

from config import load_config, save_config, set_config_value
from ui import i18n
from ui.theme import get_theme


class Phase28Base(unittest.TestCase):

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

    def tearDown(self):
        if self._old is None:
            os.environ.pop("CAPTI_CONFIG_FILE", None)
        else:
            os.environ["CAPTI_CONFIG_FILE"] = self._old
        self.tmp.cleanup()

    def _controller(self, theme="dark"):
        from ui.app_controller import AppController
        return AppController(self.root, theme_name=theme)


class TestScrollableScreens(Phase28Base):
    """Alle Screens liegen in einem vertikalen Scrollbereich."""

    def test_screens_are_scrollable(self):
        from customtkinter import CTkScrollableFrame
        controller = self._controller()
        for name in ("home", "new_project", "caption_style",
                     "settings", "processing", "result"):
            screen = controller.get_screen(name)
            self.assertIsInstance(
                screen.master, CTkScrollableFrame,
                f"Screen '{name}' hat keinen Scrollbereich")
            self.assertEqual(screen.master.cget("fg_color"),
                             get_theme("dark")["background"])


class TestThemeCorrectness(Phase28Base):
    """Startup nutzt Config-Theme; Live-Wechsel baut Screens neu."""

    def test_startup_uses_saved_theme(self):
        for theme in ("dark", "light", "yellow"):
            with self.subTest(theme=theme):
                set_config_value("theme", theme)
                controller = self._controller(theme=theme)
                self.assertEqual(controller.current_theme, theme)
                screen = controller.get_screen("settings")
                expected = get_theme(theme)["background"]
                # Wrapper und Screen-Thema tragen die Theme-Farben
                self.assertIsInstance(screen, ctk.CTkFrame)
                self.assertEqual(screen.theme["background"], expected)

    def test_live_theme_change_rebuilds_screen(self):
        controller = self._controller("dark")
        old_screen = controller.get_screen("settings")
        old_color = old_screen.color("background")
        controller.apply_theme("light")
        new_screen = controller.get_screen("settings")
        self.assertIsNot(new_screen, old_screen)
        self.assertEqual(new_screen.color("background"),
                         get_theme("light")["background"])
        self.assertNotEqual(new_screen.color("background"), old_color)
        # Sidebar/Container ebenfalls umgefärbt
        self.assertEqual(controller.sidebar.cget("fg_color"),
                         get_theme("light")["surface"])

    def test_no_fallback_to_dark_when_yellow_saved(self):
        """Gespeichertes yellow darf beim Neustart nicht still auf dark fallen."""
        set_config_value("theme", "yellow")
        controller = self._controller(theme="yellow")
        screen = controller.get_screen("home")
        self.assertEqual(screen.color("accent"),
                         get_theme("yellow")["accent"])


class TestNamePersistence(Phase28Base):
    """Name + alle anderen Werte bleiben nach Save und Neustart erhalten."""

    def test_full_settings_roundtrip_with_restart(self):
        save_config({
            "name": "TestUser",
            "theme": "yellow",
            "language": "en",
            "model": "medium",
            "caption_style": {"highlight_color": "#FF3B30",
                              "pop_enabled": True},
            "custom_key": 42,
        })
        # 'Neustart': neue Controller-Instanz liest dieselbe Config
        controller = self._controller(theme="yellow")
        self.assertEqual(controller.current_theme, "yellow")
        import ui.screens.home as home_mod
        self.assertEqual(home_mod._load_user_name(), "TestUser")
        cfg = load_config()
        self.assertEqual(cfg["name"], "TestUser")
        self.assertEqual(cfg["theme"], "yellow")
        self.assertEqual(cfg["language"], "en")
        self.assertEqual(cfg["model"], "medium")
        self.assertEqual(cfg["caption_style"]["highlight_color"], "#FF3B30")
        self.assertEqual(cfg["custom_key"], 42)  # unbekannte Keys bleiben

    def test_home_greeting_shows_name(self):
        set_config_value("name", "TestUser")

        class _Ctrl:
            current_theme = "dark"

        from ui.screens.home import HomeScreen
        wrapper = ctk.CTkFrame(self.root)
        screen = HomeScreen(wrapper, _Ctrl())

        def _texts(w):
            out = []
            if isinstance(w, ctk.CTkLabel):
                out.append(w.cget("text"))
            for ch in w.winfo_children():
                out.extend(_texts(ch))
            return out

        texts = " ".join(_texts(screen))
        self.assertIn("TestUser", texts)


class TestCaptionStyleChain(Phase28Base):
    """Config caption_style -> Processing -> Renderer -> ASS."""

    def test_strong_preset_reaches_ass_output(self):
        from caption_renderer import CaptionRenderer
        from pipeline import resolve_caption_style
        from ui.screens.processing import ProcessingScreen

        # Strong-Preset-Werte (aus CaptionStyleScreen.PRESETS) speichern
        save_config({"caption_style": {
            "normal_color": "#FFFFFF", "highlight_color": "#FF3B30",
            "outline_color": "#000000", "shadow_alpha": 180,
            "pop_enabled": True, "pop_scale": 125, "pop_decay_ms": 120,
        }})
        style_cfg = ProcessingScreen._load_caption_style()
        self.assertIsNotNone(style_cfg)
        kwargs = resolve_caption_style(style_cfg)
        renderer = CaptionRenderer(**kwargs)
        self.assertEqual(renderer.highlight_color, "&H00303BFF")  # BGR
        self.assertEqual(renderer.pop_scale, 125)

        path = os.path.join(self.tmp.name, "out.ass")
        segments = [{"start": 0.0, "end": 1.0, "text": "Hallo Welt",
                     "words": [{"start": 0.0, "end": 0.5, "word": "Hallo"},
                               {"start": 0.5, "end": 1.0, "word": "Welt"}]}]
        renderer.generate_ass(segments, path, video_width=1080,
                              video_height=1920)
        with open(path, encoding="utf-8-sig") as f:
            ass = f.read()
        # Highlight-Farbe und Pop-Scale tatsächlich in der ASS
        self.assertIn("&H00303BFF", ass)
        self.assertIn("\\fscx125\\fscy125", ass)


class TestScreenVisibilityRegression(Phase28Base):
    """Phase-28-Regression: Screens müssen im Wrapper gegriddet und
    sichtbar sein (Wrapper darf nicht auf 1 px kollabieren)."""

    def _assert_visible(self, controller, name):
        controller.show_screen(name)
        self.root.update()
        self.root.update()
        screen = controller._screens[name]
        wrapper = controller._wrappers[name]
        # Screen ist tatsächlich IM Wrapper platziert
        self.assertTrue(screen.grid_info(),
                        f"{name}: Screen ist nicht im Wrapper gegriddet")
        self.assertEqual(screen.master, wrapper)
        # Wrapper hat reale Höhe (nicht auf 1 px kollabiert) und ist sichtbar
        self.assertGreater(wrapper.winfo_height(), 100,
                           f"{name}: Wrapper kollabiert "
                           f"({wrapper.winfo_height()} px)")
        self.assertTrue(wrapper.winfo_ismapped())

    def test_navigation_cycle_keeps_content_visible(self):
        controller = self._controller()
        for name in ("home", "new_project", "caption_style",
                     "settings", "home"):
            self._assert_visible(controller, name)

    def test_apply_theme_preserves_visibility(self):
        controller = self._controller()
        controller.show_screen("settings")
        self.root.update()
        controller.apply_theme("light")
        self.root.update()
        # Nach Theme-Rebuild: neuer Screen sichtbar im neuen Theme
        screen = controller.get_screen("settings")
        self.assertTrue(screen.grid_info())
        self.assertTrue(screen.winfo_ismapped())
        self.assertEqual(screen.color("background"),
                         get_theme("light")["background"])
        # Weitere Navigation funktioniert weiterhin
        self._assert_visible(controller, "new_project")
        self._assert_visible(controller, "home")

    def test_scroll_wrapper_active_after_theme_change(self):
        from customtkinter import CTkScrollableFrame
        controller = self._controller()
        controller.get_screen("caption_style")
        controller.apply_theme("yellow")
        screen = controller.get_screen("caption_style")
        self.assertIsInstance(screen.master, CTkScrollableFrame)


if __name__ == "__main__":
    unittest.main()

