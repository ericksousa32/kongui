"""Tests of kongui.core.config.ConfigService."""

import os
import unittest
from importlib.resources import files
from unittest import mock

from kongui.core import ConfigService
from kongui.core.errors import (
    ConfigMissingError,
    ConfigValidationError,
    ValidationError,
)
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

    def errors_of(self, text):
        """Validation errors for a candidate configuration text."""
        return self.config.validate_text(text).errors

    def assert_invalid(self, text, fragment):
        errors = self.errors_of(text)
        self.assertTrue(errors, f"expected errors for:\n{text}")
        self.assertTrue(
            any(fragment in error for error in errors), f"{fragment!r} not in {errors}"
        )


class DefaultConfigTests(ConfigTestCase):
    """ensure_default_config replicates the bootstrap of konsave.__main__.main."""

    def test_kde_desktop_gets_the_kde_template(self):
        path = self.config.ensure_default_config(desktop="KDE")
        self.assertEqual(path, self.engine.config_file)
        self.assertIn("pre-configured for KDE", self.config.read_text())

    def test_other_desktops_get_the_generic_template(self):
        for desktop in ("GNOME", "KDE:GNOME", "kde", "", None):
            with self.subTest(desktop=desktop):
                if self.config.exists():
                    self.engine.config_file.unlink()
                with mock.patch.dict(os.environ, clear=False):
                    os.environ.pop("XDG_CURRENT_DESKTOP", None)
                    self.config.ensure_default_config(desktop=desktop)
                self.assertNotIn("pre-configured for KDE", self.config.read_text())

    def test_desktop_comes_from_the_environment_by_default(self):
        with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "KDE"}):
            self.config.ensure_default_config()
        self.assertIn("pre-configured for KDE", self.config.read_text())

    def test_template_can_be_forced(self):
        self.config.ensure_default_config(kind="kde", desktop="GNOME")
        self.assertIn("pre-configured for KDE", self.config.read_text())

    def test_unknown_template_is_refused(self):
        with self.assertRaises(ValidationError):
            self.config.ensure_default_config(kind="windows")
        self.assertFalse(self.config.exists())

    def test_existing_configuration_is_never_touched(self):
        write(self.engine.config_file, "my own config")
        self.config.ensure_default_config(kind="kde")
        self.assertEqual(self.config.read_text(), "my own config")

    def test_templates_are_the_ones_shipped_with_konsave(self):
        self.config.ensure_default_config(kind="other")
        shipped = (files("konsave") / "conf_other.yaml").read_text(encoding="utf-8")
        self.assertEqual(self.config.read_text(), shipped)

    def test_both_shipped_templates_validate(self):
        for kind in ("kde", "other"):
            with self.subTest(kind=kind):
                if self.config.exists():
                    self.engine.config_file.unlink()
                self.config.ensure_default_config(kind=kind)
                report = self.config.validate()
                self.assertTrue(report.ok, report.errors)
                self.assertIsNotNone(report.resolved)


class ReadingTests(ConfigTestCase):
    """read_text, placeholders and read_resolved."""

    def test_missing_file(self):
        with self.assertRaises(ConfigMissingError):
            self.config.read_text()

    def test_placeholders_are_the_ones_of_the_original_parser(self):
        found = self.config.placeholders()
        self.assertEqual(
            found["keywords"], ("$HOME", "$CONFIG_DIR", "$SHARE_DIR", "$BIN_DIR")
        )
        self.assertEqual(set(found["functions"]), {"ENDS_WITH", "BEGINS_WITH"})

    def test_read_resolved_expands_placeholders(self):
        write(self.engine.config_file, BASE_CONF)
        resolved = self.config.read_resolved()
        self.assertEqual(
            resolved["save"]["configs"]["location"], str(self.home / ".config")
        )
        self.assertEqual(
            resolved["export"]["share_folder"]["location"],
            str(self.home / ".local/share"),
        )

    def test_read_resolved_raises_with_the_report(self):
        write(self.engine.config_file, "save: [")
        with self.assertRaises(ConfigValidationError) as caught:
            self.config.read_resolved()
        self.assertFalse(caught.exception.report.ok)


class StructureValidationTests(ConfigTestCase):
    """Static checks that run before the original parser."""

    def test_valid_minimal_configuration(self):
        report = self.config.validate_text(small_conf())
        self.assertTrue(report.ok, report.errors)

    def test_missing_file(self):
        report = self.config.validate(self.base / "absent.yaml")
        self.assertIn("not found", report.errors[0])

    def test_invalid_yaml(self):
        self.assert_invalid("save: [", "invalid YAML")

    def test_root_must_be_a_mapping(self):
        for text in ("", "- a\n- b\n", "plain text\n"):
            with self.subTest(text=text):
                self.assert_invalid(text, "root must be a mapping")

    def test_save_and_export_are_required(self):
        self.assert_invalid("export: {}\n", "missing required top-level key 'save'")
        self.assert_invalid("save: {}\n", "missing required top-level key 'export'")

    def test_empty_top_level_keys_crash_the_original(self):
        self.assert_invalid("save:\nexport: {}\n", "must be a mapping of sections")

    def test_unknown_scalar_top_level_key_crashes_the_original(self):
        self.assert_invalid("save: {}\nexport: {}\nextra: 1\n", "unknown top-level key")

    def test_unknown_mapping_top_level_key_is_only_a_warning(self):
        report = self.config.validate_text("save: {}\nexport: {}\nextra: {}\n")
        self.assertTrue(report.ok)
        self.assertTrue(any("unknown top-level key" in w for w in report.warnings))

    def test_section_errors(self):
        base = 'save:\n    {name}:\n        location: "$HOME"\n        entries: []\nexport: {{}}\n'
        self.assert_invalid(base.format(name='"a/b"'), "plain folder names")
        self.assert_invalid(base.format(name='".."'), "plain folder names")
        self.assert_invalid("save:\n    s: 1\nexport: {}\n", "must be a mapping")
        self.assert_invalid(
            "save:\n    s:\n        entries: []\nexport: {}\n", "'location' must be"
        )
        self.assert_invalid(
            'save:\n    s:\n        location: "$HOME"\nexport: {}\n',
            "missing 'entries'",
        )
        self.assert_invalid(
            'save:\n    s:\n        location: "$HOME"\n        entries: x\nexport: {}\n',
            "'entries' must be a list",
        )

    def test_empty_entries_are_accepted(self):
        text = (
            'save:\n    s:\n        location: "$HOME"\n        entries:\nexport: {}\n'
        )
        self.assertTrue(self.config.validate_text(text).ok)

    def test_nested_entries_are_refused_because_save_aborts_on_them(self):
        for entry in ("Code - OSS/User/settings.json", "a/b", "..", "/etc"):
            with self.subTest(entry=entry):
                self.assert_invalid(
                    small_conf(entries=[f'"{entry}"']), "single file or folder name"
                )

    def test_duplicate_entries_and_unknown_keys_warn(self):
        text = (
            'save:\n    s:\n        location: "$HOME"\n        color: red\n'
            "        entries: [a, a]\nexport: {}\n"
        )
        report = self.config.validate_text(text)
        self.assertTrue(report.ok)
        self.assertTrue(any("duplicated" in w for w in report.warnings))
        self.assertTrue(any("unknown keys" in w for w in report.warnings))

    def test_oversized_file(self):
        write(self.engine.config_file, "x" * (ConfigService.MAX_CONFIG_BYTES + 1))
        self.assertIn("too large", self.config.validate().errors[0])


class PlaceholderValidationTests(ConfigTestCase):
    """Placeholders: only the ones of konsave.parse exist."""

    def test_supported_keywords_resolve(self):
        for word, expected in (
            ("$HOME", self.home),
            ("$CONFIG_DIR", self.home / ".config"),
            ("$SHARE_DIR", self.home / ".local/share"),
            ("$BIN_DIR", self.home / ".local/bin"),
        ):
            with self.subTest(word=word):
                report = self.config.validate_text(small_conf(location=word))
                self.assertTrue(report.ok, report.errors)
                self.assertEqual(
                    report.resolved["save"]["configs"]["location"], str(expected)
                )

    def test_placeholders_advertised_but_not_implemented_are_refused(self):
        for word in ("$PROFILES_DIR", "$KONSAVE_DIR", "$USER"):
            with self.subTest(word=word):
                self.assert_invalid(
                    small_conf(location=f"$HOME/{word}"), "unsupported placeholder"
                )

    def test_unknown_function_is_refused(self):
        self.assert_invalid(
            small_conf(location="$HOME/${CONTAINS='x'}"), "unsupported function"
        )

    def test_ends_with_and_begins_with_resolve_when_a_folder_matches(self):
        (self.home / "profiles" / "abc.default-release").mkdir(parents=True)
        for func, text in (("ENDS_WITH", ".default-release"), ("BEGINS_WITH", "abc.")):
            with self.subTest(func=func):
                location = f"$HOME/profiles/${{{func}='{text}'}}"
                report = self.config.validate_text(small_conf(location=location))
                self.assertTrue(report.ok, report.errors)
                self.assertTrue(
                    report.resolved["save"]["configs"]["location"].endswith(
                        "abc.default-release"
                    )
                )

    def test_unmatched_function_placeholder_is_an_error(self):
        (self.home / "profiles" / "other").mkdir(parents=True)
        self.assert_invalid(
            small_conf(location="$HOME/profiles/${ENDS_WITH='.default-release'}"),
            "was not resolved",
        )
        self.assertEqual(os.listdir(self.work), [], "no literal folder is created")

    def test_function_placeholder_with_missing_parent_is_an_error(self):
        errors = self.errors_of(small_conf(location="$HOME/none/${ENDS_WITH='x'}"))
        self.assertTrue(errors)

    def test_two_function_placeholders_warn(self):
        (self.home / "p" / "a.x").mkdir(parents=True)
        location = "$HOME/p/${ENDS_WITH='.x'}/${BEGINS_WITH='a'}"
        report = self.config.validate_text(small_conf(location=location))
        self.assertTrue(any("only the last" in w for w in report.warnings))

    def test_relative_location_is_an_error(self):
        self.assert_invalid(small_conf(location="relative/dir"), "not absolute")

    def test_missing_location_folder_is_only_a_warning(self):
        report = self.config.validate_text(small_conf(location="$HOME/not-there"))
        self.assertTrue(report.ok)
        self.assertTrue(any("does not exist" in w for w in report.warnings))


class DelegationTests(ConfigTestCase):
    """The original read_konsave_config is the one that resolves placeholders."""

    def test_validate_goes_through_the_engine(self):
        patched = patch_engine_call(
            self.engine,
            {
                "read_konsave_config": lambda *a, **k: fake_call(
                    returned={"save": {}, "export": {}}
                )
            },
        )
        report = self.config.validate_text(small_conf())
        self.assertTrue(report.ok)
        self.assertEqual(patched.call_args.args[0], "read_konsave_config")
        self.assertEqual(report.resolved, {"save": {}, "export": {}})

    def test_engine_failure_becomes_a_validation_error(self):
        patch_engine_call(
            self.engine,
            {
                "read_konsave_config": lambda *a, **k: fake_call(
                    errors=("KeyError: 'location'",)
                )
            },
        )
        report = self.config.validate_text(small_conf())
        self.assertFalse(report.ok)
        self.assertIn("KeyError: 'location'", report.errors[0])

    def test_unexpected_return_value_is_an_error(self):
        patch_engine_call(
            self.engine,
            {"read_konsave_config": lambda *a, **k: fake_call(returned=None)},
        )
        self.assertFalse(self.config.validate_text(small_conf()).ok)


class WriteTests(ConfigTestCase):
    """write_text validates, keeps a backup and replaces atomically."""

    def test_first_write_creates_the_file(self):
        result = self.config.write_text(small_conf())
        self.assertTrue(result.ok)
        self.assertEqual(result.path, self.engine.config_file)
        self.assertEqual(self.config.read_text(), small_conf())

    def test_second_write_keeps_a_backup_of_the_previous_version(self):
        self.config.write_text(small_conf(entries=["one"]))
        result = self.config.write_text(small_conf(entries=["two"]))
        backups = [p for p in self.engine.konsave_dir.iterdir() if ".bak-" in p.name]
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), small_conf(entries=["one"]))
        self.assertIn(backups[0].name, result.message)
        self.assertEqual(self.config.read_text(), small_conf(entries=["two"]))

    def test_invalid_text_is_refused_and_nothing_changes(self):
        self.config.write_text(small_conf())
        with self.assertRaises(ConfigValidationError) as caught:
            self.config.write_text("save: [")
        self.assertFalse(caught.exception.report.ok)
        self.assertEqual(self.config.read_text(), small_conf())
        self.assertEqual(
            [p.name for p in self.engine.konsave_dir.iterdir() if ".bak-" in p.name], []
        )

    def test_no_temporary_files_are_left_behind(self):
        self.config.write_text(small_conf())
        self.config.write_text(small_conf(entries=["x"]))
        leftovers = [
            p.name for p in self.engine.konsave_dir.iterdir() if p.name.endswith(".tmp")
        ]
        self.assertEqual(leftovers, [])

    def test_failed_replace_cleans_the_temporary_file(self):
        with mock.patch("kongui.core.config.os.replace", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                self.config.write_text(small_conf())
        self.assertEqual(
            [
                p.name
                for p in self.engine.konsave_dir.iterdir()
                if p.name.endswith(".tmp")
            ],
            [],
        )
        self.assertFalse(self.config.exists())

    def test_validate_text_writes_nothing(self):
        self.config.validate_text(small_conf())
        self.assertFalse(self.config.exists())


if __name__ == "__main__":
    unittest.main()
