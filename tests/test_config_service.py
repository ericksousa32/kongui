"""Tests of kongui.core.config.ConfigService (default file and reading only).

KonGUI does not edit, back up or validate ``conf.yaml`` files: the service only
creates the default one and reads files through the original
``read_konsave_config``.
"""

import os
import unittest
from importlib.resources import files
from unittest import mock

from kongui.core import ConfigService
from kongui.core.errors import ConfigError, ConfigMissingError, ValidationError
from tests.helpers import (
    BASE_CONF,
    IsolatedHomeTestCase,
    fake_call,
    patch_engine_call,
    small_conf,
    write,
)


class ConfigTestCase(IsolatedHomeTestCase):
    """Adds a ConfigService bound to the test home."""

    def setUp(self):
        super().setUp()
        self.engine = self.new_engine()
        self.config = ConfigService(self.engine)

    def active_text(self):
        """Text of the active file."""
        return self.engine.config_file.read_text(encoding="utf-8")

    def resolve_text(self, text):
        """Writes ``text`` as the active file and reads it back resolved."""
        write(self.engine.config_file, text)
        return self.config.resolve()


class DefaultConfigTests(ConfigTestCase):
    """ensure_default_config replicates the bootstrap of konsave.__main__.main."""

    def test_kde_desktop_gets_the_kde_template(self):
        path = self.config.ensure_default_config(desktop="KDE")
        self.assertEqual(path, self.engine.config_file)
        self.assertIn("pre-configured for KDE", self.active_text())

    def test_other_desktops_get_the_generic_template(self):
        for desktop in ("GNOME", "KDE:GNOME", "kde", "", None):
            with self.subTest(desktop=desktop):
                if self.config.exists():
                    self.engine.config_file.unlink()
                with mock.patch.dict(os.environ, clear=False):
                    os.environ.pop("XDG_CURRENT_DESKTOP", None)
                    self.config.ensure_default_config(desktop=desktop)
                self.assertNotIn("pre-configured for KDE", self.active_text())

    def test_desktop_comes_from_the_environment_by_default(self):
        with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "KDE"}):
            self.config.ensure_default_config()
        self.assertIn("pre-configured for KDE", self.active_text())

    def test_template_can_be_forced(self):
        self.config.ensure_default_config(kind="kde", desktop="GNOME")
        self.assertIn("pre-configured for KDE", self.active_text())

    def test_unknown_template_is_refused(self):
        with self.assertRaises(ValidationError):
            self.config.ensure_default_config(kind="windows")
        self.assertFalse(self.config.exists())

    def test_existing_configuration_is_never_touched(self):
        write(self.engine.config_file, "my own config")
        self.config.ensure_default_config(kind="kde")
        self.assertEqual(self.active_text(), "my own config")

    def test_templates_are_the_ones_shipped_with_konsave(self):
        self.config.ensure_default_config(kind="other")
        shipped = (files("konsave") / "conf_other.yaml").read_text(encoding="utf-8")
        self.assertEqual(self.active_text(), shipped)

    def test_both_shipped_templates_can_be_read(self):
        for kind in ("kde", "other"):
            with self.subTest(kind=kind):
                if self.config.exists():
                    self.engine.config_file.unlink()
                self.config.ensure_default_config(kind=kind)
                groups = self.config.resolve()
                self.assertIn("configs", groups["save"])


class ReadingTests(ConfigTestCase):
    """resolve reads through Konsave and returns plain groups."""

    def test_placeholders_are_resolved_by_the_original_parser(self):
        groups = self.resolve_text(BASE_CONF)
        self.assertEqual(
            groups["save"]["configs"],
            {
                "location": str(self.home / ".config"),
                "entries": ["kdeglobals", "gtk-3.0"],
            },
        )
        self.assertEqual(
            groups["export"]["share_folder"]["location"],
            str(self.home / ".local/share"),
        )

    def test_another_file_can_be_read(self):
        other = self.work / "conf.yaml"
        write(other, small_conf(location="$HOME/x", entries=("a",)))
        groups = self.config.resolve(other)
        self.assertEqual(groups["save"]["configs"]["entries"], ["a"])
        self.assertFalse(self.config.exists(), "the active file is not involved")

    def test_an_empty_entries_list_is_accepted(self):
        text = "save:\n  configs:\n    location: $HOME\n    entries:\nexport: {}\n"
        self.assertEqual(self.resolve_text(text)["save"]["configs"]["entries"], [])

    def test_nothing_else_is_checked(self):
        # No validation of its own: a missing folder or a nested entry is read
        # as written (the operations decide what is safe, see ProfileService).
        groups = self.resolve_text(
            small_conf(location="$HOME/not-there", entries=("a/b",))
        )
        self.assertEqual(groups["save"]["configs"]["entries"], ["a/b"])

    def test_missing_file(self):
        with self.assertRaises(ConfigMissingError):
            self.config.resolve()

    def test_broken_yaml_is_reported_with_konsave_s_reason(self):
        with self.assertRaises(ConfigError) as caught:
            self.resolve_text("save: [")
        self.assertIn("could not read", str(caught.exception))
        self.assertTrue(caught.exception.details)

    def test_shapes_that_cannot_be_walked_are_refused(self):
        # Konsave itself fails on most of them (its reason is kept); the rest
        # are stopped before an operation would crash on them.
        for text, fragment in (
            ("- a\n- b\n", "TypeError"),
            ("save: [1]\nexport: {}\n", "IndexError"),
            ("save:\n  g:\n    entries: []\nexport: {}\n", "KeyError"),
            (
                "save:\n  g:\n    location: $HOME\n    entries: x\nexport: {}\n",
                "'entries' must be a list",
            ),
        ):
            with self.subTest(text=text):
                with self.assertRaises(ConfigError) as caught:
                    self.resolve_text(text)
                found = " ".join((str(caught.exception),) + caught.exception.details)
                self.assertIn(fragment, found)

    def test_oversized_file(self):
        write(self.engine.config_file, "#" * (ConfigService.MAX_CONFIG_BYTES + 1))
        with self.assertRaises(ConfigError) as caught:
            self.config.resolve()
        self.assertIn("too large", str(caught.exception))

    def test_reading_goes_through_the_engine(self):
        patched = patch_engine_call(
            self.engine,
            {
                "read_konsave_config": lambda *a, **k: fake_call(
                    returned={"save": {}, "export": {}}
                )
            },
        )
        self.assertEqual(self.resolve_text(small_conf()), {"save": {}, "export": {}})
        self.assertEqual(patched.call_args.args[0], "read_konsave_config")

    def test_an_engine_failure_carries_its_messages(self):
        patch_engine_call(
            self.engine,
            {
                "read_konsave_config": lambda *a, **k: fake_call(
                    errors=("KeyError: 'location'",)
                )
            },
        )
        with self.assertRaises(ConfigError) as caught:
            self.resolve_text(small_conf())
        self.assertEqual(caught.exception.details, ("KeyError: 'location'",))

    def test_nothing_is_ever_written(self):
        self.resolve_text(BASE_CONF)
        before = self.engine.config_file.read_bytes()
        self.config.resolve()
        self.assertEqual(self.engine.config_file.read_bytes(), before)
        names = os.listdir(self.engine.config_file.parent)
        self.assertEqual([n for n in names if n.startswith("conf.yaml")], ["conf.yaml"])
        self.assertFalse(hasattr(self.config, "write_text"))


if __name__ == "__main__":
    unittest.main()
