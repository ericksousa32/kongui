"""Interaction with each page, using the fictitious data only."""

import os
import unittest
from unittest import mock

from tests.gui_helpers import HAVE_QT, GuiTestCase

if HAVE_QT:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QDialog

    from kongui.gui.widgets.dialogs import ConfirmDialog


def ask(result):
    """Patches ``ConfirmDialog.ask``; returns the mock."""
    return mock.patch.object(ConfirmDialog, "ask", return_value=result)


class DashboardTests(GuiTestCase):
    """Summary cards, active profile, activity."""

    def test_cards_show_the_fictitious_figures(self):
        window = self.make_window()
        stats = window.pages["dashboard"].stats
        self.assertEqual(stats["count"].value_label.text(), "7")
        self.assertEqual(stats["active"].value_label.text(), "Work")
        self.assertEqual(stats["size"].value_label.text(), "228,6 MB")
        self.assertEqual(stats["recent"].value_label.text(), "há 2 dias")

    def test_cards_react_to_the_store(self):
        window = self.make_window()
        stats = window.pages["dashboard"].stats
        window.controller.apply("Gaming", confirmed=True)
        self.assertEqual(stats["active"].value_label.text(), "Gaming")
        self.backend_do(window, "remove", "Retro", confirmed=True)
        self.assertEqual(stats["count"].value_label.text(), "6")

    def test_empty_store_shows_empty_states(self):
        window = self.make_window()
        page = window.pages["dashboard"]
        self.backend_do(window, "wipe_all", confirmed=True)
        self.flush()
        self.assertEqual(page.stats["count"].value_label.text(), "0")
        self.assertEqual(page.stats["active"].value_label.text(), "Nenhum")
        self.assertEqual(page.stats["recent"].value_label.text(), "—")
        self.assertIsNotNone(self.button_with_text(page, "Salvar perfil atual"))
        self.backend_do(window, "reset")
        self.flush()
        self.assertEqual(page.stats["count"].value_label.text(), "7")

    def test_activity_feed_is_limited_and_updates(self):
        window = self.make_window()
        page = window.pages["dashboard"]
        for index in range(10):
            window.context.activity.add("info", f"evento {index}")
        self.flush()
        from kongui.gui.widgets.cards import ActivityRow

        rows = page.activity_card.findChildren(ActivityRow)
        self.assertEqual(len(rows), 6)
        self.assertIn("evento 9", rows[0].text_label.text())

    def test_save_button_creates_a_profile_through_the_dialog(self):
        window = self.make_window()
        page = window.pages["dashboard"]

        def fill(dialog):
            dialog.name_edit.setText("Casa")
            dialog.description_edit.setPlainText("Para o fim de semana")

        self.accept_dialogs(fill)
        page.save_button.click()
        self.flush()
        profile = window.context.store.get("Casa")
        self.assertIsNotNone(profile)
        self.assertEqual(profile.description, "Para o fim de semana")
        self.assertEqual(window.toasts.kinds()[-1], "success")
        self.assertIn("Casa", window.context.activity.entries()[0].text)
        self.assertEqual(page.stats["count"].value_label.text(), "8")

    def test_cancelled_dialog_changes_nothing(self):
        from kongui.gui.widgets.dialogs import ProfileDialog

        window = self.make_window()
        with mock.patch.object(
            ProfileDialog, "exec", return_value=QDialog.DialogCode.Rejected
        ):
            window.pages["dashboard"].save_button.click()
        self.assertEqual(len(window.context.store.names()), 7)
        self.assertEqual(window.toasts.titles(), [])


class ProfilesPageTests(GuiTestCase):
    """Grid, list, search, sort and card actions."""

    def page(self):
        window = self.make_window()
        window.show_page("profiles")
        self.flush()
        return window, window.pages["profiles"]

    def names(self, page):
        return [card.profile_name for card in page.cards()]

    def test_shows_every_profile_sorted_by_name(self):
        _, page = self.page()
        self.assertEqual(
            self.names(page),
            [
                "Gaming",
                "Minimalist",
                "Night",
                "Presentation",
                "Retro",
                "Tablet",
                "Work",
            ],
        )
        self.assertEqual(page.count_label.text(), "7 perfis")

    def test_only_the_active_profile_is_marked(self):
        _, page = self.page()
        marked = [card.profile_name for card in page.cards() if card.property("active")]
        self.assertEqual(marked, ["Work"])
        active = next(card for card in page.cards() if card.profile_name == "Work")
        self.assertEqual(active.badge.text(), "Ativo")
        self.assertFalse(active.apply_button.isEnabled())
        self.assertEqual(active.apply_button.text(), "Em uso")

    def test_search_by_name_description_and_section(self):
        _, page = self.page()
        cases = {
            "minim": ["Minimalist"],
            "MINIMA": ["Minimalist"],
            "projector": ["Presentation"],
            "konsole": ["Retro", "Tablet"],
            "  gaming  ": ["Gaming"],
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                page.search.setText(query)
                self.flush()
                self.assertEqual(self.names(page), expected)
        page.search.setText("minim")
        self.assertEqual(page.count_label.text(), "1 resultado de 7")
        page.search.setText("min")
        self.assertEqual(
            page.count_label.text(), "2 resultados de 7"
        )  # Gaming has "min"

    def test_no_results_state_and_clear_button(self):
        _, page = self.page()
        page.search.setText("zzz")
        self.flush()
        self.assertEqual(self.names(page), [])
        self.assertFalse(page.no_results.isHidden())
        self.assertTrue(page.empty_state.isHidden())
        page.no_results.action.click()
        self.flush()
        self.assertEqual(page.search.text(), "")
        self.assertEqual(len(self.names(page)), 7)
        self.assertTrue(page.no_results.isHidden())

    def test_sorting(self):
        _, page = self.page()
        page.sort_combo.setCurrentIndex(page.sort_combo.findData("recent"))
        self.flush()
        self.assertEqual(self.names(page)[:3], ["Work", "Minimalist", "Gaming"])
        page.sort_combo.setCurrentIndex(page.sort_combo.findData("size"))
        self.flush()
        self.assertEqual(self.names(page)[:3], ["Retro", "Work", "Gaming"])

    def test_filter_and_sort_function_is_pure(self):
        from kongui.gui.mock_data import demo_profiles
        from kongui.gui.pages.profiles import filter_and_sort

        profiles = demo_profiles()
        before = list(profiles)
        self.assertEqual(len(filter_and_sort(profiles, "", "name")), 7)
        self.assertEqual(filter_and_sort(profiles, "nada", "name"), [])
        self.assertEqual(profiles, before)

    def test_list_view_uses_one_column_and_is_remembered(self):
        window, page = self.page()
        QTest.mouseClick(page.view_control.button("list"), Qt.MouseButton.LeftButton)
        self.flush()
        self.assertEqual(window.settings.get("profiles_view"), "list")
        self.assertEqual(page.grid.columns, 1)
        self.assertTrue(all(card.list_mode for card in page.cards()))
        QTest.mouseClick(page.view_control.button("grid"), Qt.MouseButton.LeftButton)
        self.flush()
        self.assertFalse(any(card.list_mode for card in page.cards()))
        self.assertGreaterEqual(page.grid.columns, 2)

    def test_grid_adapts_to_the_window_width(self):
        window, page = self.page()
        window.resize(1500, 800)
        self.flush()
        wide = page.grid.columns
        window.resize(900, 700)
        self.flush()
        narrow = page.grid.columns
        self.assertGreater(wide, narrow)
        self.assertGreaterEqual(narrow, 1)

    def test_apply_after_confirmation(self):
        window, page = self.page()
        card = next(c for c in page.cards() if c.profile_name == "Gaming")
        with ask(True) as confirm:
            card.apply_button.click()
        self.flush()
        confirm.assert_called_once()
        self.assertEqual(window.context.store.active().name, "Gaming")
        self.assertEqual(window.toasts.kinds()[-1], "success")
        self.assertIn("Simulação", window.toasts._toasts[-1].accessibleName())
        marked = [c.profile_name for c in page.cards() if c.property("active")]
        self.assertEqual(marked, ["Gaming"])

    def test_apply_declined_changes_nothing(self):
        window, page = self.page()
        card = next(c for c in page.cards() if c.profile_name == "Gaming")
        with ask(False):
            card.apply_button.click()
        self.assertEqual(window.context.store.active().name, "Work")
        self.assertEqual(window.toasts.titles(), [])

    def test_remove_needs_confirmation_and_is_destructive(self):
        window, page = self.page()
        card = next(c for c in page.cards() if c.profile_name == "Tablet")
        with ask(False):
            card.remove_action.trigger()
        self.assertIn("Tablet", window.context.store.names())
        with ask(True) as confirm:
            card.remove_action.trigger()
        self.flush()
        self.assertTrue(confirm.call_args.kwargs["destructive"])
        self.assertNotIn("Tablet", window.context.store.names())
        self.assertNotIn("Tablet", self.names(page))
        self.assertEqual(window.toasts.kinds()[-1], "warning")

    def test_duplicate(self):
        window, page = self.page()
        card = next(c for c in page.cards() if c.profile_name == "Gaming")
        card.duplicate_action.trigger()
        card.duplicate_action.trigger()
        self.flush()
        self.assertIn("Gaming (cópia)", window.context.store.names())
        self.assertIn("Gaming (cópia 2)", window.context.store.names())
        self.assertFalse(window.context.store.get("Gaming (cópia)").active)

    def test_export_button_opens_the_export_form(self):
        window, page = self.page()
        card = next(c for c in page.cards() if c.profile_name == "Night")
        card.export_button.click()
        self.assertEqual(window.current_key, "transfer")
        self.assertEqual(window.pages["transfer"].export_combo.currentData(), "Night")

    def test_empty_store_shows_the_empty_state(self):
        window, page = self.page()
        self.backend_do(window, "wipe_all", confirmed=True)
        self.flush()
        self.assertFalse(page.empty_state.isHidden())
        self.assertTrue(page.grid.isHidden())
        self.assertFalse(page.search.isEnabled())
        self.assertEqual(page.count_label.text(), "")
        self.accept_dialogs(lambda d: d.name_edit.setText("Primeiro"))
        page.empty_state.action.click()
        self.flush()
        self.assertEqual(self.names(page), ["Primeiro"])
        self.assertTrue(page.empty_state.isHidden())
        self.assertTrue(page.search.isEnabled())

    def test_new_profile_button(self):
        window, page = self.page()
        self.accept_dialogs(lambda d: d.name_edit.setText("Extra"))
        page.new_button.click()
        self.flush()
        self.assertIn("Extra", self.names(page))

    def test_cards_have_accessible_names_and_buttons_have_tooltips(self):
        _, page = self.page()
        for card in page.cards():
            self.assertEqual(card.accessibleName(), f"Perfil {card.profile_name}")
            self.assertTrue(card.export_button.toolTip())
            self.assertTrue(card.more_button.accessibleName())


class SettingsPageTests(GuiTestCase):
    """Preferences and demo controls."""

    def page(self):
        window = self.make_window()
        window.show_page("settings")
        self.flush()
        return window, window.pages["settings"]

    def test_controls_reflect_the_settings(self):
        _, page = self.page()
        self.assertEqual(page.theme_control.value(), "system")
        self.assertFalse(hasattr(page, "confirm_check"))
        self.assertEqual(page.view_control.value(), "grid")
        self.assertEqual(page.seconds_spin.value(), 5)
        self.assertTrue(page.folder_edit.isReadOnly())

    def test_theme_buttons_change_the_theme(self):
        window, page = self.page()
        QTest.mouseClick(page.theme_control.button("dark"), Qt.MouseButton.LeftButton)
        self.assertEqual(window.settings.get("theme"), "dark")
        self.assertTrue(window.theme.is_dark)
        QTest.mouseClick(page.theme_control.button("light"), Qt.MouseButton.LeftButton)
        self.assertFalse(window.theme.is_dark)
        QTest.mouseClick(page.theme_control.button("system"), Qt.MouseButton.LeftButton)
        self.assertEqual(window.settings.get("theme"), "system")

    def test_view_is_stored(self):
        window, _ = self.page()
        page = window.pages["settings"]
        QTest.mouseClick(page.view_control.button("list"), Qt.MouseButton.LeftButton)
        self.assertEqual(window.settings.get("profiles_view"), "list")
        window.show_page("profiles")
        self.flush()
        self.assertEqual(window.pages["profiles"].grid.columns, 1)

    def test_toast_duration_applies_immediately(self):
        window, page = self.page()
        page.seconds_spin.setValue(12)
        self.assertEqual(window.settings.get("toast_seconds"), 12)
        self.assertEqual(window.toasts.default_seconds, 12)

    def test_settings_changed_elsewhere_update_the_controls(self):
        window, page = self.page()
        window.settings.set("toast_seconds", 20)
        self.assertEqual(page.seconds_spin.value(), 20)

    def test_test_button_shows_a_notification(self):
        window, page = self.page()
        page.test_button.click()
        self.assertEqual(window.toasts.kinds(), ["info"])

    def test_clear_and_restore_demo_data(self):
        window, page = self.page()
        with ask(False):
            page.clear_button.click()
        self.assertEqual(len(window.context.store.names()), 7)
        with ask(True):
            page.clear_button.click()
        self.assertEqual(window.context.store.names(), [])
        page.reset_button.click()
        self.assertEqual(len(window.context.store.names()), 7)
        self.assertEqual(window.context.store.active().name, "Work")


class AboutPageTests(GuiTestCase):
    """Version, environment and links."""

    def test_shows_versions_and_prototype_notice(self):
        import PySide6

        import kongui

        window = self.make_window()
        page = window.pages["about"]
        expected = kongui.__version__ if kongui.short_version() else "dev"
        self.assertEqual(page.info_values["Versão do KonGUI"], expected)
        self.assertEqual(page.info_values["PySide6"], PySide6.__version__)
        self.assertIn("GPL", page.info_values["Licença"])

    def test_links_open_through_the_desktop_service(self):
        from kongui.gui.pages.about import KONSAVE_URL, REPOSITORY_URL

        window = self.make_window()
        page = window.pages["about"]
        with mock.patch(
            "kongui.gui.pages.about.QDesktopServices.openUrl", return_value=True
        ) as op:
            page.repository_button.click()
            page.konsave_button.click()
        self.assertEqual(
            [c.args[0].toString() for c in op.call_args_list],
            [REPOSITORY_URL, KONSAVE_URL],
        )
        self.assertTrue(REPOSITORY_URL.startswith("https://"))


class NoSideEffectsTests(GuiTestCase):
    """A full walk through the interface must not write anything."""

    def test_full_walk_leaves_home_empty(self):
        window = self.make_window()
        for key in window.pages:
            window.show_page(key)
            self.flush()
        with ask(True):
            card = window.pages["profiles"].cards()[1]
            card.apply_button.click()
            window.pages["profiles"].cards()[0].duplicate_action.trigger()
        transfer = window.pages["transfer"]
        self.assertTrue(transfer.start_export())
        self.assertIn("success", window.toasts.kinds())
        transfer.set_import_file("/x/Novo.knsv")
        with ask(True):
            self.assertTrue(transfer.start_import())
        self.assertIn("Novo", window.store.names())
        self.assertEqual(os.listdir(self.home), [])
        self.assertFalse(os.path.exists(os.path.expanduser("~/.config/konsave")))


if __name__ == "__main__":
    unittest.main()
