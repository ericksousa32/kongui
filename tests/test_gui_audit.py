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


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class ExportWarningTextTests(GuiTestCase):
    """The new service warnings reach the user, in Portuguese."""

    def test_known_warnings_are_translated_and_unknown_ones_kept(self):
        from kongui.core import CONF_DIFFERS_PREFIX
        from kongui.gui import messages

        differs = f"{CONF_DIFFERS_PREFIX} (+ only in the active file, - only in the profile, ~ changed): save(+more); export(-x)"
        text = messages.describe_warning(differs)
        self.assertIn("save(+more); export(-x)", text)
        self.assertIn("conf.yaml atual", text)
        self.assertNotIn("only in", text)
        nodata = messages.describe_warning(
            "the archive has no data folder in save/ for: a, b (the imported profile could not be applied)"
        )
        self.assertIn("a, b", nodata)
        self.assertIn("não poderá ser aplicado", nodata)
        extra = messages.describe_warning(
            "save/ has folders that its conf.yaml does not list: old (they are ignored when the profile is applied)"
        )
        self.assertIn("old", extra)
        self.assertEqual(messages.describe_warning("something else"), "something else")

    def test_a_successful_export_shows_the_warning(self):
        from kongui.core import CONF_DIFFERS_PREFIX, OperationResult
        from kongui.gui.controller import ProfileController

        result = OperationResult(
            "export",
            True,
            "ok",
            warnings=(f"{CONF_DIFFERS_PREFIX} (legend): save(+more)",),
        )
        outcome = ProfileController._outcome("export", "work", result, None, None)
        self.assertTrue(outcome.ok)
        self.assertTrue(
            any("Aviso: O .knsv leva o conf.yaml atual" in d for d in outcome.details),
            outcome.details,
        )

    def test_import_form_shows_what_the_archive_is_missing(self):
        from kongui.gui.backend import ArchiveInfo

        window = self.make_window()
        page = window.show_page("transfer")
        info = ArchiveInfo(
            "/x/p.knsv",
            "p",
            0.1,
            ("configs", "more"),
            (),
            (
                "the archive has no data folder in save/ for: more (the imported profile could not be applied)",
            ),
            False,
        )
        with mock.patch.object(window.backend, "inspect_archive", return_value=info):
            self.assertTrue(page.set_import_file("/x/p.knsv"))
            self.flush()
        self.assertIn(
            "Aviso: O arquivo não traz dados para os grupos: more",
            page.import_info.text(),
        )


if __name__ == "__main__":
    unittest.main()
