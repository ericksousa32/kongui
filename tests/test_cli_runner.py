"""Tests of kongui.core.cli.CliRunner (mocked ``subprocess.run`` + real CLI)."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from kongui.core import (
    READ_ONLY_FLAGS,
    CliExecutionError,
    CliResult,
    CliRunner,
    RunningAsRootError,
    ValidationError,
)
from tests.helpers import (
    IsolatedHomeTestCase,
    as_root,
    make_dist_info,
    non_root,
    really_root,
)


def completed(returncode=0, stdout="", stderr=""):
    """What ``subprocess.run`` returns, reduced to the fields that are used."""
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class CliResultTests(unittest.TestCase):
    """The exit code alone cannot be trusted: the original exits 0 on errors."""

    def test_a_clean_run_is_ok(self):
        self.assertTrue(CliResult(("-l",), 0, "ID\tNAME\n").ok)

    def test_a_reported_error_with_exit_code_zero_is_not_ok(self):
        result = CliResult(
            ("-l",),
            0,
            "Konsave: No profile found.\nPlease check the log at /x for more details.\n",
        )
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.reported_error)
        self.assertFalse(result.ok)

    def test_a_non_zero_exit_code_is_not_ok(self):
        self.assertFalse(CliResult(("--bad",), 2, "", "usage: error").ok)

    def test_a_timeout_is_not_ok(self):
        self.assertFalse(CliResult(("-l",), None, timed_out=True).ok)

    def test_version_parsing(self):
        self.assertEqual(
            CliResult(("-v",), 0, "Konsave: 2.2.0\n").parsed_version(), "2.2.0"
        )
        self.assertIsNone(CliResult(("-v",), 0, "something else\n").parsed_version())
        self.assertIsNone(CliResult(("-v",), 2, "Konsave: 2.2.0\n").parsed_version())


class RunnerConstructionTests(IsolatedHomeTestCase):
    """Root, home and timeout checks."""

    def test_root_is_refused(self):
        with self.assertRaises(RunningAsRootError):
            CliRunner(self.home, euid_provider=as_root)

    def test_home_must_be_an_existing_absolute_folder(self):
        for bad in (Path("relative"), self.base / "missing"):
            with self.subTest(home=bad):
                with self.assertRaises(ValidationError):
                    CliRunner(bad, euid_provider=non_root)

    def test_timeout_must_be_positive(self):
        for bad in (0, -1):
            with self.subTest(timeout=bad):
                with self.assertRaises(ValidationError):
                    CliRunner(self.home, timeout=bad, euid_provider=non_root)


class RootRefusalWithoutFilesystemTests(unittest.TestCase):
    """Runs even as root: the refusal happens before anything else."""

    def test_refusal_does_not_depend_on_the_home(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(RunningAsRootError):
                CliRunner(Path(folder), euid_provider=as_root)
            self.assertEqual(os.listdir(folder), [])


class MockedRunTests(IsolatedHomeTestCase):
    """How the command line is built and what is passed to subprocess."""

    def make(self, run, **kwargs):
        return CliRunner(self.home, euid_provider=non_root, run_func=run, **kwargs)

    def test_command_is_a_list_never_a_shell_string(self):
        run = mock.Mock(return_value=completed(stdout="Konsave: 1.0\n"))
        self.make(run, python="/usr/bin/python3").run(["--version"])
        (command,), kwargs = run.call_args
        self.assertEqual(command, ["/usr/bin/python3", "-m", "konsave", "--version"])
        self.assertIsInstance(command, list)
        self.assertIs(kwargs["shell"], False)
        self.assertIs(kwargs["check"], False)
        self.assertIs(kwargs["capture_output"], True)
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(kwargs["cwd"], str(self.home))
        self.assertEqual(kwargs["timeout"], CliRunner.DEFAULT_TIMEOUT)

    def test_environment_is_rebuilt_from_an_allow_list(self):
        run = mock.Mock(return_value=completed())
        secrets = {
            "AWS_SECRET_ACCESS_KEY": "s3cr3t",
            "GITHUB_TOKEN": "t0k3n",
            "LANG": "C",
        }
        with mock.patch.dict(os.environ, secrets):
            self.make(run, extra_pythonpath=[self.base / "meta"]).run(["-l"])
        env = run.call_args.kwargs["env"]
        self.assertEqual(env["HOME"], str(self.home))
        self.assertEqual(env["LANG"], "C")
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", env)
        self.assertNotIn("GITHUB_TOKEN", env)
        self.assertIn(str(self.base / "meta"), env["PYTHONPATH"].split(os.pathsep))
        import konsave

        repo_root = str(Path(konsave.__file__).resolve().parent.parent)
        self.assertEqual(env["PYTHONPATH"].split(os.pathsep)[0], repo_root)

    def test_custom_timeout_is_passed(self):
        run = mock.Mock(return_value=completed())
        self.make(run, timeout=5).run(["-l"])
        self.assertEqual(run.call_args.kwargs["timeout"], 5)

    def test_stdout_stderr_and_exit_code_are_returned(self):
        run = mock.Mock(return_value=completed(2, "out", "err"))
        result = self.make(run).run(["-h"])
        self.assertEqual(
            (result.returncode, result.stdout, result.stderr), (2, "out", "err")
        )
        self.assertEqual(result.args, ("-h",))
        self.assertFalse(result.ok)

    def test_bytes_and_none_output_are_handled(self):
        run = mock.Mock(return_value=completed(0, None, b"caf\xc3\xa9 \xff"))
        result = self.make(run).run(["-l"])
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "café �")

    def test_timeout_returns_a_result_with_the_partial_output(self):
        run = mock.Mock(
            side_effect=subprocess.TimeoutExpired(
                "cmd", 1, output=b"partial", stderr=None
            )
        )
        result = self.make(run).run(["-l"])
        self.assertTrue(result.timed_out)
        self.assertIsNone(result.returncode)
        self.assertEqual(result.stdout, "partial")
        self.assertFalse(result.ok)

    def test_an_interpreter_that_cannot_start_raises(self):
        run = mock.Mock(side_effect=FileNotFoundError("no such python"))
        with self.assertRaises(CliExecutionError):
            self.make(run, python="/nonexistent/python").run(["-l"])

    def test_version_helper(self):
        run = mock.Mock(return_value=completed(stdout="Konsave: 2.2.0\n"))
        self.assertEqual(self.make(run).version(), "2.2.0")
        run.return_value = completed(
            stdout="Konsave: boom\nPlease check the log at /x\n"
        )
        self.assertIsNone(self.make(run).version())


class ArgumentSafetyTests(IsolatedHomeTestCase):
    """Only exact read-only flags unless mutation is explicitly allowed."""

    def make(self, **kwargs):
        self.run_mock = mock.Mock(return_value=completed())
        return CliRunner(
            self.home, euid_provider=non_root, run_func=self.run_mock, **kwargs
        )

    def test_the_documented_read_only_flags(self):
        self.assertEqual(
            READ_ONLY_FLAGS, {"-h", "--help", "-v", "--version", "-l", "--list"}
        )
        runner = self.make()
        for flag in sorted(READ_ONLY_FLAGS):
            with self.subTest(flag=flag):
                runner.run([flag])

    def test_mutating_arguments_are_refused_by_default(self):
        runner = self.make()
        refused = [
            ["--save", "x"],
            ["-s", "x"],
            ["-a", "x"],
            ["--apply", "x"],
            ["-r", "x"],
            ["--remove", "x"],
            ["-w"],
            ["--wipe"],
            ["-e", "x"],
            ["-i", "x.knsv"],
            ["--force"],
            ["--sav", "x"],
            ["--lis"],
            ["-lv"],
            ["--list", "extra"],
            ["; rm -rf ~"],
            ["$(touch /tmp/pwned)"],
            [""],
        ]
        for args in refused:
            with self.subTest(args=args):
                with self.assertRaises(ValidationError):
                    runner.run(args)
        self.run_mock.assert_not_called()

    def test_malformed_argument_lists_are_refused(self):
        runner = self.make(allow_mutating=True)
        refused = [
            "--list",
            b"--list",
            None,
            ("-l", 5),
            ["-l", None],
            ["a\0b"],
            ["x" * (CliRunner.MAX_ARG_LENGTH + 1)],
            ["-l"] * (CliRunner.MAX_ARGS + 1),
        ]
        for args in refused:
            with self.subTest(args=args):
                with self.assertRaises(ValidationError):
                    runner.run(args)
        self.run_mock.assert_not_called()

    def test_mutating_mode_passes_each_argument_as_one_element(self):
        runner = self.make(allow_mutating=True, python="py")
        hostile = "name; rm -rf ~ && $(id) `id` | cat"
        runner.run(["--save", hostile])
        (command,), kwargs = self.run_mock.call_args
        self.assertEqual(command, ["py", "-m", "konsave", "--save", hostile])
        self.assertIs(kwargs["shell"], False)

    def test_a_tuple_of_arguments_is_accepted(self):
        self.make().run(("--list",))
        self.assertEqual(self.run_mock.call_args.args[0][-1], "--list")


@unittest.skipIf(really_root(), "refusing to start subprocesses as root")
class RealCliTests(IsolatedHomeTestCase):
    """The genuine ``python -m konsave`` in a throw-away home."""

    def setUp(self):
        super().setUp()
        self.meta = make_dist_info(self.base / "meta", "9.9.9")
        self.runner = CliRunner(
            self.home, euid_provider=non_root, extra_pythonpath=[self.meta], timeout=60
        )

    def test_version(self):
        result = self.runner.run(["--version"])
        self.assertTrue(result.ok, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "Konsave: 9.9.9")
        self.assertEqual(self.runner.version(), "9.9.9")

    def test_help_lists_the_documented_commands(self):
        result = self.runner.run(["--help"])
        self.assertTrue(result.ok)
        for flag in (
            "--list",
            "--save",
            "--apply",
            "--remove",
            "--wipe",
            "--export-profile",
            "--import-profile",
            "--export-directory",
        ):
            with self.subTest(flag=flag):
                self.assertIn(flag, result.stdout)

    def test_exit_code_zero_does_not_mean_success(self):
        (self.home / ".cache").mkdir()
        result = self.runner.run(["--list"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("No profile found", result.stdout)
        self.assertTrue(result.reported_error)
        self.assertFalse(result.ok)

    def test_without_the_cache_folder_the_original_error_handler_itself_crashes(self):
        """Known limitation: ``exception_handler`` cannot open ``~/.cache/konsave_log.txt``."""
        self.assertFalse((self.home / ".cache").exists())
        result = self.runner.run(["--list"])
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("FileNotFoundError", result.stderr)
        self.assertIn("konsave_log.txt", result.stderr)
        self.assertFalse(result.ok)

    def test_listing_with_a_profile(self):
        (self.home / ".config/konsave/profiles/demo").mkdir(parents=True)
        (self.home / ".cache").mkdir()
        result = self.runner.run(["--list"])
        self.assertTrue(result.ok, result.stdout)
        self.assertIn("demo", result.stdout)

    def test_the_first_run_creates_the_default_configuration_in_the_given_home(self):
        self.runner.run(["--version"])
        self.assertTrue((self.home / ".config/konsave/conf.yaml").is_file())

    def test_unknown_option_exits_with_status_two(self):
        mutating = CliRunner(
            self.home,
            euid_provider=non_root,
            extra_pythonpath=[self.meta],
            allow_mutating=True,
        )
        result = mutating.run(["--no-such-option"])
        self.assertEqual(result.returncode, 2)
        self.assertIn("unrecognized arguments", result.stderr)
        self.assertFalse(result.ok)

    def test_a_real_timeout_kills_the_process(self):
        slow = CliRunner(
            self.home,
            euid_provider=non_root,
            python=sys.executable,
            timeout=0.05,
            extra_pythonpath=[self.meta],
        )
        original = slow._run  # pylint: disable=protected-access

        def sleepy(command, **kwargs):
            return original([command[0], "-c", "import time; time.sleep(30)"], **kwargs)

        slow._run = sleepy  # pylint: disable=protected-access
        result = slow.run(["--version"])
        self.assertTrue(result.timed_out)
        self.assertFalse(result.ok)

    def test_nothing_is_written_outside_the_given_home(self):
        before = set(os.listdir(self.work))
        self.runner.run(["--version"])
        self.assertEqual(set(os.listdir(self.work)), before)


if __name__ == "__main__":
    unittest.main()
