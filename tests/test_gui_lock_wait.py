"""What the user sees when another process holds the lock (cross-process wait).

Two parts:

* the interface with the in-memory demo backend, whose ``start_other`` simulates
  another process, driven by a *real* worker thread so the window can be
  checked while the operation is waiting;
* the real services, below a temporary home, against a real helper process that
  holds the real ``flock``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

from PySide6.QtCore import QTimer

from kongui.core import LockCancelledError, LockTimeoutError
from kongui.gui import messages
from kongui.gui.backend import FakeBackend, ServiceBackend
from kongui.gui.tasks import ThreadExecutor
from tests import test_gui_real_backend as real
from tests.gui_helpers import GuiTestCase, WindowCase
from tests.test_locking import HOLDER

ROOT = Path(__file__).resolve().parent.parent
HOLDER_INFO = {"pid": 4242, "operation": "apply"}


class WaitCase(GuiTestCase):
    """A window with a worker thread and a backend that can be "contended"."""

    def open(self, backend=None):
        self.backend = backend or FakeBackend()
        self.executor = ThreadExecutor()
        window = self.make_window(backend=self.backend, executor=self.executor)
        self.addCleanup(self.executor.shutdown)
        self.assertTrue(self.wait_until(lambda: not window.controller.busy))
        self.outcomes = []
        window.controller.operation_finished.connect(self.outcomes.append)
        window.show_page("profiles")
        self.flush()
        return window

    def start_waiting(self, window, holder=HOLDER_INFO):
        """Starts a save while "another process" holds the lock."""
        if isinstance(self.backend, FakeBackend):
            self.backend.start_other(holder)
            self.addCleanup(self.backend.finish_other)
        self.assertTrue(window.controller.save("Novo"))
        self.addCleanup(self.settle, window)
        self.assertTrue(self.wait_until(lambda: window.controller.waiting))

    def settle(self, window):
        """Lets a still-waiting operation end before the window is destroyed."""
        self.backend.finish_other()
        self.wait_until(lambda: not window.controller.busy)


class WaitingTests(WaitCase):
    """The wait, as the window shows it."""

    def test_the_banner_explains_the_wait_and_actions_are_locked(self):
        window = self.open()
        self.start_waiting(window)
        banner = window.wait_banner
        self.assertTrue(banner.isVisibleTo(window))
        self.assertIn("Aguardando outra operação", banner.title_label.text())
        shown = " ".join(
            label.text() for label in banner.findChildren(type(banner.title_label))
        )
        self.assertIn("processo 4242", shown)
        self.assertIn("não verificado", shown)
        page = window.pages["profiles"]
        self.assertFalse(page.new_button.isEnabled())
        self.assertFalse(page.wipe_button.isEnabled())
        self.assertTrue(banner.cancel_button.isEnabled())
        self.assertTrue(window.controller.busy)

    def test_the_window_stays_responsive_while_waiting(self):
        window = self.open()
        ticks = []
        timer = QTimer(window)
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start(10)
        self.start_waiting(window)
        self.assertTrue(self.wait_until(lambda: len(ticks) >= 5, 3))
        window.show_page("settings")  # navigation still works
        self.assertEqual(window.current_key, "settings")
        timer.stop()

    def test_cancelling_the_wait_changes_nothing_and_unlocks_the_window(self):
        window = self.open()
        before = [p.name for p in window.store.profiles()]
        self.start_waiting(window)
        self.assertTrue(window.wait_banner.cancel_button.isEnabled())
        window.wait_banner.cancel_button.click()
        self.assertTrue(window.controller.cancelling)
        self.assertFalse(window.wait_banner.cancel_button.isEnabled())
        self.assertFalse(window.controller.cancel_wait(), "a second click does nothing")
        self.assertTrue(self.wait_until(lambda: not window.controller.busy))
        (outcome,) = self.outcomes
        self.assertFalse(outcome.ok)
        self.assertIsInstance(outcome.error, LockCancelledError)
        self.assertTrue(window.wait_banner.isHidden())
        self.assertEqual([p.name for p in window.store.profiles()], before)
        self.assertNotIn(("save", "Novo"), self.backend.calls)
        self.assertTrue(window.pages["profiles"].new_button.isEnabled())
        # the cancelled wait does not poison the next operation
        self.backend.finish_other()
        self.assertTrue(window.controller.save("Depois"))
        self.assertTrue(self.wait_until(lambda: not window.controller.busy))
        self.assertTrue(self.outcomes[-1].ok)

    def test_the_operation_runs_when_the_other_one_ends(self):
        window = self.open()
        self.start_waiting(window)
        self.backend.finish_other()
        self.assertTrue(self.wait_until(lambda: not window.controller.busy))
        self.assertTrue(self.outcomes[-1].ok)
        self.assertIn("Novo", [p.name for p in window.store.profiles()])
        self.assertTrue(window.wait_banner.isHidden())
        self.assertFalse(window.controller.waiting)

    def test_the_wait_ends_with_a_clear_message_when_time_runs_out(self):
        window = self.open()
        self.backend.lock_timeout = 0.2
        self.start_waiting(window)
        self.assertTrue(self.wait_until(lambda: not window.controller.busy))
        outcome = self.outcomes[-1]
        self.assertIsInstance(outcome.error, LockTimeoutError)
        text = " ".join(outcome.details)
        self.assertIn("não terminou a tempo", text)
        self.assertIn("Nada foi alterado", text)
        self.assertTrue(window.wait_banner.isHidden())

    def test_cancelling_when_nothing_waits_does_nothing(self):
        window = self.open()
        self.assertFalse(window.controller.cancel_wait())
        self.assertFalse(window.controller.waiting)

    def test_closing_is_refused_while_waiting_and_says_why(self):
        window = self.open()
        self.start_waiting(window)
        shown = []
        original = window.toasts.show_message
        window.toasts.show_message = lambda *args, **kw: (
            shown.append(args),
            original(*args, **kw),
        )[1]
        self.assertFalse(window.close())
        self.assertIn("Cancele a espera", shown[-1][2])

    def test_a_cancelled_wait_is_an_info_toast_not_an_error(self):
        window = self.open()
        shown = []
        original = window.toasts.show_message
        window.toasts.show_message = lambda *args, **kw: (
            shown.append(args),
            original(*args, **kw),
        )[1]
        self.start_waiting(window)
        window.controller.cancel_wait()
        self.assertTrue(self.wait_until(lambda: not window.controller.busy))
        self.assertEqual(shown[-1][:2], ("info", "Espera cancelada"))

    def test_a_waiting_refresh_can_be_cancelled_and_retried(self):
        window = self.open()
        self.backend.start_other(HOLDER_INFO)
        self.addCleanup(self.backend.finish_other)
        window.controller.refresh()
        self.assertTrue(self.wait_until(lambda: window.controller.waiting))
        window.controller.cancel_wait()
        self.assertTrue(self.wait_until(lambda: not window.controller.busy))
        self.assertTrue(window.wait_banner.isHidden())
        self.backend.finish_other()
        self.assertTrue(window.controller.refresh())
        self.assertTrue(self.wait_until(lambda: not window.controller.busy))
        self.assertTrue(self.outcomes[-1].ok)

    def test_the_card_being_processed_says_it_is_waiting(self):
        window = self.open()
        page = window.pages["profiles"]
        name = page.cards()[0].profile_name
        self.backend.start_other(HOLDER_INFO)
        self.addCleanup(self.backend.finish_other)
        window.controller.apply(name, confirmed=True)
        self.assertTrue(self.wait_until(lambda: window.controller.waiting))
        card = next(c for c in page.cards() if c.profile_name == name)
        self.assertIn("Aguardando", card.busy_label.text())
        window.controller.cancel_wait()
        self.assertTrue(self.wait_until(lambda: not window.controller.busy))


class BackgroundReadTests(WindowCase):
    """Reads that are not operations must not look like a wait."""

    def test_a_wait_reported_outside_an_operation_is_ignored(self):
        window = self.open_window()
        window.controller._on_wait_reported(
            {"pid": 1}
        )  # pylint: disable=protected-access
        self.assertFalse(window.controller.waiting)
        self.assertTrue(window.wait_banner.isHidden())


class MessageTests(unittest.TestCase):
    """The texts for the banner."""

    def test_describe_wait_without_and_with_holder(self):
        title, lines = messages.describe_wait(None)
        self.assertIn("Aguardando", title)
        self.assertEqual(len(lines), 1)
        _, lines = messages.describe_wait({"pid": 9, "operation": "save"})
        self.assertIn("“save”, processo 9", lines[-1])
        self.assertEqual(messages.holder_hint({}), "")


@unittest.skipIf(real.really_root(), "refusing to run file operations as root")
class RealLockWaitTests(real.RealBackendCase):
    """Real services, real worker thread, a real process holding the real lock."""

    def setUp(self):
        super().setUp()
        self.executor = ThreadExecutor()
        self.addCleanup(self.executor.shutdown)
        self.backend = ServiceBackend(self.service)
        self.window = self.make_window(backend=self.backend, executor=self.executor)
        self.assertTrue(self.wait_until(lambda: not self.window.controller.busy))
        self.outcomes = []
        self.window.controller.operation_finished.connect(self.outcomes.append)
        self.holder = subprocess.Popen(
            [
                sys.executable,
                "-c",
                HOLDER,
                "exclusive",
                self.engine.lock.path,
                "cli save",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            env={**os.environ, "PYTHONPATH": str(ROOT)},
        )
        self.addCleanup(self.stop_holder)
        self.assertEqual(self.holder.stdout.readline().strip(), "READY")

    def stop_holder(self):
        if self.holder.poll() is None:
            self.holder.stdin.close()
            self.holder.wait(10)
        if not self.holder.stdout.closed:
            self.holder.stdout.close()

    def test_waits_for_a_real_process_then_saves(self):
        controller = self.window.controller
        self.assertTrue(controller.save("later"))
        self.assertTrue(self.wait_until(lambda: controller.waiting))
        self.assertEqual(controller.waiting_holder["operation"], "cli save")
        self.assertEqual(controller.waiting_holder["pid"], self.holder.pid)
        self.assertFalse(self.folder("later").exists())
        self.stop_holder()
        self.assertTrue(self.wait_until(lambda: not controller.busy, 10))
        self.assertTrue(self.outcomes[-1].ok, self.outcomes[-1])
        self.assertTrue(self.folder("later").is_dir())

    def test_cancel_leaves_the_other_process_and_the_disk_alone(self):
        controller = self.window.controller
        self.assertTrue(controller.save("never"))
        self.assertTrue(self.wait_until(lambda: controller.waiting))
        self.window.wait_banner.cancel_button.click()
        self.assertTrue(self.wait_until(lambda: not controller.busy, 10))
        self.assertIsInstance(self.outcomes[-1].error, LockCancelledError)
        self.assertFalse(self.folder("never").exists())
        self.assertIsNone(self.holder.poll(), "the other process was not touched")

    def test_the_wait_times_out_with_the_real_lock(self):
        self.engine.lock.policy.timeout = 0.3
        controller = self.window.controller
        started = time.monotonic()
        self.assertTrue(controller.save("late"))
        self.assertTrue(self.wait_until(lambda: not controller.busy, 10))
        self.assertLess(time.monotonic() - started, 5)
        self.assertIsInstance(self.outcomes[-1].error, LockTimeoutError)
        self.assertFalse(self.folder("late").exists())


if __name__ == "__main__":
    unittest.main()
