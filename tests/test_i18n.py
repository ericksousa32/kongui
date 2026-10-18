"""Interface language: detection, preference, live switching and coverage.

The interface is written in English and translated to Brazilian Portuguese with
Qt translators (``kongui/gui/translations``). These tests cover:

* which language is chosen for a system locale, and that a saved choice wins;
* the setting: unset is different from a choice, nothing is saved by detection,
  the choice survives a restart;
* the switch with the window open: same page, typed data kept, every part of
  the window changed, later dialogs / notices / pages in the new language;
* fallback to English when a translation (or a file) is missing;
* plurals and number / date formats;
* that the translation files are complete, up to date with the code, compiled,
  and that no Portuguese text is left in the code.
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

from tests.gui_helpers import HAVE_QT, GuiTestCase, WindowCase, pin_language

ROOT = Path(__file__).resolve().parent.parent
GUI_DIR = ROOT / "kongui" / "gui"
TRANSLATIONS = GUI_DIR / "translations"
LANGUAGES = ("en", "pt_BR")


def _gui_sources():
    """Python files of the interface, as ``lupdate`` reads them."""
    return sorted(str(path) for path in GUI_DIR.rglob("*.py"))


def _messages(ts_path: Path):
    """Reads a ``.ts`` file as ``{(context, source): (numerus, forms, type)}``."""
    found = {}
    for context in ET.parse(ts_path).getroot().findall("context"):
        name = context.findtext("name")
        for message in context.findall("message"):
            translation = message.find("translation")
            forms = [
                form.text or "" for form in translation.findall("numerusform")
            ] or [translation.text or ""]
            found[(name, message.findtext("source"))] = (
                message.get("numerus") == "yes",
                forms,
                translation.get("type"),
            )
    return found


def _placeholders(text: str):
    """The ``{name}`` fields and ``%n`` of a message, as a sorted list."""
    return sorted(re.findall(r"\{[a-z_]+\}|%n|%1|%2", text))


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class DetectionTests(unittest.TestCase):
    """Which language a system locale selects."""

    def test_only_brazilian_portuguese_selects_portuguese(self):
        from kongui.gui.i18n import detect_language

        cases = {
            "pt_BR": "pt_BR",
            "pt_BR.UTF-8": "pt_BR",
            "pt_BR@euro": "pt_BR",
            "pt_PT": "en",
            "pt": "en",
            "en_US": "en",
            "en_GB": "en",
            "C": "en",
            "": "en",
            "de_DE": "en",
            "es_ES": "en",
            "ja_JP": "en",
        }
        for locale_name, expected in cases.items():
            with self.subTest(locale=locale_name):
                self.assertEqual(detect_language(locale_name), expected)

    def test_the_system_locale_is_read_when_none_is_given(self):
        from kongui.gui import i18n

        with mock.patch.object(i18n, "system_locale_name", return_value="pt_BR"):
            self.assertEqual(i18n.detect_language(), "pt_BR")
        with mock.patch.object(i18n, "system_locale_name", return_value="fr_FR"):
            self.assertEqual(i18n.detect_language(), "en")

    def test_a_saved_choice_always_wins_over_the_system(self):
        from kongui.gui import i18n

        with mock.patch.object(i18n, "system_locale_name", return_value="pt_BR"):
            self.assertEqual(i18n.effective_language("en"), "en")
            self.assertEqual(i18n.effective_language(""), "pt_BR")
        with mock.patch.object(i18n, "system_locale_name", return_value="en_US"):
            self.assertEqual(i18n.effective_language("pt_BR"), "pt_BR")
            self.assertEqual(i18n.effective_language(""), "en")

    def test_an_invalid_saved_value_counts_as_no_choice(self):
        from kongui.gui import i18n

        for value in ("fr", "PT_BR", "pt", "english", None, 3):
            with self.subTest(value=value):
                self.assertEqual(i18n.normalize_preference(value), "")
        with mock.patch.object(i18n, "system_locale_name", return_value="pt_BR"):
            self.assertEqual(i18n.effective_language("klingon"), "pt_BR")

    def test_the_selector_names_are_written_in_their_own_language(self):
        from kongui.gui.i18n import SUPPORTED

        self.assertEqual(SUPPORTED, {"en": "English", "pt_BR": "Português (Brasil)"})


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class PreferenceTests(GuiTestCase):
    """The ``language`` setting."""

    def setUp(self):
        super().setUp()
        self.ini = os.path.join(self.home, "settings", "kongui-gui.ini")
        os.makedirs(os.path.dirname(self.ini))

    def read_ini(self) -> str:
        return (
            Path(self.ini).read_text(encoding="utf-8")
            if os.path.exists(self.ini)
            else ""
        )

    def test_no_preference_is_the_default_and_is_not_a_language(self):
        from kongui.gui.state import AppSettings

        self.assertEqual(AppSettings().get("language"), "")
        self.assertEqual(AppSettings(self.ini).get("language"), "")

    def test_an_explicit_choice_is_saved_and_read_back(self):
        from kongui.gui.state import AppSettings

        for choice in ("en", "pt_BR"):
            with self.subTest(choice=choice):
                AppSettings(self.ini).set("language", choice)
                self.assertEqual(AppSettings(self.ini).get("language"), choice)
                self.assertIn(f"language={choice}", self.read_ini())

    def test_an_invalid_value_is_stored_as_no_preference(self):
        from kongui.gui.state import AppSettings

        settings = AppSettings(self.ini)
        settings.set("language", "pt_BR")
        settings.set("language", "xx")
        self.assertEqual(settings.get("language"), "")
        Path(self.ini).write_text("[General]\nlanguage=zz\n", encoding="utf-8")
        self.assertEqual(AppSettings(self.ini).get("language"), "")

    def test_a_change_is_announced_like_any_other_setting(self):
        from kongui.gui.state import AppSettings

        settings = AppSettings()
        keys = []
        settings.changed.connect(keys.append)
        settings.set("language", "en")
        settings.set("language", "en")
        settings.set("language", "pt_BR")
        self.assertEqual(keys, ["language", "language"])

    def test_detecting_a_language_never_writes_it(self):
        from kongui.gui.state import AppSettings

        settings = AppSettings(self.ini)
        window = self.make_window(settings=settings)
        self.assertEqual(window.language.language, "pt_BR")
        self.assertEqual(settings.get("language"), "")
        self.assertNotIn("language", self.read_ini())
        self.assertEqual(AppSettings(self.ini).get("language"), "")

    def test_the_preference_of_the_user_is_not_overwritten_by_the_system(self):
        from kongui.gui.state import AppSettings

        AppSettings(self.ini).set("language", "en")
        settings = AppSettings(self.ini)
        window = self.make_window(settings=settings)  # the system says pt_BR
        self.assertEqual(window.language.language, "en")
        self.assertEqual(settings.get("language"), "en")
        self.assertIn("language=en", self.read_ini())
        self.assertEqual(window.sidebar.button("profiles").text(), "Profiles")


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class FirstRunTests(GuiTestCase):
    """The language of a window opened with no saved choice."""

    def window_for(self, locale_name: str, preference: str = ""):
        from kongui.gui import i18n
        from kongui.gui.state import AppSettings

        settings = AppSettings()
        settings.set("language", preference)
        with mock.patch.object(i18n, "system_locale_name", return_value=locale_name):
            return self.make_window(settings=settings)

    def test_brazilian_portuguese_system_gets_portuguese(self):
        window = self.window_for("pt_BR")
        self.assertEqual(window.sidebar.button("profiles").text(), "Perfis")
        self.assertEqual(window.top_bar.title_label.text(), "Dashboard")
        self.assertEqual(window.top_bar.subtitle_label.text()[:9], "Visão ger")

    def test_every_other_locale_gets_english(self):
        for locale_name in ("en_US", "pt_PT", "pt", "de_DE", "C", "fr_FR"):
            with self.subTest(locale=locale_name):
                window = self.window_for(locale_name)
                self.assertEqual(window.sidebar.button("profiles").text(), "Profiles")
                self.assertEqual(
                    window.top_bar.subtitle_label.text(),
                    "Overview of your customization profiles",
                )
                self.destroy_window(window)

    def test_a_manual_english_choice_beats_a_portuguese_system(self):
        window = self.window_for("pt_BR", preference="en")
        self.assertEqual(window.sidebar.button("settings").text(), "Settings")

    def test_a_manual_portuguese_choice_beats_an_english_system(self):
        window = self.window_for("en_US", preference="pt_BR")
        self.assertEqual(window.sidebar.button("settings").text(), "Configurações")

    def test_the_system_locale_is_not_pinned_by_a_previous_window(self):
        first = self.window_for("pt_BR")
        self.assertEqual(first.sidebar.button("about").text(), "Sobre")
        self.destroy_window(first)
        second = self.window_for("en_US")
        self.assertEqual(second.sidebar.button("about").text(), "About")


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class RestartTests(GuiTestCase):
    """The choice survives closing and opening the program again."""

    LANGUAGE = "en_US"

    def test_the_chosen_language_is_used_by_the_next_window(self):
        from kongui.gui import i18n
        from kongui.gui.state import AppSettings

        ini = os.path.join(self.home, "kongui-gui.ini")
        first = self.make_window(settings=AppSettings(ini))
        self.assertEqual(first.sidebar.button("profiles").text(), "Profiles")
        first.pages["settings"].language_control.button("pt_BR").click()
        self.flush()
        self.assertEqual(first.sidebar.button("profiles").text(), "Perfis")
        self.destroy_window(first)
        i18n.manager().uninstall()  # as if the process had ended

        second = self.make_window(settings=AppSettings(ini))
        self.assertEqual(second.language.language, "pt_BR")
        self.assertEqual(second.sidebar.button("profiles").text(), "Perfis")
        self.assertEqual(AppSettings(ini).get("language"), "pt_BR")

    def test_the_choice_can_go_back_to_english_and_stays(self):
        from kongui.gui import i18n
        from kongui.gui.state import AppSettings

        ini = os.path.join(self.home, "kongui-gui.ini")
        window = self.make_window(settings=AppSettings(ini))
        page = window.pages["settings"]
        page.language_control.button("pt_BR").click()
        page.language_control.button("en").click()
        self.destroy_window(window)
        i18n.manager().uninstall()
        reopened = self.make_window(settings=AppSettings(ini))
        self.assertEqual(reopened.sidebar.button("profiles").text(), "Profiles")
        self.assertEqual(AppSettings(ini).get("language"), "en")

    def test_clicking_the_language_already_in_use_saves_it_as_a_choice(self):
        from kongui.gui.state import AppSettings

        ini = os.path.join(self.home, "kongui-gui.ini")
        settings = AppSettings(ini)
        window = self.make_window(settings=settings)
        self.assertEqual(settings.get("language"), "")
        window.pages["settings"].language_control.button("en").click()
        self.assertEqual(settings.get("language"), "en")


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class LiveSwitchTests(WindowCase):
    """Changing the language with the window open."""

    LANGUAGE = "en_US"

    def switch(self, language: str) -> None:
        self.window.settings.set("language", language)
        self.flush()

    def test_the_whole_window_changes_without_a_restart(self):
        window = self.open_window()
        titles = {
            "profiles": ("Profiles", "Perfis"),
            "settings": ("Settings", "Configurações"),
            "about": ("About", "Sobre"),
        }
        for key, (english, _portuguese) in titles.items():
            self.assertEqual(window.sidebar.button(key).text(), english)
        self.switch("pt_BR")
        for key, (_english, portuguese) in titles.items():
            with self.subTest(page=key):
                self.assertEqual(window.sidebar.button(key).text(), portuguese)
                self.assertEqual(
                    window.sidebar.button(key).accessibleName(), portuguese
                )
                self.assertIn(portuguese, window.sidebar.button(key).toolTip())
        self.switch("en")
        self.assertEqual(window.sidebar.button("profiles").text(), "Profiles")

    def test_the_current_page_is_kept_and_its_top_bar_follows(self):
        window = self.open_window(page="settings")
        self.assertEqual(window.sidebar.current_key(), "settings")
        self.assertEqual(window.top_bar.title_label.text(), "Settings")
        self.switch("pt_BR")
        self.assertEqual(window.sidebar.current_key(), "settings")
        self.assertEqual(window.top_bar.title_label.text(), "Configurações")
        self.assertNotEqual(window.top_bar.subtitle_label.text(), "")
        self.switch("en")
        self.assertEqual(window.top_bar.title_label.text(), "Settings")

    def test_the_top_bar_buttons_of_the_page_follow(self):
        window = self.open_window(page="profiles")
        before = [button.text() for button in window.top_bar.actions()]
        self.assertTrue(before)
        self.switch("pt_BR")
        after = [button.text() for button in window.top_bar.actions()]
        self.assertEqual(len(after), len(before))
        self.assertNotEqual(after, before)

    def test_typed_data_is_kept(self):
        window = self.open_window(page="transfer")
        page = window.pages["transfer"]
        page.filename_edit.setText("my-backup")
        page.destination_edit.setText("/tmp/somewhere")
        before = page.export_button.text()
        self.switch("pt_BR")
        self.assertEqual(window.sidebar.current_key(), "transfer")
        self.assertEqual(page.filename_edit.text(), "my-backup")
        self.assertEqual(page.destination_edit.text(), "/tmp/somewhere")
        self.assertNotEqual(page.export_button.text(), before)
        self.assertIn("/tmp/somewhere/my-backup.knsv", page.preview_label.text())

    def test_the_search_text_and_sort_of_the_profiles_page_are_kept(self):
        window = self.open_window(page="profiles")
        page = window.pages["profiles"]
        page.search.setText("gam")
        page.sort_combo.setCurrentIndex(1)
        self.flush()
        placeholder = page.search.placeholderText()
        self.switch("pt_BR")
        self.assertEqual(page.search.text(), "gam")
        self.assertEqual(page.sort_combo.currentIndex(), 1)
        self.assertNotEqual(page.search.placeholderText(), placeholder)
        self.assertEqual(len(self.names(page)), 1)

    def test_the_yaml_editor_keeps_its_text(self):
        from kongui.gui.widgets.dialogs import ConfirmDialog

        # Closing a window with unsaved edits asks first; answer "leave".
        patcher = mock.patch.object(ConfirmDialog, "ask", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        window = self.open_window(page="config")
        page = window.pages["config"]
        self.run_all()
        page.text_edit.setPlainText("save: {}\nexport: {}\n# my note\n")
        self.flush()
        save_text = page.save_button.text()
        self.switch("pt_BR")
        self.assertEqual(
            page.text_edit.toPlainText(), "save: {}\nexport: {}\n# my note\n"
        )
        self.assertNotEqual(page.save_button.text(), save_text)

    def test_profile_cards_follow(self):
        window = self.open_window(page="profiles")
        page = window.pages["profiles"]
        cards = len(page.cards())
        before = page.count_label.text()
        self.switch("pt_BR")
        self.assertEqual(len(page.cards()), cards)
        self.assertNotEqual(page.count_label.text(), before)
        self.assertEqual(page.count_label.text().split()[0], before.split()[0])

    def test_the_language_selector_shows_the_language_in_use(self):
        window = self.open_window(page="settings")
        control = window.pages["settings"].language_control
        self.assertEqual(control.value(), "en")
        self.switch("pt_BR")
        self.assertEqual(control.value(), "pt_BR")
        # The names are never translated.
        self.assertEqual(control.button("en").text(), "English")
        self.assertEqual(control.button("pt_BR").text(), "Português (Brasil)")

    def test_clicking_the_selector_switches_the_window(self):
        window = self.open_window(page="settings")
        control = window.pages["settings"].language_control
        control.button("pt_BR").click()
        self.flush()
        self.assertEqual(window.settings.get("language"), "pt_BR")
        self.assertEqual(window.top_bar.title_label.text(), "Configurações")
        control.button("en").click()
        self.flush()
        self.assertEqual(window.settings.get("language"), "en")
        self.assertEqual(window.top_bar.title_label.text(), "Settings")

    def test_unrelated_settings_do_not_touch_the_language(self):
        window = self.open_window(page="settings")
        window.settings.set("toast_seconds", 9)
        self.assertEqual(window.language.language, "en")
        self.assertEqual(window.settings.get("language"), "")


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class LaterComponentsTests(WindowCase):
    """Things created after a switch use the new language."""

    LANGUAGE = "en_US"

    def switch(self, language: str) -> None:
        self.window.settings.set("language", language)
        self.flush()

    def test_dialogs_opened_after_the_switch(self):
        from kongui.gui.widgets.dialogs import (
            ConfirmDialog,
            GroupNameDialog,
            ProfileDialog,
        )

        window = self.open_window()
        english = (
            ConfirmDialog(window, "T", "M").cancel_button.text(),
            ProfileDialog(window, [], ["Fonts"]).windowTitle(),
            GroupNameDialog(window, []).windowTitle(),
        )
        self.switch("pt_BR")
        portuguese = (
            ConfirmDialog(window, "T", "M").cancel_button.text(),
            ProfileDialog(window, [], ["Fonts"]).windowTitle(),
            GroupNameDialog(window, []).windowTitle(),
        )
        self.assertEqual(portuguese[0], "Cancelar")
        for first, second in zip(english, portuguese):
            self.assertNotEqual(first, second)
        self.switch("en")
        self.assertEqual(ConfirmDialog(window, "T", "M").cancel_button.text(), "Cancel")

    def test_confirmation_dialogs_of_the_actions_use_the_current_language(self):
        from kongui.gui.actions import ProfileActions, wipe_word
        from kongui.gui.widgets.dialogs import ConfirmDialog

        window = self.open_window()
        seen = []

        def fake_ask(_parent, title, message, confirm_text="", **kwargs):
            seen.append((title, message, confirm_text, kwargs.get("require_text")))
            return False

        with mock.patch.object(ConfirmDialog, "ask", side_effect=fake_ask):
            actions = ProfileActions(window.context)
            actions.apply(window, "Gaming")
            actions.wipe_all(window)
            self.switch("pt_BR")
            actions.apply(window, "Gaming")
            actions.wipe_all(window)
        self.assertEqual(seen[0][0], "Apply “Gaming”?")
        self.assertEqual(seen[0][2], "Apply")
        self.assertIn("(Prototype: nothing will be changed.)", seen[0][1])
        self.assertEqual(seen[1][3], "DELETE")
        self.assertEqual(seen[2][0], "Aplicar “Gaming”?")
        self.assertEqual(seen[2][2], "Aplicar")
        self.assertIn("(Protótipo: nada será alterado.)", seen[2][1])
        self.assertEqual(seen[3][3], wipe_word())
        self.assertNotEqual(seen[3][3], "DELETE")

    def test_notices_after_an_operation(self):
        window = self.open_window()
        window.controller.apply("Gaming", confirmed=True)
        self.run_all()
        self.assertEqual(window.toasts.titles()[-1], "Profile “Gaming” applied")
        window.toasts.dismiss_all()
        self.switch("pt_BR")
        window.controller.apply("Tablet", confirmed=True)
        self.run_all()
        self.assertEqual(window.toasts.titles()[-1], "Perfil “Tablet” aplicado")

    def test_errors_use_the_current_language(self):
        window = self.open_window()
        window.controller.apply("Nope", confirmed=True)
        self.run_all()
        english = self.outcomes[-1]
        self.assertFalse(english.ok)
        self.assertEqual(english.title, "Could not apply profile “Nope”")
        self.switch("pt_BR")
        window.controller.apply("Nope", confirmed=True)
        self.run_all()
        portuguese = self.outcomes[-1]
        self.assertEqual(portuguese.title, "Não foi possível aplicar o perfil “Nope”")
        self.assertNotEqual(english.details, portuguese.details)

    def test_cards_created_after_the_switch(self):
        window = self.open_window(page="profiles")
        window.settings.set("language", "pt_BR")
        self.flush()
        window.controller.refresh()
        self.run_all()
        texts = set()
        for card in window.pages["profiles"].cards():
            texts |= _walk_texts(card)
        self.assertIn("Aplicar", texts)
        self.assertNotIn("Apply", texts)

    def test_demo_data_is_always_english(self):
        from kongui.gui.backend import FakeBackend
        from kongui.gui.mock_data import demo_activity, sections

        def snapshot():
            profiles = FakeBackend().list_profiles()
            return (
                [(p.name, p.description, tuple(p.sections)) for p in profiles],
                list(sections()),
                [entry.text for entry in demo_activity()],
            )

        english = snapshot()
        self.assertIn("Work", [name for name, _, _ in english[0]])
        pin_language(self, "pt_BR")
        self.assertEqual(snapshot(), english)


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class FallbackTests(GuiTestCase):
    """A missing translation, or a missing file, falls back to English."""

    LANGUAGE = "en_US"

    def make_catalog(self, source: str, folder: str, with_pt: bool = True):
        """Writes a tiny pt_BR catalog with one translated message."""
        ts = os.path.join(folder, "kongui_pt_BR.ts")
        Path(ts).write_text(
            '<?xml version="1.0" encoding="utf-8"?><!DOCTYPE TS><TS version="2.1" '
            'language="pt_BR"><context><name>Probe</name><message><source>Hello'
            "</source><translation>Olá</translation></message></context></TS>",
            encoding="utf-8",
        )
        if with_pt:
            subprocess.run(
                ["pyside6-lrelease", ts, "-qm", ts[:-3] + ".qm"],
                check=True,
                capture_output=True,
            )

    def test_an_untranslated_message_shows_its_english_source(self):
        from PySide6.QtCore import QCoreApplication

        from kongui.gui import i18n

        if shutil.which("pyside6-lrelease") is None:
            self.skipTest("pyside6-lrelease is not installed")
        folder = tempfile.mkdtemp(prefix="kongui-i18n-")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        self.make_catalog("Hello", folder)
        with mock.patch.object(i18n, "TRANSLATIONS_DIR", folder):
            i18n.manager().install("pt_BR")
            self.assertEqual(QCoreApplication.translate("Probe", "Hello"), "Olá")
            self.assertEqual(QCoreApplication.translate("Probe", "Goodbye"), "Goodbye")
            self.assertEqual(QCoreApplication.translate("Other", "Hello"), "Hello")

    def test_a_missing_catalog_file_falls_back_without_failing(self):
        from kongui.gui import i18n

        folder = tempfile.mkdtemp(prefix="kongui-i18n-")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        with mock.patch.object(i18n, "TRANSLATIONS_DIR", folder):
            self.assertEqual(i18n.manager().install("pt_BR"), "pt_BR")
            window = self.make_window()
            self.assertEqual(window.sidebar.button("profiles").text(), "Profiles")
            self.assertEqual(window.top_bar.title_label.text(), "Dashboard")

    def test_an_unreadable_catalog_file_falls_back_without_failing(self):
        from kongui.gui import i18n

        folder = tempfile.mkdtemp(prefix="kongui-i18n-")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        Path(folder, "kongui_pt_BR.qm").write_bytes(b"not a catalog")
        with mock.patch.object(i18n, "TRANSLATIONS_DIR", folder):
            i18n.manager().install("pt_BR")
            window = self.make_window()
            self.assertEqual(window.sidebar.button("settings").text(), "Settings")

    def test_an_unknown_language_is_english(self):
        from kongui.gui import i18n

        self.assertEqual(i18n.manager().install("tlh"), "en")
        self.assertEqual(i18n.manager().language, "en")
        window = self.make_window()
        self.assertEqual(window.sidebar.button("about").text(), "About")

    def test_the_manager_announces_a_change_once_per_change(self):
        from kongui.gui import i18n

        seen = []
        manager = i18n.manager()
        manager.language_changed.connect(seen.append)
        self.addCleanup(manager.language_changed.disconnect, seen.append)
        manager.install("pt_BR")
        manager.install("pt_BR")
        manager.install("en")
        self.assertEqual(seen, ["pt_BR", "en"])

    def test_text_that_is_a_function_is_evaluated_again(self):
        from kongui.gui import i18n
        from kongui.gui.widgets.common import Badge, Button, Label

        calls = []

        def make(text: str):
            def current():
                calls.append(text)
                return f"{text}-{i18n.current()}"

            return current

        label, badge = Label(make("a")), Badge(make("b"))
        button = Button(make("c"), tooltip=make("d"))
        self.assertEqual(
            (label.text(), badge.text(), button.text(), button.toolTip()),
            ("a-en", "b-en", "c-en", "d-en"),
        )
        i18n.manager().install("pt_BR")
        self.assertEqual(
            (label.text(), badge.text(), button.text(), button.toolTip()),
            ("a-pt_BR", "b-pt_BR", "c-pt_BR", "d-pt_BR"),
        )
        self.assertEqual(Label("plain").text(), "plain")


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class FormatTests(GuiTestCase):
    """Plurals, numbers and dates in each language."""

    LANGUAGE = "en_US"

    def test_plurals(self):
        from PySide6.QtCore import QCoreApplication

        from kongui.gui import i18n

        def count(n):
            return QCoreApplication.translate("ProfilesPage", "%n profile(s)", "", n)

        i18n.manager().install("en")
        self.assertEqual(
            [count(n) for n in (0, 1, 2, 7)],
            ["0 profiles", "1 profile", "2 profiles", "7 profiles"],
        )
        i18n.manager().install("pt_BR")
        # Portuguese (Brazil) treats 0 as singular, like Qt / CLDR.
        self.assertEqual(
            [count(n) for n in (0, 1, 2, 7)],
            ["0 perfil", "1 perfil", "2 perfis", "7 perfis"],
        )

    def test_sizes_use_the_decimal_separator_of_the_language(self):
        from kongui.gui import i18n
        from kongui.gui.formatting import format_kib, format_size

        i18n.manager().install("en")
        self.assertEqual(
            (
                format_size(48.24),
                format_size(0),
                format_size(1536),
                format_size(1000),
                format_kib(1536),
            ),
            ("48.2 MB", "0.0 MB", "1.5 GB", "1000.0 MB", "1.5 KB"),
        )
        i18n.manager().install("pt_BR")
        self.assertEqual(
            (
                format_size(48.24),
                format_size(0),
                format_size(1536),
                format_size(1000),
                format_kib(1536),
            ),
            ("48,2 MB", "0,0 MB", "1,5 GB", "1000,0 MB", "1,5 KB"),
        )

    def test_dates(self):
        from datetime import datetime, timedelta

        from kongui.gui import i18n
        from kongui.gui.formatting import format_date, format_datetime, format_relative

        now = datetime(2026, 10, 16, 12, 0)
        moment = datetime(2024, 3, 2, 14, 5, 9)
        i18n.manager().install("en")
        self.assertEqual(format_date(moment), "Mar 2, 2024")
        self.assertEqual(format_datetime(moment), "2024-03-02 14:05:09")
        self.assertEqual(
            [format_relative(now - timedelta(days=d), now) for d in (0, 1, 5, 45, 200)],
            ["today", "yesterday", "5 days ago", "1 month ago", "6 months ago"],
        )
        i18n.manager().install("pt_BR")
        self.assertEqual(format_date(moment), "2 mar 2024")
        self.assertEqual(format_datetime(moment), "02/03/2024 14:05:09")
        self.assertEqual(
            [format_relative(now - timedelta(days=d), now) for d in (0, 1, 5, 45, 200)],
            ["hoje", "ontem", "há 5 dias", "há 1 mês", "há 6 meses"],
        )


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class MessageTests(GuiTestCase):
    """The text tables of ``messages.py`` in both languages."""

    LANGUAGE = "en_US"

    def test_known_texts_in_both_languages(self):
        from kongui.core import ProfileExistsError, ProfileNotFoundError
        from kongui.gui import i18n, messages

        i18n.manager().install("en")
        self.assertEqual(messages.success_title("save", "A"), "Profile “A” saved")
        self.assertEqual(
            messages.failure_title("remove", "A"), "Could not remove profile “A”"
        )
        self.assertEqual(
            messages.failure_title("save_config", "A"), "Could not save conf.yaml"
        )
        self.assertEqual(
            messages.failure_title("nope", ""), "Could not complete the operation"
        )
        self.assertIn(
            "already exists", messages.describe_error(ProfileExistsError("x"))[0]
        )
        self.assertEqual(
            messages.outcome_hint("apply", True),
            "Log out and back in to see all the changes.",
        )
        i18n.manager().install("pt_BR")
        self.assertEqual(messages.success_title("save", "A"), "Perfil “A” salvo")
        self.assertEqual(
            messages.failure_title("remove", "A"),
            "Não foi possível remover o perfil “A”",
        )
        self.assertEqual(
            messages.failure_title("save_config", "A"),
            "Não foi possível salvar o conf.yaml",
        )
        self.assertIn(
            "não existe mais", messages.describe_error(ProfileNotFoundError("x"))[0]
        )
        self.assertEqual(
            messages.outcome_hint("apply", True),
            "Saia e entre na sessão para ver todas as mudanças.",
        )

    def test_every_table_entry_has_a_portuguese_translation(self):
        from PySide6.QtCore import QCoreApplication

        from kongui.gui import i18n, messages

        i18n.manager().install("pt_BR")
        tables = [
            messages.SUCCESS,
            messages.SUCCESS_HINT,
            messages.FAILURE_TITLES,
            messages.FAILURE_TITLES_WITH_NAME,
            messages.PROBLEM_TEXTS,
            dict(messages._VALIDATION_TEXTS),  # pylint: disable=protected-access
        ]
        for table in tables:
            for source in table.values():
                with self.subTest(source=source[:50]):
                    self.assertNotEqual(
                        QCoreApplication.translate("messages", source), source
                    )

    def test_problem_texts_and_positions(self):
        from kongui.core import Problem
        from kongui.gui import i18n, messages

        problem = Problem(
            "error",
            "missing-top-key",
            ("export",),
            "x",
            line=3,
            column=2,
            args={"key": "export"},
        )
        i18n.manager().install("en")
        self.assertEqual(messages.problem_place(problem), "line 3, column 2 · export")
        self.assertIn("The “export” section is missing", messages.problem_text(problem))
        self.assertIn("“export: {}”", messages.problem_text(problem))
        i18n.manager().install("pt_BR")
        self.assertEqual(messages.problem_place(problem), "linha 3, coluna 2 · export")
        self.assertIn("Falta a seção “export”", messages.problem_text(problem))

    def test_validation_messages(self):
        from kongui.gui import i18n
        from kongui.gui.validation import group_name_problem, profile_name_problem

        i18n.manager().install("en")
        self.assertEqual(profile_name_problem(" "), "Enter a name for the profile.")
        self.assertEqual(
            profile_name_problem("a", ["a"]), "A profile with that name already exists."
        )
        self.assertEqual(group_name_problem("a/b").split(".")[0], "Invalid name")
        i18n.manager().install("pt_BR")
        self.assertEqual(profile_name_problem(" "), "Informe um nome para o perfil.")
        self.assertEqual(
            profile_name_problem("a", ["a"]), "Já existe um perfil com esse nome."
        )

    def test_core_warnings_are_translated_and_unknown_ones_kept(self):
        from kongui.core import KEPT_PREFIX
        from kongui.gui import i18n, messages

        line = f"{KEPT_PREFIX}20260101-000000"
        i18n.manager().install("en")
        self.assertEqual(
            messages.describe_warning(line),
            "Safety copy stored (20260101-000000). To undo, use Settings → Safety copies.",
        )
        self.assertEqual(messages.describe_note("odd text"), "Warning: odd text")
        i18n.manager().install("pt_BR")
        self.assertTrue(
            messages.describe_warning(line).startswith("Cópia de segurança guardada")
        )
        self.assertEqual(messages.describe_note("odd text"), "Aviso: odd text")
        self.assertEqual(messages.describe_warning("odd text"), "odd text")


def _walk_texts(root):
    """Every text a user can read in the widgets under ``root``."""
    from PySide6.QtWidgets import (
        QAbstractButton,
        QCheckBox,
        QComboBox,
        QLabel,
        QLineEdit,
        QPlainTextEdit,
        QWidget,
    )

    found = set()
    for widget in [root, *root.findChildren(QWidget)]:
        for getter in ("toolTip", "accessibleName", "windowTitle"):
            text = getattr(widget, getter)()
            if text:
                found.add(text)
    for kind in (QLabel, QAbstractButton, QCheckBox):
        for widget in root.findChildren(kind):
            if widget.text():
                found.add(widget.text())
    for combo in root.findChildren(QComboBox):
        found.update(combo.itemText(i) for i in range(combo.count()))
    for edit in root.findChildren(QLineEdit):
        if edit.placeholderText():
            found.add(edit.placeholderText())
    for edit in root.findChildren(QPlainTextEdit):
        if edit.placeholderText():
            found.add(edit.placeholderText())
    return found


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class WholeInterfaceTests(WindowCase):
    """Walks every page: nothing is left in the other language."""

    LANGUAGE = "en_US"

    @staticmethod
    def catalog(language: str):
        """``{source: translation}`` of finished, different messages."""
        pairs = {}
        for (_ctx, source), (numerus, forms, kind) in _messages(
            TRANSLATIONS / f"kongui_{language}.ts"
        ).items():
            if kind or numerus:
                continue
            pairs[source] = forms[0]
        return pairs

    def visit_everything(self, window):
        texts = set()
        for key in window.pages:
            window.show_page(key)
            self.run_all()
            self.flush()
            texts |= _walk_texts(window)
            texts |= _walk_texts(window.pages[key])
        return texts

    maxDiff = None

    def demo_data(self, window):
        """Texts that are data of the fictitious profiles, not interface text.

        They are always English, whatever the interface language (documented in
        docs/GUI_PROTOTYPE.md).
        """
        from kongui.gui.mock_data import sections

        found = set(sections())
        for profile in window.backend.list_profiles():
            found.add(profile.name)
            found.add(profile.description)
            found.update(profile.sections)
        return found

    def test_nothing_stays_untranslated_in_portuguese(self):
        window = self.open_window()
        demo = self.demo_data(window)
        window.settings.set("language", "pt_BR")
        self.flush()
        translations = self.catalog("pt_BR")
        english_only = {
            source
            for source, translated in translations.items()
            if translated != source and len(source) > 3
        }
        leaked = sorted((self.visit_everything(window) & english_only) - demo)
        self.assertEqual(leaked, [], "English text shown in the Portuguese interface")

    def test_nothing_is_left_in_portuguese_in_english(self):
        window = self.open_window()
        translations = self.catalog("pt_BR")
        portuguese = {
            translated
            for source, translated in translations.items()
            if translated != source and len(translated) > 3
        }
        leaked = sorted(self.visit_everything(window) & portuguese)
        self.assertEqual(leaked, [], "Portuguese text shown in the English interface")

    def test_switching_back_and_forth_leaves_no_mixed_text(self):
        window = self.open_window()
        self.visit_everything(window)  # lets every page finish loading
        english = self.visit_everything(window)
        for language in ("pt_BR", "en", "pt_BR", "en"):
            window.settings.set("language", language)
            self.flush()
        self.assertEqual(self.visit_everything(window), english)


class TranslationFilesTests(unittest.TestCase):
    """The ``.ts`` / ``.qm`` files that ship with the interface."""

    def test_every_language_has_its_files(self):
        for language in LANGUAGES:
            with self.subTest(language=language):
                self.assertTrue((TRANSLATIONS / f"kongui_{language}.ts").is_file())
                self.assertTrue((TRANSLATIONS / f"kongui_{language}.qm").is_file())

    def test_every_message_is_finished(self):
        for language in LANGUAGES:
            for key, (_numerus, forms, kind) in _messages(
                TRANSLATIONS / f"kongui_{language}.ts"
            ).items():
                with self.subTest(language=language, message=key[1][:40]):
                    self.assertIsNone(kind, f"{language}: {key} is {kind}")
                    self.assertTrue(all(form for form in forms), f"{language}: {key}")

    def test_numerus_messages_have_both_forms(self):
        for language in LANGUAGES:
            for key, (numerus, forms, _kind) in _messages(
                TRANSLATIONS / f"kongui_{language}.ts"
            ).items():
                if numerus:
                    with self.subTest(language=language, message=key[1][:40]):
                        self.assertEqual(len(forms), 2)
                        for form in forms:
                            self.assertIn("%n", form)

    def test_translations_keep_the_placeholders_of_the_source(self):
        for language in LANGUAGES:
            for (_ctx, source), (_numerus, forms, _kind) in _messages(
                TRANSLATIONS / f"kongui_{language}.ts"
            ).items():
                for form in forms:
                    with self.subTest(language=language, message=source[:40]):
                        self.assertEqual(_placeholders(form), _placeholders(source))

    def test_english_is_the_source_text(self):
        for (_ctx, source), (numerus, forms, _kind) in _messages(
            TRANSLATIONS / "kongui_en.ts"
        ).items():
            if not numerus:
                with self.subTest(message=source[:40]):
                    self.assertEqual(forms[0], source)

    def test_both_languages_hold_the_same_messages(self):
        english = set(_messages(TRANSLATIONS / "kongui_en.ts"))
        portuguese = set(_messages(TRANSLATIONS / "kongui_pt_BR.ts"))
        self.assertEqual(english ^ portuguese, set())

    @unittest.skipUnless(
        shutil.which("pyside6-lupdate"), "pyside6-lupdate is not installed"
    )
    def test_the_ts_files_hold_every_text_of_the_code(self):
        """Running ``lupdate`` again must find nothing new and nothing gone."""
        for language in LANGUAGES:
            with self.subTest(language=language):
                folder = tempfile.mkdtemp(prefix="kongui-lupdate-")
                self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
                copy = Path(folder, f"kongui_{language}.ts")
                shutil.copy(TRANSLATIONS / f"kongui_{language}.ts", copy)
                subprocess.run(
                    [
                        "pyside6-lupdate",
                        *_gui_sources(),
                        "-ts",
                        str(copy),
                        "-no-obsolete",
                        "-locations",
                        "none",
                    ],
                    check=True,
                    capture_output=True,
                    cwd=ROOT,
                )
                self.assertEqual(
                    set(_messages(copy)),
                    set(_messages(TRANSLATIONS / f"kongui_{language}.ts")),
                    "kongui/gui/translations is out of date: run `make translations`",
                )

    @unittest.skipUnless(
        shutil.which("pyside6-lrelease"), "pyside6-lrelease is not installed"
    )
    def test_the_compiled_files_are_up_to_date(self):
        for language in LANGUAGES:
            with self.subTest(language=language):
                folder = tempfile.mkdtemp(prefix="kongui-lrelease-")
                self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
                built = Path(folder, f"kongui_{language}.qm")
                subprocess.run(
                    [
                        "pyside6-lrelease",
                        str(TRANSLATIONS / f"kongui_{language}.ts"),
                        "-qm",
                        str(built),
                    ],
                    check=True,
                    capture_output=True,
                )
                self.assertEqual(
                    built.read_bytes(),
                    (TRANSLATIONS / f"kongui_{language}.qm").read_bytes(),
                    f"kongui_{language}.qm is stale: run `make translations`",
                )

    def test_the_translations_are_packaged(self):
        setup = (ROOT / "setup.py").read_text(encoding="utf-8")
        self.assertIn("translations", setup)
        self.assertIn("*.qm", setup)


class NoHardcodedPortugueseTests(unittest.TestCase):
    """Texts live in the catalogs, not in the code."""

    WORDS = re.compile(
        r"[áàâãéêíóôõúçÁÉÍÓÚÇ]|\b(não|para|com|uma|perfil|perfis|arquivo|erro|salvar|"
        r"nome|pasta|mais|ainda|sem|ser|dos|das|você|seu|sua|este|esta|ou|aplicar)\b",
        re.IGNORECASE,
    )
    ALLOWED = {
        "https://github.com/ericksousa32/kongui",
        "https://github.com/prayag2/konsave",
    }

    @staticmethod
    def docstrings(tree):
        found = set()
        for node in ast.walk(tree):
            if (
                isinstance(
                    node,
                    (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
                )
                and node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(getattr(node.body[0], "value", None), ast.Constant)
            ):
                found.add(id(node.body[0].value))
        return found

    def test_no_portuguese_literal_in_the_interface_code(self):
        offenders = []
        for path in GUI_DIR.rglob("*.py"):
            if (
                path.name == "i18n.py"
            ):  # holds the language names, written in their language
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            skip = self.docstrings(tree)
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and id(node) not in skip
                    and node.value not in self.ALLOWED
                    and self.WORDS.search(node.value)
                ):
                    offenders.append(
                        f"{path.relative_to(ROOT)}:{node.lineno}: {node.value[:60]!r}"
                    )
        self.assertEqual(offenders, [])


class PinHelperTests(GuiTestCase):
    """The test helper itself: a pinned language is removed afterwards."""

    def test_pinning_is_undone_at_cleanup(self):
        from kongui.gui import i18n

        class Probe(unittest.TestCase):
            def runTest(self):
                pass

        probe = Probe()
        pin_language(probe, "pt_BR")
        self.assertEqual(i18n.current(), "pt_BR")
        probe.doCleanups()
        self.assertEqual(i18n.current(), "en")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
