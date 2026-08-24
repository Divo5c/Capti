"""
Regressionstests Phase 19: zentrale UI-Übersetzung (de/en).

Config-Zugriffe laufen über eine temporäre APPDATA-Umgebung,
damit die echte Nutzer-Config nicht berührt wird.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import i18n


class I18nTestBase(unittest.TestCase):
    """Setzt APPDATA auf ein Temp-Verzeichnis und stellt Sprache zurück."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_appdata = os.environ.get("APPDATA")
        os.environ["APPDATA"] = self._tmp.name
        i18n.set_language("de")

    def tearDown(self):
        if self._old_appdata is not None:
            os.environ["APPDATA"] = self._old_appdata
        else:
            os.environ.pop("APPDATA", None)
        self._tmp.cleanup()
        i18n.set_language("de")

    def _config_path(self):
        return os.path.join(self._tmp.name, "Capti", "config.json")

    @staticmethod
    def _visible_texts(widget):
        """Sammelt Texte aller Labels/Buttons (Frames haben kein cget('text'))."""
        import customtkinter as ctk
        texts = []
        for w in widget.winfo_children():
            if isinstance(w, (ctk.CTkLabel, ctk.CTkButton)):
                texts.append(str(w.cget("text")))
        return " ".join(texts)


class TestI18nCore(I18nTestBase):

    def test_german_texts(self):
        i18n.set_language("de")
        self.assertEqual(i18n.t("np.title"), "Neues Projekt")
        self.assertEqual(i18n.t("set.title"), "Einstellungen")
        self.assertEqual(i18n.t("proc.step1"), "Audio extrahieren")

    def test_english_texts(self):
        i18n.set_language("en")
        self.assertEqual(i18n.t("np.title"), "New Project")
        self.assertEqual(i18n.t("set.title"), "Settings")
        self.assertEqual(i18n.t("proc.step1"), "Extract audio")

    def test_unknown_key_falls_back_safely(self):
        i18n.set_language("en")
        self.assertEqual(i18n.t("does.not.exist"), "does.not.exist")

    def test_placeholders(self):
        i18n.set_language("de")
        self.assertEqual(i18n.t("home.greeting", name="Diraj"), "Hallo, Diraj!")
        i18n.set_language("en")
        self.assertEqual(i18n.t("home.greeting", name="Diraj"), "Hello, Diraj!")

    def test_invalid_language_falls_back_to_de(self):
        i18n.set_language("fr")
        self.assertEqual(i18n.get_language(), "de")
        self.assertEqual(i18n.t("np.title"), "Neues Projekt")

    def test_all_keys_present_in_both_languages(self):
        de = set(i18n.TRANSLATIONS["de"])
        en = set(i18n.TRANSLATIONS["en"])
        self.assertEqual(de, en)


class TestI18nConfig(I18nTestBase):

    def test_language_loaded_from_config(self):
        os.makedirs(os.path.dirname(self._config_path()), exist_ok=True)
        with open(self._config_path(), "w", encoding="utf-8") as f:
            json.dump({"language": "en", "name": "Test"}, f)

        from ui.app_controller import _read_config
        config = _read_config()
        self.assertEqual(config.get("language"), "en")
        i18n.set_language(config["language"])
        self.assertEqual(i18n.t("set.title"), "Settings")

    def test_save_preserves_other_keys(self):
        from ui.app_controller import _config_file, _read_config
        os.makedirs(_config_file().parent, exist_ok=True)
        with open(_config_file(), "w", encoding="utf-8") as f:
            json.dump({"name": "Diraj", "theme": "light",
                       "caption_style": {"font_size": 72}, "custom_key": 42}, f)

        # Merge-Speicherung wie in controller.set_language
        from ui import app_controller
        app_controller.i18n.set_language("en")
        config = _read_config()
        config["language"] = "en"
        with open(_config_file(), "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

        saved = _read_config()
        self.assertEqual(saved["name"], "Diraj")
        self.assertEqual(saved["theme"], "light")
        self.assertEqual(saved["caption_style"]["font_size"], 72)
        self.assertEqual(saved["custom_key"], 42)
        self.assertEqual(saved["language"], "en")


class TestScreensBothLanguages(I18nTestBase):
    """Alle Screens bauen ohne Fehler in beiden Sprachen."""

    LANGS = ("de", "en")

    def _build_controller(self, lang="de"):
        import customtkinter as ctk
        from ui.app_controller import AppController
        # Sprache über die Config setzen (Controller lädt sie im Init)
        os.makedirs(os.path.dirname(self._config_path()), exist_ok=True)
        with open(self._config_path(), "w", encoding="utf-8") as f:
            json.dump({"language": lang}, f)
        root = ctk.CTk()
        root.withdraw()
        controller = AppController(root, theme_name="dark")
        return root, controller

    def test_home_both_languages(self):
        for lang in self.LANGS:
            root, ctrl = self._build_controller(lang)
            try:
                home = ctrl.get_screen("home")
                root.update()
                joined = self._visible_texts(home)
                expected = "Hallo" if lang == "de" else "Hello"
                self.assertIn(expected, joined)
            finally:
                root.destroy()

    def test_new_project_both_languages(self):
        for lang in self.LANGS:
            root, ctrl = self._build_controller(lang)
            try:
                np = ctrl.get_screen("new_project")
                root.update()
                title = np.drop_text.cget("text")
                self.assertEqual(title, "Video hierher ziehen" if lang == "de"
                                 else "Drag a video here")
            finally:
                root.destroy()

    def test_processing_both_languages(self):
        for lang in self.LANGS:
            root, ctrl = self._build_controller(lang)
            try:
                proc = ctrl.get_screen("processing")
                root.update()
                first_step = proc._format_step(0)
                expected = "1. Audio extrahieren" if lang == "de" else "1. Extract audio"
                self.assertIn(expected, first_step)
            finally:
                root.destroy()

    def test_result_both_languages(self):
        for lang in self.LANGS:
            root, ctrl = self._build_controller(lang)
            try:
                res = ctrl.get_screen("result")
                root.update()
                res.reset()
                self.assertEqual(res.filename_label.cget("text"),
                                 "Kein Ergebnis vorhanden" if lang == "de"
                                 else "No result available")
            finally:
                root.destroy()

    def test_settings_both_languages(self):
        for lang in self.LANGS:
            root, ctrl = self._build_controller(lang)
            try:
                st = ctrl.get_screen("settings")
                root.update()
                values = list(st.theme_segmented.cget("values"))
                # Phase 27: sichtbare Labels statt roher i18n-Keys
                expected = [i18n.TRANSLATIONS[lang][f"set.theme.{c}"]
                            for c in ("dark", "light", "yellow")]
                self.assertEqual(values, expected)
            finally:
                root.destroy()

    def test_caption_style_both_languages(self):
        for lang in self.LANGS:
            root, ctrl = self._build_controller(lang)
            try:
                cs = ctrl.get_screen("caption_style")
                root.update()
                cs.apply_preset("Clean")
                text = cs.success_label.cget("text")
                self.assertTrue(text.startswith("Preset"))
            finally:
                root.destroy()


class TestLiveLanguageSwitch(I18nTestBase):

    def test_controller_set_language_rebuilds_and_persists(self):
        import customtkinter as ctk
        from ui.app_controller import AppController, _read_config
        # Sprache de in Config schreiben
        os.makedirs(os.path.dirname(self._config_path()), exist_ok=True)
        with open(self._config_path(), "w", encoding="utf-8") as f:
            json.dump({"language": "de", "keep_me": 1}, f)
        root = ctk.CTk()
        root.withdraw()
        try:
            ctrl = AppController(root, theme_name="dark")
            root.update()
            home_de = ctrl.get_screen("home")
            texts_de = self._visible_texts(home_de)
            self.assertIn("Hallo", texts_de)

            # Live-Wechsel nach English (ohne Neustart)
            ctrl.set_language("en")
            root.update()
            home_en = ctrl.get_screen("home")  # neu erstellt
            texts_en = self._visible_texts(home_en)
            self.assertIn("Hello", texts_en)
            self.assertNotIn("Hallo", texts_en)

            # Sprache in Config gespeichert, andere Keys erhalten
            saved = _read_config()
            self.assertEqual(saved.get("language"), "en")
            self.assertEqual(saved.get("keep_me"), 1)

            # Zurück nach Deutsch
            ctrl.set_language("de")
            root.update()
            home_back = ctrl.get_screen("home")
            texts_back = self._visible_texts(home_back)
            self.assertIn("Hallo", texts_back)
        finally:
            root.destroy()


class TestThemesWithI18n(I18nTestBase):

    def test_all_three_themes_build_in_both_languages(self):
        import customtkinter as ctk
        from ui.app_controller import AppController
        for lang in ("de", "en"):
            i18n.set_language(lang)
            os.makedirs(os.path.dirname(self._config_path()), exist_ok=True)
            with open(self._config_path(), "w", encoding="utf-8") as f:
                json.dump({"language": lang}, f)
            for theme in ("dark", "light", "yellow"):
                root = ctk.CTk()
                root.withdraw()
                try:
                    ctrl = AppController(root, theme_name=theme)
                    root.update()
                    for name in ctrl.screen_names:
                        ctrl.get_screen(name)
                    root.update()
                finally:
                    root.destroy()


if __name__ == "__main__":
    unittest.main()