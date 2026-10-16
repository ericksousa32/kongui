"""Navigation: sidebar, shortcuts, top bar, theme switch."""

import unittest

from tests.gui_helpers import HAVE_QT, GuiTestCase

if HAVE_QT:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

TITLES = {
    "dashboard": "Dashboard",
    "profiles": "Perfis",
    "transfer": "Importar / Exportar",
    "settings": "Configurações",
    "about": "Sobre",
}


class SidebarNavigationTests(GuiTestCase):
    """Clicking the sidebar changes the page, the title and the highlight."""

    def test_each_button_opens_its_page(self):
        window = self.make_window()
        for key, title in TITLES.items():
            with self.subTest(key=key):
                QTest.mouseClick(window.sidebar.button(key), Qt.MouseButton.LeftButton)
                self.flush()
                self.assertEqual(window.current_key, key)
                self.assertIs(window.stack.currentWidget(), window.pages[key])
                self.assertEqual(window.top_bar.title_label.text(), title)
                self.assertEqual(window.windowTitle(), f"{title} — KonGUI")
                self.assertEqual(window.sidebar.current_key(), key)
                checked = [
                    k
                    for k in window.sidebar.keys()
                    if window.sidebar.button(k).isChecked()
                ]
                self.assertEqual(checked, [key])

    def test_going_back_and_forth_keeps_state(self):
        window = self.make_window()
        window.show_page("profiles")
        window.pages["profiles"].search.setText("gam")
        window.show_page("about")
        window.show_page("profiles")
        self.assertEqual(window.pages["profiles"].search.text(), "gam")

    def test_unknown_page_is_a_key_error(self):
        window = self.make_window()
        with self.assertRaises(KeyError):
            window.show_page("nope")
        self.assertEqual(window.current_key, "dashboard")

    def test_top_bar_actions_follow_the_page(self):
        window = self.make_window()
        expected = {
            "dashboard": ["Importar", "Salvar perfil atual"],
            "profiles": ["Limpar todos", "Novo perfil"],
            "transfer": [],
            "settings": [],
            "about": [],
        }
        for key, labels in expected.items():
            with self.subTest(key=key):
                window.show_page(key)
                self.flush()
                self.assertEqual([b.text() for b in window.top_bar.actions()], labels)
                for widget in window.top_bar.actions():
                    self.assertTrue(widget.isVisible())

    def test_top_bar_buttons_survive_many_page_changes(self):
        window = self.make_window()
        for _ in range(3):
            for key in TITLES:
                window.show_page(key)
        window.show_page("dashboard")
        self.flush()
        self.assertEqual(len(window.top_bar.actions()), 2)
        self.assertTrue(all(w.isVisible() for w in window.top_bar.actions()))

    def test_dashboard_buttons_navigate(self):
        window = self.make_window()
        page = window.pages["dashboard"]
        page.import_button.click()
        self.assertEqual(window.current_key, "transfer")
        window.show_page("dashboard")
        self.flush()
        self.button_with_text(page, "Ver perfis").click()
        self.assertEqual(window.current_key, "profiles")


class ShortcutTests(GuiTestCase):
    """Keyboard shortcuts."""

    def press(self, window, key, modifier=Qt.KeyboardModifier.ControlModifier):
        window.activateWindow()
        window.setFocus()
        self.flush()
        QTest.keyClick(window, key, modifier)
        self.flush()

    def test_ctrl_digits_switch_pages(self):
        window = self.make_window()
        for digit, key in zip("12345", TITLES):
            with self.subTest(digit=digit):
                self.press(window, getattr(Qt.Key, f"Key_{digit}"))
                self.assertEqual(window.current_key, key)

    def test_ctrl_f_focuses_the_search_box(self):
        window = self.make_window()
        window.show_page("about")
        self.press(window, Qt.Key.Key_F)
        self.assertEqual(window.current_key, "profiles")
        self.assertIs(QApplication.focusWidget(), window.pages["profiles"].search)

    def test_focus_search_method_works_without_the_keyboard(self):
        window = self.make_window()
        window.focus_search()
        self.assertEqual(window.current_key, "profiles")
        self.assertIs(QApplication.focusWidget(), window.pages["profiles"].search)


class ExportShortcutTests(GuiTestCase):
    """Jumping from a profile to the export form."""

    def test_open_export_selects_the_profile(self):
        window = self.make_window()
        window.open_export("Gaming")
        self.assertEqual(window.current_key, "transfer")
        page = window.pages["transfer"]
        self.assertEqual(page.export_combo.currentData(), "Gaming")
        self.assertEqual(page.filename_edit.text(), "Gaming")

    def test_unknown_profile_leaves_the_selection_alone(self):
        window = self.make_window()
        page = window.pages["transfer"]
        self.assertFalse(page.select_profile("Fantasma"))


class ThemeSwitchTests(GuiTestCase):
    """The sidebar shortcut and the settings control change the theme."""

    def test_toggle_button_flips_light_and_dark(self):
        from kongui.gui.state import AppSettings

        settings = AppSettings()
        settings.set("theme", "light")
        window = self.make_window(settings=settings)
        self.assertFalse(window.theme.is_dark)
        QTest.mouseClick(window.sidebar.theme_button, Qt.MouseButton.LeftButton)
        self.flush()
        self.assertTrue(window.theme.is_dark)
        self.assertEqual(settings.get("theme"), "dark")
        QTest.mouseClick(window.sidebar.theme_button, Qt.MouseButton.LeftButton)
        self.flush()
        self.assertFalse(window.theme.is_dark)
        self.assertEqual(settings.get("theme"), "light")

    def test_stylesheet_and_palette_change_with_the_theme(self):
        from PySide6.QtGui import QPalette

        window = self.make_window()
        window.settings.set("theme", "light")
        light_sheet = self.app.styleSheet()
        light_window = self.app.palette().color(QPalette.ColorRole.Window).lightness()
        window.settings.set("theme", "dark")
        self.assertNotEqual(self.app.styleSheet(), light_sheet)
        self.assertLess(
            self.app.palette().color(QPalette.ColorRole.Window).lightness(),
            light_window,
        )

    def test_settings_control_follows_the_toggle(self):
        window = self.make_window()
        window.settings.set("theme", "light")
        window.toggle_theme()
        self.assertEqual(window.pages["settings"].theme_control.value(), "dark")

    def test_saved_theme_is_applied_at_start(self):
        from kongui.gui.state import AppSettings

        settings = AppSettings()
        settings.set("theme", "dark")
        window = self.make_window(settings=settings)
        self.assertTrue(window.theme.is_dark)

    def test_nav_icons_are_rebuilt_on_theme_change(self):
        window = self.make_window()
        window.settings.set("theme", "light")
        light = window.sidebar.button("profiles").icon().pixmap(20, 20).toImage()
        window.settings.set("theme", "dark")
        dark = window.sidebar.button("profiles").icon().pixmap(20, 20).toImage()
        self.assertNotEqual(light, dark)


if __name__ == "__main__":
    unittest.main()
