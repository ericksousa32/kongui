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
        self.assertEqual(stats["active"].value_label.text(), "Trabalho")
        self.assertEqual(stats["size"].value_label.text(), "228,6 MB")
        self.assertEqual(stats["recent"].value_label.text(), "há 2 dias")

    def test_cards_react_to_the_store(self):
        window = self.make_window()
        stats = window.pages["dashboard"].stats
        window.context.store.activate("Gaming")
        self.assertEqual(stats["active"].value_label.text(), "Gaming")
        window.context.store.remove("Retrô")
        self.assertEqual(stats["count"].value_label.text(), "6")

    def test_empty_store_shows_empty_states(self):
        window = self.make_window()
        page = window.pages["dashboard"]
        window.context.store.clear()
        self.flush()
        self.assertEqual(page.stats["count"].value_label.text(), "0")
        self.assertEqual(page.stats["active"].value_label.text(), "Nenhum")
        self.assertEqual(page.stats["recent"].value_label.text(), "—")
        self.assertIsNotNone(self.button_with_text(page, "Salvar perfil atual"))
        window.context.store.reset_demo()
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
                "Apresentação",
                "Gaming",
                "Minimalista",
                "Noturno",
                "Retrô",
                "Tablet",
                "Trabalho",
            ],
        )
        self.assertEqual(page.count_label.text(), "7 perfis")

    def test_only_the_active_profile_is_marked(self):
        _, page = self.page()
        marked = [card.profile_name for card in page.cards() if card.property("active")]
        self.assertEqual(marked, ["Trabalho"])
        active = next(card for card in page.cards() if card.profile_name == "Trabalho")
        self.assertEqual(active.badge.text(), "Ativo")
        self.assertFalse(active.apply_button.isEnabled())
        self.assertEqual(active.apply_button.text(), "Em uso")

    def test_search_by_name_description_and_section(self):
        _, page = self.page()
        cases = {
            "minim": ["Minimalista"],
            "MINIMA": ["Minimalista"],
            "projetor": ["Apresentação"],
            "konsole": ["Retrô", "Tablet"],
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
        self.assertEqual(self.names(page)[:3], ["Trabalho", "Minimalista", "Gaming"])
        page.sort_combo.setCurrentIndex(page.sort_combo.findData("size"))
        self.flush()
        self.assertEqual(self.names(page)[:3], ["Retrô", "Trabalho", "Gaming"])

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
        self.assertEqual(window.context.store.active().name, "Trabalho")
        self.assertEqual(window.toasts.titles(), [])

    def test_apply_skips_the_question_when_the_setting_is_off(self):
        window, page = self.page()
        window.settings.set("confirm_apply", False)
        card = next(c for c in page.cards() if c.profile_name == "Gaming")
        with ask(False) as confirm:
            card.apply_button.click()
        confirm.assert_not_called()
        self.assertEqual(window.context.store.active().name, "Gaming")

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
        card = next(c for c in page.cards() if c.profile_name == "Noturno")
        card.export_button.click()
        self.assertEqual(window.current_key, "transfer")
        self.assertEqual(window.pages["transfer"].export_combo.currentData(), "Noturno")

    def test_empty_store_shows_the_empty_state(self):
        window, page = self.page()
        window.context.store.clear()
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


class TransferPageTests(GuiTestCase):
    """Simulated export and import."""

    def page(self):
        window = self.make_window()
        window.show_page("transfer")
        page = window.pages["transfer"]
        page.STEPS = 3
        page.STEP_MS = 1
        self.flush()
        return window, page

    def test_export_form_defaults(self):
        _, page = self.page()
        self.assertEqual(page.export_combo.count(), 7)
        self.assertEqual(page.export_combo.currentData(), "Trabalho")
        self.assertEqual(page.filename_edit.text(), "Trabalho")
        self.assertEqual(page.export_target(), "~/Downloads/Trabalho.knsv")
        self.assertTrue(page.export_button.isEnabled())
        self.assertIn("~/Downloads/Trabalho.knsv", page.preview_label.text())

    def test_changing_the_profile_suggests_the_file_name(self):
        _, page = self.page()
        page.select_profile("Gaming")
        self.assertEqual(page.filename_edit.text(), "Gaming")
        self.assertEqual(page.export_target(), "~/Downloads/Gaming.knsv")

    def test_invalid_file_names_disable_export(self):
        _, page = self.page()
        for bad in ("../x", "a/b", "", "x.knsv", "-rf"):
            with self.subTest(name=bad):
                page.filename_edit.setText(bad)
                self.assertFalse(page.export_button.isEnabled())
                self.assertFalse(page.start_export())
        page.filename_edit.setText("ok")
        self.assertTrue(page.export_button.isEnabled())
        page.destination_edit.setText("   ")
        self.assertFalse(page.export_button.isEnabled())

    def test_export_runs_progress_then_notifies(self):
        window, page = self.page()
        page.destination_edit.setText("~/Backups/")
        page.export_button.click()
        self.assertFalse(page.export_button.isEnabled(), "must be locked while running")
        self.assertFalse(page.export_progress.isHidden())
        self.assertTrue(self.wait_until(lambda: "success" in window.toasts.kinds()))
        self.assertTrue(page.export_progress.isHidden())
        self.assertTrue(page.export_button.isEnabled())
        entry = window.context.activity.entries()[0]
        self.assertEqual(entry.kind, "export")
        self.assertIn("~/Backups/Trabalho.knsv", entry.text)

    def test_export_shows_up_in_recent_transfers(self):
        from kongui.gui.widgets.cards import ActivityRow

        window, page = self.page()
        page.start_export()
        self.assertTrue(self.wait_until(lambda: window.toasts.titles()))
        self.flush()
        texts = [
            row.text_label.text() for row in page.recent_card.findChildren(ActivityRow)
        ]
        self.assertIn("“Trabalho” exportado para ~/Downloads/Trabalho.knsv", texts)
        self.assertLessEqual(len(texts), 5)

    def test_existing_archive_is_an_error_unless_overwrite_is_checked(self):
        window, page = self.page()
        page.select_profile("Minimalista")
        self.assertFalse(page.start_export())
        self.assertEqual(window.toasts.kinds(), ["error"])
        self.assertTrue(page.export_button.isEnabled())
        page.overwrite_check.setChecked(True)
        self.assertTrue(page.start_export())
        self.assertTrue(self.wait_until(lambda: "success" in window.toasts.kinds()))

    def test_export_with_no_profiles_shows_a_hint(self):
        window, page = self.page()
        window.context.store.clear()
        self.flush()
        self.assertFalse(page.export_empty.isHidden())
        self.assertTrue(page.export_form.isHidden())
        window.context.store.reset_demo()
        self.flush()
        self.assertTrue(page.export_empty.isHidden())
        self.assertFalse(page.export_form.isHidden())

    def test_export_list_follows_the_store(self):
        window, page = self.page()
        page.select_profile("Gaming")
        window.context.store.remove("Retrô")
        self.assertEqual(page.export_combo.count(), 6)
        self.assertEqual(page.export_combo.currentData(), "Gaming")

    def test_import_refuses_other_extensions(self):
        window, page = self.page()
        self.assertFalse(page.set_import_file("/tmp/readme.txt"))
        self.assertEqual(window.toasts.kinds(), ["warning"])
        self.assertFalse(page.drop_zone.isHidden())

    def test_import_flow(self):
        window, page = self.page()
        self.assertTrue(page.set_import_file("/home/x/Downloads/Verão.knsv"))
        self.flush()
        self.assertTrue(page.drop_zone.isHidden())
        self.assertFalse(page.import_form.isHidden())
        self.assertEqual(page.import_name_edit.text(), "Verão")
        self.assertIn("Verão.knsv", page.file_label.text())
        self.assertTrue(page.import_button.isEnabled())
        page.import_button.click()
        self.assertFalse(page.import_button.isEnabled())
        self.assertTrue(
            self.wait_until(lambda: window.context.store.get("Verão") is not None)
        )
        self.flush()
        self.assertFalse(window.context.store.get("Verão").active)
        self.assertEqual(window.context.activity.entries()[0].kind, "import")
        self.assertFalse(page.drop_zone.isHidden(), "form must reset after importing")
        self.assertIn(
            "Verão", page.export_combo.itemText(page.export_combo.count() - 1)
        )

    def test_import_and_apply(self):
        window, page = self.page()
        page.set_import_file("/x/Escuro.knsv")
        page.apply_after_check.setChecked(True)
        page.import_button.click()
        self.assertTrue(
            self.wait_until(lambda: window.context.store.get("Escuro") is not None)
        )
        self.flush()
        self.assertEqual(window.context.store.active().name, "Escuro")

    def test_import_name_conflicts_and_invalid_names(self):
        _, page = self.page()
        page.set_import_file("/x/Gaming.knsv")
        self.flush()
        self.assertFalse(page.import_button.isEnabled())
        self.assertFalse(page.import_error.isHidden())
        self.assertIn("Já existe", page.import_error.text())
        self.assertFalse(page.start_import())
        page.import_name_edit.setText("../escape")
        self.assertFalse(page.import_button.isEnabled())
        page.import_name_edit.setText("Gaming 2")
        self.assertTrue(page.import_button.isEnabled())
        self.assertTrue(page.import_error.isHidden())

    def test_import_can_be_cancelled_with_change_button(self):
        _, page = self.page()
        page.set_import_file("/x/a.knsv")
        self.flush()
        page.clear_file_button.click()
        self.flush()
        self.assertFalse(page.drop_zone.isHidden())
        self.assertTrue(page.import_form.isHidden())
        self.assertEqual(page.import_name_edit.text(), "")

    def test_real_file_size_is_shown_but_the_file_is_never_opened(self):
        _, page = self.page()
        path = os.path.join(self.home, "grande.knsv")
        with open(path, "wb") as handle:
            handle.write(b"\0" * (3 * 1048576))
        with mock.patch(
            "builtins.open", side_effect=AssertionError("must not open files")
        ):
            page.set_import_file(path)
        self.assertIn("3,0 MB", page.file_label.text())

    def test_drop_zone_signal_selects_the_file(self):
        _, page = self.page()
        page.drop_zone.file_chosen.emit("/x/Solto.knsv")
        self.flush()
        self.assertEqual(page.import_name_edit.text(), "Solto")


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
        self.assertTrue(page.confirm_check.isChecked())
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

    def test_confirm_checkbox_and_view_are_stored(self):
        window, page = self.page()
        page.confirm_check.click()
        self.assertIs(window.settings.get("confirm_apply"), False)
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
        window.settings.set("confirm_apply", False)
        window.settings.set("toast_seconds", 20)
        self.assertFalse(page.confirm_check.isChecked())
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
        self.assertEqual(window.context.store.active().name, "Trabalho")


class AboutPageTests(GuiTestCase):
    """Version, environment and links."""

    def test_shows_versions_and_prototype_notice(self):
        import PySide6

        from kongui import __version__

        window = self.make_window()
        page = window.pages["about"]
        self.assertEqual(page.info_values["Versão do KonGUI"], __version__)
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
        transfer.STEPS, transfer.STEP_MS = 2, 1
        transfer.start_export()
        self.assertTrue(self.wait_until(lambda: "success" in window.toasts.kinds()))
        self.assertEqual(os.listdir(self.home), [])
        self.assertFalse(os.path.exists(os.path.expanduser("~/.config/konsave")))


if __name__ == "__main__":
    unittest.main()
