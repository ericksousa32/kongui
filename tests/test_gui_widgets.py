"""Reusable widgets, theme tokens, formatting and dialogs."""

import unittest
from datetime import datetime, timedelta
from unittest import mock

from tests.gui_helpers import HAVE_QT, GuiTestCase, pin_language

if HAVE_QT:
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QColor, QDropEvent, QPalette
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QDialog, QWidget


def luminance(color) -> float:
    """Relative luminance (WCAG) of a ``QColor``."""

    def channel(value):
        value /= 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * channel(color.red())
        + 0.7152 * channel(color.green())
        + 0.0722 * channel(color.blue())
    )


def contrast(first, second) -> float:
    """WCAG contrast ratio between two colours."""
    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


class FormattingTests(unittest.TestCase):
    """Text helpers."""

    def setUp(self):
        super().setUp()
        pin_language(self)

    def test_sizes(self):
        from kongui.gui.formatting import format_size

        self.assertEqual(format_size(48.24), "48,2 MB")
        self.assertEqual(format_size(0), "0,0 MB")
        self.assertEqual(format_size(1536), "1,5 GB")

    def test_relative_dates(self):
        from kongui.gui.formatting import format_relative

        now = datetime(2026, 10, 16, 12, 0)
        cases = [
            (now, "hoje"),
            (now - timedelta(days=1), "ontem"),
            (now - timedelta(days=5), "há 5 dias"),
            (now - timedelta(days=45), "há 1 mês"),
            (now - timedelta(days=200), "há 6 meses"),
            (datetime(2024, 3, 2), "2 mar 2024"),
            (now + timedelta(days=3), "hoje"),
        ]
        for moment, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(format_relative(moment, now), expected)


class ThemeTests(GuiTestCase):
    """Tokens, palette and manager."""

    def test_fixed_palettes_are_readable(self):
        from kongui.gui.theme import fixed_tokens

        for dark in (False, True):
            tokens = fixed_tokens(dark)
            for name in ("text", "muted", "success", "warning", "danger", "accent"):
                with self.subTest(dark=dark, color=name):
                    self.assertGreaterEqual(
                        contrast(getattr(tokens, name), tokens.surface), 4.5, name
                    )
            with self.subTest(dark=dark, color="on_accent"):
                self.assertGreaterEqual(contrast(tokens.on_accent, tokens.accent), 4.5)
            with self.subTest(dark=dark, color="text on window"):
                self.assertGreaterEqual(contrast(tokens.text, tokens.window), 7)

    def test_system_tokens_follow_the_palette(self):
        from kongui.gui.theme import system_tokens

        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#202124"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#eeeeee"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#111111"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#3daee9"))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
        tokens = system_tokens(palette)
        self.assertTrue(tokens.dark)
        self.assertEqual(tokens.accent.name(), "#3daee9")
        self.assertEqual(tokens.text.name(), "#eeeeee")
        # White on the Breeze blue is unreadable, so the text colour is corrected.
        self.assertGreaterEqual(contrast(tokens.on_accent, tokens.accent), 4.5)

    def test_stylesheet_has_no_unresolved_placeholders(self):
        from kongui.gui.theme import build_stylesheet, fixed_tokens

        for dark in (False, True):
            sheet = build_stylesheet(fixed_tokens(dark))
            self.assertNotIn("{", sheet.replace("{ ", "").replace("{\n", ""))
            self.assertNotIn("None", sheet)

    def test_mode_parsing_falls_back_to_system(self):
        from kongui.gui.theme import ThemeMode

        self.assertIs(ThemeMode.parse("dark"), ThemeMode.DARK)
        self.assertIs(ThemeMode.parse("light"), ThemeMode.LIGHT)
        self.assertIs(ThemeMode.parse("neon"), ThemeMode.SYSTEM)
        self.assertIs(ThemeMode.parse(None), ThemeMode.SYSTEM)

    def test_manager_emits_once_and_restores_the_platform_palette(self):
        from kongui.gui.theme import ThemeMode, get_theme

        manager = get_theme()
        manager.set_mode(ThemeMode.SYSTEM)
        seen = []
        manager.changed.connect(lambda: seen.append(1))
        manager.set_mode(ThemeMode.DARK)
        self.assertEqual(len(seen), 1)
        self.assertTrue(manager.is_dark)
        manager.set_mode(ThemeMode.DARK)
        self.assertEqual(len(seen), 1, "setting the same mode must not refresh again")
        self.assertNotEqual(self.app.palette().resolveMask(), 0)
        manager.set_mode(ThemeMode.SYSTEM)
        self.assertEqual(
            self.app.palette().resolveMask(), 0, "platform palette not restored"
        )

    def test_widgets_get_the_dark_palette(self):
        from kongui.gui.theme import ThemeMode, get_theme

        get_theme().set_mode(ThemeMode.DARK)
        self.assertLess(
            self.app.palette().color(QPalette.ColorRole.Base).lightness(), 128
        )
        get_theme().set_mode(ThemeMode.LIGHT)
        self.assertGreater(
            self.app.palette().color(QPalette.ColorRole.Base).lightness(), 200
        )

    def test_get_theme_is_shared(self):
        from kongui.gui.theme import get_theme

        self.assertIs(get_theme(), get_theme())


class CommonWidgetTests(GuiTestCase):
    """Buttons, labels, badges, segmented control."""

    def test_button_variants(self):
        from kongui.gui.widgets.common import Button

        for variant in Button.VARIANTS:
            self.assertEqual(Button("x", variant=variant).property("variant"), variant)
        with self.assertRaises(ValueError):
            Button("x", variant="fancy")

    def test_icon_only_button_gets_an_accessible_name(self):
        from kongui.gui.widgets.common import Button

        button = Button(variant="icon", icon_name="trash", tooltip="Remover")
        self.assertEqual(button.accessibleName(), "Remover")
        self.assertFalse(button.icon().isNull())
        button.set_icon_name(None)
        self.assertTrue(button.icon().isNull())

    def test_button_icon_changes_with_the_theme(self):
        from kongui.gui.theme import ThemeMode, get_theme
        from kongui.gui.widgets.common import Button

        button = Button("x", icon_name="plus")
        get_theme().set_mode(ThemeMode.LIGHT)
        light = button.icon().pixmap(18, 18).toImage()
        get_theme().set_mode(ThemeMode.DARK)
        self.assertNotEqual(button.icon().pixmap(18, 18).toImage(), light)

    def test_label_roles(self):
        from kongui.gui.widgets.common import Label

        base = Label("a").font().pointSizeF()
        self.assertGreater(Label("a", "title").font().pointSizeF(), base)
        self.assertLess(Label("a", "caption").font().pointSizeF(), base)
        self.assertEqual(Label("a", "muted").property("role"), "muted")

    def test_badge_tone(self):
        from kongui.gui.widgets.common import Badge

        badge = Badge("Ativo", "accent")
        self.assertEqual(badge.property("tone"), "accent")
        badge.set_tone("danger")
        self.assertEqual(badge.property("tone"), "danger")

    def test_segmented_control(self):
        from kongui.gui.widgets.common import SegmentedControl

        control = SegmentedControl(
            [("a", "A", None), ("b", "B", "grid"), ("c", "C", None)]
        )
        self.assertIsNone(control.value())
        control.set_value("b")
        self.assertEqual(control.value(), "b")
        seen = []
        control.selected.connect(seen.append)
        control.set_value("a")
        self.assertEqual(seen, [], "set_value must not emit")
        QTest.mouseClick(control.button("c"), Qt.MouseButton.LeftButton)
        self.assertEqual(seen, ["c"])
        self.assertEqual(control.value(), "c")
        self.assertFalse(control.button("a").isChecked())
        self.assertEqual(
            [control.button(v).property("segpos") for v in "abc"],
            ["first", "middle", "last"],
        )
        with self.assertRaises(KeyError):
            control.set_value("zzz")

    def test_search_field(self):
        from kongui.gui.widgets.search import SearchField

        field = SearchField("Buscar perfis")
        self.assertEqual(field.placeholderText(), "Buscar perfis")
        self.assertTrue(field.isClearButtonEnabled())
        self.assertEqual(field.accessibleName(), "Buscar perfis")
        field.setText("x")
        field.clear()
        self.assertEqual(field.text(), "")

    def test_empty_state_action(self):
        from kongui.gui.widgets.states import EmptyState

        state = EmptyState("profiles", "Vazio", "Dica", "Criar", "plus")
        seen = []
        state.action_triggered.connect(lambda: seen.append(1))
        state.action.click()
        self.assertEqual(seen, [1])
        self.assertIsNone(EmptyState("profiles", "Vazio", "Dica").action)


class GridTests(GuiTestCase):
    """Adaptive column count."""

    def test_columns_for_width(self):
        from kongui.gui.widgets.grid import ResponsiveGrid

        grid = ResponsiveGrid(min_item_width=300, spacing=20, max_columns=4)
        table = {0: 1, 100: 1, 300: 1, 619: 1, 620: 2, 940: 3, 1260: 4, 5000: 4}
        for width, expected in table.items():
            with self.subTest(width=width):
                self.assertEqual(grid.columns_for_width(width), expected)

    def test_allowed_columns_avoid_a_lonely_last_item(self):
        from kongui.gui.widgets.grid import ResponsiveGrid

        grid = ResponsiveGrid(
            min_item_width=180, max_columns=4, allowed_columns=(1, 2, 4)
        )
        self.assertEqual(grid.columns_for_width(640), 2)  # 3 would fit
        self.assertEqual(grid.columns_for_width(900), 4)
        self.assertEqual(grid.columns_for_width(10), 1)

    def test_forced_columns_win(self):
        from kongui.gui.widgets.grid import ResponsiveGrid

        grid = ResponsiveGrid(min_item_width=100)
        grid.set_forced_columns(1)
        self.assertEqual(grid.columns_for_width(5000), 1)
        grid.set_forced_columns(None)
        self.assertGreater(grid.columns_for_width(5000), 1)

    def test_layout_reflows_when_resized(self):
        from kongui.gui.widgets.grid import ResponsiveGrid

        host = QWidget()
        self.addCleanup(host.close)
        grid = ResponsiveGrid(min_item_width=200, spacing=10, max_columns=5)
        grid.setParent(host)
        grid.set_items([QWidget() for _ in range(6)])
        grid.resize(230, 400)
        host.show()
        self.flush()
        self.assertEqual(grid.columns, 1)
        grid.resize(700, 400)
        self.flush()
        self.assertEqual(grid.columns, 3)
        positions = {
            (grid._layout.getItemPosition(i)[0], grid._layout.getItemPosition(i)[1])
            for i in range(6)
        }
        self.assertEqual(positions, {(r, c) for r in range(2) for c in range(3)})
        grid.resize(230, 400)
        self.flush()
        self.assertEqual(grid.columns, 1)

    def test_set_items_replaces_and_deletes_old_widgets(self):
        from kongui.gui.widgets.grid import ResponsiveGrid

        grid = ResponsiveGrid()
        first = [QWidget() for _ in range(3)]
        grid.set_items(first)
        grid.set_items([QWidget()])
        self.assertEqual(len(grid.items()), 1)
        grid.set_items([])
        self.assertEqual(grid.items(), [])


class ToastTests(GuiTestCase):
    """Notifications."""

    def host(self, seconds=5):
        from kongui.gui.widgets.toast import ToastHost

        parent = QWidget()
        parent.resize(800, 600)
        self.addCleanup(parent.close)
        parent.show()
        return ToastHost(parent, seconds)

    def test_show_stack_and_limit(self):
        host = self.host()
        for index in range(6):
            host.show_message("info", f"n{index}", seconds=0)
        self.assertEqual(host.titles(), ["n2", "n3", "n4", "n5"])
        self.assertTrue(host.isVisible())

    def test_kinds_and_invalid_kind(self):
        host = self.host()
        for kind in ("success", "info", "warning", "error"):
            host.show_message(kind, kind, seconds=0)
        self.assertEqual(host.kinds(), ["success", "info", "warning", "error"])
        with self.assertRaises(ValueError):
            host.show_message("loud", "x")

    def test_close_button_and_dismiss_all(self):
        host = self.host()
        first = host.show_message("info", "a", seconds=0)
        host.show_message("info", "b", seconds=0)
        first.close_button.click()
        self.assertEqual(host.titles(), ["b"])
        host.dismiss_all()
        self.assertEqual(host.titles(), [])
        self.assertFalse(host.isVisible())
        host.dismiss(first)  # already gone: no error

    def test_auto_dismiss(self):
        host = self.host()
        host.show_message("success", "bye", seconds=0.05)
        self.assertEqual(host.titles(), ["bye"])
        self.assertTrue(self.wait_until(lambda: not host.titles()))

    def test_zero_seconds_stays(self):
        host = self.host()
        host.show_message("info", "stay", seconds=0)
        QTest.qWait(80)
        self.assertEqual(host.titles(), ["stay"])

    def test_stack_stays_inside_the_parent_and_follows_resizes(self):
        host = self.host()
        host.show_message("info", "a", "b " * 40, seconds=0)
        parent = host.parentWidget()
        self.flush()
        self.assertLessEqual(host.geometry().right(), parent.width())
        self.assertLessEqual(host.geometry().bottom(), parent.height())
        self.assertGreater(host.height(), 50)
        parent.resize(500, 400)
        self.flush()
        self.assertLessEqual(host.geometry().right(), 500)
        self.assertLessEqual(host.geometry().bottom(), 400)

    def test_every_toast_is_tall_enough_for_its_text(self):
        host = self.host()
        for index in range(3):
            host.show_message("info", f"t{index}", "linha longa " * 12, seconds=0)
        self.flush()
        for toast in host._toasts:
            self.assertGreaterEqual(toast.height(), toast.minimumSizeHint().height())


class DialogTests(GuiTestCase):
    """Profile and confirmation dialogs."""

    def dialog(self, existing=("Work",)):
        from kongui.core import CATEGORIES
        from kongui.gui.widgets.dialogs import ProfileDialog

        dialog = ProfileDialog(None, existing, CATEGORIES)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_starts_invalid_without_scolding(self):
        dialog = self.dialog()
        self.assertFalse(dialog.confirm_button.isEnabled())
        self.assertTrue(dialog.error_label.isHidden())
        self.assertEqual(dialog.validation_error(), "Informe um nome para o perfil.")

    def test_valid_name_enables_save(self):
        dialog = self.dialog()
        dialog.name_edit.setText("Novo")
        self.assertTrue(dialog.confirm_button.isEnabled())
        self.assertIsNone(dialog.validation_error())
        self.assertTrue(dialog.error_label.isHidden())

    def test_refused_names(self):
        dialog = self.dialog()
        for bad in (
            "../x",
            "..",
            ".",
            "a/b",
            "-rf",
            " x",
            "x ",
            "x.knsv",
            "Work",
            "x" * 201,
        ):
            with self.subTest(name=bad):
                dialog.name_edit.setText(bad)
                self.assertFalse(dialog.confirm_button.isEnabled())
                self.assertTrue(dialog.validation_error())
                self.assertFalse(dialog.error_label.isHidden())
                self.assertTrue(dialog.name_edit.property("invalid"))

    def test_duplicate_has_its_own_message(self):
        dialog = self.dialog()
        dialog.name_edit.setText("Work")
        self.assertEqual(
            dialog.validation_error(), "Já existe um perfil com esse nome."
        )

    def test_needs_at_least_one_section(self):
        dialog = self.dialog()
        dialog.name_edit.setText("Novo")
        for check in dialog.section_checks:
            check.setChecked(False)
        self.assertFalse(dialog.confirm_button.isEnabled())
        self.assertIn("seção", dialog.validation_error())
        dialog.section_checks[0].setChecked(True)
        self.assertTrue(dialog.confirm_button.isEnabled())

    def test_values(self):
        dialog = self.dialog()
        dialog.name_edit.setText("Novo")
        dialog.description_edit.setPlainText("  uma descrição  ")
        for check in dialog.section_checks[2:]:
            check.setChecked(False)
        name, description, sections = dialog.values()
        self.assertEqual((name, description), ("Novo", "uma descrição"))
        self.assertEqual(len(sections), 2)

    def test_values_returns_category_keys_not_labels(self):
        from kongui.core import CATEGORIES

        dialog = self.dialog()
        for check in dialog.section_checks:
            check.setChecked(check.property("sectionKey") == CATEGORIES[0])
        _, _, sections = dialog.values()
        self.assertEqual(sections, (CATEGORIES[0],))

    def test_select_all_and_clear_all_toggle_every_box(self):
        dialog = self.dialog()
        clear_all, select_all = None, None
        for button in dialog.findChildren(type(dialog.confirm_button)):
            if button.text() == "Desmarcar tudo":
                clear_all = button
            elif button.text() == "Selecionar tudo":
                select_all = button
        self.assertIsNotNone(select_all)
        self.assertIsNotNone(clear_all)
        clear_all.click()
        self.assertFalse(any(check.isChecked() for check in dialog.section_checks))
        select_all.click()
        self.assertTrue(all(check.isChecked() for check in dialog.section_checks))

    def test_dependency_warning_names_the_missing_category(self):
        from kongui.core import ICONS

        dialog = self.dialog()
        for check in dialog.section_checks:
            key = check.property("sectionKey")
            check.setChecked(key == ICONS)
        self.assertIn("Configurações do sistema", dialog.warning_label.text())

    def test_no_warning_once_the_dependency_is_also_checked(self):
        from kongui.core import ICONS, SYSTEM

        dialog = self.dialog()
        for check in dialog.section_checks:
            key = check.property("sectionKey")
            check.setChecked(key in (ICONS, SYSTEM))
        self.assertNotIn("Selecione também", dialog.warning_label.text())
        self.assertTrue(dialog.warning_label.text().startswith("Vai incluir:"))
        self.assertIn("Ícones e cursores", dialog.warning_label.text())

    def test_enter_is_ignored_while_invalid(self):
        dialog = self.dialog()
        dialog.show()
        QTest.keyClick(dialog.name_edit, Qt.Key.Key_Return)
        self.assertTrue(dialog.isVisible())
        self.assertEqual(dialog.result(), 0)
        dialog.name_edit.setText("Novo")
        QTest.keyClick(dialog.name_edit, Qt.Key.Key_Return)
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted.value)

    def test_cancel_rejects(self):
        dialog = self.dialog()
        dialog.show()
        dialog.cancel_button.click()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected.value)

    def test_confirm_dialog_buttons_and_default_focus(self):
        from kongui.gui.widgets.dialogs import ConfirmDialog

        dialog = ConfirmDialog(None, "Remover?", "Texto", "Remover", destructive=True)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.confirm_button.property("variant"), "danger-solid")
        self.assertEqual(dialog.confirm_button.text(), "Remover")
        dialog.show()
        self.flush()
        self.assertTrue(
            dialog.cancel_button.hasFocus(), "the safe button must have focus"
        )

    def test_ask_returns_the_user_choice(self):
        from kongui.gui.widgets.dialogs import ConfirmDialog

        with mock.patch.object(
            ConfirmDialog, "exec", return_value=QDialog.DialogCode.Accepted
        ):
            self.assertTrue(ConfirmDialog.ask(None, "t", "m"))
        with mock.patch.object(
            ConfirmDialog, "exec", return_value=QDialog.DialogCode.Rejected
        ):
            self.assertFalse(ConfirmDialog.ask(None, "t", "m"))


class DropZoneTests(GuiTestCase):
    """Dragging files onto the import area."""

    @staticmethod
    def drop(zone, *paths):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(path) for path in paths])
        event = QDropEvent(
            QPointF(5, 5),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        zone.dropEvent(event)
        return event

    def test_knsv_filter(self):
        from kongui.gui.widgets.dropzone import knsv_paths

        self.assertEqual(
            knsv_paths(
                ["/a/x.knsv", "/a/y.KNSV", "/a/z.zip", "/a/knsv", "/a/w.knsv.bak"]
            ),
            ["/a/x.knsv", "/a/y.KNSV"],
        )

    def test_drop_accepts_the_first_knsv(self):
        from kongui.gui.widgets.dropzone import DropZone

        zone = DropZone()
        chosen, rejected = [], []
        zone.file_chosen.connect(chosen.append)
        zone.file_rejected.connect(lambda: rejected.append(1))
        event = self.drop(zone, "/tmp/readme.txt", "/tmp/a.knsv", "/tmp/b.knsv")
        self.assertTrue(event.isAccepted())
        self.assertEqual(chosen, ["/tmp/a.knsv"])
        self.assertEqual(rejected, [])

    def test_drop_without_knsv_is_rejected(self):
        from kongui.gui.widgets.dropzone import DropZone

        zone = DropZone()
        chosen, rejected = [], []
        zone.file_chosen.connect(chosen.append)
        zone.file_rejected.connect(lambda: rejected.append(1))
        event = self.drop(zone, "/tmp/readme.txt")
        self.assertFalse(event.isAccepted())
        self.assertEqual((chosen, rejected), ([], [1]))

    def test_browse_button_signal(self):
        from kongui.gui.widgets.dropzone import DropZone

        zone = DropZone()
        seen = []
        zone.browse_requested.connect(lambda: seen.append(1))
        zone.browse_button.click()
        self.assertEqual(seen, [1])


if __name__ == "__main__":
    unittest.main()
