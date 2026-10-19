"""The version comes from the installed package, never from a constant."""

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import kongui
from tests.gui_helpers import HAVE_QT, GuiTestCase
from tests.test_packaging import make_dist

ROOT = Path(__file__).resolve().parent.parent
RELEASE = "0.1.0a1"
BETWEEN_TAGS = "0.1.0a2.dev3+g1a2b3c4.d20261018"


class HelperTests(unittest.TestCase):
    """``short_version`` and ``version_label`` for every kind of version."""

    def check(self, version, short, label):
        with mock.patch.object(kongui, "__version__", version):
            self.assertEqual(kongui.short_version(), short)
            self.assertEqual(kongui.version_label(), label)

    def test_a_release(self):
        self.check(RELEASE, RELEASE, "v0.1.0a1")

    def test_a_stable_release(self):
        self.check("1.0.0", "1.0.0", "v1.0.0")

    def test_a_build_between_tags_loses_only_the_local_part(self):
        self.check(BETWEEN_TAGS, "0.1.0a2.dev3", "v0.1.0a2.dev3")

    def test_an_unknown_version_is_dev_not_a_placeholder(self):
        self.check(kongui.UNKNOWN_VERSION, "", "dev")
        self.assertNotIn("unknown", kongui.version_label())

    def test_the_unknown_marker_is_a_valid_but_obviously_empty_version(self):
        self.assertEqual(kongui.UNKNOWN_VERSION, "0+unknown")


class SourceTests(unittest.TestCase):
    """Nothing in the source may hold a version of its own."""

    def test_no_version_is_written_in_the_package(self):
        text = (ROOT / "kongui" / "__init__.py").read_text(encoding="utf-8")
        self.assertNotRegex(text, r'__version__\s*=\s*"\d')
        self.assertIn('version("kongui")', text)

    def test_the_package_version_comes_from_the_git_tag(self):
        setup = (ROOT / "setup.py").read_text(encoding="utf-8")
        self.assertIn("use_scm_version=True", setup)
        self.assertNotRegex(setup, r'\bversion\s*=\s*"')


class InstalledVersionTests(unittest.TestCase):
    """What ``import kongui`` reports, with and without an installed package."""

    def version_with(self, *dists):
        """Imports ``kongui`` in a clean process that "has installed" ``dists``."""
        with tempfile.TemporaryDirectory() as folder:
            site = Path(folder) / "site"
            site.mkdir()
            for name, version in dists:
                make_dist(site, name, version)
            env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT), str(site)]))
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import kongui;"
                    "print(kongui.__version__, kongui.short_version(),"
                    " kongui.version_label(), sep='|')",
                ],
                cwd=folder,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip().split("|")

    def test_an_installed_release_is_reported(self):
        self.assertEqual(
            self.version_with(("kongui", RELEASE)), [RELEASE, RELEASE, "v" + RELEASE]
        )

    def test_an_installed_build_between_tags_is_reported_in_full_and_short(self):
        full, short, label = self.version_with(("kongui", BETWEEN_TAGS))
        self.assertEqual(full, BETWEEN_TAGS)
        self.assertEqual(short, "0.1.0a2.dev3")
        self.assertEqual(label, "v0.1.0a2.dev3")

    def test_an_uninstalled_checkout_reports_an_unknown_version(self):
        self.assertEqual(self.version_with(), ["0+unknown", "", "dev"])

    def test_another_distribution_is_not_mistaken_for_it(self):
        """The original Konsave being installed says nothing about KonGUI."""
        self.assertEqual(self.version_with(("konsave", "2.2.0"))[0], "0+unknown")

    def test_the_version_follows_pep_440(self):
        pattern = re.compile(r"^\d+(\.\d+)*((a|b|rc)\d+)?(\.dev\d+)?(\+[\w.]+)?$")
        for version in (RELEASE, BETWEEN_TAGS, "1.0.0", "0.1.0rc1"):
            with self.subTest(version=version):
                self.assertRegex(version, pattern)


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class InterfaceTests(GuiTestCase):
    """Where the interface shows the version."""

    LANGUAGE = "en_US"

    def window_with(self, version):
        """Builds the window while the package reports ``version``."""
        patcher = mock.patch.object(kongui, "__version__", version)
        patcher.start()
        self.addCleanup(patcher.stop)
        return self.make_window()

    @staticmethod
    def labels(window):
        from kongui.gui.widgets.common import Badge, Label

        found = window.findChildren(Label) + window.findChildren(Badge)
        return [widget.text() for widget in found]

    def test_a_build_between_tags_is_shown_in_the_badge_the_row_and_the_sidebar(self):
        window = self.window_with(BETWEEN_TAGS)
        self.assertEqual(
            window.pages["about"].info_values["KonGUI version"], BETWEEN_TAGS
        )
        texts = self.labels(window)
        self.assertIn("v0.1.0a2.dev3", texts)
        self.assertIn("v0.1.0a2.dev3 · fictitious data", texts)
        self.assertNotIn("v" + BETWEEN_TAGS, texts)

    def test_the_whole_version_is_only_in_the_about_row(self):
        window = self.window_with(BETWEEN_TAGS)
        about_row = window.pages["about"].info_values["KonGUI version"]
        self.assertEqual(about_row, BETWEEN_TAGS)
        for text in self.labels(window):
            if text != about_row:
                self.assertNotIn("+g1a2b3c4", text)

    def test_a_release_is_shown_as_it_is(self):
        window = self.window_with(RELEASE)
        self.assertEqual(window.pages["about"].info_values["KonGUI version"], RELEASE)
        self.assertIn("v0.1.0a1", self.labels(window))

    def test_an_unknown_version_shows_dev(self):
        window = self.window_with(kongui.UNKNOWN_VERSION)
        self.assertEqual(window.pages["about"].info_values["KonGUI version"], "dev")
        texts = self.labels(window)
        self.assertIn("dev", texts)
        self.assertIn("dev · fictitious data", texts)
        self.assertEqual([t for t in texts if "0+unknown" in t], [])

    def test_the_sidebar_in_portuguese(self):
        from tests.gui_helpers import pin_language

        pin_language(self, "pt_BR")
        window = self.window_with(RELEASE)
        self.assertIn("v0.1.0a1 · dados fictícios", self.labels(window))


if __name__ == "__main__":
    unittest.main()
