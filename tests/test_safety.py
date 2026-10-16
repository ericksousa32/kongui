"""Tests of kongui.core.safety (root guard and name validation)."""

import os
import unittest

from kongui.core.errors import RunningAsRootError, ValidationError
from kongui.core.safety import (
    current_euid,
    ensure_not_root,
    validate_archive_name,
    validate_profile_name,
)
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
