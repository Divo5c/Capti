"""
Regressionstests Phase 32: realistische & animierte Caption-Style-Vorschau.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import customtkinter as ctk


class Phase32Base(unittest.TestCase):

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

    def _screen(self):
        from ui.app_controller import AppController
        controller = AppController(self.root)
        screen = controller.get_screen("caption_style")
        self.root.update()
        return controller, screen

    def _canvas_texts(self, screen):
        canvas = screen.preview_canvas
        return [canvas.itemcget(i, "fill") for i in canvas.find_all()
                if canvas.type(i) == "text"]


class TestPreviewBasics(Phase32Base):
    """Preview-Grundfunktion + Style-Werte."""

    def test_preview_created_with_sample_text(self):
        _, screen = self._screen()
        self.assertIsInstance(screen.preview_canvas.winfo_children(), list)
        words = [w["text"] for w in screen._preview_words]
        self.assertGreaterEqual(len(words), 6)   # mehrzeiliger Beispielsatz
        # Zwei Zeilen gemäß Renderer-Limit (max_words_per_line)
        ys = sorted({round(w["y"]) for w in screen._preview_words})
        self.assertLessEqual(len(ys), 2)

    def test_uses_renderer_layout_values(self):
        from caption_renderer import CaptionRenderer
        _, screen = self._screen()
        layout = CaptionRenderer.compute_layout(1080, 1920)
        scale = screen._preview_size[1] / 1920
        expected_px = max(12, int(round(layout["font_size"] * scale)))
        self.assertEqual(screen._preview_font.cget("size"), expected_px)
        self.assertEqual(screen._preview_font.cget("family"),
                         screen.style["font_name"])

    def test_color_change_updates_preview(self):
        _, screen = self._screen()
        screen._color_vars["normal_color"].set("#4EC9B0")
        screen._on_color_change("normal_color")
        fills = self._canvas_texts(screen)
        self.assertIn("#4EC9B0", fills)

    def test_highlight_change_updates_preview(self):
        _, screen = self._screen()
        screen._color_vars["highlight_color"].set("#FF3B30")
        screen._on_color_change("highlight_color")
        # Rahmen während des ersten Worts zeichnen -> Highlight sichtbar
        slot = screen._preview_timeline[0]
        screen._draw_preview_frame(slot["start"] + 200)
        self.assertIn("#FF3B30", self._canvas_texts(screen))

    def test_font_change_updates_preview(self):
        _, screen = self._screen()
        screen.style["font_name"] = "Orbitron Medium"
        screen._apply_preview()
        self.assertEqual(screen._preview_font.cget("family"),
                         "Orbitron Medium")


class TestPopAnimation(Phase32Base):
    """Pop-Scale/Decay-Semantik wie im ASS-Renderer."""

    def _timeline(self, screen):
        return screen._preview_timeline

    def test_pop_disabled_no_scale(self):  # Pop aus -> immer 100 %
        _, screen = self._screen()
        screen.style["pop_enabled"] = False
        # Wie im echten UI-Flow (_on_pop_change -> _apply_preview) neu aufbauen,
        # damit der Render-Snapshot den geänderten Style enthält (Block 18).
        screen._rebuild_preview_layout()
        for t in (350, 500, 600, 900):
            active, scale = screen._current_pop_state(t)
            self.assertEqual(scale, 100.0, f"t={t}")

    def test_pop_enabled_scales_up(self):
        _, screen = self._screen()
        screen.style["pop_enabled"] = True
        slot = self._timeline(screen)[0]
        mid_word = slot["start"] + (slot["end"] - slot["start"]) // 2
        active, scale = screen._current_pop_state(mid_word)
        self.assertIsNotNone(active)
        self.assertGreater(scale, 100.0)

    def test_pop_scale_100_means_no_scaling(self):
        _, screen = self._screen()
        screen.style["pop_scale"] = 100
        screen._rebuild_preview_layout()
        slot = self._timeline(screen)[0]
        _, scale = screen._current_pop_state(slot["start"] + 200)
        self.assertEqual(scale, 100.0)

    def test_bigger_pop_scale_gives_bigger_preview_scale(self):
        _, screen = self._screen()
        slot = self._timeline(screen)[0]
        t = slot["end"] - 10   # kurz vor Wortende: nahe Maximalwert
        screen.style["pop_scale"] = 110
        screen._rebuild_preview_layout()
        _, small = screen._current_pop_state(t)
        screen.style["pop_scale"] = 150
        screen._rebuild_preview_layout()
        _, big = screen._current_pop_state(t)
        self.assertGreater(big, small)

    def test_decay_returns_to_100(self):
        _, screen = self._screen()
        screen.style["pop_enabled"] = True
        slot = self._timeline(screen)[0]
        _, scale_end = screen._current_pop_state(
            slot["decay_end"] - 1)     # Decay fast fertig
        self.assertLessEqual(scale_end, 101.0)

    def test_timer_cancels_cleanly(self):
        controller, screen = self._screen()
        self.assertIsNotNone(screen._preview_after_id)
        screen.on_hide()
        self.assertIsNone(screen._preview_after_id)


class TestPreviewLifecycle(Phase32Base):

    def test_on_hide_stops_and_on_show_restarts(self):
        controller, screen = self._screen()
        timer_before = screen._preview_after_id
        screen.on_hide()
        self.assertIsNone(screen._preview_after_id)
        screen.on_show()
        self.root.update()
        self.assertIsNotNone(screen._preview_after_id)
        self.assertNotEqual(screen._preview_after_id, timer_before)
        screen.on_hide()   # aufräumen

    def test_navigation_away_no_tcl_error(self):
        controller, screen = self._screen()
        controller.show_screen("home")
        self.root.update()
        # Kein Crash; Timer beim Wiederkommen neu gestartet
        controller.show_screen("caption_style")
        self.root.update()
        self.assertTrue(controller._screens["caption_style"]
                        ._preview_words)


if __name__ == "__main__":
    unittest.main()