"""Tests of kongui.core.safety (root guard and name validation)."""

import os
import unittest

from kongui.core.errors import RunningAsRootError, ValidationError
from kongui.core.safety import (
    MAX_NAME_BYTES,
    RESERVED_PREFIX,
    current_euid,
    ensure_not_root,
    validate_archive_name,
    validate_profile_name,
)
from kongui.gui.validation import archive_name_problem, profile_name_problem
from tests.helpers import as_root, non_root


class RootGuardTests(unittest.TestCase):
    """The layer must refuse to run as root."""

    def test_root_is_refused(self):
        with self.assertRaises(RunningAsRootError):
            ensure_not_root(as_root)

    def test_ordinary_user_is_accepted(self):
        ensure_not_root(non_root)

    def test_platform_without_euid_is_accepted(self):
        ensure_not_root(lambda: None)

    def test_current_euid_matches_the_process(self):
        if hasattr(os, "geteuid"):
            self.assertEqual(current_euid(), os.geteuid())


class ProfileNameTests(unittest.TestCase):
    """Names are joined to the profiles folder by the original code."""

    def test_acceptable_names(self):
        for name in ("work", "my profile", "café", "a.b", "dark-theme_2", "x" * 200):
            with self.subTest(name=name):
                self.assertEqual(validate_profile_name(name), name)

    def test_unacceptable_names(self):
        bad = [
            "",
            " ",
            " x",
            "x ",
            ".",
            "..",
            "../escape",
            "a/b",
            "a\\b",
            "/abs",
            "-rf",
            "x\x00y",
            "x\ny",
            "x\x7f",
            "x.knsv",
            "a.knsv.knsv",
            "x" * 201,
            None,
            5,
            b"x",
            ["x"],
        ]
        for name in bad:
            with self.subTest(name=name):
                with self.assertRaises(ValidationError):
                    validate_profile_name(name)


class NameSafetyAuditTests(unittest.TestCase):
    """Found by the final audit: both rules were missing and had visible effects."""

    def test_reserved_prefix_is_refused_because_listing_would_hide_it(self):
        for name in (
            f"{RESERVED_PREFIX}x",
            RESERVED_PREFIX,
            f"{RESERVED_PREFIX}new-1-2-work",
        ):
            with self.subTest(name=name):
                with self.assertRaises(ValidationError):
                    validate_profile_name(name)

    def test_names_that_only_resemble_the_prefix_are_accepted(self):
        for name in (".kongui", "kongui-x", "x.kongui-", ".config"):
            with self.subTest(name=name):
                self.assertEqual(validate_profile_name(name), name)

    def test_length_limit_is_in_bytes_not_characters(self):
        # Linux refuses file names above 255 *bytes*; 150 accented letters are 300.
        for name in (
            "é" * (MAX_NAME_BYTES // 2),
            "x" * MAX_NAME_BYTES,
            "🎨" * (MAX_NAME_BYTES // 4),
        ):
            with self.subTest(name=name[:6], size=len(name.encode())):
                self.assertEqual(validate_profile_name(name), name)
                self.assertEqual(validate_archive_name(name), name)
        for name in (
            "é" * (MAX_NAME_BYTES // 2 + 1),
            "x" * (MAX_NAME_BYTES + 1),
            "🎨" * (MAX_NAME_BYTES // 4 + 1),
        ):
            with self.subTest(name=name[:6], size=len(name.encode())):
                with self.assertRaises(ValidationError):
                    validate_profile_name(name)
                with self.assertRaises(ValidationError):
                    validate_archive_name(name)


class NameMessageTests(unittest.TestCase):
    """The interface refuses exactly what the services refuse, and says why."""

    def test_reserved_prefix_and_byte_limit_are_explained(self):
        for name in (".kongui-x", "é" * 101):
            with self.subTest(name=name[:8]):
                message = profile_name_problem(name)
                self.assertIsNotNone(message)
                self.assertIn("200 bytes", message)
        self.assertIn(".kongui-", profile_name_problem(".kongui-x"))
        self.assertIn("200 bytes", archive_name_problem("é" * 101))

    def test_the_interface_accepts_what_the_service_accepts(self):
        for name in ("é" * 100, ".kongui", "x" * 200):
            self.assertIsNone(profile_name_problem(name))
            self.assertIsNone(archive_name_problem(name))


class ArchiveNameTests(unittest.TestCase):
    """The archive name is the base name; the extension is added by Konsave."""

    def test_acceptable(self):
        self.assertEqual(validate_archive_name("backup-2026"), "backup-2026")

    def test_extensions_are_refused(self):
        for name in ("x.knsv", "x.KNSV", "x.zip", "x.ZIP"):
            with self.subTest(name=name):
                with self.assertRaises(ValidationError):
                    validate_archive_name(name)

    def test_paths_and_blank_are_refused(self):
        for name in ("", "a/b", "..", ".", "-x", "x\x00"):
            with self.subTest(name=name):
                with self.assertRaises(ValidationError):
                    validate_archive_name(name)


if __name__ == "__main__":
    unittest.main()
