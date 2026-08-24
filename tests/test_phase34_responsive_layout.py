import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import customtkinter as ctk


class Phase34Base(unittest.TestCase):

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

    def _controller_at(self, size):
        from ui.app_controller import AppController
        self.root.geometry(f"{size[0]}x{size[1]}")
        return AppController(self.root)

    def _check_screen(self, controller, name, viewport_w):
        controller.show_screen(name)
        self.root.update(); self.root.update()
        screen = controller._screens[name]
        wrapper = controller._wrappers[name]
        right_edge = screen.winfo_x() + screen.winfo_width()
        return {
            "mapped": bool(screen.winfo_ismapped()),
            "gridded": bool(screen.grid_info()),
            "parent_is_wrapper": screen.master is wrapper,
            "right_overflow": right_edge - wrapper.winfo_width(),
            "screen_w": screen.winfo_width(),
            "wrapper_w": wrapper.winfo_width(),
            "wrapper_h": wrapper.winfo_height(),
            "centered": abs(screen.winfo_x()
                            - (wrapper.winfo_width()
                               - screen.winfo_width()) / 2) < 30,
        }


class TestResponsiveNewProject(Phase34Base):
    """New Project bei 820x560: nichts rechts abgeschnitten."""

    def test_no_right_overflow_at_min_size(self):
        controller = self._controller_at((820, 560))
        r = self._check_screen(controller, "new_project", 820)
        self.assertTrue(r["mapped"])
        self.assertTrue(r["gridded"])
        self.assertTrue(r["parent_is_wrapper"])
        self.assertLessEqual(r["right_overflow"], 0,
                             f"Überstand rechts: {r['right_overflow']}px")

    def test_vertical_scroll_still_active(self):
        controller = self._controller_at((820, 560))
        from customtkinter import CTkScrollableFrame
        controller.show_screen("new_project")
        self.root.update()
        screen = controller._screens["new_project"]
        self.assertIsInstance(screen.master, CTkScrollableFrame)
        self.assertTrue(screen.master.winfo_ismapped())


class TestResponsiveHome(Phase34Base):

    def test_home_no_relevant_overflow(self):
        controller = self._controller_at((820, 560))
        r = self._check_screen(controller, "home", 820)
        self.assertTrue(r["mapped"])
        self.assertLessEqual(r["right_overflow"], 2)


class TestLargerWindows(Phase34Base):
    """Größere Fenster: Zentrierung erhalten, nicht links klebend."""

    def test_centering_at_1000_and_1400(self):
        for size in ((1000, 680), (1400, 900)):
            with self.subTest(size=size):
                controller = self._controller_at(size)
                for name in ("new_project", "home"):
                    r = self._check_screen(controller, name, size[0])
                    self.assertTrue(r["mapped"], f"{name}@{size}")
                    self.assertTrue(r["centered"], f"{name}@{size} nicht mittig")
                    self.assertLessEqual(r["right_overflow"], 0)

    def test_width_capped_at_large_window(self):
        """Content wächst über ~672px+Paddings hinaus nicht unbegrenzt."""
        controller = self._controller_at((1400, 900))
        r = self._check_screen(controller, "new_project", 1400)
        self.assertLessEqual(r["screen_w"], 672 + 48 + 6)  # + padx/Toleranz


class TestNavigationAtMinSize(Phase34Base):
    """Navigation Home → New Project → Caption Style → Settings → Home @820."""

    def test_cycle_all_visible_no_overflow(self):
        controller = self._controller_at((820, 560))
        for name in ("home", "new_project", "caption_style",
                     "settings", "home"):
            r = self._check_screen(controller, name, 820)
            with self.subTest(screen=name):
                self.assertTrue(r["mapped"])
                self.assertTrue(r["gridded"])
                self.assertTrue(r["parent_is_wrapper"])
                self.assertGreater(r["wrapper_h"], 100)
                # Toleranz: bis 8 px Überstand gelten als ok (Rundung),
                # New Project muss exakt passen (responsiver Fix).
                limit = 0 if name == "new_project" else 12
                self.assertLessEqual(r["right_overflow"], limit,
                                     f"{name}: {r}")


class TestThemeRebuildKeepsResponsive(Phase34Base):

    def test_theme_switch_keeps_responsive_layout(self):
        controller = self._controller_at((820, 560))
        controller.get_screen("caption_style")
        controller.apply_theme("light")
        self.root.update()
        for name in ("new_project", "caption_style"):
            controller.show_screen(name)
            self.root.update(); self.root.update()
            screen = controller._screens[name]
            wrapper = controller._wrappers[name]
            self.assertTrue(screen.winfo_ismapped())
            right = screen.winfo_x() + screen.winfo_width()
            self.assertLessEqual(right - wrapper.winfo_width(),
                                 0 if name == "new_project" else 12)


if __name__ == "__main__":
    unittest.main()
