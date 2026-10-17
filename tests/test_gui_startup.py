"""Start-up checks: the window opens, the layout is as designed, nothing leaks."""

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.gui_helpers import HAVE_QT, GuiTestCase

ROOT = Path(__file__).resolve().parent.parent
GUI_SOURCES = sorted((ROOT / "kongui" / "gui").rglob("*.py"))


class StartupTests(GuiTestCase):
    """The main window and its fixed structure."""

    def test_window_opens_with_six_pages_in_order(self):
        window = self.make_window()
        self.assertTrue(window.isVisible())
        self.assertEqual(
            list(window.pages),
            ["dashboard", "profiles", "transfer", "config", "settings", "about"],
        )
        self.assertEqual(window.sidebar.keys(), list(window.pages))
        self.assertEqual(window.stack.count(), 6)

    def test_starts_on_the_dashboard(self):
        window = self.make_window()
        self.assertEqual(window.current_key, "dashboard")
        self.assertEqual(window.top_bar.title_label.text(), "Dashboard")
        self.assertEqual(window.sidebar.current_key(), "dashboard")

    def test_sidebar_is_fixed_and_labelled(self):
        window = self.make_window()
        labels = [window.sidebar.button(key).text() for key in window.sidebar.keys()]
        self.assertEqual(
            labels,
            [
                "Dashboard",
                "Perfis",
                "Importar / Exportar",
                "Configuração do Konsave",
                "Configurações",
                "Sobre",
            ],
        )
        self.assertEqual(window.sidebar.minimumWidth(), window.sidebar.maximumWidth())
        for key in window.sidebar.keys():
            button = window.sidebar.button(key)
            self.assertFalse(button.icon().isNull(), key)
            self.assertTrue(button.accessibleName())
        window.resize(1500, 900)
        self.flush()
        self.assertEqual(window.sidebar.width(), window.sidebar.WIDTH)

    def test_minimum_size_is_enforced(self):
        window = self.make_window()
        window.resize(300, 200)
        self.flush()
        self.assertGreaterEqual(window.width(), 900)
        self.assertGreaterEqual(window.height(), 600)

    def test_every_page_has_title_subtitle_and_icon(self):
        window = self.make_window()
        for page in window.pages.values():
            self.assertTrue(page.title and page.subtitle and page.icon_name, page.key)
            self.assertEqual(page.objectName(), "Page")

    def test_data_is_fictitious_and_deterministic_in_size(self):
        window = self.make_window()
        self.assertEqual(len(window.context.store.names()), 7)
        self.assertEqual(window.context.store.active().name, "Trabalho")
        self.assertEqual(len(window.context.activity.entries()), 6)

    def test_every_icon_renders(self):
        from PySide6.QtGui import QColor

        from kongui.gui import icons

        for name in icons.ICON_NAMES:
            with self.subTest(name=name):
                pixmap = icons.pixmap(name, QColor("#336699"), 20)
                self.assertFalse(pixmap.isNull())
                image = pixmap.toImage()
                visible = any(
                    image.pixelColor(x, y).alpha() > 0
                    for x in range(image.width())
                    for y in range(image.height())
                )
                self.assertTrue(visible, f"{name} is blank")

    def test_unknown_icon_is_an_error(self):
        from PySide6.QtGui import QColor

        from kongui.gui import icons

        with self.assertRaises(KeyError):
            icons.pixmap("nope", QColor("#000000"))


class DocumentationTests(unittest.TestCase):
    """The prototype document must name what exists."""

    @classmethod
    def setUpClass(cls):
        cls.text = (ROOT / "docs" / "GUI_PROTOTYPE.md").read_text(encoding="utf-8")

    def test_pages_shortcuts_and_commands_are_documented(self):
        for item in (
            "`dashboard`",
            "`profiles`",
            "`transfer`",
            "`config`",
            "`settings`",
            "`about`",
            "Ctrl+1",
            "Ctrl+2",
            "Ctrl+3",
            "Ctrl+4",
            "Ctrl+5",
            "Ctrl+6",
            "Ctrl+F",
            "Ctrl+N",
            "Ctrl+S",
            "python3 -m kongui.gui",
            "unittest discover",
        ):
            with self.subTest(item=item):
                self.assertIn(item, self.text)

    def test_every_gui_module_is_listed(self):
        for source in GUI_SOURCES:
            if source.name == "__init__.py" or source.parent.name in (
                "pages",
                "widgets",
            ):
                continue
            with self.subTest(module=source.name):
                self.assertIn(f"`{source.name}`", self.text)

    def test_every_widget_and_page_module_is_listed(self):
        for source in GUI_SOURCES:
            if source.parent.name == "widgets" and source.name != "__init__.py":
                with self.subTest(module=source.name):
                    self.assertIn(source.stem, self.text)


class PreferencesTests(GuiTestCase):
    """Settings persistence and validation."""

    def test_in_memory_by_default_and_defaults(self):
        from kongui.gui.state import AppSettings

        settings = AppSettings()
        self.assertEqual(settings.get("theme"), "system")
        self.assertEqual(settings.get("toast_seconds"), 5)
        with self.assertRaises(KeyError):
            settings.get("confirm_apply")
        self.assertEqual(settings.get("profiles_view"), "grid")

    def test_values_are_saved_to_the_given_file_only(self):
        from kongui.gui.state import AppSettings

        path = os.path.join(self.home, "prefs.ini")
        first = AppSettings(path)
        first.set("theme", "dark")
        first.set("last_applied", "Gaming")
        first.set("toast_seconds", 9)
        first.set("profiles_view", "list")
        second = AppSettings(path)
        self.assertEqual(second.get("theme"), "dark")
        self.assertEqual(second.get("last_applied"), "Gaming")
        self.assertEqual(second.get("toast_seconds"), 9)
        self.assertEqual(second.get("profiles_view"), "list")
        self.assertEqual(os.listdir(self.home), ["prefs.ini"])

    def test_garbage_in_the_file_falls_back_to_defaults(self):
        from kongui.gui.state import AppSettings

        path = os.path.join(self.home, "prefs.ini")
        Path(path).write_text(
            "[General]\ntheme=neon\nprofiles_view=cube\ntoast_seconds=abc\nlast_applied=ok\n",
            encoding="utf-8",
        )
        settings = AppSettings(path)
        self.assertEqual(settings.get("theme"), "system")
        self.assertEqual(settings.get("profiles_view"), "grid")
        self.assertEqual(settings.get("toast_seconds"), 5)
        self.assertEqual(settings.get("last_applied"), "ok")

    def test_toast_seconds_is_clamped_and_unknown_keys_refused(self):
        from kongui.gui.state import AppSettings

        settings = AppSettings()
        settings.set("toast_seconds", 9999)
        self.assertEqual(settings.get("toast_seconds"), 60)
        settings.set("toast_seconds", -4)
        self.assertEqual(settings.get("toast_seconds"), 1)
        with self.assertRaises(KeyError):
            settings.set("nope", 1)
        with self.assertRaises(KeyError):
            settings.get("nope")

    def test_changed_is_emitted_only_for_real_changes(self):
        from kongui.gui.state import AppSettings

        settings = AppSettings()
        seen = []
        settings.changed.connect(seen.append)
        settings.set("theme", "dark")
        settings.set("theme", "dark")
        self.assertEqual(seen, ["theme"])


class EntryPointTests(GuiTestCase):
    """``main`` and the module entry point."""

    def test_main_reports_a_missing_konsave(self):
        from kongui.core.errors import EngineLoadError
        from kongui.gui import app

        with mock.patch.object(
            app.ServiceBackend, "create", side_effect=EngineLoadError("sem konsave")
        ):
            with mock.patch.object(app, "create_app") as create:
                self.assertEqual(app.main([]), 1)
        create.assert_not_called()

    def test_demo_flag_builds_the_fake_backend(self):
        from kongui.gui import app
        from kongui.gui.backend import FakeBackend

        self.assertIsInstance(app.build_backend(True), FakeBackend)
        with mock.patch.object(app.ServiceBackend, "create") as create:
            app.build_backend(False)
        create.assert_called_once_with()

    def test_main_refuses_to_run_as_root(self):
        from kongui.core.errors import RunningAsRootError
        from kongui.gui import app

        with mock.patch.object(
            app, "ensure_not_root", side_effect=RunningAsRootError("root")
        ):
            with mock.patch.object(app, "create_app") as create:
                self.assertEqual(app.main([]), 1)
        create.assert_not_called()

    def test_settings_path_lives_under_the_config_folder(self):
        from kongui.gui.app import settings_path

        with mock.patch.dict(
            os.environ, {"XDG_CONFIG_HOME": os.path.join(self.home, "cfg")}
        ):
            path = settings_path()
        self.assertIsNotNone(path)
        self.assertTrue(path.startswith(self.home))
        self.assertTrue(path.endswith("kongui-gui.ini"))


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class IsolationTests(unittest.TestCase):
    """The prototype must not reach Konsave or the services."""

    def test_importing_the_gui_does_not_load_konsave(self):
        code = (
            "import sys, kongui.gui.main_window, kongui.gui.app;"
            "bad=[m for m in sys.modules if m=='konsave' or m.startswith('konsave.')];"
            "print(bad)"
        )
        env = dict(os.environ, PYTHONPATH=str(ROOT), QT_QPA_PLATFORM="offscreen")
        with tempfile.TemporaryDirectory() as home:
            env["HOME"] = home
            result = subprocess.run(
                [sys.executable, "-c", code],
                env=env,
                cwd=home,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "[]")
            self.assertEqual(os.listdir(home), [], "importing created files in HOME")

    def test_only_the_backend_module_uses_services_engine_or_config(self):
        forbidden = re.compile(
            r"^\s*(?:from|import)\s+(?:konsave\b|kongui\.core\.(?:engine|profiles|config|cli)\b|subprocess\b)",
            re.MULTILINE,
        )
        self.assertTrue(GUI_SOURCES)
        for source in GUI_SOURCES:
            if source.name == "backend.py":
                continue
            with self.subTest(source=source.name):
                self.assertIsNone(forbidden.search(source.read_text(encoding="utf-8")))

    def test_backend_never_imports_konsave_or_subprocess(self):
        text = (ROOT / "kongui" / "gui" / "backend.py").read_text(encoding="utf-8")
        self.assertIsNone(
            re.search(r"^\s*(?:from|import)\s+(?:konsave\b|subprocess\b)", text, re.M)
        )

    def test_core_modules_used_by_the_gui(self):
        pattern = re.compile(r"^\s*from\s+kongui\.core\.(\w+)", re.MULTILINE)
        used = {}
        for source in GUI_SOURCES:
            for module in pattern.findall(source.read_text(encoding="utf-8")):
                used.setdefault(module, set()).add(source.name)
        allowed = {
            "safety",
            "errors",
            "engine",
            "profiles",
            "config",
            "results",
            "confedit",
        }
        self.assertLessEqual(set(used), allowed)
        for module in ("engine", "profiles", "config"):
            self.assertLessEqual(used.get(module, set()), {"backend.py"}, module)


if __name__ == "__main__":
    unittest.main()
