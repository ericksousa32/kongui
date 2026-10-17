"""Tests of ProfileService running the *original* Konsave code.

Nothing is mocked here: the services call the real ``konsave.funcs`` inside
temporary home directories. These tests also pin down limitations inherited
from the original (marked "known limitation") so that a change is noticed.
"""

import os
import stat
import unittest
import zipfile

from kongui.core import (
    ArchiveExistsError,
    ConfigValidationError,
    ConfirmationRequiredError,
    ProfileExistsError,
    ProfileInvalidError,
    ValidationError,
)
from tests.helpers import BASE_CONF, IsolatedHomeTestCase, make_knsv, small_conf, write


def tree(root):
    """Relative paths of everything below ``root``, sorted."""
    return sorted(
        os.path.relpath(os.path.join(base, name), root)
        for base, dirs, files in os.walk(root)
        for name in dirs + files
    )


class IntegrationCase(IsolatedHomeTestCase):
    """A home with a configuration and live files, plus a second home helper."""

    def setUp(self):
        super().setUp()
        self.engine, self.config, self.profiles = self.new_services()
        self.populate_live()

    def second_home(self, name="second"):
        """Services for another home that can receive an import."""
        home = self.base / name
        (home / ".config").mkdir(parents=True)
        (home / ".local/share").mkdir(parents=True)
        return self.new_services(home)

    def archive_with_export(self, conf, export_files):
        """A .knsv whose export section writes ``export_files``."""
        members = {"conf.yaml": conf, "save/configs/kdeglobals": "saved"}
        members.update(export_files)
        return make_knsv(self.work / "hostile.knsv", members)


class SaveIntegrationTests(IntegrationCase):
    """save_profile through the service."""

    def test_save_copies_the_configured_entries(self):
        result = self.profiles.save("work")
        self.assertTrue(result.ok, result.message)
        folder = self.engine.profiles_dir / "work"
        self.assertEqual(
            tree(folder),
            [
                "conf.yaml",
                "configs",
                "configs/gtk-3.0",
                "configs/gtk-3.0/settings.ini",
                "configs/kdeglobals",
            ],
        )
        self.assertEqual((folder / "configs/kdeglobals").read_text(), "kdeglobals-A")
        self.assertEqual((folder / "conf.yaml").read_text(), self.config.read_text())
        self.assertIn("saving profile", result.stdout)
        self.assertEqual(result.errors, ())

    def test_listing_reflects_the_new_profile_at_once(self):
        self.assertEqual(self.profiles.list_profiles(), [])
        self.profiles.save("work").raise_for_status()
        self.assertEqual([p.name for p in self.profiles.list_profiles()], ["work"])

    def test_missing_entries_are_skipped_silently_by_the_original(self):
        (self.home / ".config/kdeglobals").unlink()
        result = self.profiles.save("work")
        self.assertTrue(result.ok)
        self.assertFalse(
            (self.engine.profiles_dir / "work/configs/kdeglobals").exists()
        )

    def test_dangerous_names_are_stopped_before_the_original_runs(self):
        for bad in ("../escape", ".", "..", "a/b", "", " x"):
            with self.subTest(name=bad):
                with self.assertRaises(ValidationError):
                    self.profiles.save(bad)
        self.assertEqual(
            sorted(os.listdir(self.engine.konsave_dir)), ["conf.yaml", "profiles"]
        )
        self.assertEqual(os.listdir(self.engine.profiles_dir), [])

    def test_every_accepted_name_stays_listed_and_removable(self):
        """Audit: ``.kongui-x`` used to be saved but hidden from the list.

        Whatever ``save`` accepts must be visible to ``list_profiles`` and
        removable, and whatever is refused must leave nothing on disk.
        """
        for bad in (".kongui-hidden", ".kongui-", "é" * 150, "x" * 201):
            with self.subTest(name=bad[:14]):
                with self.assertRaises(ValidationError):
                    self.profiles.save(bad)
        self.assertEqual(os.listdir(self.engine.profiles_dir), [])
        for good in (".kongui", "é" * 100, "meu perfil 🎨 ç", "a" * 200):
            with self.subTest(name=good[:14]):
                self.assertTrue(self.profiles.save(good).ok)
                self.assertIn(good, [p.name for p in self.profiles.list_profiles()])
                self.assertTrue(self.profiles.replace(good, confirmed=True).ok)
                self.assertTrue(self.profiles.remove(good, confirmed=True).ok)
        self.assertEqual(os.listdir(self.engine.profiles_dir), [])

    def test_existing_profile_requires_overwrite(self):
        self.profiles.save("work").raise_for_status()
        with self.assertRaises(ProfileExistsError):
            self.profiles.save("work")
        self.assertTrue(self.profiles.save("work", overwrite=True).ok)

    def test_overwrite_merges_instead_of_replacing(self):
        """Known limitation: files removed from the system stay in the profile."""
        self.profiles.save("work").raise_for_status()
        (self.home / ".config/gtk-3.0/settings.ini").unlink()
        write(self.home / ".config/gtk-3.0/new.ini")
        self.profiles.save("work", overwrite=True).raise_for_status()
        saved = tree(self.engine.profiles_dir / "work/configs/gtk-3.0")
        self.assertEqual(saved, ["new.ini", "settings.ini"])

    def test_nested_entry_is_refused_instead_of_leaving_a_partial_profile(self):
        write(self.home / ".config/Code - OSS/User/settings.json")
        self.config.write_text(small_conf(entries=["kdeglobals"]))
        self.engine.config_file.write_text(
            small_conf(entries=['"Code - OSS/User/settings.json"', "kdeglobals"])
        )
        with self.assertRaises(ConfigValidationError):
            self.profiles.save("work")
        self.assertEqual(os.listdir(self.engine.profiles_dir), [])

    def test_unmatched_function_placeholder_creates_nothing_anywhere(self):
        (self.home / "ff" / "abc.other").mkdir(parents=True)
        self.engine.config_file.write_text(
            small_conf(location="$HOME/ff/${ENDS_WITH='.default-release'}")
        )
        with self.assertRaises(ConfigValidationError):
            self.profiles.save("work")
        self.assertEqual(os.listdir(self.work), [])
        self.assertEqual(os.listdir(self.engine.profiles_dir), [])

    def test_matched_function_placeholder_works_end_to_end(self):
        write(self.home / "ff/abc.default-release/chrome/userChrome.css", "css")
        self.engine.config_file.write_text(
            small_conf(
                location="$HOME/ff/${ENDS_WITH='.default-release'}", entries=["chrome"]
            )
        )
        self.profiles.save("ff").raise_for_status()
        self.assertEqual(
            (self.engine.profiles_dir / "ff/configs/chrome/userChrome.css").read_text(),
            "css",
        )

    def test_a_broken_original_call_is_reported_and_cleaned_up(self):
        """The original aborts if a destination cannot be created."""
        # A *file* where the profile section folder must go makes mkdir fail.
        profile = self.engine.profiles_dir / "work"
        write(profile / "configs", "i am a file")
        result = self.profiles.save("work", overwrite=True)
        self.assertFalse(result.ok)
        self.assertTrue(result.errors)
        self.assertTrue(profile.exists(), "a pre-existing folder is never removed")


class ApplyIntegrationTests(IntegrationCase):
    """apply_profile through the service."""

    def test_apply_restores_the_saved_files(self):
        self.profiles.save("work").raise_for_status()
        write(self.home / ".config/kdeglobals", "CHANGED-LATER")
        result = self.profiles.apply("work", confirmed=True)
        self.assertTrue(result.ok, result.message)
        self.assertEqual((self.home / ".config/kdeglobals").read_text(), "kdeglobals-A")
        self.assertIn("copying files", result.stdout)

    def test_apply_keeps_a_safety_copy_of_what_it_overwrites(self):
        self.profiles.save("work").raise_for_status()
        write(self.home / ".config/kdeglobals", "UNSAVED-WORK")
        result = self.profiles.apply("work", confirmed=True)
        result.raise_for_status()
        self.assertIsNotNone(result.backup)
        (copy,) = self.profiles.list_backups()
        self.assertEqual(copy.path, result.backup)
        self.profiles.restore_backup(copy.id, confirmed=True)
        self.assertEqual((self.home / ".config/kdeglobals").read_text(), "UNSAVED-WORK")

    def test_apply_merges_folders(self):
        """Known limitation: files that are not in the profile stay."""
        self.profiles.save("work").raise_for_status()
        write(self.home / ".config/gtk-3.0/extra.ini")
        self.profiles.apply("work", confirmed=True).raise_for_status()
        self.assertTrue((self.home / ".config/gtk-3.0/extra.ini").exists())

    def test_apply_requires_confirmation(self):
        self.profiles.save("work").raise_for_status()
        write(self.home / ".config/kdeglobals", "CHANGED-LATER")
        with self.assertRaises(ConfirmationRequiredError):
            self.profiles.apply("work")
        self.assertEqual(
            (self.home / ".config/kdeglobals").read_text(), "CHANGED-LATER"
        )

    def test_apply_does_not_claim_success_when_the_original_fails_midway(self):
        self.profiles.save("work").raise_for_status()
        (self.home / ".config/kdeglobals").unlink()
        (self.home / ".config/kdeglobals").mkdir()  # a folder where a file is due
        result = self.profiles.apply("work", confirmed=True)
        self.assertIn("applied successfully", result.stdout, "the original says so")
        self.assertFalse(result.ok)
        self.assertTrue(result.errors)

    def test_destination_that_vanished_is_refused_up_front(self):
        self.engine.config_file.write_text(
            small_conf(location="$HOME/.local/share/a/b", entries=["thing"])
        )
        write(self.home / ".local/share/a/b/thing")
        self.profiles.save("deep").raise_for_status()
        import shutil

        shutil.rmtree(self.home / ".local/share/a")
        with self.assertRaises(ConfigValidationError):
            self.profiles.apply("deep", confirmed=True)

    def test_vanished_placeholder_target_leaves_no_literal_folder(self):
        write(self.home / "ff/abc.default-release/x")
        self.engine.config_file.write_text(
            small_conf(
                location="$HOME/ff/${ENDS_WITH='.default-release'}", entries=["x"]
            )
        )
        self.profiles.save("ff").raise_for_status()
        os.rename(self.home / "ff/abc.default-release", self.home / "ff/abc.renamed")
        with self.assertRaises(ConfigValidationError):
            self.profiles.apply("ff", confirmed=True)
        self.assertEqual(os.listdir(self.work), [])

    def test_a_profile_without_conf_cannot_be_applied(self):
        self.profiles.save("work").raise_for_status()
        (self.engine.profiles_dir / "work/conf.yaml").unlink()
        with self.assertRaises(ProfileInvalidError):
            self.profiles.apply("work", confirmed=True)


class RemoveAndWipeIntegrationTests(IntegrationCase):
    """remove_profile and wipe through the service."""

    def test_remove_deletes_only_the_chosen_profile(self):
        self.profiles.save("a").raise_for_status()
        self.profiles.save("b").raise_for_status()
        self.profiles.remove("a", confirmed=True).raise_for_status()
        self.assertEqual([p.name for p in self.profiles.list_profiles()], ["b"])

    def test_wipe_removes_every_profile_and_keeps_the_configuration(self):
        self.profiles.save("a").raise_for_status()
        self.profiles.save("b").raise_for_status()
        with self.assertRaises(ConfirmationRequiredError):
            self.profiles.wipe_all()
        self.assertEqual(len(self.profiles.list_profiles()), 2)
        result = self.profiles.wipe_all(confirmed=True)
        self.assertTrue(result.ok, result.message)
        self.assertEqual(self.profiles.list_profiles(), [])
        self.assertTrue(self.engine.config_file.is_file())
        self.assertTrue(self.engine.profiles_dir.is_dir())
        self.assertTrue(self.profiles.save("again").ok, "usable after a wipe")


class ExportImportIntegrationTests(IntegrationCase):
    """The full cycle: export in one home, import in another."""

    def setUp(self):
        super().setUp()
        self.profiles.save("shared").raise_for_status()
        self.out = self.base / "out"
        self.out.mkdir()

    def test_export_produces_a_zip_with_the_documented_layout(self):
        result = self.profiles.export("shared", directory=self.out)
        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.path, self.out / "shared.knsv")
        with zipfile.ZipFile(result.path) as handle:
            names = set(handle.namelist())
        self.assertTrue(
            {
                "conf.yaml",
                "save/configs/kdeglobals",
                "save/configs/gtk-3.0/settings.ini",
                "export/share_folder/icons/theme.txt",
            }
            <= names
        )
        self.assertEqual(os.listdir(self.out), ["shared.knsv"], "no staging folder")

    def test_export_respects_the_archive_name(self):
        result = self.profiles.export(
            "shared", directory=self.out, archive_name="backup"
        )
        self.assertEqual(result.path.name, "backup.knsv")

    def test_conflict_policies_with_the_real_original(self):
        self.profiles.export("shared", directory=self.out).raise_for_status()
        with self.assertRaises(ArchiveExistsError):
            self.profiles.export("shared", directory=self.out)
        unique = self.profiles.export(
            "shared", directory=self.out, on_conflict="unique"
        )
        self.assertEqual(unique.path.name, "shared-2.knsv")
        before = (self.out / "shared.knsv").stat().st_mtime_ns
        replaced = self.profiles.export(
            "shared", directory=self.out, on_conflict="overwrite"
        )
        self.assertTrue(replaced.ok, replaced.message)
        self.assertGreaterEqual((self.out / "shared.knsv").stat().st_mtime_ns, before)
        self.assertEqual(sorted(os.listdir(self.out)), ["shared-2.knsv", "shared.knsv"])

    def test_a_folder_with_the_archive_name_is_never_deleted(self):
        """The original ``force`` would rmtree it."""
        precious = write(self.out / "Docs" / "precious.txt", "do not lose")
        with self.assertRaises(ArchiveExistsError):
            self.profiles.export(
                "shared",
                directory=self.out,
                archive_name="Docs",
                on_conflict="overwrite",
            )
        self.assertEqual(precious.read_text(), "do not lose")

    def test_round_trip_between_two_homes(self):
        archive = self.profiles.export("shared", directory=self.out).path
        engine_b, _, profiles_b = self.second_home()
        write(engine_b.home / ".local/share/icons/theme.txt", "theme-B")
        write(engine_b.home / ".config/kdeglobals", "kdeglobals-B")

        with self.assertRaises(ConfirmationRequiredError):
            profiles_b.import_profile(archive)
        self.assertEqual(profiles_b.list_profiles(), [])

        result = profiles_b.import_profile(archive, confirmed=True)
        self.assertTrue(result.ok, result.message)
        self.assertEqual([p.name for p in profiles_b.list_profiles()], ["shared"])
        self.assertEqual(
            (engine_b.profiles_dir / "shared/configs/kdeglobals").read_text(),
            "kdeglobals-A",
        )
        self.assertEqual(
            (engine_b.home / ".local/share/icons/theme.txt").read_text(),
            "theme-A",
            "the export section is written to the system on import",
        )
        self.assertEqual(
            (engine_b.home / ".config/kdeglobals").read_text(),
            "kdeglobals-B",
            "the save section only becomes a profile until it is applied",
        )
        self.assertFalse((engine_b.temp_dir / "shared").exists())

        with self.assertRaises(ProfileExistsError):
            profiles_b.import_profile(archive, confirmed=True)

        profiles_b.apply("shared", confirmed=True).raise_for_status()
        self.assertEqual(
            (engine_b.home / ".config/kdeglobals").read_text(), "kdeglobals-A"
        )

    def test_import_into_a_home_without_the_destination_folder_is_reported(self):
        archive = self.profiles.export("shared", directory=self.out).path
        home = self.base / "bare"
        (home / ".config").mkdir(parents=True)
        engine_b, _, profiles_b = self.new_services(home)
        result = profiles_b.import_profile(archive, confirmed=True)
        self.assertFalse(result.ok, "the original prints success but logs the error")
        self.assertIn("Profile successfully imported", result.stdout)
        self.assertEqual(
            profiles_b.list_profiles(), [], "the partial import is reverted"
        )
        self.assertFalse((engine_b.temp_dir / "shared").exists())

    def test_known_limitations_of_the_archive_format(self):
        """Permissions and symbolic links do not survive (original behaviour)."""
        write(self.home / ".local/share/icons/run.sh", "#!/bin/sh", 0o755)
        os.symlink("settings.ini", self.home / ".config/gtk-3.0/link.ini")
        self.profiles.save("shared", overwrite=True).raise_for_status()
        archive = self.profiles.export(
            "shared", directory=self.out, on_conflict="overwrite"
        ).path
        engine_b, _, profiles_b = self.second_home()
        profiles_b.import_profile(archive, confirmed=True).raise_for_status()
        mode = stat.S_IMODE(
            (engine_b.home / ".local/share/icons/run.sh").stat().st_mode
        )
        self.assertFalse(mode & stat.S_IXUSR, "the executable bit is lost")
        link = engine_b.profiles_dir / "shared/configs/gtk-3.0/link.ini"
        self.assertFalse(link.is_symlink(), "symbolic links become regular files")


class InspectArchiveIntegrationTests(IntegrationCase):
    """inspect_archive: the import checks, read only."""

    def setUp(self):
        super().setUp()
        self.profiles.save("shared").raise_for_status()
        self.out = self.base / "out"
        self.out.mkdir()
        self.archive = self.profiles.export("shared", directory=self.out).path

    def test_describes_an_archive_made_by_export(self):
        info = self.profiles.inspect_archive(self.archive)
        self.assertEqual(info.name, "shared")
        self.assertEqual(info.path, self.archive)
        self.assertEqual(info.save_sections, ("configs",))
        self.assertEqual(info.export_sections, ("share_folder",))
        self.assertEqual(info.size_bytes, self.archive.stat().st_size)
        self.assertGreater(info.member_count, 3)
        self.assertTrue(info.name_taken, "the profile exists in this home")

    def test_name_is_free_in_another_home(self):
        _, _, profiles_b = self.second_home()
        self.assertFalse(profiles_b.inspect_archive(self.archive).name_taken)

    def test_writes_nothing(self):
        before = tree(self.base)
        self.profiles.inspect_archive(self.archive)
        self.assertEqual(tree(self.base), before)

    def test_refuses_what_import_would_refuse(self):
        bad = {
            "missing": self.out / "nope.knsv",
            "extension": write(self.out / "plain.txt"),
            "not a zip": write(self.out / "fake.knsv", "not a zip"),
            "no conf": make_knsv(self.out / "noconf.knsv", {"save/a": "x"}),
            "no save": make_knsv(self.out / "nosave.knsv", {"conf.yaml": BASE_CONF}),
            "unsafe": make_knsv(
                self.out / "unsafe.knsv",
                {"conf.yaml": BASE_CONF, "save/a": "x", "../evil": "x"},
            ),
        }
        for label, path in bad.items():
            with self.subTest(case=label):
                with self.assertRaises(ValidationError):
                    self.profiles.inspect_archive(path)

    def test_refuses_an_unsafe_configuration(self):
        conf = (
            'save:\n    configs:\n        location: "/etc"\n        entries: []\n'
            "export: {}\n"
        )
        archive = make_knsv(self.out / "etc.knsv", {"conf.yaml": conf, "save/a": "x"})
        with self.assertRaises(ConfigValidationError):
            self.profiles.inspect_archive(archive)
        info = self.profiles.inspect_archive(archive, allow_outside_home=True)
        self.assertEqual(info.name, "etc")


class HostileArchiveIntegrationTests(IntegrationCase):
    """A .knsv is untrusted input: its conf.yaml chooses where files go."""

    def test_destinations_outside_home_are_refused_and_nothing_is_written(self):
        outside = self.base / "outside"
        outside.mkdir()
        conf = (
            'save:\n    configs:\n        location: "$HOME/.config"\n        entries: []\n'
            f'export:\n    x:\n        location: "{outside}"\n        entries: [marker.txt]\n'
        )
        archive = self.archive_with_export(conf, {"export/x/marker.txt": "m"})
        with self.assertRaises(ConfigValidationError) as caught:
            self.profiles.import_profile(archive, confirmed=True)
        self.assertTrue(
            any("outside the home" in e for e in caught.exception.report.errors)
        )
        self.assertEqual(os.listdir(outside), [])
        self.assertEqual(self.profiles.list_profiles(), [])

    def test_the_opt_in_allows_the_import(self):
        outside = self.base / "outside"
        outside.mkdir()
        conf = (
            'save:\n    configs:\n        location: "$HOME/.config"\n        entries: []\n'
            f'export:\n    x:\n        location: "{outside}"\n        entries: [marker.txt]\n'
        )
        archive = self.archive_with_export(conf, {"export/x/marker.txt": "m"})
        result = self.profiles.import_profile(
            archive, confirmed=True, allow_outside_home=True
        )
        self.assertTrue(result.ok, result.message)
        self.assertEqual((outside / "marker.txt").read_text(), "m")

    def test_a_symlinked_home_subfolder_cannot_be_used_to_escape(self):
        outside = self.base / "outside"
        outside.mkdir()
        os.symlink(outside, self.home / "escape")
        conf = (
            'save:\n    configs:\n        location: "$HOME/.config"\n        entries: []\n'
            'export:\n    x:\n        location: "$HOME/escape"\n        entries: [marker.txt]\n'
        )
        archive = self.archive_with_export(conf, {"export/x/marker.txt": "m"})
        with self.assertRaises(ConfigValidationError):
            self.profiles.import_profile(archive, confirmed=True)
        self.assertEqual(os.listdir(outside), [])

    def test_members_that_climb_out_are_refused_before_extraction(self):
        archive = make_knsv(
            self.work / "dots.knsv",
            {"conf.yaml": BASE_CONF, "save/configs/a": "x", "../../escape.txt": "x"},
        )
        with self.assertRaises(ValidationError):
            self.profiles.import_profile(archive, confirmed=True)
        self.assertFalse((self.base / "escape.txt").exists())
        self.assertFalse((self.engine.temp_dir / "dots").exists())

    def test_names_that_would_merge_into_an_existing_profile_are_refused(self):
        self.profiles.save("my").raise_for_status()
        (self.engine.profiles_dir / "my/OLD").write_text("old")
        archive = make_knsv(
            self.work / "my.knsv.knsv",
            {"conf.yaml": BASE_CONF, "save/configs/kdeglobals": "NEW"},
        )
        with self.assertRaises(ValidationError):
            self.profiles.import_profile(archive, confirmed=True)
        self.assertTrue((self.engine.profiles_dir / "my/OLD").exists())
        self.assertFalse(
            (self.engine.profiles_dir / "my/configs/kdeglobals").read_text() == "NEW"
        )

    def test_an_oversized_configuration_inside_the_archive_is_refused(self):
        archive = make_knsv(
            self.work / "big.knsv",
            {"conf.yaml": "#" * (2 * 1024 * 1024), "save/configs/a": "x"},
        )
        with self.assertRaises(ValidationError):
            self.profiles.import_profile(archive, confirmed=True)


if __name__ == "__main__":
    unittest.main()


class ReplaceIntegrationTests(IntegrationCase):
    """ProfileService.replace: a real replacement, unlike ``save(overwrite=True)``."""

    def test_files_that_no_longer_exist_do_not_survive(self):
        self.profiles.save("work").raise_for_status()
        write(self.engine.profiles_dir / "work/configs/stale-file", "from the old save")
        write(self.home / ".config/kdeglobals", "kdeglobals-B")
        result = self.profiles.replace("work", confirmed=True)
        self.assertTrue(result.ok, result.message)
        folder = self.engine.profiles_dir / "work"
        self.assertFalse((folder / "configs/stale-file").exists())
        self.assertEqual((folder / "configs/kdeglobals").read_text(), "kdeglobals-B")
        self.assertEqual(result.path, folder)

    def test_the_merge_behaviour_of_save_is_the_reason_it_exists(self):
        """Known limitation of the original, pinned so the contrast stays visible."""
        self.profiles.save("work").raise_for_status()
        write(self.engine.profiles_dir / "work/configs/stale-file", "old")
        self.profiles.save("work", overwrite=True).raise_for_status()
        self.assertTrue((self.engine.profiles_dir / "work/configs/stale-file").exists())

    def test_no_temporary_folder_is_left_and_the_listing_is_clean(self):
        self.profiles.save("work").raise_for_status()
        self.profiles.replace("work", confirmed=True).raise_for_status()
        self.assertEqual(self.engine.profile_names(), ["work"])
        self.assertEqual([p.name for p in self.profiles.list_profiles()], ["work"])

    def test_other_profiles_are_untouched(self):
        self.profiles.save("a").raise_for_status()
        self.profiles.save("b").raise_for_status()
        before = tree(self.engine.profiles_dir / "b")
        self.profiles.replace("a", confirmed=True).raise_for_status()
        self.assertEqual(tree(self.engine.profiles_dir / "b"), before)

    def test_requires_explicit_confirmation(self):
        self.profiles.save("work").raise_for_status()
        for value in (False, None, 1, "yes"):
            with self.subTest(confirmed=value):
                with self.assertRaises(ConfirmationRequiredError):
                    self.profiles.replace("work", confirmed=value)

    def test_unknown_profile_and_bad_names(self):
        from kongui.core import ProfileNotFoundError

        with self.assertRaises(ProfileNotFoundError):
            self.profiles.replace("ghost", confirmed=True)
        with self.assertRaises(ValidationError):
            self.profiles.replace("../x", confirmed=True)
        self.assertEqual(self.engine.profile_names(), [])

    def test_invalid_active_configuration_leaves_the_profile_alone(self):
        self.profiles.save("work").raise_for_status()
        before = tree(self.engine.profiles_dir / "work")
        write(self.engine.config_file, "save: [not, a, mapping]\n")
        with self.assertRaises(ConfigValidationError):
            self.profiles.replace("work", confirmed=True)
        self.assertEqual(tree(self.engine.profiles_dir / "work"), before)
        self.assertEqual(self.engine.profile_names(), ["work"])

    def test_a_failing_save_keeps_the_old_profile_and_cleans_up(self):
        from unittest import mock

        from tests.helpers import fake_call, patch_engine_call

        self.profiles.save("work").raise_for_status()
        before = tree(self.engine.profiles_dir / "work")

        def broken_save(name, *args, **kwargs):
            (self.engine.profiles_dir / name).mkdir()
            return fake_call("save_profile", errors=("disk full",))

        patch_engine_call(self.engine, {"save_profile": broken_save})
        result = self.profiles.replace("work", confirmed=True)
        self.assertFalse(result.ok)
        self.assertIn("left as it was", result.message)
        self.assertEqual(tree(self.engine.profiles_dir / "work"), before)
        self.assertEqual(self.engine.profile_names(), ["work"])
        mock.patch.stopall()

    def test_a_failing_swap_puts_the_old_profile_back(self):
        from unittest import mock

        self.profiles.save("work").raise_for_status()
        old_content = (self.engine.profiles_dir / "work/configs/kdeglobals").read_text()
        write(self.home / ".config/kdeglobals", "kdeglobals-NEW")
        real_rename = os.rename
        calls = []

        def flaky_rename(source, target):
            calls.append((str(source), str(target)))
            if len(calls) == 2:  # moving the new copy into place
                raise OSError("simulated failure")
            return real_rename(source, target)

        with mock.patch("kongui.core.profiles.os.rename", side_effect=flaky_rename):
            result = self.profiles.replace("work", confirmed=True)
        self.assertFalse(result.ok)
        self.assertIn("simulated failure", result.message)
        self.assertIn("put back", " ".join(result.warnings))
        self.assertEqual(
            (self.engine.profiles_dir / "work/configs/kdeglobals").read_text(),
            old_content,
        )
        self.assertEqual(self.engine.profile_names(), ["work"])

    def test_a_failing_first_rename_keeps_everything(self):
        from unittest import mock

        self.profiles.save("work").raise_for_status()
        with mock.patch(
            "kongui.core.profiles.os.rename", side_effect=OSError("denied")
        ):
            result = self.profiles.replace("work", confirmed=True)
        self.assertFalse(result.ok)
        self.assertEqual(self.engine.profile_names(), ["work"])
        self.assertTrue((self.engine.profiles_dir / "work/conf.yaml").is_file())

    def test_a_crash_leftover_is_never_listed_as_a_profile(self):
        self.profiles.save("work").raise_for_status()
        (self.engine.profiles_dir / ".kongui-new-1-2-work").mkdir()
        self.assertEqual([p.name for p in self.profiles.list_profiles()], ["work"])
