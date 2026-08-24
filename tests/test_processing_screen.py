"""
Tests für den Processing-Screen (Phase 6).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Hermetisch: echte Nutzer-Config niemals lesen/schreiben
import tempfile as _tmp
if "CAPTI_CONFIG_FILE" not in os.environ:
    os.environ["APPDATA"] = _tmp.mkdtemp(prefix="capti_test_appdata_")


import customtkinter as ctk

from ui.app_controller import AppController
from ui.screens.processing import ProcessingScreen, STEPS


class TestProcessingScreen(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        ctk.set_appearance_mode("dark")
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except Exception:
            pass

    def setUp(self):
        self.controller = AppController(self.root)
        self.screen = self.controller.get_screen("processing")

    def test_screen_builds(self):
        self.assertIsInstance(self.screen, ProcessingScreen)
        for attr in ("percent_label", "progress_bar", "status_label",
                     "log_box", "btn_back"):
            self.assertIsNotNone(getattr(self.screen, attr, None))

    def test_progress_updates_display(self):
        self.screen.update_progress(42)
        self.assertEqual(self.screen.percent_label.cget("text"), "42 %")
        self.assertAlmostEqual(self.screen.progress_bar.get(), 0.42)

    def test_progress_clamped(self):
        self.screen.update_progress(150)
        self.assertEqual(self.screen.percent_label.cget("text"), "100 %")
        self.screen.update_progress(-10)
        self.assertEqual(self.screen.percent_label.cget("text"), "0 %")

    def test_status_updatable(self):
        self.screen.update_status("Transkribiere Audio...")
        self.assertEqual(self.screen.status_label.cget("text"), "Transkribiere Audio...")

    def test_log_lines_added(self):
        self.screen.add_log("INFO", "Audio extrahiert")
        content = self.screen.log_box.get("1.0", "end")
        self.assertIn("[INFO] Audio extrahiert", content)

    def test_steps_update_with_progress(self):
        """Progress-Schwellen ordnen Schritte automatisch zu."""
        self.screen.update_progress(30)  # Schritt 2 (Transkription) aktiv (20–40 %)
        self.assertEqual(self.screen._step_states[0], "completed")
        self.assertEqual(self.screen._step_states[1], "active")
        self.assertEqual(self.screen._step_states[2], "pending")

    def test_set_step_explicit(self):
        self.screen.set_step(3, "completed")
        self.assertEqual(self.screen._step_states[3], "completed")
        # Ungültige Werte werden ignoriert
        self.screen.set_step(99, "completed")
        self.screen.set_step(0, "bogus")
        self.assertEqual(self.screen._step_states[0], "pending")

    def test_complete_sets_all_done_and_unlocks(self):
        self.screen.lock_navigation()
        self.screen.complete()
        self.assertEqual(set(self.screen._step_states), {"completed"})
        self.assertEqual(self.screen.percent_label.cget("text"), "100 %")
        self.assertFalse(self.screen._nav_locked)

    def test_error_state_unlocks_navigation(self):
        self.screen.lock_navigation()
        self.screen.show_error("boom")
        self.assertIn("boom", self.screen.error_label.cget("text"))
        self.assertFalse(self.screen._nav_locked)

    def test_nav_lock_blocks_back(self):
        """Nav-Lock aus Phase 3: Zurück gesperrt während Verarbeitung."""
        self.controller.show_screen("processing")
        self.screen.lock_navigation()
        self.screen._go_back()
        self.assertEqual(self.controller.current_screen, "processing")
        self.screen.unlock_navigation()
        self.screen._go_back()
        self.assertEqual(self.controller.current_screen, "home")

    def test_reset_clears_state(self):
        self.screen.update_progress(80)
        self.screen.add_log("INFO", "x")
        self.screen.reset()
        self.assertEqual(self.screen.percent_label.cget("text"), "0 %")
        self.assertEqual(set(self.screen._step_states), {"pending"})
        self.assertEqual(self.screen.log_box.get("1.0", "end").strip(), "")


if __name__ == "__main__":
    unittest.main()