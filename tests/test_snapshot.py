"""Safety copies before apply/import (RN-01): make, list, restore, delete.

Everything runs the real Konsave code inside temporary homes.
"""

import json
from pathlib import Path
import os
import stat
from unittest import mock

from kongui.core import (
    ConfirmationRequiredError,
    SnapshotError,
    SnapshotNotFoundError,
    ValidationError,
)
from tests.helpers import BASE_CONF, IsolatedHomeTestCase, make_knsv, write


class SnapshotCase(IsolatedHomeTestCase):
    """A home with live files and one saved profile."""

    def setUp(self):
        super().setUp()
        self.engine, self.config, self.profiles = self.new_services()
        self.populate_live()
        self.profiles.save("work").raise_for_status()
        self.kde = self.home / ".config/kdeglobals"

    def only_copy(self):
        (copy,) = self.profiles.list_backups()
        return copy


class ApplySnapshotTests(SnapshotCase):
    """apply keeps what it overwrites."""

    def test_overwritten_file_comes_back_with_its_content_and_mode(self):
        self.kde.write_text("MINE")
        os.chmod(self.kde, 0o640)
        result = self.profiles.apply("work", confirmed=True)
        self.assertTrue(result.ok, result.message)
        self.assertEqual(self.kde.read_text(), "kdeglobals-A")
        copy = self.only_copy()
        self.assertEqual(copy.operation, "apply")
        self.assertEqual(copy.profile, "work")
        self.assertIs(copy.succeeded, True)
        self.assertGreaterEqual(copy.replaced, 1)
        restored = self.profiles.restore_backup(copy.id, confirmed=True)
        self.assertTrue(restored.ok, restored.message)
        self.assertEqual(self.kde.read_text(), "MINE")
        self.assertEqual(stat.S_IMODE(os.stat(self.kde).st_mode), 0o640)

    def test_the_copy_folder_is_private(self):
        self.kde.write_text("MINE")
        self.profiles.apply("work", confirmed=True).raise_for_status()
        copy = self.only_copy()
        self.assertEqual(stat.S_IMODE(os.stat(copy.path).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(copy.path.parent).st_mode), 0o700)

    def test_files_and_folders_the_apply_created_are_removed_on_restore(self):
        for path in (self.kde, self.home / ".config/gtk-3.0/settings.ini"):
            path.unlink()
        (self.home / ".config/gtk-3.0").rmdir()
        self.profiles.apply("work", confirmed=True).raise_for_status()
        self.assertTrue(self.kde.exists())
        copy = self.only_copy()
        self.assertEqual(copy.replaced, 0)
        self.assertEqual(copy.created_files, 2)
        self.profiles.restore_backup(copy.id, confirmed=True).raise_for_status()
        self.assertFalse(self.kde.exists())
        self.assertFalse((self.home / ".config/gtk-3.0").exists())

    def test_files_that_were_not_touched_stay_as_they_are(self):
        extra = self.home / ".config/gtk-3.0/extra.ini"
        write(extra, "extra")
        self.kde.write_text("MINE")
        self.profiles.apply("work", confirmed=True).raise_for_status()
        extra.write_text("changed after the apply")
        self.profiles.restore_backup(self.only_copy().id, confirmed=True)
        self.assertEqual(extra.read_text(), "changed after the apply")

    def test_a_symlink_is_replaced_and_recreated(self):
        real = self.home / "elsewhere.txt"
        real.write_text("REAL")
        self.kde.unlink()
        self.kde.symlink_to(real)
        self.profiles.apply("work", confirmed=True).raise_for_status()
        self.assertFalse(self.kde.is_symlink())
        self.profiles.restore_backup(self.only_copy().id, confirmed=True)
        self.assertTrue(self.kde.is_symlink())
        self.assertEqual(os.readlink(self.kde), str(real))
        self.assertEqual(real.read_text(), "REAL")

    def test_if_the_copy_fails_nothing_is_applied(self):
        self.kde.write_text("MINE")
        with mock.patch(
            "kongui.core.snapshot.shutil.copy2", side_effect=OSError("disk full")
        ):
            with self.assertRaises(SnapshotError) as caught:
                self.profiles.apply("work", confirmed=True)
        self.assertIn("nothing was changed", str(caught.exception))
        self.assertEqual(self.kde.read_text(), "MINE")
        self.assertEqual(self.profiles.list_backups(), [])
        self.assertEqual(os.listdir(self.engine.konsave_dir / "kongui-backups"), [])

    def test_an_unwritable_copy_folder_stops_the_apply(self):
        self.kde.write_text("MINE")
        (self.engine.konsave_dir / "kongui-backups").write_text("in the way")
        with self.assertRaises(SnapshotError):
            self.profiles.apply("work", confirmed=True)
        self.assertEqual(self.kde.read_text(), "MINE")

    def test_the_result_names_the_copy(self):
        result = self.profiles.apply("work", confirmed=True)
        self.assertEqual(result.backup, self.only_copy().path)
        self.assertTrue(any("safety copy kept" in w for w in result.warnings))

    def test_a_refused_apply_makes_no_copy(self):
        with self.assertRaises(ConfirmationRequiredError):
            self.profiles.apply("work")
        self.assertEqual(self.profiles.list_backups(), [])


class ImportSnapshotTests(SnapshotCase):
    """import keeps what its export section overwrites."""

    def archive(self):
        members = {
            "conf.yaml": BASE_CONF,
            "save/configs/kdeglobals": "saved",
            "export/share_folder/icons/theme.txt": "FROM-ARCHIVE",
            "export/share_folder/icons/new.txt": "NEW",
            "export/share_folder/other/ignored.txt": "IGNORED",
        }
        return make_knsv(self.work / "incoming.knsv", members)

    def test_import_keeps_and_restores_the_overwritten_files(self):
        theme = self.home / ".local/share/icons/theme.txt"
        result = self.profiles.import_profile(self.archive(), confirmed=True)
        self.assertTrue(result.ok, result.message)
        self.assertEqual(theme.read_text(), "FROM-ARCHIVE")
        copy = self.only_copy()
        self.assertEqual((copy.operation, copy.profile), ("import", "incoming"))
        self.assertEqual((copy.replaced, copy.created_files), (1, 1))
        self.profiles.restore_backup(copy.id, confirmed=True).raise_for_status()
        self.assertEqual(theme.read_text(), "theme-A")
        self.assertFalse((self.home / ".local/share/icons/new.txt").exists())
        self.assertTrue(
            (self.engine.profiles_dir / "incoming").is_dir(), "the profile stays"
        )

    def test_a_refused_import_makes_no_copy(self):
        with self.assertRaises(ConfirmationRequiredError):
            self.profiles.import_profile(self.archive())
        self.assertEqual(self.profiles.list_backups(), [])

    def test_if_the_copy_fails_nothing_is_imported(self):
        with mock.patch(
            "kongui.core.snapshot.shutil.copy2", side_effect=OSError("no space")
        ):
            with self.assertRaises(SnapshotError):
                self.profiles.import_profile(self.archive(), confirmed=True)
        self.assertEqual(
            (self.home / ".local/share/icons/theme.txt").read_text(), "theme-A"
        )
        self.assertNotIn("incoming", self.engine.profile_names())


class RestoreRulesTests(SnapshotCase):
    """Confirmation, ids, damaged copies and partial failures."""

    def make_copy(self):
        self.kde.write_text("MINE")
        self.profiles.apply("work", confirmed=True).raise_for_status()
        return self.only_copy()

    def test_restore_and_delete_need_a_real_true(self):
        copy = self.make_copy()
        for flag in (False, 1, "yes"):
            with self.subTest(flag=flag):
                with self.assertRaises(ConfirmationRequiredError):
                    self.profiles.restore_backup(copy.id, confirmed=flag)
                with self.assertRaises(ConfirmationRequiredError):
                    self.profiles.delete_backup(copy.id, confirmed=flag)
        self.assertEqual(self.kde.read_text(), "kdeglobals-A")
        self.assertTrue(copy.path.is_dir())

    def test_ids_cannot_escape_the_folder(self):
        for bad in ("../x", "", "20200101-000000-000000-apply/..", None, 5):
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    self.profiles.restore_backup(bad, confirmed=True)
                with self.assertRaises(ValidationError):
                    self.profiles.delete_backup(bad, confirmed=True)

    def test_unknown_id(self):
        with self.assertRaises(SnapshotNotFoundError):
            self.profiles.restore_backup("20200101-000000-000000-apply", confirmed=True)

    def test_restore_keeps_the_current_state_as_a_new_copy(self):
        copy = self.make_copy()
        result = self.profiles.restore_backup(copy.id, confirmed=True)
        self.assertEqual(self.kde.read_text(), "MINE")
        self.assertEqual(len(self.profiles.list_backups()), 2)
        undo = self.profiles.list_backups()[0]
        self.assertEqual(undo.operation, "restore")
        self.assertEqual(result.backup, undo.path)
        self.profiles.restore_backup(undo.id, confirmed=True).raise_for_status()
        self.assertEqual(self.kde.read_text(), "kdeglobals-A")

    def edit_manifest(self, copy, change):
        path = copy.path / "manifest.json"
        data = json.loads(path.read_text())
        change(data)
        path.write_text(json.dumps(data))

    def test_a_tampered_path_outside_home_is_refused_untouched(self):
        copy = self.make_copy()
        outside = self.work / "outside.txt"
        outside.write_text("keep")
        self.edit_manifest(copy, lambda d: d["entries"][0].update(path=str(outside)))
        with self.assertRaises(ValidationError):
            self.profiles.restore_backup(copy.id, confirmed=True)
        self.assertEqual(outside.read_text(), "keep")
        self.assertEqual(self.kde.read_text(), "kdeglobals-A")

    def test_damaged_copies_are_reported_not_applied(self):
        copy = self.make_copy()
        stored = next(p for p in (copy.path / "files").iterdir())
        stored.unlink()
        with self.assertRaises(SnapshotError):
            self.profiles.restore_backup(copy.id, confirmed=True)
        (copy.path / "manifest.json").write_text("{not json")
        listed = self.profiles.list_backups()[0]
        self.assertTrue(listed.problem)
        with self.assertRaises(SnapshotError):
            self.profiles.restore_backup(copy.id, confirmed=True)
        self.assertEqual(self.kde.read_text(), "kdeglobals-A")

    def test_stored_names_cannot_point_elsewhere(self):
        copy = self.make_copy()
        self.edit_manifest(copy, lambda d: d["entries"][0].update(stored="../../x"))
        with self.assertRaises(SnapshotError):
            self.profiles.restore_backup(copy.id, confirmed=True)

    def test_one_path_failing_does_not_stop_the_others(self):
        self.kde.write_text("MINE")
        gtk = self.home / ".config/gtk-3.0/settings.ini"
        gtk.write_text("MINE-GTK")
        self.profiles.apply("work", confirmed=True).raise_for_status()
        copy = self.only_copy()
        gtk.unlink()
        gtk.mkdir()  # a folder where a file must go back
        result = self.profiles.restore_backup(copy.id, confirmed=True)
        self.assertFalse(result.ok)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("settings.ini", result.errors[0])
        self.assertEqual(self.kde.read_text(), "MINE")

    def test_delete_removes_only_that_copy_and_nothing_is_pruned(self):
        first = self.make_copy()
        for _ in range(24):
            self.profiles.apply("work", confirmed=True).raise_for_status()
        self.assertEqual(len(self.profiles.list_backups()), 25)
        result = self.profiles.delete_backup(first.id, confirmed=True)
        self.assertTrue(result.ok)
        self.assertEqual(len(self.profiles.list_backups()), 24)
        with self.assertRaises(SnapshotNotFoundError):
            self.profiles.delete_backup(first.id, confirmed=True)

    def test_listing_ignores_foreign_names_and_is_newest_first(self):
        self.make_copy()
        self.profiles.apply("work", confirmed=True).raise_for_status()
        (self.engine.konsave_dir / "kongui-backups" / "notes.txt").write_text("x")
        ids = [c.id for c in self.profiles.list_backups()]
        self.assertEqual(ids, sorted(ids, reverse=True))
        self.assertEqual(len(ids), 2)

    def test_a_failed_apply_is_recorded_as_failed(self):
        self.kde.write_text("MINE")
        original = self.engine.call

        def failing(name, *args, **kwargs):
            call = original(name, *args, **kwargs)
            if name == "apply_profile":
                return type(call)(
                    name, None, call.stdout, call.stderr, ("boom",), RuntimeError("x")
                )
            return call

        with mock.patch.object(self.engine, "call", side_effect=failing):
            result = self.profiles.apply("work", confirmed=True)
        self.assertFalse(result.ok)
        self.assertIs(self.only_copy().succeeded, False)


FILE_ENTRY_CONF = """---
save:
    configs:
        location: "$HOME/.config"
        entries:
            - kdeglobals
export:
    icons:
        location: "$HOME/.local/share/icons"
        entries:
            - theme.txt
...
"""


class EdgeCaseTests(SnapshotCase):
    """Rarer paths: links written through, odd manifests, failing disks."""

    def test_an_import_that_writes_through_a_link_gets_the_target_back(self):
        real = self.work / "shared-theme.txt"
        real.write_text("TARGET-BEFORE")
        theme = self.home / ".local/share/icons/theme.txt"
        theme.unlink()
        theme.symlink_to(real)
        archive = make_knsv(
            self.work / "linked.knsv",
            {
                "conf.yaml": FILE_ENTRY_CONF,
                "save/configs/kdeglobals": "saved",
                "export/icons/theme.txt": "FROM-ARCHIVE",
            },
        )
        # the destination is outside the home on purpose: allowed explicitly
        self.profiles.import_profile(
            archive, confirmed=True, allow_outside_home=True
        ).raise_for_status()
        self.assertEqual(real.read_text(), "FROM-ARCHIVE")
        copy = self.only_copy()
        with self.assertRaises(ValidationError):
            self.profiles.restore_backup(copy.id, confirmed=True)
        self.assertEqual(real.read_text(), "FROM-ARCHIVE", "refused untouched")
        self.profiles.restore_backup(
            copy.id, confirmed=True, allow_outside_home=True
        ).raise_for_status()
        self.assertEqual(real.read_text(), "TARGET-BEFORE")
        self.assertTrue(theme.is_symlink())

    def test_a_non_empty_folder_the_apply_created_is_kept(self):
        gtk = self.home / ".config/gtk-3.0"
        (gtk / "settings.ini").unlink()
        gtk.rmdir()
        self.profiles.apply("work", confirmed=True).raise_for_status()
        write(gtk / "mine.ini", "added later")
        self.profiles.restore_backup(self.only_copy().id, confirmed=True)
        self.assertEqual((gtk / "mine.ini").read_text(), "added later")
        self.assertFalse((gtk / "settings.ini").exists())

    def test_damaged_manifests_are_refused_one_by_one(self):
        self.kde.write_text("MINE")
        self.profiles.apply("work", confirmed=True).raise_for_status()
        copy = self.only_copy()
        path = copy.path / "manifest.json"
        good = json.loads(path.read_text())
        broken = {
            "not a dict": [1, 2],
            "wrong version": {**good, "version": 99},
            "entry not a dict": {**good, "entries": ["x"]},
            "relative path": {**good, "entries": [{"path": "a", "kind": "created"}]},
            "unknown kind": {
                **good,
                "entries": [{"path": str(self.kde), "kind": "weird"}],
            },
            "link without text": {
                **good,
                "entries": [{"path": str(self.kde), "kind": "symlink"}],
            },
        }
        for label, data in broken.items():
            with self.subTest(label):
                path.write_text(json.dumps(data))
                with self.assertRaises(SnapshotError):
                    self.profiles.restore_backup(copy.id, confirmed=True)
        self.assertEqual(self.kde.read_text(), "kdeglobals-A")

    def test_unknown_operations_and_relative_destinations_are_programming_errors(self):
        service = self.profiles._snapshots  # pylint: disable=protected-access
        with self.assertRaises(ValueError):
            service.create("explode", "x", [self.kde])
        with self.assertRaises(SnapshotError):
            service.create("apply", "x", [Path("relative/file")])
        self.assertIsNone(service.create("apply", "x", []))
        self.assertEqual(self.profiles.list_backups(), [])

    def test_a_folder_in_the_way_of_a_planned_write_is_not_copied(self):
        self.kde.unlink()
        self.kde.mkdir()  # the original will fail on this by itself
        self.profiles.apply("work", confirmed=True)
        (copy,) = self.profiles.list_backups()
        manifest = json.loads((copy.path / "manifest.json").read_text())
        self.assertNotIn(str(self.kde), [e["path"] for e in manifest["entries"]])

    def test_a_link_loop_in_the_profile_does_not_hang_the_plan(self):
        profile = self.engine.profiles_dir / "work/configs"
        (profile / "loop").symlink_to(profile)
        files = self.profiles._snapshots.destinations_of_apply(  # pylint: disable=protected-access
            {"configs": {"location": str(self.home / ".config")}},
            self.engine.profiles_dir / "work",
        )
        self.assertTrue(files)

    def test_the_record_of_the_outcome_may_fail_without_failing_the_apply(self):
        real_write = __import__("kongui.core.snapshot", fromlist=["x"])._write_json
        calls = []

        def flaky(path, data):
            calls.append(path)
            if len(calls) == 2:
                raise OSError("read-only")
            real_write(path, data)

        with mock.patch("kongui.core.snapshot._write_json", side_effect=flaky):
            result = self.profiles.apply("work", confirmed=True)
        self.assertTrue(result.ok)
        self.assertTrue(any("could not update" in w for w in result.warnings))

    def test_listing_an_unreadable_folder_and_deleting_failures(self):
        self.profiles.apply("work", confirmed=True).raise_for_status()
        copy = self.only_copy()
        with mock.patch("kongui.core.snapshot.os.listdir", side_effect=OSError("no")):
            with self.assertRaises(SnapshotError):
                self.profiles.list_backups()
        with mock.patch(
            "kongui.core.snapshot.shutil.rmtree", side_effect=OSError("no")
        ):
            with self.assertRaises(SnapshotError):
                self.profiles.delete_backup(copy.id, confirmed=True)
        self.assertTrue(copy.path.is_dir())
        self.assertEqual(self.profiles.list_backups()[0].id, copy.id)
        self.assertEqual(
            self.profiles._snapshots.get(copy.id).id, copy.id
        )  # pylint: disable=protected-access
        self.assertEqual(
            self.profiles._snapshots.root.name,
            "kongui-backups",  # pylint: disable=protected-access
        )

    def test_a_missing_backup_folder_lists_nothing(self):
        self.assertEqual(self.profiles.list_backups(), [])
