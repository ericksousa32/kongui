"""The cross-process lock, proved with real processes and the real kernel lock.

``konsave/lock.py`` is exercised directly, through the original CLI
(``python -m konsave``), through ``ProfileService`` (what the interface calls)
and with processes that are killed. Nothing here mocks ``fcntl``.
"""

import os
import signal
import stat
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

from kongui.core import (
    LockBusyError,
    LockCancelledError,
    LockTimeoutError,
    LockUnavailableError,
    LockUsageError,
)
from konsave.lock import (
    EXCLUSIVE,
    SHARED,
    OperationLock,
    default_lock_path,
    timeout_from_environment,
)
from tests.gui_helpers import pin_language
from tests.helpers import IsolatedHomeTestCase, make_dist_info, really_root

ROOT = Path(__file__).resolve().parent.parent

HOLDER = """
import sys
from konsave.lock import OperationLock
mode, path, operation = sys.argv[1:4]
with OperationLock(path).hold(mode, operation=operation, timeout=5):
    print("READY", flush=True)
    sys.stdin.readline()
"""

#: Runs a real ``konsave`` command whose ``save_profile`` pauses (still inside the
#: command's lock) until a "release" file appears.
SLOW_CLI = """
import os, sys, time
import konsave.funcs as funcs
marker, release = sys.argv[1], sys.argv[2]
original = funcs.save_profile
def slow(*args, **kwargs):
    open(marker, "w").close()
    while not os.path.exists(release):
        time.sleep(0.02)
    return original(*args, **kwargs)
funcs.save_profile = slow
sys.argv = ["konsave"] + sys.argv[3:]
import konsave.__main__ as cli
cli.main()
"""

#: Two ProfileService users in one process each: this one applies slowly.
SLOW_SERVICE = """
import os, sys, time
from pathlib import Path
from kongui.core import ConfigService, KonsaveEngine, ProfileService
home, marker, release = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
engine = KonsaveEngine(home, euid_provider=lambda: 1000)
service = ProfileService(engine, ConfigService(engine))
original = engine.funcs.apply_profile
def slow(*args, **kwargs):
    open(marker, "w").close()
    while not os.path.exists(release):
        time.sleep(0.02)
    return original(*args, **kwargs)
engine.funcs.apply_profile = slow
result = service.apply("work", confirmed=True)
print("DONE", result.ok, flush=True)
"""


class Child:
    """A helper process with line-based reading."""

    def __init__(self, test, args, env):
        self.proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            cwd=test.work,
        )
        test.addCleanup(self.stop)

    def line(self, timeout=15):
        """Reads one stdout line, failing the test instead of hanging."""
        timer = threading.Timer(timeout, self.proc.kill)
        timer.start()
        try:
            return self.proc.stdout.readline().strip()
        finally:
            timer.cancel()

    def finish(self, timeout=20):
        """Closes stdin and returns ``(returncode, stdout, stderr)``."""
        try:
            out, err = self.proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            out, err = self.proc.communicate()
        return self.proc.returncode, out, err

    def stop(self):
        """Kills the process if it is still alive."""
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.communicate()


@unittest.skipIf(really_root(), "refusing to start subprocesses as root")
class LockCase(IsolatedHomeTestCase):
    """A home, a lock path and helpers to start processes on it."""

    def setUp(self):
        super().setUp()
        self.meta = make_dist_info(self.base / "meta", "9.9.9")
        (self.home / ".cache").mkdir()
        self.engine, self.config, self.profiles = self.new_services()
        self.populate_live()
        self.path = default_lock_path(str(self.engine.konsave_dir))

    def env(self, **extra):
        env = dict(os.environ)
        env.update(
            HOME=str(self.home),
            PYTHONPATH=os.pathsep.join([str(ROOT), str(self.meta)]),
            PYTHONDONTWRITEBYTECODE="1",
        )
        env.pop("XDG_CURRENT_DESKTOP", None)
        env.update(extra)
        return env

    def holder(self, mode=EXCLUSIVE, operation="holder"):
        """Starts a process that holds the lock until its stdin is closed."""
        child = Child(
            self,
            [sys.executable, "-c", HOLDER, mode, self.path, operation],
            self.env(),
        )
        self.assertEqual(child.line(), "READY")
        return child

    def release(self, child):
        """Lets a holder exit and checks it ended well."""
        code, _, err = child.finish()
        self.assertEqual(code, 0, err)

    def cli(self, *args, timeout="0.3", background=False):
        """Runs ``python -m konsave`` on the test home."""
        command = [sys.executable, "-m", "konsave", *args]
        env = self.env(KONSAVE_LOCK_TIMEOUT=str(timeout))
        if background:
            return Child(self, command, env)
        done = subprocess.run(
            command,
            env=env,
            cwd=self.work,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        return done.returncode, done.stdout, done.stderr

    def slow_cli(self, *args):
        """Starts a CLI command that stays inside its lock until released."""
        self.marker = self.base / "marker"
        self.gate = self.base / "release"
        child = Child(
            self,
            [sys.executable, "-c", SLOW_CLI, str(self.marker), str(self.gate), *args],
            self.env(KONSAVE_LOCK_TIMEOUT="30"),
        )
        deadline = time.time() + 15
        while not self.marker.exists() and time.time() < deadline:
            time.sleep(0.02)
        self.assertTrue(self.marker.exists(), "the slow command never started")
        return child

    def open_gate(self):
        self.gate.write_text("go")

    def quick(self, mode, **kwargs):
        """Tries the lock in this process."""
        return OperationLock(self.path).hold(mode, **kwargs)


class OneProcessTests(LockCase):
    """The lock object itself, in this process."""

    def test_the_lock_file_is_private_stable_and_never_removed(self):
        with self.quick(EXCLUSIVE, timeout=0):
            first = os.stat(self.path)
        self.assertEqual(stat.S_IMODE(first.st_mode), 0o600)
        with self.quick(SHARED, timeout=0):
            pass
        self.assertEqual(os.stat(self.path).st_ino, first.st_ino)

    def test_an_exception_inside_releases_the_lock(self):
        with self.assertRaises(RuntimeError):
            with self.quick(EXCLUSIVE, timeout=0):
                raise RuntimeError("boom")
        child = self.holder()  # would block (and fail) if it were still held
        self.release(child)

    def test_it_is_reentrant_per_thread_but_never_upgrades(self):
        with self.quick(EXCLUSIVE, timeout=0):
            with self.quick(EXCLUSIVE, timeout=0):
                with self.quick(SHARED, timeout=0):
                    pass
        with self.quick(SHARED, timeout=0):
            with self.assertRaises(LockUsageError):
                with self.quick(EXCLUSIVE, timeout=0):
                    pass
        with self.quick(EXCLUSIVE, timeout=0):  # still usable afterwards
            pass

    def test_another_thread_has_to_wait(self):
        got = []
        with self.quick(EXCLUSIVE, timeout=0):

            def other():
                try:
                    with self.quick(EXCLUSIVE, timeout=0):
                        got.append("in")
                except LockBusyError:
                    got.append("busy")

            thread = threading.Thread(target=other)
            thread.start()
            thread.join(10)
        self.assertEqual(got, ["busy"])

    def test_cancel_ends_the_wait_without_touching_the_other_process(self):
        child = self.holder()
        cancel = threading.Event()
        waited = []
        threading.Timer(0.3, cancel.set).start()
        started = time.monotonic()
        with self.assertRaises(LockCancelledError):
            with self.quick(
                EXCLUSIVE, timeout=30, cancel=cancel, on_wait=waited.append
            ):
                pass
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(len(waited), 1, "on_wait is called once")
        # the other process still owns it
        with self.assertRaises(LockBusyError):
            with self.quick(EXCLUSIVE, timeout=0):
                pass
        self.release(child)

    def test_timeout_is_a_busy_error_not_a_system_error(self):
        child = self.holder(operation="apply")
        started = time.monotonic()
        with self.assertRaises(LockTimeoutError) as caught:
            with self.quick(EXCLUSIVE, timeout=0.4):
                pass
        self.assertGreaterEqual(time.monotonic() - started, 0.35)
        self.assertIsInstance(caught.exception, LockBusyError)
        self.assertNotIsInstance(caught.exception, LockUnavailableError)
        holder = caught.exception.holder
        self.assertEqual(holder["operation"], "apply")
        self.assertEqual(holder["pid"], child.proc.pid)
        self.release(child)
        with self.quick(EXCLUSIVE, timeout=0):  # and now it is free
            pass

    def test_timeout_settings_from_the_environment(self):
        read = timeout_from_environment
        self.assertEqual(read({}), 30.0)
        self.assertEqual(read({"KONSAVE_LOCK_TIMEOUT": "2.5"}), 2.5)
        self.assertEqual(read({"KONSAVE_LOCK_TIMEOUT": "0"}), 0.0)
        self.assertIsNone(read({"KONSAVE_LOCK_TIMEOUT": "-1"}))
        self.assertIsNone(read({"KONSAVE_LOCK_TIMEOUT": "inf"}))
        self.assertEqual(read({"KONSAVE_LOCK_TIMEOUT": "abc"}), 30.0)
        self.assertEqual(read({"KONSAVE_LOCK_TIMEOUT": "nan"}), 30.0)
        with self.assertRaises(ValueError):
            with self.quick("sideways"):
                pass


class TwoProcessTests(LockCase):
    """Real processes competing for the kernel lock."""

    def test_exclusive_excludes_exclusive_and_shared(self):
        child = self.holder(EXCLUSIVE)
        for mode in (EXCLUSIVE, SHARED):
            with self.subTest(mode=mode):
                with self.assertRaises(LockBusyError):
                    with self.quick(mode, timeout=0):
                        pass
        self.release(child)

    def test_shared_readers_coexist_but_keep_writers_out(self):
        first = self.holder(SHARED)
        second = self.holder(SHARED)
        with self.quick(SHARED, timeout=0):  # and a third one, here
            outcome = []

            def writer():  # another thread: a different lock holder
                try:
                    with self.quick(EXCLUSIVE, timeout=0):
                        outcome.append("got it")
                except LockBusyError:
                    outcome.append("busy")

            thread = threading.Thread(target=writer)
            thread.start()
            thread.join(10)
            self.assertEqual(outcome, ["busy"])
        with self.assertRaises(LockBusyError):
            with self.quick(EXCLUSIVE, timeout=0):
                pass
        self.release(first)
        with self.assertRaises(LockBusyError):
            with self.quick(EXCLUSIVE, timeout=0):
                pass
        self.release(second)
        with self.quick(EXCLUSIVE, timeout=0):
            pass

    def test_the_second_operation_waits_for_the_first(self):
        child = self.holder()
        result = []

        def second():
            with self.quick(EXCLUSIVE, timeout=20):
                result.append(time.monotonic())

        thread = threading.Thread(target=second)
        thread.start()
        time.sleep(0.4)
        self.assertEqual(result, [], "it must still be waiting")
        released = time.monotonic()
        self.release(child)
        thread.join(20)
        self.assertEqual(len(result), 1)
        self.assertGreaterEqual(result[0], released)

    def test_a_killed_process_releases_the_lock(self):
        child = self.holder(operation="crashing")
        child.proc.send_signal(signal.SIGKILL)
        child.proc.wait(10)
        with self.quick(EXCLUSIVE, timeout=2):  # the kernel dropped it
            pass

    def test_a_stale_record_is_not_taken_for_an_owner(self):
        child = self.holder(operation="crashing")
        child.proc.send_signal(signal.SIGKILL)
        child.proc.wait(10)
        third = self.holder(SHARED)  # a live shared holder keeps writers out
        with self.assertRaises(LockBusyError) as caught:
            with self.quick(EXCLUSIVE, timeout=0):
                pass
        self.assertIsNone(caught.exception.holder, "a dead pid is no holder")
        self.release(third)


class UnavailableTests(LockCase):
    """Real problems are not contention."""

    def test_a_folder_that_cannot_be_written(self):
        folder = Path(self.engine.konsave_dir)
        os.unlink(self.path)  # only a test may do this; it must be created again
        os.chmod(folder, 0o500)
        self.addCleanup(os.chmod, folder, 0o700)
        with self.assertRaises(LockUnavailableError) as caught:
            with self.quick(EXCLUSIVE, timeout=5):
                pass
        self.assertNotIsInstance(caught.exception, LockBusyError)

    def test_a_directory_or_a_link_in_place_of_the_file(self):
        os.unlink(self.path)
        os.mkdir(self.path)
        with self.assertRaises(LockUnavailableError):
            with self.quick(SHARED, timeout=0):
                pass
        os.rmdir(self.path)
        target = self.base / "elsewhere"
        target.write_text("")
        os.symlink(target, self.path)
        with self.assertRaises(LockUnavailableError):
            with self.quick(EXCLUSIVE, timeout=0):
                pass

    def test_a_missing_folder_is_created_privately(self):
        path = str(self.base / "fresh" / "konsave" / ".kongui.lock")
        with OperationLock(path).hold(EXCLUSIVE, timeout=0):
            pass
        self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode), 0o700)


class CliTests(LockCase):
    """The original command line, with the lock patch."""

    def test_commands_without_shared_data_never_wait(self):
        child = self.holder()
        for args in (["--version"], ["--help"], []):
            with self.subTest(args=args):
                code, out, err = self.cli(*args)
                self.assertEqual(code, 0, err)
                self.assertNotIn("waiting", err)
        self.release(child)

    def test_a_busy_lock_is_reported_and_nothing_changes(self):
        child = self.holder(operation="apply")
        code, out, err = self.cli("--save", "blocked", timeout="0.3")
        self.assertEqual(code, 75)
        self.assertIn("another Konsave operation", err)
        self.assertIn("Nothing was changed", err)
        self.assertNotIn("blocked", os.listdir(self.engine.profiles_dir))
        self.release(child)
        code, out, err = self.cli("--save", "blocked")
        self.assertEqual(code, 0, err)
        self.assertIn("blocked", os.listdir(self.engine.profiles_dir))

    def test_a_waiting_command_runs_when_the_lock_is_freed(self):
        child = self.holder()
        waiting = self.cli("--save", "later", timeout="30", background=True)
        time.sleep(0.6)
        self.assertIsNone(waiting.proc.poll(), "still waiting")
        self.release(child)
        code, out, err = waiting.finish()
        self.assertEqual(code, 0, err)
        self.assertIn("waiting", err)
        self.assertIn("later", os.listdir(self.engine.profiles_dir))

    def test_a_waiting_command_can_be_interrupted(self):
        child = self.holder()
        waiting = self.cli("--save", "never", timeout="-1", background=True)
        time.sleep(0.6)
        waiting.proc.send_signal(signal.SIGINT)
        code, out, err = waiting.finish()
        self.assertEqual(code, 130)
        self.assertIn("Nothing was changed", err)
        self.release(child)
        self.assertNotIn("never", os.listdir(self.engine.profiles_dir))

    def test_a_reader_waits_for_a_writer_and_writers_for_readers(self):
        writer = self.holder(EXCLUSIVE)
        self.assertEqual(self.cli("--list", timeout="0.3")[0], 75)
        self.release(writer)
        reader = self.holder(SHARED)
        self.assertEqual(self.cli("--list", timeout="0.3")[0], 0)  # readers coexist
        self.assertEqual(self.cli("--save", "w", timeout="0.3")[0], 75)
        self.release(reader)

    def test_two_cli_instances_never_overlap(self):
        first = self.slow_cli("--save", "one")
        code, out, err = self.cli("--save", "two", timeout="0.3")
        self.assertEqual(code, 75, err)
        second = self.cli("--save", "two", timeout="30", background=True)
        time.sleep(0.5)
        self.assertIsNone(second.proc.poll())
        self.assertNotIn("two", os.listdir(self.engine.profiles_dir))
        self.open_gate()
        self.assertEqual(first.finish()[0], 0)
        code, out, err = second.finish()
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(os.listdir(self.engine.profiles_dir)), ["one", "two"])

    def test_a_waiting_save_does_not_overwrite_what_the_first_one_created(self):
        """Upstream decides from a profile list read at import time; the patch
        reads it again after the lock, so the waiting command sees ``one``."""
        first = self.slow_cli("--save", "one")
        second = self.cli("--save", "one", timeout="30", background=True)
        time.sleep(0.5)
        self.open_gate()
        self.assertEqual(first.finish()[0], 0)
        code, out, err = second.finish()
        self.assertIn("already exists", out + err)
        self.assertEqual(
            (self.engine.profiles_dir / "one/configs/kdeglobals").read_text(),
            "kdeglobals-A",
        )

    def test_an_unusable_lock_is_an_error_not_a_hang(self):
        self.profiles.save("x").raise_for_status()
        folder = Path(self.engine.konsave_dir)
        os.chmod(self.path, 0o600)
        os.unlink(self.path)  # a test may remove it; real users must not
        os.chmod(folder, 0o500)
        self.addCleanup(os.chmod, folder, 0o700)
        code, out, err = self.cli("--list", timeout="1")
        self.assertEqual(code, 1)
        self.assertIn("cannot open the lock file", err)
        self.assertNotIn("Traceback", err)

    def test_the_first_run_creates_the_default_configuration_once(self):
        fresh = self.base / "fresh"
        (fresh / ".cache").mkdir(parents=True)
        env = self.env(HOME=str(fresh), KONSAVE_LOCK_TIMEOUT="30")
        command = [sys.executable, "-m", "konsave", "--version"]
        runs = [Child(self, command, env) for _ in range(4)]
        for run in runs:
            self.assertEqual(run.finish()[0], 0)
        self.assertTrue((fresh / ".config/konsave/conf.yaml").is_file())


class ServiceTests(LockCase):
    """What the interface calls (``ProfileService``) against other processes."""

    def setUp(self):
        super().setUp()
        pin_language(self)
        self.profiles.save("work").raise_for_status()
        self.profiles.engine.lock.policy.timeout = 0.3

    def test_an_operation_is_refused_while_another_process_writes(self):
        child = self.holder(operation="cli apply")
        with self.assertRaises(LockTimeoutError) as caught:
            self.profiles.apply("work", confirmed=True)
        self.assertEqual(caught.exception.holder["operation"], "cli apply")
        for call in (
            lambda: self.profiles.save("other"),
            lambda: self.profiles.remove("work", confirmed=True),
            lambda: self.profiles.wipe_all(confirmed=True),
            lambda: self.profiles.replace("work", confirmed=True),
            lambda: self.profiles.list_profiles(),
            lambda: self.profiles.export("work", directory=self.work),
            lambda: self.config.write_text(self.config.read_text()),
        ):
            with self.assertRaises(LockBusyError):
                call()
        self.release(child)
        self.assertEqual([p.name for p in self.profiles.list_profiles()], ["work"])
        self.assertTrue(self.profiles.apply("work", confirmed=True).ok)

    def test_nothing_is_written_when_the_lock_is_not_obtained(self):
        live = self.home / ".config/kdeglobals"
        live.write_text("MINE")
        child = self.holder()
        with self.assertRaises(LockBusyError):
            self.profiles.apply("work", confirmed=True)
        self.assertEqual(live.read_text(), "MINE")
        self.assertEqual(self.profiles.list_backups.__name__, "list_backups")
        self.release(child)
        self.assertEqual(self.profiles.list_backups(), [])

    def test_readers_run_together_and_writers_wait_for_them(self):
        child = self.holder(SHARED)
        self.assertEqual([p.name for p in self.profiles.list_profiles()], ["work"])
        self.assertTrue(self.profiles.export("work", directory=self.work).ok)
        with self.assertRaises(LockBusyError):
            self.profiles.save("blocked")
        self.release(child)

    def test_a_cancelled_wait_leaves_the_other_operation_alone(self):
        child = self.holder()
        cancel = threading.Event()
        self.profiles.engine.lock.policy.cancel = cancel
        self.profiles.engine.lock.policy.timeout = 30
        threading.Timer(0.3, cancel.set).start()
        with self.assertRaises(LockCancelledError):
            self.profiles.save("never")
        self.assertIsNone(child.proc.poll(), "the other process was not touched")
        self.release(child)

    def test_two_interface_instances_share_one_lock(self):
        marker, gate = self.base / "svc-marker", self.base / "svc-gate"
        first = Child(
            self,
            [
                sys.executable,
                "-c",
                SLOW_SERVICE,
                str(self.home),
                str(marker),
                str(gate),
            ],
            self.env(),
        )
        deadline = time.time() + 20
        while not marker.exists() and time.time() < deadline:
            time.sleep(0.02)
        self.assertTrue(marker.exists(), first.proc.poll())
        with self.assertRaises(LockTimeoutError):
            self.profiles.apply("work", confirmed=True)  # the second instance
        gate.write_text("go")
        code, out, err = first.finish()
        self.assertEqual(code, 0, err)
        self.assertIn("DONE True", out)
        self.assertTrue(self.profiles.apply("work", confirmed=True).ok)

    def test_the_interface_and_the_cli_exclude_each_other_both_ways(self):
        slow = self.slow_cli("--save", "cli-profile")
        with self.assertRaises(LockTimeoutError):
            self.profiles.save("gui-profile")
        self.open_gate()
        self.assertEqual(slow.finish()[0], 0)
        self.assertTrue(self.profiles.save("gui-profile").ok)
        # the other way round: the CLI refuses while the service holds the lock
        with self.engine.lock.hold(EXCLUSIVE, "gui apply"):
            code, out, err = self.cli("--save", "late", timeout="0.3")
        self.assertEqual(code, 75)
        self.assertIn("gui apply", err)
        self.assertNotIn("late", os.listdir(self.engine.profiles_dir))

    def test_nested_service_calls_do_not_deadlock(self):
        self.profiles.engine.lock.policy.timeout = 0
        self.assertTrue(self.profiles.replace("work", confirmed=True).ok)
        self.assertTrue(self.profiles.apply("work", confirmed=True).ok)
        (copy,) = [c for c in self.profiles.list_backups() if c.operation == "apply"]
        self.assertTrue(self.profiles.restore_backup(copy.id, confirmed=True).ok)

    def test_lock_errors_have_texts_in_the_interface(self):
        from kongui.gui import messages

        busy = " ".join(
            messages.describe_error(
                LockBusyError("x", {"pid": 7, "operation": "apply"})
            )
        )
        self.assertIn("Outra operação do Konsave está em andamento", busy)
        self.assertIn("processo 7", busy)
        self.assertIn(
            "cancelada", " ".join(messages.describe_error(LockCancelledError("x")))
        )
        self.assertIn(
            "arquivo de trava",
            " ".join(messages.describe_error(LockUnavailableError("denied"))),
        )
