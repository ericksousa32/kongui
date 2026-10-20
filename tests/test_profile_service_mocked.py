"""Tests of ProfileService with the original functions replaced by mocks.

``engine.call`` is patched for the destructive functions, so these tests check
*what the service asks the original code to do* and *how it interprets the
outcome*, without running the original code. Configuration reading
(``read_konsave_config``) still goes to the real code.
"""

import os
import shutil
import unittest
import zipfile

from kongui.core import (
    NOT_IMPLEMENTED_OPERATIONS,
    ArchiveExistsError,
    ConfigMissingError,
    ConfigError,
    ConfirmationRequiredError,
    NotImplementedOperationError,
    OperationFailedError,
    OperationResult,
    ProfileExistsError,
    ProfileInvalidError,
    ProfileNotFoundError,
    ValidationError,
)
from tests.helpers import (
    BASE_CONF,
    IsolatedHomeTestCase,
    fake_call,
    make_knsv,
    patch_engine_call,
    small_conf,
    write,
)


class MockedServiceCase(IsolatedHomeTestCase):
    """Engine, services and helpers shared by the tests below."""

    def setUp(self):
        super().setUp()
        self.engine, self.config, self.profiles = self.new_services()
        (self.home / ".config").mkdir(exist_ok=True)

    def make_profile(self, name="p", conf=BASE_CONF, with_config=True):
        """Creates a profile folder the way ``save_profile`` would."""
        folder = self.engine.profiles_dir / name
        (folder / "configs").mkdir(parents=True)
        if with_config:
            write(folder / "conf.yaml", conf)
        return folder

    def calls_of(self, patched, function):
        """Calls made to the engine for one original function."""
        return [c for c in patched.call_args_list if c.args[0] == function]

    def valid_archive(self, name="shared.knsv", conf=BASE_CONF):
        """A minimal but structurally valid .knsv."""
        return make_knsv(
            self.work / name, {"conf.yaml": conf, "save/configs/kdeglobals": "x"}
        )


class ListAndGetTests(MockedServiceCase):
    """Profile queries read the disk every time."""

    def test_sorted_and_flags(self):
        self.make_profile("b")
        self.make_profile("a", with_config=False)
        listed = self.profiles.list_profiles()
        self.assertEqual([p.name for p in listed], ["a", "b"])
        self.assertEqual([p.has_config for p in listed], [False, True])
        self.assertTrue(all(p.modified is not None for p in listed))

    def test_loose_files_are_ignored(self):
        write(self.engine.profiles_dir / "notes.txt")
        self.assertEqual(self.profiles.list_profiles(), [])

    def test_a_new_profile_appears_without_restarting(self):
        self.assertEqual(self.profiles.list_profiles(), [])
        self.make_profile("late")
        self.assertEqual([p.name for p in self.profiles.list_profiles()], ["late"])

    def test_get_profile(self):
        self.make_profile("p")
        self.assertEqual(self.profiles.get_profile("p").name, "p")
        with self.assertRaises(ProfileNotFoundError):
            self.profiles.get_profile("nope")
        with self.assertRaises(ValidationError):
            self.profiles.get_profile("../x")


class SaveTests(MockedServiceCase):
    """save -> save_profile."""

    def test_arguments_given_to_the_original(self):
        self.make_profile("other")
        patched = patch_engine_call(
            self.engine, {"save_profile": lambda *a, **k: fake_call()}
        )
        self.profiles.save("new")
        (call,) = self.calls_of(patched, "save_profile")
        self.assertEqual(call.args, ("save_profile", "new", ["other"]))
        self.assertEqual(call.kwargs, {"force": False})

    def test_overwrite_maps_to_force(self):
        self.make_profile("p")
        patched = patch_engine_call(
            self.engine, {"save_profile": lambda *a, **k: fake_call()}
        )
        self.profiles.save("p", overwrite=True)
        (call,) = self.calls_of(patched, "save_profile")
        self.assertEqual(call.kwargs, {"force": True})

    def test_success_requires_the_profile_conf(self):
        def creates_conf(name, names, force):
            write(self.engine.profiles_dir / name / "conf.yaml")
            return fake_call(stdout="Konsave: saving profile...\n")

        patch_engine_call(self.engine, {"save_profile": creates_conf})
        result = self.profiles.save("p")
        self.assertTrue(result.ok)
        self.assertEqual(result.operation, "save")
        self.assertEqual(result.path, self.engine.profiles_dir / "p")
        self.assertIn("saving profile", result.stdout)

    def test_a_logged_error_fails_even_if_the_conf_exists(self):
        def creates_conf_but_logs(name, names, force):
            write(self.engine.profiles_dir / name / "conf.yaml")
            return fake_call(errors=("OSError: disk full",), stderr="warn")

        patch_engine_call(self.engine, {"save_profile": creates_conf_but_logs})
        result = self.profiles.save("p")
        self.assertFalse(result.ok)
        self.assertIn("OSError: disk full", result.message)
        self.assertEqual(result.errors, ("OSError: disk full",))
        self.assertEqual(result.stderr, "warn")

    def test_silent_failure_is_detected_by_the_missing_conf(self):
        patch_engine_call(self.engine, {"save_profile": lambda *a, **k: fake_call()})
        self.assertFalse(self.profiles.save("p").ok)

    def test_partial_profile_created_by_a_failed_call_is_removed(self):
        def fails_halfway(name, names, force):
            (self.engine.profiles_dir / name / "configs").mkdir(parents=True)
            return fake_call(errors=("FileNotFoundError: x",))

        patch_engine_call(self.engine, {"save_profile": fails_halfway})
        result = self.profiles.save("p")
        self.assertFalse(result.ok)
        self.assertFalse((self.engine.profiles_dir / "p").exists())
        self.assertTrue(any("removed leftover" in w for w in result.warnings))

    def test_an_existing_profile_is_never_removed_by_a_failed_overwrite(self):
        folder = self.make_profile("p")
        patch_engine_call(
            self.engine,
            {"save_profile": lambda *a, **k: fake_call(errors=("E: x",))},
        )
        self.assertFalse(self.profiles.save("p", overwrite=True).ok)
        self.assertTrue(folder.is_dir())

    def test_preconditions_fail_before_calling_the_original(self):
        self.make_profile("p")
        patched = patch_engine_call(
            self.engine, {"save_profile": lambda *a, **k: fake_call()}
        )
        with self.assertRaises(ProfileExistsError):
            self.profiles.save("p")
        for bad in ("../x", ".", "", "a/b", "x.knsv"):
            with self.subTest(name=bad):
                with self.assertRaises(ValidationError):
                    self.profiles.save(bad)
        self.engine.config_file.unlink()
        with self.assertRaises(ConfigMissingError):
            self.profiles.save("new")
        self.assertEqual(self.calls_of(patched, "save_profile"), [])


class ApplyTests(MockedServiceCase):
    """apply -> apply_profile (destructive)."""

    def test_confirmation_is_mandatory_and_exact(self):
        self.make_profile("p")
        patched = patch_engine_call(
            self.engine, {"apply_profile": lambda *a, **k: fake_call()}
        )
        for value in (False, None, 1, "yes", "True", [True]):
            with self.subTest(confirmed=value):
                with self.assertRaises(ConfirmationRequiredError):
                    self.profiles.apply("p", confirmed=value)
        with self.assertRaises(ConfirmationRequiredError):
            self.profiles.apply("p")
        self.assertEqual(self.calls_of(patched, "apply_profile"), [])

    def test_arguments_given_to_the_original(self):
        self.make_profile("p")
        self.make_profile("q")
        patched = patch_engine_call(
            self.engine, {"apply_profile": lambda *a, **k: fake_call()}
        )
        result = self.profiles.apply("p", confirmed=True)
        (call,) = self.calls_of(patched, "apply_profile")
        self.assertEqual(call.args, ("apply_profile", "p", ["p", "q"], 2))
        self.assertTrue(result.ok)
        self.assertIn("log out", result.message)

    def test_a_logged_error_fails_despite_the_success_message(self):
        self.make_profile("p")
        patch_engine_call(
            self.engine,
            {
                "apply_profile": lambda *a, **k: fake_call(
                    errors=("FileNotFoundError: x",),
                    stdout="Konsave: Profile applied successfully!\n",
                )
            },
        )
        result = self.profiles.apply("p", confirmed=True)
        self.assertFalse(result.ok)
        self.assertIn("applied successfully", result.stdout)
        self.assertIn("FileNotFoundError", result.message)

    def test_unknown_or_incomplete_profiles(self):
        self.make_profile("broken", with_config=False)
        patched = patch_engine_call(
            self.engine, {"apply_profile": lambda *a, **k: fake_call()}
        )
        with self.assertRaises(ProfileNotFoundError):
            self.profiles.apply("ghost", confirmed=True)
        with self.assertRaises(ProfileInvalidError):
            self.profiles.apply("broken", confirmed=True)
        with self.assertRaises(ValidationError):
            self.profiles.apply("../p", confirmed=True)
        self.assertEqual(self.calls_of(patched, "apply_profile"), [])

    def test_a_section_missing_from_the_profile_is_refused(self):
        folder = self.make_profile("p")
        shutil.rmtree(folder / "configs")
        patched = patch_engine_call(
            self.engine, {"apply_profile": lambda *a, **k: fake_call()}
        )
        with self.assertRaises(ConfigError) as caught:
            self.profiles.apply("p", confirmed=True)
        self.assertTrue(any("folder missing" in e for e in caught.exception.details))
        self.assertEqual(self.calls_of(patched, "apply_profile"), [])

    def test_destination_whose_parent_is_missing_is_refused(self):
        self.make_profile("p", conf=small_conf(location="$HOME/gone/deeper"))
        patched = patch_engine_call(
            self.engine, {"apply_profile": lambda *a, **k: fake_call()}
        )
        with self.assertRaises(ConfigError):
            self.profiles.apply("p", confirmed=True)
        self.assertEqual(self.calls_of(patched, "apply_profile"), [])

    def test_destination_outside_home_needs_an_explicit_opt_in(self):
        outside = self.base / "outside"
        outside.mkdir()
        self.make_profile("p", conf=small_conf(location=str(outside)))
        patched = patch_engine_call(
            self.engine, {"apply_profile": lambda *a, **k: fake_call()}
        )
        with self.assertRaises(ConfigError) as caught:
            self.profiles.apply("p", confirmed=True)
        self.assertTrue(any("outside the home" in e for e in caught.exception.details))
        self.assertEqual(self.calls_of(patched, "apply_profile"), [])
        self.assertTrue(
            self.profiles.apply("p", confirmed=True, allow_outside_home=True).ok
        )

    def test_a_symlink_that_escapes_the_home_is_treated_as_outside(self):
        outside = self.base / "outside"
        outside.mkdir()
        os.symlink(outside, self.home / "link")
        self.make_profile("p", conf=small_conf(location="$HOME/link"))
        patch_engine_call(self.engine, {"apply_profile": lambda *a, **k: fake_call()})
        with self.assertRaises(ConfigError):
            self.profiles.apply("p", confirmed=True)


class RemoveTests(MockedServiceCase):
    """remove -> remove_profile (destructive)."""

    def test_confirmation_is_mandatory(self):
        folder = self.make_profile("p")
        patched = patch_engine_call(
            self.engine, {"remove_profile": lambda *a, **k: fake_call()}
        )
        with self.assertRaises(ConfirmationRequiredError):
            self.profiles.remove("p")
        self.assertEqual(self.calls_of(patched, "remove_profile"), [])
        self.assertTrue(folder.is_dir())

    def test_arguments_and_success(self):
        folder = self.make_profile("p")

        def removes(name, names, count):
            shutil.rmtree(self.engine.profiles_dir / name)
            return fake_call()

        patched = patch_engine_call(self.engine, {"remove_profile": removes})
        result = self.profiles.remove("p", confirmed=True)
        (call,) = self.calls_of(patched, "remove_profile")
        self.assertEqual(call.args, ("remove_profile", "p", ["p"], 1))
        self.assertTrue(result.ok)
        self.assertFalse(folder.exists())

    def test_folder_still_there_means_failure(self):
        self.make_profile("p")
        patch_engine_call(self.engine, {"remove_profile": lambda *a, **k: fake_call()})
        self.assertFalse(self.profiles.remove("p", confirmed=True).ok)

    def test_unknown_profile(self):
        with self.assertRaises(ProfileNotFoundError):
            self.profiles.remove("ghost", confirmed=True)


class ExportTests(MockedServiceCase):
    """export -> export; the original ``force`` is never used on folders."""

    def setUp(self):
        super().setUp()
        self.make_profile("p")
        self.out = self.base / "out"
        self.out.mkdir()

    def fake_export(self, name, names, count, folder, base, force):
        """Behaves like a successful original export."""
        make_knsv(self.out / f"{base}.knsv", {"conf.yaml": BASE_CONF})
        return fake_call(stdout="Konsave: exported\n")

    def export_args(self, **kwargs):
        patched = patch_engine_call(self.engine, {"export": self.fake_export})
        result = self.profiles.export("p", directory=self.out, **kwargs)
        (call,) = self.calls_of(patched, "export")
        return result, call.args

    def test_default_arguments(self):
        result, args = self.export_args()
        self.assertEqual(args, ("export", "p", ["p"], 1, str(self.out), "p", False))
        self.assertTrue(result.ok)
        self.assertEqual(result.path, self.out / "p.knsv")

    def test_custom_archive_name(self):
        result, args = self.export_args(archive_name="backup")
        self.assertEqual(args[5], "backup")
        self.assertEqual(result.path, self.out / "backup.knsv")

    def test_error_policy_refuses_any_existing_target(self):
        patch_engine_call(self.engine, {"export": self.fake_export})
        for existing in ("p", "p.knsv", "p.zip"):
            with self.subTest(existing=existing):
                target = self.out / existing
                if existing == "p":
                    target.mkdir()
                else:
                    write(target)
                with self.assertRaises(ArchiveExistsError):
                    self.profiles.export("p", directory=self.out)
                if target.is_dir():
                    target.rmdir()
                else:
                    target.unlink()

    def test_unique_policy_picks_a_free_name_and_never_forces(self):
        write(self.out / "p.knsv")
        (self.out / "p-2").mkdir()
        result, args = self.export_args(on_conflict="unique")
        self.assertEqual(args[5:], ("p-3", False))
        self.assertEqual(result.path, self.out / "p-3.knsv")

    def test_overwrite_policy_forces_only_to_replace_a_regular_knsv(self):
        write(self.out / "p.knsv", "old")
        result, args = self.export_args(on_conflict="overwrite")
        self.assertEqual(args[5:], ("p", True))
        self.assertTrue(result.ok)

    def test_overwrite_policy_without_an_existing_file_does_not_force(self):
        _, args = self.export_args(on_conflict="overwrite")
        self.assertEqual(args[5:], ("p", False))

    def test_overwrite_policy_never_endangers_a_folder_or_a_zip(self):
        patched = patch_engine_call(self.engine, {"export": self.fake_export})
        precious = write(self.out / "p" / "precious.txt")
        with self.assertRaises(ArchiveExistsError):
            self.profiles.export("p", directory=self.out, on_conflict="overwrite")
        self.assertTrue(precious.exists())
        shutil.rmtree(self.out / "p")
        write(self.out / "p.zip")
        with self.assertRaises(ArchiveExistsError):
            self.profiles.export("p", directory=self.out, on_conflict="overwrite")
        self.assertEqual(self.calls_of(patched, "export"), [])

    def test_overwrite_policy_refuses_a_symlink_or_directory_named_like_the_archive(
        self,
    ):
        patch_engine_call(self.engine, {"export": self.fake_export})
        (self.out / "p.knsv").mkdir()
        with self.assertRaises(ArchiveExistsError):
            self.profiles.export("p", directory=self.out, on_conflict="overwrite")
        (self.out / "p.knsv").rmdir()
        write(self.base / "real")
        os.symlink(self.base / "real", self.out / "p.knsv")
        with self.assertRaises(ArchiveExistsError):
            self.profiles.export("p", directory=self.out, on_conflict="overwrite")

    def test_invalid_arguments_never_reach_the_original(self):
        patched = patch_engine_call(self.engine, {"export": self.fake_export})
        cases = [
            ({"on_conflict": "merge"}, ValidationError),
            ({"archive_name": "a/b"}, ValidationError),
            ({"archive_name": "x.knsv"}, ValidationError),
            ({"directory": self.base / "missing"}, ValidationError),
        ]
        for kwargs, expected in cases:
            with self.subTest(kwargs=kwargs):
                arguments = {"directory": self.out}
                arguments.update(kwargs)
                with self.assertRaises(expected):
                    self.profiles.export("p", **arguments)
        with self.assertRaises(ProfileNotFoundError):
            self.profiles.export("ghost", directory=self.out)
        self.make_profile("broken", with_config=False)
        with self.assertRaises(ProfileInvalidError):
            self.profiles.export("broken", directory=self.out)
        self.assertEqual(self.calls_of(patched, "export"), [])

    def test_a_missing_archive_means_failure(self):
        patch_engine_call(self.engine, {"export": lambda *a, **k: fake_call()})
        self.assertFalse(self.profiles.export("p", directory=self.out).ok)

    def test_an_archive_without_conf_means_failure(self):
        def bad_archive(name, names, count, folder, base, force):
            make_knsv(self.out / f"{base}.knsv", {"other": "x"})
            return fake_call()

        patch_engine_call(self.engine, {"export": bad_archive})
        self.assertFalse(self.profiles.export("p", directory=self.out).ok)

    def test_a_logged_error_means_failure_and_leftovers_are_removed(self):
        def fails(name, names, count, folder, base, force):
            write(self.out / base / "save" / "partial")
            write(self.out / f"{base}.zip")
            return fake_call(errors=("OSError: no space",))

        patch_engine_call(self.engine, {"export": fails})
        result = self.profiles.export("p", directory=self.out)
        self.assertFalse(result.ok)
        self.assertEqual(sorted(os.listdir(self.out)), [])
        self.assertEqual(sum("removed leftover" in w for w in result.warnings), 2)


class ImportTests(MockedServiceCase):
    """import_profile -> import_profile (destructive)."""

    def test_confirmation_is_mandatory(self):
        archive = self.valid_archive()
        patched = patch_engine_call(
            self.engine, {"import_profile": lambda *a, **k: fake_call()}
        )
        with self.assertRaises(ConfirmationRequiredError):
            self.profiles.import_profile(archive)
        self.assertEqual(self.calls_of(patched, "import_profile"), [])

    def test_arguments_and_success(self):
        archive = self.valid_archive("shared.knsv")

        def imports(path):
            write(self.engine.profiles_dir / "shared" / "conf.yaml")
            return fake_call(stdout="Konsave: Profile successfully imported!\n")

        patched = patch_engine_call(self.engine, {"import_profile": imports})
        result = self.profiles.import_profile(archive, confirmed=True)
        (call,) = self.calls_of(patched, "import_profile")
        self.assertEqual(call.args, ("import_profile", str(archive)))
        self.assertTrue(result.ok)
        self.assertEqual(result.path, self.engine.profiles_dir / "shared")

    def test_files_that_are_not_acceptable_archives(self):
        patched = patch_engine_call(
            self.engine, {"import_profile": lambda *a, **k: fake_call()}
        )
        write(self.work / "plain.txt")
        write(self.work / "fake.knsv", "not a zip")
        write(self.work / ".knsv", "x")
        cases = [
            self.work / "missing.knsv",
            self.work / "plain.txt",
            self.work / "fake.knsv",
            self.work / ".knsv",
            self.valid_archive("my.knsv.knsv"),
            make_knsv(self.work / "noconf.knsv", {"save/a": "x"}),
            make_knsv(self.work / "nosave.knsv", {"conf.yaml": BASE_CONF}),
            make_knsv(
                self.work / "dots.knsv",
                {"conf.yaml": BASE_CONF, "save/a": "x", "../escape": "x"},
            ),
            make_knsv(
                self.work / "abs.knsv",
                {"conf.yaml": BASE_CONF, "save/a": "x", "/etc/passwd": "x"},
            ),
        ]
        for case in cases:
            with self.subTest(archive=case.name):
                with self.assertRaises(ValidationError):
                    self.profiles.import_profile(case, confirmed=True)
        self.assertEqual(self.calls_of(patched, "import_profile"), [])

    def test_an_archive_with_an_invalid_configuration(self):
        archive = self.valid_archive(conf=small_conf(entries=["a/b"]))
        with self.assertRaises(ConfigError):
            self.profiles.import_profile(archive, confirmed=True)

    def test_destination_outside_home_is_refused_unless_allowed(self):
        outside = self.base / "outside"
        outside.mkdir()
        conf = (
            'save:\n    configs:\n        location: "$HOME/.config"\n        entries: []\n'
            f'export:\n    x:\n        location: "{outside}"\n        entries: [m]\n'
        )
        archive = self.valid_archive("evil.knsv", conf)
        patched = patch_engine_call(
            self.engine,
            {
                "import_profile": lambda *a, **k: (
                    write(self.engine.profiles_dir / "evil" / "conf.yaml"),
                    fake_call(),
                )[1]
            },
        )
        with self.assertRaises(ConfigError):
            self.profiles.import_profile(archive, confirmed=True)
        self.assertEqual(self.calls_of(patched, "import_profile"), [])
        self.assertTrue(
            self.profiles.import_profile(
                archive, confirmed=True, allow_outside_home=True
            ).ok
        )

    def test_existing_profile_and_stale_staging_folder(self):
        archive = self.valid_archive("shared.knsv")
        patched = patch_engine_call(
            self.engine, {"import_profile": lambda *a, **k: fake_call()}
        )
        self.make_profile("shared")
        with self.assertRaises(ProfileExistsError):
            self.profiles.import_profile(archive, confirmed=True)
        shutil.rmtree(self.engine.profiles_dir / "shared")
        (self.engine.temp_dir / "shared").mkdir(parents=True)
        with self.assertRaises(ValidationError):
            self.profiles.import_profile(archive, confirmed=True)
        self.assertEqual(self.calls_of(patched, "import_profile"), [])

    def test_failure_removes_what_the_call_created(self):
        archive = self.valid_archive("shared.knsv")

        def fails_halfway(path):
            write(self.engine.profiles_dir / "shared" / "conf.yaml")
            write(self.engine.temp_dir / "shared" / "x")
            return fake_call(errors=("FileNotFoundError: dest",))

        patch_engine_call(self.engine, {"import_profile": fails_halfway})
        result = self.profiles.import_profile(archive, confirmed=True)
        self.assertFalse(result.ok)
        self.assertIn("may already be written", result.message)
        self.assertFalse((self.engine.profiles_dir / "shared").exists())
        self.assertFalse((self.engine.temp_dir / "shared").exists())

    def test_the_archive_is_not_extracted_by_the_validation(self):
        archive = self.valid_archive("shared.knsv")
        patch_engine_call(
            self.engine, {"import_profile": lambda *a, **k: fake_call(errors=("E: x",))}
        )
        self.profiles.import_profile(archive, confirmed=True)
        self.assertFalse((self.engine.temp_dir / "shared").exists())
        with zipfile.ZipFile(archive) as handle:
            self.assertIn("conf.yaml", handle.namelist())


class WipeTests(MockedServiceCase):
    """wipe_all -> wipe, without ever reading stdin."""

    def test_confirmation_is_mandatory(self):
        patched = patch_engine_call(self.engine, {"wipe": lambda *a, **k: fake_call()})
        with self.assertRaises(ConfirmationRequiredError):
            self.profiles.wipe_all()
        self.assertEqual(self.calls_of(patched, "wipe"), [])

    def test_the_prompt_is_answered_by_an_override_not_by_stdin(self):
        self.make_profile("p")
        seen = {}

        def wipes(*args, overrides=None, **kwargs):
            seen["answer"] = overrides["input"]("Enter WIPE: ")
            shutil.rmtree(self.engine.profiles_dir)
            return fake_call()

        patch_engine_call(self.engine, {"wipe": wipes})
        result = self.profiles.wipe_all(confirmed=True)
        self.assertEqual(seen["answer"], "WIPE")
        self.assertTrue(result.ok)
        self.assertTrue(self.engine.profiles_dir.is_dir(), "folder is recreated")

    def test_profiles_left_behind_mean_failure(self):
        self.make_profile("p")
        patch_engine_call(self.engine, {"wipe": lambda *a, **k: fake_call()})
        self.assertFalse(self.profiles.wipe_all(confirmed=True).ok)


class NotImplementedTests(MockedServiceCase):
    """Nothing is left unimplemented since the safety copies exist."""

    def test_the_list_of_missing_operations_is_empty(self):
        self.assertEqual(dict(NOT_IMPLEMENTED_OPERATIONS), {})


class ResultTests(unittest.TestCase):
    """OperationResult.raise_for_status."""

    def test_success_is_returned_and_failure_raises(self):
        good = OperationResult("x", True, "fine")
        self.assertIs(good.raise_for_status(), good)
        bad = OperationResult("x", False, "broken", errors=("E: boom",))
        with self.assertRaises(OperationFailedError) as caught:
            bad.raise_for_status()
        self.assertIs(caught.exception.result, bad)
        self.assertEqual(str(caught.exception), "broken")


if __name__ == "__main__":
    unittest.main()
