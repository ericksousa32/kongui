"""Tests added by the final audit: each one pins down a reproduced problem.

The names say what was wrong; the docstrings say how it showed up.
"""

import unittest
from unittest import mock

from tests.gui_helpers import HAVE_QT, GuiTestCase, ManualExecutor


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class CloseWhileBusyTests(GuiTestCase):
    """Closing the window used to freeze it, hide it and orphan the operation."""

    def test_window_stays_open_while_an_operation_runs(self):
        executor = ManualExecutor()
        window = self.make_window(executor=executor)
        window.controller.refresh()
        executor.run_next()
        self.assertTrue(window.controller.save("novo"))
        self.assertTrue(window.controller.busy)
        with mock.patch.object(executor, "shutdown") as shutdown:
            self.assertFalse(window.close())
            shutdown.assert_not_called()
        self.assertTrue(window.isVisible())
        self.assertIn("Operação em andamento", self.visible_toast_text(window))

    def test_window_closes_once_the_operation_is_over(self):
        executor = ManualExecutor()
        window = self.make_window(executor=executor)
        window.controller.save("novo")
        self.assertFalse(window.close())
        while executor.run_next():
            pass
        self.assertFalse(window.controller.busy)
        self.assertTrue(window.close())

    def visible_toast_text(self, window) -> str:
        """Text of every notification currently on screen."""
        from PySide6.QtWidgets import QLabel

        return " ".join(
            label.text() for label in window.toasts.findChildren(QLabel) if label.text()
        )


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class WorkerAfterTeardownTests(GuiTestCase):
    """A worker finishing after the interface is gone printed a traceback."""

    def test_job_survives_a_destroyed_signal_source(self):
        import shiboken6

        from kongui.gui.tasks import _Job, _Signals

        signals = _Signals()
        ran = []
        job = _Job(1, lambda: ran.append(True), signals)
        shiboken6.delete(signals)
        job.run()  # used to raise RuntimeError: Signal source has been deleted
        self.assertEqual(ran, [True])


if __name__ == "__main__":
    unittest.main()
