"""Protections of import and export: size limits, free space, safe failures.

The real limits are large (512 MiB, 2 GiB, 10,000 entries), so the tests lower
them with ``mock.patch`` instead of building huge files, and they simulate a full
disk instead of filling the real one. Everything runs in temporary homes.
"""

from __future__ import annotations

import errno
import os
import shutil
import unittest
import zipfile
from collections import namedtuple
from pathlib import Path
from unittest import mock

from kongui.core import (
    ArchiveLimitError,
    InsufficientSpaceError,
    ValidationError,
)
from kongui.core.safety import (
    DISK_MARGIN_BYTES,
    MAX_ARCHIVE_BYTES,
    MAX_ARCHIVE_ENTRIES,
    MAX_EXTRACTED_BYTES,
    require_free_space,
    tree_size,
)
from tests.gui_helpers import HAVE_QT, GuiTestCase
from tests.helpers import BASE_CONF, make_knsv
from tests.test_profile_service_integration import IntegrationCase

DiskUsage = namedtuple("DiskUsage", "total used free")
PROFILES = "kongui.core.profiles"


def disk_with_free(free: int):
    """A ``shutil.disk_usage`` replacement that reports ``free`` bytes."""
    return mock.patch("shutil.disk_usage", return_value=DiskUsage(10**12, 0, free))


class LimitsCase(IntegrationCase):
    """Services plus helpers to inspect what an operation left behind."""

    def good_archive(self, name="good", extra=None):
        """A small valid ``.knsv`` named ``<name>.knsv``."""
        members = {"conf.yaml": BASE_CONF, "save/configs/kdeglobals": "colors"}
        members.update(extra or {})
        return make_knsv(self.work / f"{name}.knsv", members)

    def assert_nothing_was_imported(self, name):
        """No profile, no staging folder and no safety copy were left."""
        self.assertFalse((self.engine.profiles_dir / name).exists())
        self.assertFalse((self.engine.temp_dir / name).exists())
        backups = self.engine.konsave_dir / "kongui-backups"
        self.assertEqual(list(backups.iterdir()) if backups.exists() else [], [])

    def compressed_archive(self, name, members):
        """A ``.knsv`` whose members are deflated (the stored default hides bombs)."""
        path = self.work / f"{name}.knsv"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as handle:
            handle.writestr("conf.yaml", BASE_CONF)
            for member, text in members.items():
                handle.writestr(member, text)
        return path

    def engine_calls(self):
        """Spy on the original engine: every call it receives is recorded."""
        return mock.patch.object(self.engine, "call", wraps=self.engine.call)

    def assert_engine_did_not_change_anything(self, calls):
        """Only read-only calls (reading ``conf.yaml``) may have reached the engine."""
        names = [call.args[0] for call in calls.call_args_list]
        self.assertEqual(
            [name for name in names if name != "read_konsave_config"],
            [],
        )


class ConstantsTests(unittest.TestCase):
    """The initial limits are the ones agreed for the first release."""

    def test_initial_values(self):
        self.assertEqual(MAX_ARCHIVE_BYTES, 512 * 1024**2)
        self.assertEqual(MAX_EXTRACTED_BYTES, 2 * 1024**3)
        self.assertEqual(MAX_ARCHIVE_ENTRIES, 10_000)


class ImportLimitTests(LimitsCase):
    """Import: size of the file, entries, real decompressed bytes."""

    def test_a_normal_archive_is_imported(self):
        result = self.profiles.import_profile(self.good_archive(), confirmed=True)
        self.assertTrue(result.ok, result.message)
        self.assertEqual(
            (self.engine.profiles_dir / "good/configs/kdeglobals").read_text(),
            "colors",
        )
        self.assertFalse((self.engine.temp_dir / "good").exists())

    def test_the_real_sample_archive_is_far_below_the_limits(self):
        sample = Path(__file__).with_name("profile_test.knsv")
        size = sample.stat().st_size
        with zipfile.ZipFile(sample) as handle:
            entries = len(handle.infolist())
        extracted = self.profiles._measure_extracted(
            sample
        )  # pylint: disable=protected-access
        self.assertLess(size, MAX_ARCHIVE_BYTES // 50)
        self.assertLess(extracted, MAX_EXTRACTED_BYTES // 100)
        self.assertLess(entries, MAX_ARCHIVE_ENTRIES // 10)

    def test_a_file_above_the_size_limit_is_refused(self):
        archive = self.good_archive(extra={"save/configs/blob": "x" * 5000})
        with mock.patch(f"{PROFILES}.MAX_ARCHIVE_BYTES", 1000):
            with self.assertRaises(ArchiveLimitError) as caught:
                self.profiles.import_profile(archive, confirmed=True)
            with self.assertRaises(ArchiveLimitError):
                self.profiles.inspect_archive(archive)
        error = caught.exception
        self.assertEqual((error.kind, error.limit), ("size", 1000))
        self.assertEqual(error.actual, archive.stat().st_size)
        self.assertIsInstance(error, ValidationError)
        self.assert_nothing_was_imported("good")

    def test_a_file_exactly_at_the_size_limit_is_accepted(self):
        archive = self.good_archive()
        with mock.patch(f"{PROFILES}.MAX_ARCHIVE_BYTES", archive.stat().st_size):
            self.assertTrue(
                self.profiles.import_profile(archive, confirmed=True).ok,
            )

    def test_too_many_entries_are_refused(self):
        archive = self.good_archive(extra={f"save/configs/f{i}": "" for i in range(8)})
        with mock.patch(f"{PROFILES}.MAX_ARCHIVE_ENTRIES", 5):
            with self.assertRaises(ArchiveLimitError) as caught:
                self.profiles.import_profile(archive, confirmed=True)
            with self.assertRaises(ArchiveLimitError):
                self.profiles.inspect_archive(archive)
        self.assertEqual(caught.exception.kind, "entries")
        self.assertEqual(caught.exception.actual, 10)
        self.assert_nothing_was_imported("good")

    def test_decompressing_stops_as_soon_as_the_limit_is_passed(self):
        # 3 MiB of zeros compress to a few KB: only the real count can tell.
        archive = self.compressed_archive(
            "good", {"save/configs/bomb": "\0" * (3 << 20)}
        )
        self.assertLess(archive.stat().st_size, 100_000)
        read = []
        original = zipfile.ZipExtFile.read

        def spy(stream, size=-1):
            data = original(stream, size)
            read.append(len(data))
            return data

        with mock.patch(f"{PROFILES}.MAX_EXTRACTED_BYTES", 100_000), mock.patch(
            f"{PROFILES}._COUNT_CHUNK", 4096
        ), mock.patch.object(zipfile.ZipExtFile, "read", spy):
            with self.engine_calls() as calls:
                with self.assertRaises(ArchiveLimitError) as caught:
                    self.profiles.import_profile(archive, confirmed=True)
        self.assertEqual(caught.exception.kind, "extracted")
        self.assertLessEqual(sum(read), 100_000 + 2 * 4096)
        self.assertLess(sum(read), 3 << 20)
        self.assert_engine_did_not_change_anything(calls)
        self.assert_nothing_was_imported("good")

    def test_the_count_is_of_the_bytes_actually_read(self):
        archive = self.good_archive(extra={"save/configs/a": "A" * 1234})
        real = len(BASE_CONF) + len("colors") + 1234
        self.assertEqual(
            self.profiles._measure_extracted(
                archive
            ),  # pylint: disable=protected-access
            real,
        )


class UnsafeAndBrokenArchiveTests(LimitsCase):
    """Unsafe member names and damaged files fail clearly, before any effect."""

    def test_unsafe_member_names_are_refused(self):
        for name in ("/etc/evil", "save/../../evil", "..\\evil"):
            with self.subTest(member=name):
                archive = make_knsv(
                    self.work / "unsafe.knsv",
                    {"conf.yaml": BASE_CONF, "save/configs/a": "x", name: "x"},
                )
                with self.assertRaises(ValidationError) as caught:
                    self.profiles.import_profile(archive, confirmed=True)
                self.assertIn("unsafe path", str(caught.exception))
                self.assert_nothing_was_imported("unsafe")
                self.assertFalse((self.base / "evil").exists())

    def test_a_damaged_member_is_found_before_anything_is_changed(self):
        archive = self.good_archive(extra={"save/configs/data": "A" * 5000})
        raw = bytearray(archive.read_bytes())
        raw[raw.find(b"A" * 100) + 10] = ord("B")
        archive.write_bytes(bytes(raw))
        self.assertEqual(self.profiles.inspect_archive(archive).name, "good")
        with self.engine_calls() as calls:
            with self.assertRaises(ValidationError) as caught:
                self.profiles.import_profile(archive, confirmed=True)
        self.assertIn("corrupted archive", str(caught.exception))
        self.assert_engine_did_not_change_anything(calls)
        self.assert_nothing_was_imported("good")

    def test_a_truncated_empty_or_random_file_is_refused(self):
        good = self.good_archive().read_bytes()
        cases = {
            "truncated": good[:-40],
            "empty": b"",
            "random": os.urandom(2000),
            "text": b"not a zip at all",
        }
        for label, data in cases.items():
            with self.subTest(case=label):
                archive = self.work / f"{label}.knsv"
                archive.write_bytes(data)
                with self.assertRaises(ValidationError) as caught:
                    self.profiles.import_profile(archive, confirmed=True)
                self.assertIn("not a readable archive", str(caught.exception))
                self.assert_nothing_was_imported(label)

    def test_a_member_with_unsupported_data_is_refused(self):
        archive = self.good_archive(extra={"save/configs/x": "x"})
        with mock.patch.object(
            zipfile.ZipFile, "open", side_effect=NotImplementedError("bzip3")
        ):
            with self.assertRaises(ValidationError):
                self.profiles.import_profile(archive, confirmed=True)
        self.assert_nothing_was_imported("good")


class ImportSpaceTests(LimitsCase):
    """Free-space estimate before the import, and a real "no space" error."""

    def test_not_enough_space_stops_the_import_before_any_change(self):
        archive = self.good_archive(extra={"save/configs/blob": "x" * 50_000})
        with disk_with_free(1000), self.engine_calls() as calls:
            with self.assertRaises(InsufficientSpaceError) as caught:
                self.profiles.import_profile(archive, confirmed=True)
        error = caught.exception
        self.assertEqual(error.available, 1000)
        self.assertGreater(error.needed, 2 * 50_000 + DISK_MARGIN_BYTES - 1)
        self.assertEqual(Path(error.folder), self.engine.konsave_dir)
        self.assert_engine_did_not_change_anything(calls)
        self.assert_nothing_was_imported("good")

    def test_enough_space_lets_the_import_go_on(self):
        archive = self.good_archive()
        with disk_with_free(DISK_MARGIN_BYTES + 10**6):
            self.assertTrue(self.profiles.import_profile(archive, confirmed=True).ok)

    def test_the_estimate_is_twice_the_extracted_size_plus_the_margin(self):
        archive = self.good_archive(extra={"save/configs/blob": "x" * 1000})
        extracted = len(BASE_CONF) + len("colors") + 1000
        needed = 2 * extracted + DISK_MARGIN_BYTES
        with disk_with_free(needed - 1):
            with self.assertRaises(InsufficientSpaceError):
                self.profiles.import_profile(archive, confirmed=True)
        with disk_with_free(needed):
            self.assertTrue(self.profiles.import_profile(archive, confirmed=True).ok)

    def test_a_real_no_space_error_is_reported_and_cleaned_up(self):
        archive = self.good_archive()
        full = OSError(errno.ENOSPC, "No space left on device")
        with mock.patch("zipfile.ZipFile.extractall", side_effect=full):
            result = self.profiles.import_profile(archive, confirmed=True)
        self.assertFalse(result.ok)
        self.assertIn("No space left on device", result.message)
        self.assertFalse((self.engine.profiles_dir / "good").exists())
        self.assertFalse((self.engine.temp_dir / "good").exists())


class ExportSafetyTests(LimitsCase):
    """Export: space check, and a failure never costs the previous export."""

    def setUp(self):
        super().setUp()
        self.profiles.save("p").raise_for_status()
        self.out = self.work / "out"
        self.out.mkdir()

    def export(self, **kwargs):
        return self.profiles.export("p", directory=self.out, **kwargs)

    @staticmethod
    def partial_then_full_disk(base, *_args, **_kwargs):
        """A ``make_archive`` that writes half a zip and then runs out of space."""
        Path(f"{base}.zip").write_bytes(b"PK\x03\x04 half an archive")
        raise OSError(errno.ENOSPC, "No space left on device")

    def test_a_normal_export_is_unchanged(self):
        result = self.export()
        self.assertTrue(result.ok, result.message)
        self.assertEqual(os.listdir(self.out), ["p.knsv"])
        with zipfile.ZipFile(self.out / "p.knsv") as handle:
            self.assertIn("conf.yaml", handle.namelist())

    def test_not_enough_space_stops_the_export_before_writing(self):
        with disk_with_free(1000), self.engine_calls() as calls:
            with self.assertRaises(InsufficientSpaceError) as caught:
                self.export()
        self.assertEqual(Path(caught.exception.folder), self.out)
        self.assert_engine_did_not_change_anything(calls)
        self.assertEqual(os.listdir(self.out), [])

    def test_the_estimate_counts_the_profile_twice(self):
        size = tree_size(self.engine.profiles_dir / "p")
        self.assertGreater(size, 0)
        needed = 2 * size + DISK_MARGIN_BYTES
        # The export section reads live files too, so only a lower bound is exact.
        with disk_with_free(needed - 1):
            with self.assertRaises(InsufficientSpaceError) as caught:
                self.export()
        self.assertGreaterEqual(caught.exception.needed, needed)

    def test_a_failed_export_keeps_the_previous_one(self):
        self.assertTrue(self.export().ok)
        before = (self.out / "p.knsv").read_bytes()
        with mock.patch("shutil.make_archive", self.partial_then_full_disk):
            result = self.export(on_conflict="overwrite")
        self.assertFalse(result.ok)
        self.assertEqual((self.out / "p.knsv").read_bytes(), before)
        self.assertEqual(os.listdir(self.out), ["p.knsv"])

    def test_a_failed_export_leaves_no_temporary_files(self):
        with mock.patch("shutil.make_archive", self.partial_then_full_disk):
            result = self.export()
        self.assertFalse(result.ok)
        self.assertIn("No space left on device", result.message)
        self.assertEqual(os.listdir(self.out), [])

    def test_a_failure_while_copying_also_leaves_nothing(self):
        with mock.patch("shutil.copy", side_effect=OSError(errno.EIO, "io")):
            result = self.export()
        self.assertFalse(result.ok)
        self.assertEqual(os.listdir(self.out), [])

    def test_the_overwrite_confirmation_policy_is_kept(self):
        self.assertTrue(self.export().ok)
        with self.assertRaises(Exception) as caught:
            self.export()  # default policy "error": never overwrites silently
        self.assertEqual(type(caught.exception).__name__, "ArchiveExistsError")
        self.assertTrue(self.export(on_conflict="unique").ok)
        self.assertEqual(sorted(os.listdir(self.out)), ["p-2.knsv", "p.knsv"])
        self.assertTrue(self.export(on_conflict="overwrite").ok)


class HelperTests(unittest.TestCase):
    """``tree_size`` and ``require_free_space``."""

    def setUp(self):
        folder = Path(os.path.realpath(__import__("tempfile").mkdtemp()))
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        self.folder = folder

    def test_tree_size_adds_files_and_does_not_follow_links(self):
        (self.folder / "a").write_bytes(b"x" * 100)
        (self.folder / "sub").mkdir()
        (self.folder / "sub/b").write_bytes(b"y" * 50)
        big = self.folder.parent / (self.folder.name + "-outside")
        big.mkdir()
        self.addCleanup(shutil.rmtree, big, ignore_errors=True)
        (big / "huge").write_bytes(b"z" * 10_000)
        os.symlink(big, self.folder / "link")
        total = tree_size(self.folder)
        self.assertGreaterEqual(total, 150)
        self.assertLess(total, 10_000)
        self.assertEqual(tree_size(self.folder / "missing"), 0)

    def test_an_unreadable_disk_does_not_block_the_operation(self):
        with mock.patch("shutil.disk_usage", side_effect=OSError("no")):
            require_free_space(self.folder, 10**15, "a test")

    def test_the_margin_is_part_of_the_requirement(self):
        with disk_with_free(DISK_MARGIN_BYTES):
            with self.assertRaises(InsufficientSpaceError):
                require_free_space(self.folder, 1, "a test")
            require_free_space(self.folder, 0, "a test")


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class MessageTests(GuiTestCase):
    """What the user reads, in both languages."""

    LANGUAGE = "en_US"

    def lines(self, error, language):
        from kongui.gui import i18n, messages

        i18n.manager().install(language)
        return " ".join(messages.describe_error(error))

    def test_limit_messages(self):
        size = ArchiveLimitError("x", "size", 512 * 1024**2, 600 * 1024**2)
        entries = ArchiveLimitError("x", "entries", 10_000, 12_345)
        extracted = ArchiveLimitError("x", "extracted", 2 * 1024**3)
        english = self.lines(size, "en")
        self.assertIn("too large to import (600.0 MB; the limit is 512.0 MB)", english)
        self.assertIn(
            "too many items (12345; the limit is 10000)", self.lines(entries, "en")
        )
        self.assertIn("more than 2.0 GB", self.lines(extracted, "en"))
        portuguese = self.lines(size, "pt_BR")
        self.assertIn(
            "grande demais para importar (600,0 MB; o limite é 512,0 MB)", portuguese
        )
        self.assertIn(
            "itens demais (12345; o limite é 10000)", self.lines(entries, "pt_BR")
        )
        self.assertIn("mais de 2,0 GB", self.lines(extracted, "pt_BR"))

    def test_space_message(self):
        error = InsufficientSpaceError(
            "x", "/home/a/.config/konsave", 300 * 1024**2, 5 * 1024**2
        )
        english = self.lines(error, "en")
        self.assertIn("Not enough free disk space in /home/a/.config/konsave", english)
        self.assertIn("300.0 MB", english)
        self.assertIn("5.0 MB are free", english)
        self.assertIn("Nothing was changed", english)
        self.assertIn("Não há espaço livre suficiente", self.lines(error, "pt_BR"))

    def test_corrupted_and_full_disk_messages(self):
        corrupted = ValidationError("corrupted archive: Bad CRC-32 for file 'x'")
        self.assertIn("The file is corrupted", self.lines(corrupted, "en"))
        self.assertIn("O arquivo está corrompido", self.lines(corrupted, "pt_BR"))
        full = OSError(errno.ENOSPC, "No space left on device")
        self.assertIn("ran out of free space", self.lines(full, "en"))
        self.assertIn("ficou sem espaço livre", self.lines(full, "pt_BR"))

    def test_engine_failures_get_a_plain_explanation_first(self):
        from kongui.core import OperationResult
        from kongui.gui import i18n, messages

        result = OperationResult(
            operation="import",
            ok=False,
            message="import failed: OSError: [Errno 28] No space left on device",
        )
        i18n.manager().install("en")
        lines = messages.describe_result(result)
        self.assertIn("ran out of free space", lines[0])
        self.assertIn("No space left on device", " ".join(lines))
        i18n.manager().install("pt_BR")
        self.assertIn("ficou sem espaço livre", messages.describe_result(result)[0])
        other = OperationResult(
            operation="import", ok=False, message="import failed: boom"
        )
        self.assertEqual(messages.describe_result(other)[0], "import failed: boom")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
