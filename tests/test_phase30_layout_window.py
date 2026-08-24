"""
Regressionstests Phase 30: Zentriertes Layout + persistenter Fensterzustand.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import customtkinter as ctk

from config import (
    MIN_WINDOW_HEIGHT, MIN_WINDOW_WIDTH,
    load_config, load_window_state, save_config, save_window_state,
    sanitize_geometry, set_config_value,
)
from ui.theme import get_theme


class WindowStateBase(unittest.TestCase):

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


class TestGeometrySanitize(WindowStateBase):
    """1-3: Validierung/Defaults/Klammerung der Geometry."""

    def test_default_when_no_window_config(self):  # 1
        state = load_window_state()
        self.assertIsNone(state["geometry"])
        self.assertFalse(state["maximized"])

    def test_valid_geometry_normalized(self):
        self.assertEqual(sanitize_geometry("1400x900+100+50"),
                         "1400x900+100+50")
        self.assertEqual(sanitize_geometry("1024x768-20-40"),
                         "1024x768-20-40")

    def test_geometry_clamped_to_minsize(self):  # 3
        result = sanitize_geometry("400x300+10+10")
        w, h = result.split("+")[0].split("x")
        self.assertEqual((int(w), int(h)),
                         (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT))
        # Position bleibt erhalten
        self.assertTrue(result.endswith("+10+10"))

    def test_invalid_geometries_rejected(self):  # 7 (teil 1)
        for bad in ("garbage", "100x100", "axb+c+d", "", None, "1x1"):
            self.assertIsNone(sanitize_geometry(bad))

    def test_broken_window_state_does_not_crash(self):  # 7
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            f.write('{"window_geometry": 42, "window_maximized": "yes!"}')
        state = load_window_state()  # darf nicht crashen
        self.assertIsNone(state["geometry"])
        self.assertEqual(state["maximized"], True)  # truthy -> bool

    def test_other_keys_preserved_on_save(self):  # 8
        save_config({"theme": "yellow", "name": "Diraj", "custom": [1]})
        save_window_state("1200x800+5+5", False)
        cfg = load_config()
        self.assertEqual(cfg["theme"], "yellow")
        self.assertEqual(cfg["name"], "Diraj")
        self.assertEqual(cfg["custom"], [1])
        self.assertEqual(cfg["window_geometry"], "1200x800+5+5")
        self.assertFalse(cfg["window_maximized"])


class TestWindowStateRoundtrip(WindowStateBase):
    """4-6: Maximiert/normal über 'Neustart'."""

    def test_maximized_restored(self):
        save_window_state("1400x900+0+0", True)
        state = load_window_state()
        self.assertTrue(state["maximized"])

    def test_not_maximized_stays_normal(self):
        set_config_value("window_maximized", True)
        save_window_state("1000x680+12+12", False)
        state = load_window_state()
        self.assertFalse(state["maximized"])
        self.assertIn("1000x680", state["geometry"])


class TestLayoutAndScrollRegression(unittest.TestCase):
    """9-12: Zentrierung + Scroll-Architektur bei zwei Fensterbreiten."""

    @classmethod
    def setUpClass(cls):
        ctk.set_appearance_mode("dark")
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()
        import ui.i18n as i18n
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

    def _controller(self, width_height=(1000, 680)):
        from ui.app_controller import AppController
        self.root.geometry(f"{width_height[0]}x{width_height[1]}")
        return AppController(self.root)

    def test_navigation_all_screens_mapped_and_scrolled(self):  # 9+10
        controller = self._controller((900, 600))
        for name in ("home", "new_project", "caption_style",
                     "settings", "home"):
            controller.show_screen(name)
            self.root.update(); self.root.update()
            screen = controller._screens[name]
            self.assertTrue(screen.grid_info(), name)
            self.assertTrue(screen.winfo_ismapped(), name)
            # Scroll-Wrapper aktiv (Streck-Spalten vorhanden)
            wrapper = controller._wrappers[name]
            self.assertEqual(wrapper.grid_columnconfigure(0)["weight"], 1)
            self.assertEqual(wrapper.grid_columnconfigure(2)["weight"], 1)

    def test_content_horizontally_centered_at_two_widths(self):  # 12
        from ui.app_controller import AppController
        for size in ((1000, 680), (1500, 900)):
            with self.subTest(size=size):
                controller = AppController(self.root,
                                           theme_name="dark") \
                    if not hasattr(self, "_c") else self._c
                controller.root.geometry(f"{size[0]}x{size[1]}")
                controller.show_screen("new_project")
                self.root.update(); self.root.update()
                screen = controller._screens["new_project"]
                wrapper = controller._wrappers["new_project"]
                vw = wrapper.winfo_width()
                sx = screen.winfo_x()
                sw = screen.winfo_width()
                left_gap, right_gap = sx, vw - (sx + sw)
                # Beide Seiten ähnlich groß -> zentriert; kein Überlauf
                self.assertGreaterEqual(left_gap, 0)
                self.assertGreaterEqual(right_gap, 0)
                self.assertLess(abs(left_gap - right_gap), 30,
                                f"nicht zentriert: {left_gap}/{right_gap}")
        self._c = controller

    def test_scroll_wrapper_survives_theme_change(self):  # 11
        from customtkinter import CTkScrollableFrame
        from ui.theme import get_theme
        controller = self._controller((1200, 800))
        controller.get_screen("caption_style")
        controller.apply_theme("yellow")
        screen = controller.get_screen("caption_style")
        self.root.update()
        self.assertIsInstance(screen.master, CTkScrollableFrame)
        self.assertTrue(screen.winfo_ismapped())
        self.assertEqual(screen.master.cget("fg_color"),
                         get_theme("yellow")["background"])

    def test_small_window_still_scrollable_and_mapped(self):
        controller = self._controller((820, 560))
        controller.show_screen("settings")
        self.root.update(); self.root.update()
        screen = controller._screens["settings"]
        wrapper = controller._wrappers["settings"]
        self.assertTrue(screen.winfo_ismapped())
        # Inhalt höher als Viewport -> vertikal scrollbar
        self.assertGreaterEqual(wrapper.winfo_height(), MIN_WINDOW_HEIGHT - 50)


if __name__ == "__main__":
    unittest.main()
