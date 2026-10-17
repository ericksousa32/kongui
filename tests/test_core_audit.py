"""Core tests added by the final audit (real Konsave code, temporary homes).

The scenario: the user saves a profile, later edits the active ``conf.yaml``
(the GUI now makes that easy), then exports the profile. The original ``export``
takes ``save/`` from the *profile's* groups but writes the *active* ``conf.yaml``
into the ``.knsv``, so the archive can disagree with itself.
"""

import os
import unittest
import zipfile

import yaml

from kongui.core import CONF_DIFFERS_PREFIX, ConfigMissingError, ConfigValidationError
from kongui.core import Group, apply_model, parse_model
from kongui.core.profiles import describe_conf_differences
from tests.helpers import BASE_CONF, make_knsv, write
from tests.test_profile_service_integration import IntegrationCase

TWO_GROUPS = BASE_CONF.replace(
    "export:",
    "    more:\n"
    '        location: "$HOME/.config"\n'
    "        entries:\n"
    "            - extrafile\n"
    "export:",
)


class ConfDifferenceTests(unittest.TestCase):
    """The pure comparison."""

    def test_same_groups_say_nothing(self):
        data = yaml.safe_load(BASE_CONF)
        self.assertEqual(describe_conf_differences(data, yaml.safe_load(BASE_CONF)), "")

    def test_added_removed_and_changed_groups_are_marked(self):
        mine = yaml.safe_load(TWO_GROUPS)
        active = yaml.safe_load(BASE_CONF)
        active["save"]["configs"]["entries"].append("newfile")
        active["export"]["fonts"] = {"location": "$HOME", "entries": ["f"]}
        text = describe_conf_differences(mine, active)
        self.assertEqual(text, "save(-more ~configs); export(+fonts)")

    def test_missing_entries_and_empty_sections_are_equivalent(self):
        mine = {"save": {"a": {"location": "$HOME", "entries": None}}, "export": {}}
        active = {"save": {"a": {"location": "$HOME"}}, "export": None}
        self.assertEqual(describe_conf_differences(mine, active), "")

    def test_garbage_does_not_raise(self):
        self.assertEqual(describe_conf_differences(None, None), "")
        self.assertEqual(describe_conf_differences([], "x"), "")


class ExportWarnsWhenTheConfigChangedTests(IntegrationCase):
    """Reproduced with the original code: nothing was said before."""

    def export(self):
        return self.profiles.export("work", directory=self.work)

    def setUp(self):
        super().setUp()
        write(self.home / ".config/extrafile", "extra")
        self.profiles.save("work").raise_for_status()

    def test_unchanged_configuration_exports_without_warning(self):
        result = self.export()
        self.assertTrue(result.ok, result.message)
        self.assertFalse(
            [line for line in result.warnings if line.startswith(CONF_DIFFERS_PREFIX)]
        )

    def test_group_added_after_saving_is_reported(self):
        self.config.write_text(TWO_GROUPS)
        result = self.export()
        self.assertTrue(result.ok, result.message)
        found = [w for w in result.warnings if w.startswith(CONF_DIFFERS_PREFIX)]
        self.assertEqual(len(found), 1, result.warnings)
        self.assertIn("save(+more)", found[0])
        # ...and this is the failure the warning is about: it cannot be applied.
        other = self.second_home()[2]
        other.import_profile(self.work / "work.knsv", confirmed=True).raise_for_status()
        with self.assertRaises(ConfigValidationError) as caught:
            other.apply("work", confirmed=True)
        self.assertIn("save.more", " ".join(caught.exception.report.errors))

    def test_group_removed_after_saving_is_reported(self):
        self.config.write_text(TWO_GROUPS)
        self.profiles.save("both").raise_for_status()
        self.config.write_text(BASE_CONF)
        result = self.profiles.export("both", directory=self.work)
        self.assertTrue(result.ok, result.message)
        found = [w for w in result.warnings if w.startswith(CONF_DIFFERS_PREFIX)]
        self.assertEqual(len(found), 1, result.warnings)
        self.assertIn("save(-more)", found[0])
        with zipfile.ZipFile(self.work / "both.knsv") as handle:
            self.assertTrue(
                any(name.startswith("save/more/") for name in handle.namelist())
            )
            self.assertNotIn("more", yaml.safe_load(handle.read("conf.yaml"))["save"])

    def test_unreadable_active_configuration_does_not_break_the_export(self):
        active = self.config.config_path
        original = active.read_text(encoding="utf-8")
        try:
            active.write_bytes(b"\xff\xfe not utf-8")
            result = self.export()
        finally:
            active.write_text(original, encoding="utf-8")
        self.assertFalse(
            [w for w in result.warnings if w.startswith(CONF_DIFFERS_PREFIX)]
        )


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


class LineEndingTests(unittest.TestCase):
    """A CRLF ``conf.yaml`` came back with mixed line endings."""

    CRLF = BASE_CONF.replace("\n", "\r\n")

    def add_group(self, text):
        model = parse_model(text)
        groups = tuple(model.groups("save")) + (Group("novo", "$HOME", ("x",), None),)
        return apply_model(text, model.with_groups("save", groups))

    def test_crlf_file_stays_crlf(self):
        result = self.add_group(self.CRLF)
        self.assertTrue(result.preserved)
        self.assertEqual(result.text.count("\n"), result.text.count("\r\n"))
        self.assertIn("novo", yaml.safe_load(result.text)["save"])

    def test_lf_file_stays_lf(self):
        result = self.add_group(BASE_CONF)
        self.assertNotIn("\r", result.text)

    def test_lossy_rewrite_also_keeps_crlf(self):
        flow = 'save: {a: {location: "$HOME", entries: [x]}}\r\nexport: {}\r\n'
        result = self.add_group(flow)
        self.assertFalse(result.preserved)
        self.assertEqual(result.text.count("\n"), result.text.count("\r\n"))


if __name__ == "__main__":
    unittest.main()
