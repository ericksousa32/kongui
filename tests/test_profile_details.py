"""Profile description and sections (core): storage, association and safety.

The description is a small file inside each profile folder
(``.kongui-profile.json``); the sections are read from the profile's own
``conf.yaml``. Everything runs against the real Konsave in a temporary home.
"""

from __future__ import annotations

import errno
import json
import os
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from kongui.core import (
    DESCRIPTION_NOT_REMOVED,
    DESCRIPTION_NOT_SAVED,
    MAX_DESCRIPTION_CHARS,
    ProfileNotFoundError,
    ValidationError,
)
from kongui.core.profilemeta import (
    META_FILENAME,
    MAX_META_BYTES,
    clean_description,
    profile_sections,
    read_description,
    write_description,
)
from tests.helpers import install_conf, BASE_CONF, make_knsv, write
from tests.test_profile_service_integration import IntegrationCase

TWO_GROUPS = """save:
    configs:
        location: "$HOME/.config"
        entries:
            - kdeglobals
    app_layouts:
        location: "$HOME/.local/share/kxmlgui5"
        entries:
            - dolphin
    autostart:
        location: "$HOME/.config/autostart"
        entries:
export:
    share_folder:
        location: "$HOME/.local/share"
        entries:
            - icons
"""


class DetailsCase(IntegrationCase):
    """Services plus small helpers."""

    def folder(self, name):
        return self.engine.profiles_dir / name

    def details(self, *names, profiles=None):
        return (profiles or self.profiles).profile_details(names)

    def new_service_on_same_home(self):
        """A second service object over the same folders ("restart")."""
        return self.new_services()[2]

    @staticmethod
    def archive_contents(path):
        """Names and bytes of every member of a ``.knsv``."""
        with zipfile.ZipFile(path) as handle:
            return {name: handle.read(name) for name in handle.namelist()}


class PersistenceTests(DetailsCase):
    """1. Metadata is stored, read back, survives a restart and can change."""

    def test_a_description_is_stored_and_read_back(self):
        self.profiles.save("work").raise_for_status()
        self.assertEqual(self.details("work")["work"].description, "")
        result = self.profiles.set_description("work", "Dark theme\nand shortcuts")
        self.assertTrue(result.ok, result.message)
        self.assertEqual(
            self.details("work")["work"].description, "Dark theme\nand shortcuts"
        )
        stored = json.loads((self.folder("work") / META_FILENAME).read_text("utf-8"))
        self.assertEqual(stored["description"], "Dark theme\nand shortcuts")

    def test_the_description_survives_a_new_service(self):
        self.profiles.save("work", description="Kept").raise_for_status()
        again = self.new_service_on_same_home()
        self.assertEqual(
            self.details("work", profiles=again)["work"].description, "Kept"
        )

    def test_changing_and_clearing_replace_the_old_value(self):
        self.profiles.save("work", description="First").raise_for_status()
        self.profiles.set_description("work", "Second")
        self.assertEqual(self.details("work")["work"].description, "Second")
        self.profiles.set_description("work", "")
        self.assertEqual(self.details("work")["work"].description, "")
        self.assertFalse((self.folder("work") / META_FILENAME).exists())

    def test_saving_again_keeps_the_description_unless_a_new_one_is_given(self):
        self.profiles.save("work", description="Keep me").raise_for_status()
        self.profiles.save("work", overwrite=True).raise_for_status()
        self.assertEqual(self.details("work")["work"].description, "Keep me")
        self.profiles.save("work", overwrite=True, description="New").raise_for_status()
        self.assertEqual(self.details("work")["work"].description, "New")

    def test_replacing_a_profile_carries_the_description_over(self):
        self.profiles.save("work", description="Carried").raise_for_status()
        write(self.home / ".config" / "kdeglobals", "kdeglobals-B")
        self.profiles.replace("work", confirmed=True).raise_for_status()
        self.assertEqual(self.details("work")["work"].description, "Carried")
        self.assertEqual(
            (self.folder("work") / "configs" / "kdeglobals").read_text(),
            "kdeglobals-B",
        )

    def test_unknown_profiles_and_bad_input(self):
        with self.assertRaises(ProfileNotFoundError):
            self.profiles.set_description("ghost", "x")
        self.profiles.save("work").raise_for_status()
        with self.assertRaises(ValidationError):
            self.profiles.set_description("../work", "x")
        self.assertEqual(self.details("ghost", "../work", ""), {})


class IsolationTests(DetailsCase):
    """2. A profile's details never leak into or change another's."""

    def test_editing_one_profile_leaves_the_other_alone(self):
        self.profiles.save("a", description="About A").raise_for_status()
        self.profiles.save("b", description="About B").raise_for_status()
        self.profiles.set_description("a", "Changed A")
        found = self.details("a", "b")
        self.assertEqual(found["a"].description, "Changed A")
        self.assertEqual(found["b"].description, "About B")


class RenameTests(DetailsCase):
    """3. The details live in the folder, so a renamed folder keeps them."""

    def test_the_description_follows_a_renamed_folder(self):
        self.profiles.save("old", description="Mine").raise_for_status()
        self.profiles.save("other", description="Not mine").raise_for_status()
        os.rename(self.folder("old"), self.folder("renamed"))
        found = self.details("old", "renamed", "other")
        self.assertNotIn("old", found)
        self.assertEqual(found["renamed"].description, "Mine")
        self.assertEqual(found["other"].description, "Not mine")

    def test_the_file_does_not_depend_on_the_profile_name(self):
        self.profiles.save("work", description="Text").raise_for_status()
        raw = (self.folder("work") / META_FILENAME).read_text("utf-8")
        self.assertNotIn("work", raw)


class ImportTests(DetailsCase):
    """4. Imported profiles start with defaults; nothing is attached by name."""

    def archive(self, name, extra=None):
        members = {"conf.yaml": BASE_CONF, "save/configs/kdeglobals": "imported"}
        members.update(extra or {})
        return make_knsv(self.work / f"{name}.knsv", members)

    def test_an_imported_profile_has_default_details_and_is_usable(self):
        self.profiles.save("existing", description="Stays").raise_for_status()
        result = self.profiles.import_profile(self.archive("fresh"), confirmed=True)
        self.assertTrue(result.ok, result.message)
        found = self.details("fresh", "existing")
        self.assertEqual(found["fresh"].description, "")
        self.assertEqual(found["fresh"].sections, ("configs",))
        self.assertEqual(found["existing"].description, "Stays")
        self.assertTrue(self.profiles.apply("fresh", confirmed=True).ok)

    def test_a_description_planted_in_an_archive_is_dropped(self):
        planted = json.dumps({"version": 1, "description": "planted"})
        archive = self.archive("trojan", {f"save/{META_FILENAME}": planted})
        result = self.profiles.import_profile(archive, confirmed=True)
        self.assertTrue(result.ok, result.message)
        self.assertFalse((self.folder("trojan") / META_FILENAME).exists())
        self.assertEqual(self.details("trojan")["trojan"].description, "")

    def test_a_planted_description_does_not_replace_the_name_based_one(self):
        self.profiles.save("work", description="Mine").raise_for_status()
        archive = self.archive(
            "work2",
            {f"save/{META_FILENAME}": json.dumps({"version": 1, "description": "x"})},
        )
        self.profiles.import_profile(archive, confirmed=True).raise_for_status()
        self.assertEqual(self.details("work")["work"].description, "Mine")

    def test_failing_to_drop_the_planted_file_is_a_warning_not_a_failure(self):
        planted = json.dumps({"version": 1, "description": "planted"})
        archive = self.archive("trojan", {f"save/{META_FILENAME}": planted})
        with mock.patch(
            "kongui.core.profiles.remove_description",
            side_effect=OSError(errno.EACCES, "Permission denied"),
        ):
            result = self.profiles.import_profile(archive, confirmed=True)
        self.assertTrue(result.ok)
        self.assertTrue(
            any(line.startswith(DESCRIPTION_NOT_REMOVED) for line in result.warnings)
        )


class DeleteTests(DetailsCase):
    """5. Removing a profile takes its details along and spares the others."""

    def test_remove_and_wipe(self):
        self.profiles.save("a", description="A").raise_for_status()
        self.profiles.save("b", description="B").raise_for_status()
        self.profiles.remove("a", confirmed=True).raise_for_status()
        self.assertFalse(self.folder("a").exists())
        self.assertEqual(list(self.details("a", "b")), ["b"])
        self.assertEqual(self.details("b")["b"].description, "B")
        # A new profile with the same name does not inherit anything.
        self.profiles.save("a").raise_for_status()
        self.assertEqual(self.details("a")["a"].description, "")
        self.profiles.wipe_all(confirmed=True).raise_for_status()
        self.assertEqual(self.details("a", "b"), {})


class MissingStorageTests(DetailsCase):
    """6. There is nothing to initialise: no file means no description."""

    def test_a_home_without_any_metadata_works(self):
        self.assertEqual(self.details("anything"), {})
        self.assertEqual(self.profiles.list_profiles(), [])
        self.profiles.save("first").raise_for_status()
        self.assertEqual(self.details("first")["first"].description, "")
        self.profiles.set_description("first", "Created on demand")
        self.assertTrue((self.folder("first") / META_FILENAME).is_file())

    def test_the_real_home_is_never_used(self):
        self.assertTrue(str(self.engine.profiles_dir).startswith(str(self.base)))


class KonsaveCompatibilityTests(DetailsCase):
    """7. The Konsave files and the ``.knsv`` are not touched."""

    def test_editing_the_description_changes_nothing_else(self):
        self.profiles.save("work").raise_for_status()
        folder = self.folder("work")
        os.utime(folder, (1_000_000_000, 1_000_000_000))
        before = sorted(p.relative_to(folder) for p in folder.rglob("*"))
        conf = (folder / "conf.yaml").read_bytes()
        self.profiles.set_description("work", "A description")
        after = sorted(
            p.relative_to(folder) for p in folder.rglob("*") if p.name != META_FILENAME
        )
        self.assertEqual(before, after)
        self.assertEqual((folder / "conf.yaml").read_bytes(), conf)
        self.assertEqual(folder.stat().st_mtime_ns, 1_000_000_000 * 10**9)
        self.assertEqual(
            [p.name for p in folder.iterdir() if p.name.startswith(META_FILENAME)],
            [META_FILENAME],
            "no temporary file is left behind",
        )

    def test_the_exported_archive_does_not_depend_on_the_description(self):
        self.profiles.save("work").raise_for_status()
        out = self.base / "out"
        out.mkdir()
        self.profiles.export(
            "work", directory=out, archive_name="before"
        ).raise_for_status()
        self.profiles.set_description("work", "Changed afterwards")
        self.profiles.export(
            "work", directory=out, archive_name="after"
        ).raise_for_status()
        first = self.archive_contents(out / "before.knsv")
        second = self.archive_contents(out / "after.knsv")
        self.assertEqual(first, second)
        self.assertFalse([name for name in second if "kongui" in name])

    def test_apply_still_works_with_a_description(self):
        self.profiles.save("work", description="x").raise_for_status()
        write(self.home / ".config" / "kdeglobals", "changed")
        self.assertTrue(self.profiles.apply("work", confirmed=True).ok)
        self.assertEqual(
            (self.home / ".config" / "kdeglobals").read_text(), "kdeglobals-A"
        )


class FailureTests(DetailsCase):
    """8. A write that fails is reported, never shown as done."""

    def full_disk(self):
        return mock.patch(
            "kongui.core.profilemeta.os.replace",
            side_effect=OSError(errno.ENOSPC, "No space left on device"),
        )

    def test_set_description_raises_and_keeps_the_old_text(self):
        self.profiles.save("work", description="Old").raise_for_status()
        with self.full_disk():
            with self.assertRaises(OSError):
                self.profiles.set_description("work", "New")
        self.assertEqual(self.details("work")["work"].description, "Old")
        self.assertEqual(
            [p.name for p in self.folder("work").iterdir() if "tmp" in p.name], []
        )

    def test_a_save_whose_description_fails_is_a_warning(self):
        with self.full_disk():
            result = self.profiles.save("work", description="Lost")
        self.assertTrue(result.ok, "the profile itself was saved")
        self.assertTrue(
            any(line.startswith(DESCRIPTION_NOT_SAVED) for line in result.warnings)
        )
        self.assertIn("No space left", " ".join(result.warnings))
        self.assertEqual(self.details("work")["work"].description, "")

    def test_a_replace_that_cannot_carry_the_description_changes_nothing(self):
        self.profiles.save("work", description="Keep").raise_for_status()
        write(self.home / ".config" / "kdeglobals", "kdeglobals-B")
        with self.full_disk():
            result = self.profiles.replace("work", confirmed=True)
        self.assertFalse(result.ok)
        self.assertIn("description could not be carried over", result.message)
        self.assertEqual(self.details("work")["work"].description, "Keep")
        self.assertEqual(
            (self.folder("work") / "configs" / "kdeglobals").read_text(), "kdeglobals-A"
        )
        self.assertEqual([p.name for p in self.engine.profiles_dir.iterdir()], ["work"])

    def test_a_too_long_description_is_refused_before_anything_is_written(self):
        with self.assertRaises(ValidationError):
            self.profiles.save("work", description="x" * (MAX_DESCRIPTION_CHARS + 1))
        self.assertFalse(self.folder("work").exists())
        self.profiles.save("work").raise_for_status()
        with self.assertRaises(ValidationError):
            self.profiles.set_description("work", "x" * (MAX_DESCRIPTION_CHARS + 1))
        self.assertEqual(self.details("work")["work"].description, "")


class ReadingIsDefensiveTests(DetailsCase):
    """A folder can come from anywhere: a bad file means no description."""

    def put(self, name, content):
        self.profiles.save(name).raise_for_status()
        path = self.folder(name) / META_FILENAME
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        return self.folder(name)

    def test_bad_files_read_as_empty(self):
        cases = {
            "garbage": b"\xff\xfe not json",
            "list": "[1, 2]",
            "nodesc": json.dumps({"version": 1}),
            "number": json.dumps({"version": 1, "description": 5}),
            "future": json.dumps({"version": 2, "description": "from later"}),
            "oversized": json.dumps(
                {"version": 1, "description": "x" * MAX_META_BYTES}
            ),
        }
        for label, content in cases.items():
            with self.subTest(case=label):
                folder = self.put(label, content)
                self.assertEqual(read_description(folder), "")
        self.assertEqual(
            self.details(*cases)["garbage"].description, "", "listing still works"
        )

    def test_a_link_instead_of_a_file_is_ignored(self):
        folder = self.put("linked", "{}")
        target = self.base / "outside.json"
        target.write_text(json.dumps({"version": 1, "description": "outside"}))
        (folder / META_FILENAME).unlink()
        os.symlink(target, folder / META_FILENAME)
        self.assertEqual(read_description(folder), "")

    def test_a_long_stored_text_is_cut_not_trusted(self):
        folder = self.put("long", json.dumps({"version": 1, "description": "y" * 2000}))
        self.assertEqual(len(read_description(folder)), MAX_DESCRIPTION_CHARS)


class CleaningTests(unittest.TestCase):
    """The text that is kept is plain and printable."""

    def test_normalisation(self):
        self.assertEqual(clean_description("  a\r\nb\rc  "), "a\nb\nc")
        self.assertEqual(clean_description("a\x00b\x07c\tz"), "abc\tz")
        self.assertEqual(clean_description("a‮b"), "ab")
        self.assertEqual(clean_description("café ☕ 日本語"), "café ☕ 日本語")
        self.assertEqual(clean_description(""), "")

    def test_the_limit_counts_characters(self):
        self.assertEqual(len(clean_description("é" * MAX_DESCRIPTION_CHARS)), 500)
        with self.assertRaises(ValidationError):
            clean_description("é" * (MAX_DESCRIPTION_CHARS + 1))
        self.assertEqual(
            len(clean_description("é" * 900, truncate=True)), MAX_DESCRIPTION_CHARS
        )

    def test_only_text_is_accepted(self):
        with self.assertRaises(ValidationError):
            clean_description(None)

    def test_markup_is_kept_as_plain_text(self):
        self.assertEqual(clean_description("<b>x</b>"), "<b>x</b>")


class SectionsTests(DetailsCase):
    """Sections: the ``save`` groups of the profile that hold files."""

    def setUp(self):
        super().setUp()
        install_conf(self.config, TWO_GROUPS)
        write(self.home / ".config" / "kdeglobals", "x")

    def test_empty_groups_are_hidden(self):
        self.profiles.save("work").raise_for_status()
        folder = self.folder("work")
        self.assertTrue((folder / "app_layouts").is_dir(), "Konsave makes the folder")
        self.assertEqual(profile_sections(folder), ("configs",))
        self.assertEqual(self.details("work")["work"].sections, ("configs",))

    def test_a_group_with_a_file_shows_in_the_order_of_the_conf(self):
        write(self.home / ".local/share/kxmlgui5/dolphin/ui.rc", "x")
        self.profiles.save("work").raise_for_status()
        self.assertEqual(
            profile_sections(self.folder("work")), ("configs", "app_layouts")
        )

    def test_sections_come_from_the_profile_not_from_the_current_conf(self):
        self.profiles.save("work").raise_for_status()
        install_conf(self.config, BASE_CONF)
        self.assertEqual(profile_sections(self.folder("work")), ("configs",))

    def test_odd_configurations_never_raise(self):
        folder = self.base / "odd"
        folder.mkdir()
        self.assertEqual(profile_sections(folder), ())
        (folder / "conf.yaml").write_text("save: [unclosed")
        self.assertEqual(profile_sections(folder), ())
        (folder / "conf.yaml").write_text("- just\n- a list\n")
        self.assertEqual(profile_sections(folder), ())
        (folder / "conf.yaml").write_text(
            "save:\n  ../escape:\n    entries: []\n  ok:\n    entries: []\n"
        )
        write(self.base / "escape" / "file", "x")
        write(folder / "ok" / "file", "x")
        self.assertEqual(
            profile_sections(folder), ("ok",), "a group cannot leave the folder"
        )

    def test_a_linked_group_folder_does_not_count(self):
        folder = self.base / "linked"
        folder.mkdir()
        (folder / "conf.yaml").write_text("save:\n  configs:\n    entries: []\n")
        outside = self.base / "outside"
        write(outside / "file", "x")
        os.symlink(outside, folder / "configs")
        self.assertEqual(profile_sections(folder), ())

    def test_unknown_group_names_are_kept_as_they_are(self):
        folder = self.base / "custom"
        folder.mkdir()
        (folder / "conf.yaml").write_text("save:\n  my_vim:\n    entries: []\n")
        write(folder / "my_vim" / "vimrc", "x")
        self.assertEqual(profile_sections(folder), ("my_vim",))


class WriteHelperTests(unittest.TestCase):
    """The file helper on its own."""

    def test_write_is_atomic_and_keeps_the_folder_time(self):
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            os.utime(folder, (1_100_000_000, 1_100_000_000))
            write_description(folder, "hello")
            self.assertEqual(read_description(folder), "hello")
            self.assertEqual(folder.stat().st_mtime_ns, 1_100_000_000 * 10**9)
            write_description(folder, "")
            self.assertFalse((folder / META_FILENAME).exists())
            self.assertEqual(os.listdir(folder), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
