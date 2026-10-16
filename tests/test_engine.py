"""Tests of kongui.core.engine (loading, isolation, call observation)."""

import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import konsave

from kongui.core import engine as engine_module
from kongui.core.engine import (
    ALLOWED_CALLS,
    EngineCall,
    KonsaveEngine,
    extract_log_errors,
)
from kongui.core.errors import EngineLoadError, RunningAsRootError, ValidationError
from tests.helpers import BASE_CONF, IsolatedHomeTestCase, as_root, non_root, write

LOG_SAMPLE = """[15/10/2026 10:00:00]
Traceback (most recent call last):
  File "x.py", line 1, in f
AssertionError: No profile saved yet.

[15/10/2026 10:00:01]
Traceback (most recent call last):
FileNotFoundError: [Errno 2] No such file or directory: '/x'

"""


def konsave_modules() -> dict:
    """Snapshot of the Konsave modules currently in ``sys.modules``."""
    return {k: id(v) for k, v in sys.modules.items() if k.startswith("konsave")}


class RootRefusalTests(unittest.TestCase):
    """Root must be refused before anything is created (runs even as root)."""

    def test_engine_refuses_root_without_touching_the_disk(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(RunningAsRootError):
                KonsaveEngine(Path(folder), euid_provider=as_root)
            self.assertEqual(os.listdir(folder), [])


class LogParsingTests(unittest.TestCase):
    """The original handler writes a header and a traceback per error."""

    def test_one_summary_per_entry(self):
        self.assertEqual(
            extract_log_errors(LOG_SAMPLE),
            (
                "AssertionError: No profile saved yet.",
                "FileNotFoundError: [Errno 2] No such file or directory: '/x'",
            ),
        )

    def test_empty_and_unrelated_text(self):
        self.assertEqual(extract_log_errors(""), ())
        self.assertEqual(extract_log_errors("no header here\n"), ())

    def test_header_without_traceback(self):
        self.assertEqual(
            extract_log_errors("[15/10/2026 10:00:00]\n"), ("unknown error",)
        )


class EngineCallValueTests(unittest.TestCase):
    """EngineCall.failed / error_messages."""

    def test_clean_call(self):
        call = EngineCall("save_profile", None, "", "", ())
        self.assertFalse(call.failed)
        self.assertEqual(call.error_messages, ())

    def test_logged_error_fails(self):
        call = EngineCall("x", None, "", "", ("E: boom",))
        self.assertTrue(call.failed)

    def test_escaped_exception_fails_and_is_reported(self):
        call = EngineCall("x", None, "", "", (), RuntimeError("bad"))
        self.assertTrue(call.failed)
        self.assertEqual(call.error_messages, ("RuntimeError: bad",))


class EngineLoadingTests(IsolatedHomeTestCase):
    """The engine binds a private copy of Konsave to the chosen home."""

    def test_paths_live_inside_the_chosen_home(self):
        engine = self.new_engine()
        self.assertEqual(engine.home, self.home)
        for path in (
            engine.konsave_dir,
            engine.profiles_dir,
            engine.config_file,
            engine.temp_dir,
            engine.log_file,
        ):
            with self.subTest(path=path):
                self.assertTrue(str(path).startswith(str(self.home) + os.sep))
        self.assertEqual(engine.config_file, self.home / ".config/konsave/conf.yaml")
        self.assertEqual(engine.export_extension, ".knsv")
        self.assertTrue(engine.version)

    def test_loading_leaves_the_process_untouched(self):
        modules_before = konsave_modules()
        attrs_before = {
            n: hasattr(konsave, n) for n in ("consts", "parse", "funcs", "__version__")
        }
        home_env = os.environ["HOME"]
        # A *different* home, otherwise a missing restore would be invisible.
        self.new_engine(self.base / "elsewhere")
        self.assertEqual(os.environ["HOME"], home_env)
        self.assertNotEqual(os.environ["HOME"], str(self.base / "elsewhere"))
        self.assertEqual(konsave_modules(), modules_before)
        self.assertEqual({n: hasattr(konsave, n) for n in attrs_before}, attrs_before)

    def test_a_missing_package_version_is_supplied_only_while_loading(self):
        """An uninstalled checkout has no ``konsave.__version__``."""
        if hasattr(konsave, "__version__"):
            original = konsave.__version__
            del konsave.__version__
            self.addCleanup(setattr, konsave, "__version__", original)
        engine = self.new_engine()
        self.assertEqual(engine.version, engine_module.FALLBACK_VERSION)
        self.assertFalse(hasattr(konsave, "__version__"))

    def test_an_installed_package_version_is_used_and_kept(self):
        had = hasattr(konsave, "__version__")
        previous = getattr(konsave, "__version__", None)

        def restore():
            if had:
                konsave.__version__ = previous
            else:
                del konsave.__version__

        konsave.__version__ = "7.7.7"
        self.addCleanup(restore)
        engine = self.new_engine()
        self.assertEqual(engine.version, "7.7.7")
        self.assertEqual(konsave.__version__, "7.7.7")

    def test_the_real_home_is_not_used_to_create_folders(self):
        other = self.base / "other_home"
        engine = self.new_engine(other)
        self.assertTrue(engine.profiles_dir.is_dir())
        self.assertTrue(str(engine.profiles_dir).startswith(str(other)))
        self.assertFalse((self.home / ".config").exists())

    def test_two_engines_do_not_share_state(self):
        first, _, profiles = self.new_services()
        self.populate_live()
        profiles.save("only-in-first").raise_for_status()
        second = self.new_engine(self.base / "second")
        self.assertEqual(first.profile_names(), ["only-in-first"])
        self.assertEqual(second.profile_names(), [])

    def test_home_must_be_an_existing_absolute_folder(self):
        for bad in (Path("relative"), self.base / "missing"):
            with self.subTest(home=bad):
                with self.assertRaises(ValidationError):
                    KonsaveEngine(bad, euid_provider=non_root)

    def test_import_failure_is_wrapped_and_state_restored(self):
        modules_before = konsave_modules()
        home_env = os.environ["HOME"]
        with mock.patch.object(
            engine_module.importlib, "import_module", side_effect=ImportError("nope")
        ):
            with self.assertRaises(EngineLoadError):
                KonsaveEngine(self.home, euid_provider=non_root)
        self.assertEqual(konsave_modules(), modules_before)
        self.assertEqual(os.environ["HOME"], home_env)

    def test_missing_function_is_detected(self):
        real = engine_module._load_modules  # pylint: disable=protected-access

        def without_export(home):
            modules = real(home)
            del modules["funcs"].export
            return modules

        with mock.patch.object(engine_module, "_load_modules", without_export):
            with self.assertRaises(EngineLoadError):
                KonsaveEngine(self.home, euid_provider=non_root)

    def test_only_known_functions_can_be_called(self):
        engine = self.new_engine()
        self.assertEqual(
            ALLOWED_CALLS,
            {
                "save_profile",
                "apply_profile",
                "remove_profile",
                "export",
                "import_profile",
                "wipe",
                "read_konsave_config",
            },
        )
        for name in ("copy", "mkdir", "list_profiles", "main", "__import__", "nope"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    engine.call(name)


class EngineRuntimeTests(IsolatedHomeTestCase):
    """Behaviour of ensure_runtime_dirs, profile_names and call."""

    def test_runtime_dirs_are_created(self):
        engine = self.new_engine()
        (self.home / ".cache").mkdir(exist_ok=True)
        engine.profiles_dir.rmdir()
        engine.ensure_runtime_dirs()
        self.assertTrue(engine.profiles_dir.is_dir())
        self.assertTrue(engine.log_file.parent.is_dir())

    def test_profile_names_are_fresh_not_a_snapshot(self):
        engine = self.new_engine()
        self.assertEqual(engine.profile_names(), [])
        (engine.profiles_dir / "b").mkdir()
        (engine.profiles_dir / "a").mkdir()
        self.assertEqual(engine.profile_names(), ["a", "b"])

    def test_profile_names_without_folder(self):
        engine = self.new_engine()
        engine.profiles_dir.rmdir()
        self.assertEqual(engine.profile_names(), [])

    def test_call_captures_stdout(self):
        engine = self.new_engine()
        write(engine.config_file, BASE_CONF)
        self.populate_live()
        call = engine.call("save_profile", "p", [], force=False)
        self.assertFalse(call.failed)
        self.assertIn("saving profile", call.stdout)
        self.assertEqual(call.stderr, "")
        self.assertIsNone(call.returned)

    def test_call_detects_an_error_the_original_swallows(self):
        engine = self.new_engine()
        call = engine.call("remove_profile", "ghost", [], 0)
        self.assertIsNone(call.returned)
        self.assertTrue(call.failed)
        self.assertEqual(call.errors, ("AssertionError: No profile saved yet.",))
        self.assertIn("Please check the log", call.stdout)

    def test_errors_are_attributed_only_to_their_own_call(self):
        engine = self.new_engine()
        failing = engine.call("remove_profile", "ghost", [], 0)
        write(engine.config_file, BASE_CONF)
        working = engine.call("save_profile", "p", [], force=False)
        self.assertTrue(failing.failed)
        self.assertFalse(working.failed)

    def test_call_works_without_the_cache_folder(self):
        engine = self.new_engine()
        self.assertFalse((self.home / ".cache").exists())
        call = engine.call("remove_profile", "ghost", [], 0)
        self.assertEqual(len(call.errors), 1)
        self.assertIsNone(call.raised)

    def test_exception_escaping_the_handler_is_captured(self):
        engine = self.new_engine()
        with mock.patch.object(
            engine.funcs, "save_profile", side_effect=RuntimeError("boom")
        ):
            call = engine.call("save_profile", "p", [])
        self.assertTrue(call.failed)
        self.assertEqual(call.error_messages, ("RuntimeError: boom",))

    def test_stderr_is_captured_separately(self):
        engine = self.new_engine()

        def noisy(*_args, **_kwargs):
            print("to-out")
            print("to-err", file=sys.stderr)

        with mock.patch.object(engine.funcs, "save_profile", noisy):
            call = engine.call("save_profile", "p", [])
        self.assertEqual(call.stdout, "to-out\n")
        self.assertEqual(call.stderr, "to-err\n")
        self.assertFalse(call.failed)

    def test_process_streams_are_restored(self):
        engine = self.new_engine()
        out, err = sys.stdout, sys.stderr
        engine.call("remove_profile", "ghost", [], 0)
        self.assertIs(sys.stdout, out)
        self.assertIs(sys.stderr, err)

    def test_overrides_are_temporary(self):
        engine = self.new_engine()
        (engine.profiles_dir / "p").mkdir()
        call = engine.call("wipe", overrides={"input": lambda _prompt="": "WIPE"})
        self.assertFalse(call.failed)
        self.assertFalse(engine.profiles_dir.exists())
        self.assertFalse(hasattr(engine.funcs, "input"))

    def test_the_original_can_never_block_waiting_for_the_terminal(self):
        """``wipe`` without an override must fail fast, not wait for stdin."""
        engine = self.new_engine()
        (engine.profiles_dir / "p").mkdir()
        # Even if the process stdin would answer the prompt, it is not read.
        with mock.patch.object(sys, "stdin", io.StringIO("WIPE\n")):
            call = engine.call("wipe")
        self.assertTrue(call.failed)
        self.assertTrue(any("EOFError" in error for error in call.errors), call.errors)
        self.assertTrue((engine.profiles_dir / "p").is_dir(), "nothing was wiped")

    def test_stdin_is_restored_after_a_call(self):
        engine = self.new_engine()
        stdin = sys.stdin
        engine.call("remove_profile", "ghost", [], 0)
        self.assertIs(sys.stdin, stdin)

    def test_overrides_are_removed_even_if_the_call_raises(self):
        engine = self.new_engine()
        with mock.patch.object(engine.funcs, "wipe", side_effect=RuntimeError("x")):
            engine.call("wipe", overrides={"input": lambda _p="": "WIPE"})
        self.assertFalse(hasattr(engine.funcs, "input"))

    def test_read_konsave_config_returns_the_resolved_mapping(self):
        engine = self.new_engine()
        write(engine.config_file, BASE_CONF)
        call = engine.call("read_konsave_config", str(engine.config_file))
        self.assertFalse(call.failed)
        self.assertEqual(
            call.returned["save"]["configs"]["location"], str(self.home / ".config")
        )


if __name__ == "__main__":
    unittest.main()
