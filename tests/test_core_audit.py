"""Core tests added by the final audit (real Konsave code, temporary homes).

The scenario: the user saves a profile, later edits the active ``conf.yaml`` by
hand, then exports the profile. The original ``export`` takes ``save/`` from the
*profile's* groups but writes the *active* ``conf.yaml`` into the ``.knsv``, so
the archive can disagree with itself. KonGUI no longer warns about it (decided
on 2026-10-19, the export behaves as Konsave's), but applying such an archive
elsewhere is still refused with a reason, and inspecting it tells what is
missing.
"""

import os
import unittest
import zipfile

import yaml

from kongui.core import ConfigError, ConfigMissingError
from tests.helpers import install_conf, BASE_CONF, make_knsv, write
from tests.test_profile_service_integration import IntegrationCase

TWO_GROUPS = BASE_CONF.replace(
    "export:",
    "    more:\n"
    '        location: "$HOME/.config"\n'
    "        entries:\n"
    "            - extrafile\n"
    "export:",
)


class ExportAfterTheConfigChangedTests(IntegrationCase):
    """What Konsave does, and what KonGUI still protects."""

    def setUp(self):
        super().setUp()
        write(self.home / ".config/extrafile", "extra")
        self.profiles.save("work").raise_for_status()

    def test_a_group_added_later_makes_the_archive_unappliable_elsewhere(self):
        install_conf(self.config, TWO_GROUPS)
        result = self.profiles.export("work", directory=self.work)
        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.warnings, ())  # no warning any more
        other = self.second_home()[2]
        other.import_profile(self.work / "work.knsv", confirmed=True).raise_for_status()
        with self.assertRaises(ConfigError) as caught:
            other.apply("work", confirmed=True)
        self.assertIn("save.more", " ".join(caught.exception.details))

    def test_a_group_removed_later_is_left_out_of_the_archive_conf(self):
        install_conf(self.config, TWO_GROUPS)
        self.profiles.save("both").raise_for_status()
        install_conf(self.config, BASE_CONF)
        result = self.profiles.export("both", directory=self.work)
        self.assertTrue(result.ok, result.message)
        with zipfile.ZipFile(self.work / "both.knsv") as handle:
            self.assertTrue(
                any(name.startswith("save/more/") for name in handle.namelist())
            )
            self.assertNotIn("more", yaml.safe_load(handle.read("conf.yaml"))["save"])


class InspectArchiveFolderTests(IntegrationCase):
    """Inspection tells, before importing, that the profile could not be applied."""

    def make(self, conf, members):
        base = {"conf.yaml": conf, "save/": ""}
        base.update(members)
        return make_knsv(self.work / "case.knsv", base)

    def test_consistent_archive_has_no_folder_warnings(self):
        archive = self.make(
            BASE_CONF, {"save/configs/": "", "save/configs/kdeglobals": "x"}
        )
        info = self.profiles.inspect_archive(archive)
        self.assertEqual(info.warnings, ())

    def test_group_without_data_is_reported(self):
        archive = self.make(TWO_GROUPS, {"save/configs/kdeglobals": "x"})
        warnings = self.profiles.inspect_archive(archive).warnings
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn("no data folder in save/ for: more", warnings[0])

    def test_data_without_group_is_reported(self):
        archive = self.make(
            BASE_CONF, {"save/configs/kdeglobals": "x", "save/old/a": "y"}
        )
        warnings = self.profiles.inspect_archive(archive).warnings
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn("folders that its conf.yaml does not list: old", warnings[0])


class ExportNeedsTheActiveConfigTests(IntegrationCase):
    """On a fresh account that only imported a profile, export crashed with a
    bare ``FileNotFoundError: .../konsave/conf.yaml`` from the original code."""

    def test_missing_active_config_is_a_clear_error_and_leaves_nothing(self):
        self.profiles.save("work").raise_for_status()
        self.config.config_path.unlink()
        with self.assertRaises(ConfigMissingError):
            self.profiles.export("work", directory=self.work)
        self.assertEqual(os.listdir(self.work), [])


if __name__ == "__main__":
    unittest.main()
