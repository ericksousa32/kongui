"""Export and import through ``ServiceBackend``: real Konsave, temporary homes.

Everything runs inside private temporary folders (two separate "homes" for the
round trip); the real session is never touched and the tests refuse to run as
root. Archives are checked against the layout of the original ``.knsv`` and
against the genuine ``python -m konsave`` command, in both directions.
"""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from kongui.core import (
    ArchiveExistsError,
    CliRunner,
    ConfigService,
    ConfigValidationError,
    ConfirmationRequiredError,
    KonsaveEngine,
    ProfileExistsError,
    ProfileNotFoundError,
    ProfileService,
    ValidationError,
)
from kongui.gui.backend import ServiceBackend
from tests.helpers import (
    BASE_CONF,
    IsolatedHomeTestCase,
    make_dist_info,
    make_knsv,
    non_root,
    really_root,
    write,
)


def digest(path: Path) -> str:
    """SHA-256 of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(folder: Path) -> dict:
    """Relative path -> content (``None`` for folders) of everything below ``folder``."""
    result = {}
    for base, dirs, files in os.walk(folder):
        for name in dirs:
            result[os.path.relpath(os.path.join(base, name), folder)] = None
        for name in files:
            full = Path(base) / name
            result[os.path.relpath(full, folder)] = full.read_bytes()
    return result


class TransferCase(IsolatedHomeTestCase):
    """Two homes (A and B) with the same Konsave configuration."""

    def make_home(self, name):
        """Creates a home with live files and returns ``(engine, service, backend)``."""
        home = self.base / name
        (home / ".config").mkdir(parents=True)
        (home / ".local/share").mkdir(parents=True)
        engine = KonsaveEngine(home, euid_provider=non_root)
        config = ConfigService(engine)
        config.write_text(BASE_CONF)
        service = ProfileService(engine, config)
        return engine, service, ServiceBackend(service)

    def setUp(self):
        super().setUp()
        self.engine_a, self.service_a, self.backend_a = self.make_home("a")
        self.engine_b, self.service_b, self.backend_b = self.make_home("b")
        self.live(self.engine_a.home, "A")
        self.live(self.engine_b.home, "B")
        self.backend_a.save("work").raise_for_status()
        self.out = self.base / "out"
        self.out.mkdir()

    @staticmethod
    def live(home, tag):
        """Writes the live files that ``BASE_CONF`` saves and exports."""
        write(home / ".config/kdeglobals", f"kdeglobals-{tag}")
        write(home / ".config/gtk-3.0/settings.ini", f"[Settings]{tag}")
        write(home / ".local/share/icons/theme.txt", f"theme-{tag}")

    def export(self, **kwargs):
        """Exports ``work`` from home A."""
        kwargs.setdefault("name", "work")
        kwargs.setdefault("directory", str(self.out))
        return self.backend_a.export_profile(**kwargs)


class ExportTests(TransferCase):
    """Export: -e (profile), -d (folder), -n (name), -f (conflict)."""

    def test_creates_a_standard_knsv(self):
        result = self.export()
        self.assertTrue(result.ok, result.message)
        archive = self.out / "work.knsv"
        self.assertEqual(result.path, archive)
        with zipfile.ZipFile(archive) as handle:
            names = set(handle.namelist())
            self.assertEqual(handle.read("conf.yaml").decode(), BASE_CONF)
        for expected in (
            "conf.yaml",
            "save/configs/kdeglobals",
            "save/configs/gtk-3.0/settings.ini",
            "export/share_folder/icons/theme.txt",
        ):
            self.assertIn(expected, names)
        self.assertEqual(sorted(os.listdir(self.out)), ["work.knsv"], "no leftovers")

    def test_custom_name_and_folder(self):
        target = self.out / "sub"
        target.mkdir()
        result = self.export(directory=str(target), archive_name="backup-2026")
        self.assertEqual(result.path, target / "backup-2026.knsv")
        self.assertEqual(os.listdir(self.out), ["sub"])

    def test_tilde_means_the_home_of_the_engine(self):
        (self.engine_a.home / "Downloads").mkdir()
        result = self.export(directory="~/Downloads")
        self.assertEqual(result.path, self.engine_a.home / "Downloads/work.knsv")

    def test_error_policy_never_replaces(self):
        self.export()
        before = digest(self.out / "work.knsv")
        write(self.engine_a.home / ".config/kdeglobals", "kdeglobals-NEW")
        with self.assertRaises(ArchiveExistsError):
            self.export(on_conflict="error")
        self.assertEqual(digest(self.out / "work.knsv"), before)

    def test_unique_policy_picks_a_free_name(self):
        self.export()
        second = self.export(on_conflict="unique")
        third = self.export(on_conflict="unique")
        self.assertEqual(second.path.name, "work-2.knsv")
        self.assertEqual(third.path.name, "work-3.knsv")
        self.assertEqual(
            sorted(os.listdir(self.out)), ["work-2.knsv", "work-3.knsv", "work.knsv"]
        )

    def test_overwrite_policy_replaces_only_a_regular_knsv(self):
        self.export()
        write(self.engine_a.home / ".config/kdeglobals", "kdeglobals-NEW")
        self.backend_a.overwrite("work", confirmed=True).raise_for_status()
        result = self.export(on_conflict="overwrite")
        self.assertTrue(result.ok, result.message)
        with zipfile.ZipFile(self.out / "work.knsv") as handle:
            self.assertEqual(
                handle.read("save/configs/kdeglobals").decode(), "kdeglobals-NEW"
            )
        self.assertEqual(os.listdir(self.out), ["work.knsv"])

    def test_a_folder_or_zip_with_that_name_is_never_deleted(self):
        folder = self.out / "work"
        folder.mkdir()
        write(folder / "precious.txt", "keep")
        write(self.out / "work.zip", "zip")
        for policy in ("error", "overwrite"):
            with self.subTest(policy=policy):
                with self.assertRaises(ArchiveExistsError):
                    self.export(on_conflict=policy)
        self.assertEqual((folder / "precious.txt").read_text(), "keep")
        self.assertEqual((self.out / "work.zip").read_text(), "zip")
        unique = self.export(on_conflict="unique")
        self.assertEqual(unique.path.name, "work-2.knsv")
        self.assertEqual((folder / "precious.txt").read_text(), "keep")

    def test_a_symlink_is_never_followed_or_replaced(self):
        target = write(self.base / "elsewhere.txt", "outside")
        (self.out / "work.knsv").symlink_to(target)
        with self.assertRaises(ArchiveExistsError):
            self.export(on_conflict="overwrite")
        self.assertEqual(target.read_text(), "outside")

    def test_invalid_file_names_are_refused(self):
        for bad in ("../x", "a/b", "", ".", "..", "x.knsv", "x.zip", "-rf", "a\nb"):
            with self.subTest(name=bad):
                if bad == "":
                    result = self.export(archive_name=bad)  # "" means default name
                    self.assertTrue(result.ok)
                    (self.out / "work.knsv").unlink()
                    continue
                with self.assertRaises(ValidationError):
                    self.export(archive_name=bad)
        self.assertEqual(os.listdir(self.out), [])

    def test_unknown_profile_and_bad_policy(self):
        with self.assertRaises(ProfileNotFoundError):
            self.export(name="ghost")
        with self.assertRaises(ValidationError):
            self.export(on_conflict="force")

    def test_folder_problems(self):
        with self.assertRaises(ValidationError):
            self.export(directory=str(self.out / "missing"))
        plain = write(self.out / "plain.txt")
        with self.assertRaises(ValidationError):
            self.export(directory=str(plain))
        locked = self.out / "locked"
        locked.mkdir()
        locked.chmod(stat.S_IRUSR | stat.S_IXUSR)
        self.addCleanup(locked.chmod, stat.S_IRWXU)
        with self.assertRaises(ValidationError) as caught:
            self.export(directory=str(locked))
        self.assertIn("not writable", str(caught.exception))
        self.assertEqual(os.listdir(locked), [])

    def test_probe_describes_the_target(self):
        probe = self.backend_a.probe_export(str(self.out), "work")
        self.assertEqual((probe.folder_problem, probe.conflict), ("", ""))
        self.assertEqual(probe.path, str(self.out / "work.knsv"))
        self.export()
        probe = self.backend_a.probe_export(str(self.out), "work")
        self.assertEqual(probe.conflict, "archive")
        self.assertEqual(probe.unique_path, str(self.out / "work-2.knsv"))
        (self.out / "docs").mkdir()
        self.assertEqual(
            self.backend_a.probe_export(str(self.out), "docs").conflict, "blocked"
        )
        write(self.out / "z.zip")
        self.assertEqual(
            self.backend_a.probe_export(str(self.out), "z").conflict, "blocked"
        )
        self.assertEqual(
            self.backend_a.probe_export(str(self.out / "nope"), "x").folder_problem,
            "missing",
        )
        self.assertEqual(
            self.backend_a.probe_export(str(self.out / "z.zip"), "x").folder_problem,
            "not_dir",
        )

    def test_probe_writes_nothing(self):
        before = snapshot(self.base)
        self.backend_a.probe_export(str(self.out), "work")
        self.assertEqual(snapshot(self.base), before)


class ImportTests(TransferCase):
    """Import: -i (file); name from the file unless another is chosen."""

    def setUp(self):
        super().setUp()
        self.archive = self.export().path

    def import_b(self, name=None, path=None, confirmed=True):
        """Imports into home B."""
        return self.backend_b.import_profile(
            str(path or self.archive), name, confirmed=confirmed
        )

    def test_round_trip_between_two_homes(self):
        info = self.backend_b.inspect_archive(str(self.archive))
        self.assertEqual(info.name, "work")
        self.assertFalse(info.name_taken)
        self.assertEqual(info.save_sections, ("configs",))
        self.assertEqual(info.export_sections, ("share_folder",))
        result = self.import_b()
        self.assertTrue(result.ok, result.message)
        self.assertEqual([p.name for p in self.backend_b.list_profiles()], ["work"])
        self.assertEqual(
            snapshot(self.engine_a.profiles_dir / "work"),
            snapshot(self.engine_b.profiles_dir / "work"),
            "the imported profile is identical to the exported one",
        )
        self.assertEqual(
            (self.engine_b.home / ".local/share/icons/theme.txt").read_text(),
            "theme-A",
        )
        self.assertEqual(
            (self.engine_b.home / ".config/kdeglobals").read_text(),
            "kdeglobals-B",
            "importing alone does not touch the save section of the live system",
        )

    def test_round_trip_then_apply_restores_the_original_files(self):
        self.import_b().raise_for_status()
        self.backend_b.apply("work", confirmed=True).raise_for_status()
        self.assertEqual(
            (self.engine_b.home / ".config/kdeglobals").read_text(), "kdeglobals-A"
        )

    def test_a_second_round_trip_keeps_the_archive_stable(self):
        """Export from B what A exported: same content again."""
        self.import_b().raise_for_status()
        second = self.backend_b.export_profile("work", str(self.out), "again")
        with zipfile.ZipFile(self.archive) as first, zipfile.ZipFile(
            second.path
        ) as again:
            for member in ("conf.yaml", "save/configs/kdeglobals"):
                self.assertEqual(first.read(member), again.read(member))
            self.assertEqual(
                {n for n in first.namelist() if not n.endswith("/")},
                {n for n in again.namelist() if not n.endswith("/")},
            )

    def test_import_under_another_name(self):
        before = digest(self.archive)
        result = self.import_b(name="viagem")
        self.assertTrue(result.ok, result.message)
        self.assertEqual([p.name for p in self.backend_b.list_profiles()], ["viagem"])
        self.assertEqual(
            snapshot(self.engine_a.profiles_dir / "work"),
            snapshot(self.engine_b.profiles_dir / "viagem"),
        )
        self.assertEqual(digest(self.archive), before, "the source file is untouched")
        self.assertEqual(sorted(os.listdir(self.out)), ["work.knsv"])

    def test_the_temporary_copy_is_removed_even_when_the_import_fails(self):
        scratch = self.base / "scratch"
        scratch.mkdir()
        with mock.patch.object(tempfile, "tempdir", str(scratch)):
            self.import_b(name="viagem").raise_for_status()
            self.backend_b.remove("viagem", confirmed=True)
            self.engine_b.profiles_dir.joinpath("x").mkdir()
            with mock.patch.object(
                self.service_b, "import_profile", side_effect=ValidationError("boom")
            ):
                with self.assertRaises(ValidationError):
                    self.import_b(name="outro")
        self.assertEqual(os.listdir(scratch), [])

    def test_a_permission_error_while_copying_is_reported_and_cleaned(self):
        scratch = self.base / "scratch"
        scratch.mkdir()
        with mock.patch.object(tempfile, "tempdir", str(scratch)):
            with mock.patch(
                "kongui.gui.backend.shutil.copyfile",
                side_effect=PermissionError(13, "denied", str(self.archive)),
            ):
                with self.assertRaises(PermissionError):
                    self.import_b(name="viagem")
        self.assertEqual(os.listdir(scratch), [])
        self.assertEqual(self.backend_b.list_profiles(), [])

    def test_never_replaces_an_existing_profile(self):
        self.import_b().raise_for_status()
        write(self.engine_b.profiles_dir / "work/configs/marker", "mine")
        with self.assertRaises(ProfileExistsError):
            self.import_b()
        with self.assertRaises(ProfileExistsError):
            self.import_b(name="work")
        self.assertEqual(
            (self.engine_b.profiles_dir / "work/configs/marker").read_text(), "mine"
        )
        self.assertTrue(self.backend_b.inspect_archive(str(self.archive)).name_taken)

    def test_renaming_onto_an_existing_profile_is_refused(self):
        self.backend_b.save("outro").raise_for_status()
        before = snapshot(self.engine_b.profiles_dir / "outro")
        with self.assertRaises(ProfileExistsError):
            self.import_b(name="outro")
        self.assertEqual(snapshot(self.engine_b.profiles_dir / "outro"), before)

    def test_needs_explicit_confirmation_and_writes_nothing_without_it(self):
        before = snapshot(self.engine_b.home)
        for value in (False, None, 1, "yes"):
            with self.subTest(value=value):
                with self.assertRaises(ConfirmationRequiredError):
                    self.import_b(confirmed=value)
        self.assertEqual(snapshot(self.engine_b.home), before)

    def test_invalid_new_names_are_refused_before_anything_is_written(self):
        before = snapshot(self.engine_b.home)
        for bad in ("../x", "a/b", ".", "..", "x.knsv", "-rf", " x", "a\nb"):
            with self.subTest(name=bad):
                with self.assertRaises(ValidationError):
                    self.import_b(name=bad)
        self.assertEqual(snapshot(self.engine_b.home), before)

    def test_missing_and_invalid_files(self):
        folder = self.out
        cases = {
            "missing": folder / "ghost.knsv",
            "wrong extension": write(folder / "work.txt"),
            "not a zip": write(folder / "fake.knsv", "not a zip"),
            "empty file": write(folder / "empty.knsv", ""),
            "a folder": folder,
            "no conf.yaml": make_knsv(folder / "noconf.knsv", {"save/a": "x"}),
            "no save/": make_knsv(folder / "nosave.knsv", {"conf.yaml": BASE_CONF}),
            "unsafe member": make_knsv(
                folder / "unsafe.knsv",
                {"conf.yaml": BASE_CONF, "save/a": "x", "/etc/evil": "x"},
            ),
        }
        before = snapshot(self.engine_b.home)
        for label, path in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(ValidationError):
                    self.backend_b.inspect_archive(str(path))
                with self.assertRaises(ValidationError):
                    self.import_b(path=path)
        self.assertEqual(snapshot(self.engine_b.home), before)

    def test_an_archive_that_writes_outside_the_home_is_refused(self):
        outside = self.base / "outside"
        outside.mkdir()
        conf = (
            'save:\n    configs:\n        location: "$HOME/.config"\n        entries: []\n'
            f'export:\n    x:\n        location: "{outside}"\n        entries: [m.txt]\n'
        )
        archive = make_knsv(
            self.out / "evil.knsv",
            {"conf.yaml": conf, "save/a": "x", "export/x/m.txt": "m"},
        )
        with self.assertRaises(ConfigValidationError):
            self.backend_b.inspect_archive(str(archive))
        with self.assertRaises(ConfigValidationError):
            self.import_b(path=archive)
        self.assertEqual(os.listdir(outside), [])

    def test_an_unreadable_file_is_reported(self):
        locked = write(self.out / "locked.knsv", "x")
        locked.chmod(0)
        self.addCleanup(locked.chmod, stat.S_IRWXU)
        with self.assertRaises(ValidationError):
            self.backend_b.inspect_archive(str(locked))
        with self.assertRaises(ValidationError):
            self.import_b(path=locked)

    def test_inspection_writes_nothing(self):
        before = snapshot(self.base)
        self.backend_b.inspect_archive(str(self.archive))
        self.assertEqual(snapshot(self.base), before)

    def test_partial_failures_are_reported_not_hidden(self):
        """A destination folder that does not exist makes the original fail."""
        bare = self.base / "bare"
        (bare / ".config").mkdir(parents=True)
        engine = KonsaveEngine(bare, euid_provider=non_root)
        backend = ServiceBackend(ProfileService(engine, ConfigService(engine)))
        result = backend.import_profile(str(self.archive), None, confirmed=True)
        self.assertFalse(result.ok)
        self.assertEqual(backend.list_profiles(), [], "the partial import is reverted")


@unittest.skipIf(really_root(), "refusing to start subprocesses as root")
class CliCompatibilityTests(TransferCase):
    """Archives are interchangeable with the genuine ``python -m konsave``."""

    def cli(self, engine):
        """A runner of the original CLI inside one of the homes."""
        meta = make_dist_info(self.base / f"meta-{engine.home.name}")
        return CliRunner(
            engine.home,
            euid_provider=non_root,
            extra_pythonpath=[meta],
            allow_mutating=True,
            timeout=120,
        )

    def test_a_file_exported_by_the_original_cli_imports_in_the_gui(self):
        result = self.cli(self.engine_a).run(
            ["-e", "work", "-d", str(self.out), "-n", "from_cli"]
        )
        self.assertTrue(result.ok, result.stdout + result.stderr)
        archive = self.out / "from_cli.knsv"
        self.assertTrue(archive.is_file())
        info = self.backend_b.inspect_archive(str(archive))
        self.assertEqual(info.name, "from_cli")
        self.backend_b.import_profile(str(archive), confirmed=True).raise_for_status()
        self.assertEqual(
            snapshot(self.engine_a.profiles_dir / "work"),
            snapshot(self.engine_b.profiles_dir / "from_cli"),
        )

    def test_a_file_exported_by_the_gui_imports_with_the_original_cli(self):
        archive = self.export(archive_name="from_gui").path
        result = self.cli(self.engine_b).run(["-i", str(archive)])
        self.assertTrue(result.ok, result.stdout + result.stderr)
        self.assertEqual([p.name for p in self.backend_b.list_profiles()], ["from_gui"])
        self.assertEqual(
            snapshot(self.engine_a.profiles_dir / "work"),
            snapshot(self.engine_b.profiles_dir / "from_gui"),
        )

    def test_the_cli_force_flag_and_the_overwrite_policy_agree(self):
        """``-f`` replaces the file; so does ``overwrite`` (after confirmation)."""
        self.export(archive_name="same")
        write(self.engine_a.home / ".config/kdeglobals", "kdeglobals-NEW")
        self.backend_a.overwrite("work", confirmed=True).raise_for_status()
        result = self.cli(self.engine_a).run(
            ["-e", "work", "-d", str(self.out), "-n", "same", "-f"]
        )
        self.assertTrue(result.ok, result.stdout + result.stderr)
        with zipfile.ZipFile(self.out / "same.knsv") as handle:
            from_cli = handle.read("save/configs/kdeglobals")
        self.export(archive_name="same", on_conflict="overwrite")
        with zipfile.ZipFile(self.out / "same.knsv") as handle:
            from_gui = handle.read("save/configs/kdeglobals")
        self.assertEqual(from_cli, from_gui)
        self.assertEqual(from_gui, b"kdeglobals-NEW")
        self.assertEqual(os.listdir(self.out), ["same.knsv"])


if __name__ == "__main__":
    unittest.main()
