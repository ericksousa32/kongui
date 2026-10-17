"""Safety copies in the interface (RN-01): outcome text, dialog, controller.

Demo tests use ``FakeBackend``; the end-to-end ones use the real services in a
temporary home (nothing touches the real session).
"""

from __future__ import annotations

import unittest
from unittest import mock

from tests.gui_helpers import HAVE_QT, WindowCase
from tests.test_gui_real_backend import RealBackendCase
from tests.helpers import write

if HAVE_QT:
    from kongui.core import ConfirmationRequiredError, SnapshotNotFoundError
    from kongui.gui import messages
    from kongui.gui.widgets.dialogs import ConfirmDialog, SafetyCopiesDialog


def confirm(result):
    """Patches ``ConfirmDialog.ask``."""
    return mock.patch.object(ConfirmDialog, "ask", return_value=result)


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class DemoSafetyCopyTests(WindowCase):
    """The dialog and the controller on the fictitious backend."""

    def setUp(self):
        super().setUp()
        patcher = confirm(True)  # also outlives the window's own cleanup
        self.ask = patcher.start()
        self.addCleanup(patcher.stop)

    def open_dialog(self):
        window = self.open_window(page="settings")
        page = window.pages["settings"]
        dialog = page.build_safety_copies_dialog()
        self.addCleanup(dialog.close)
        self.run_all()
        return window, page, dialog

    def make_copies(self, window):
        window.controller.apply("Trabalho", confirmed=True)
        self.run_all()
        window.controller.apply("Gaming", confirmed=True)
        self.run_all()

    def test_an_empty_list_says_so(self):
        _, _, dialog = self.open_dialog()
        self.assertEqual(dialog.list_widget.count(), 0)
        self.assertIn("Ainda não há cópias", dialog.status_label.text())
        self.assertFalse(dialog.confirm_button.isEnabled())
        self.assertFalse(dialog.delete_button.isEnabled())

    def test_apply_adds_a_copy_and_the_notice_names_it(self):
        window, page, dialog = self.open_dialog()
        self.make_copies(window)
        page.reload_safety_copies()
        self.run_all()
        self.assertEqual(dialog.list_widget.count(), 2)
        self.assertIn("Antes de aplicar “Gaming”", dialog.list_widget.item(0).text())
        details = "\n".join(self.outcomes[-1].details)
        self.assertIn("Cópia de segurança guardada", details)
        self.assertNotIn("Aviso: Cópia de segurança", details)

    def test_restore_asks_first_and_then_calls_the_backend(self):
        window, page, dialog = self.open_dialog()
        self.make_copies(window)
        page.reload_safety_copies()
        self.run_all()
        self.ask.return_value = False
        dialog.confirm_button.click()
        self.run_all()
        self.assertNotIn("restore_backup", [c[0] for c in self.backend.calls])
        self.ask.return_value = True
        dialog.confirm_button.click()
        self.run_all()
        self.assertIn("restore_backup", [c[0] for c in self.backend.calls])
        self.assertEqual(self.outcomes[-1].title, "Cópia de segurança restaurada")
        self.assertTrue(self.ask.call_args.kwargs["destructive"])

    def test_delete_removes_one_copy_and_refreshes_the_list(self):
        window, page, dialog = self.open_dialog()
        self.make_copies(window)
        page.reload_safety_copies()
        self.run_all()
        dialog.list_widget.setCurrentRow(1)
        dialog.delete_button.click()
        self.run_all()
        self.assertEqual(dialog.list_widget.count(), 1)
        self.assertIn("“Gaming”", dialog.list_widget.item(0).text())
        self.assertEqual(self.outcomes[-1].title, "Cópia de segurança apagada")

    def test_declining_the_delete_keeps_the_copy(self):
        window, page, dialog = self.open_dialog()
        self.make_copies(window)
        page.reload_safety_copies()
        self.run_all()
        self.ask.return_value = False
        dialog.delete_button.click()
        self.run_all()
        self.assertEqual(dialog.list_widget.count(), 2)

    def test_buttons_are_locked_while_an_operation_runs(self):
        window, page, dialog = self.open_dialog()
        self.make_copies(window)
        page.reload_safety_copies()
        self.run_all()
        self.assertTrue(dialog.confirm_button.isEnabled())
        window.controller.refresh()  # queued, not run: the controller is busy
        self.flush()
        self.assertFalse(dialog.confirm_button.isEnabled())
        self.assertFalse(dialog.delete_button.isEnabled())
        self.run_all()
        self.assertTrue(dialog.confirm_button.isEnabled())

    def test_a_list_error_is_shown_in_the_dialog(self):
        window, page, dialog = self.open_dialog()
        self.backend.fail_next("list_backups", SnapshotNotFoundError("gone"))
        page.reload_safety_copies()
        self.run_all()
        self.assertIn("não existe mais", dialog.status_label.text())
        self.assertEqual(dialog.list_widget.count(), 0)

    def test_a_copy_that_vanished_is_reported_and_the_list_reloaded(self):
        window, page, dialog = self.open_dialog()
        self.make_copies(window)
        page.reload_safety_copies()
        self.run_all()
        self.backend._copies.clear()  # deleted behind the dialog's back
        dialog.confirm_button.click()
        self.run_all()
        self.assertFalse(self.outcomes[-1].ok)
        self.assertEqual(dialog.list_widget.count(), 0)

    def test_the_controller_refuses_without_a_real_true(self):
        window = self.open_window()
        for flag in (False, 1, "yes"):
            with self.assertRaises(ConfirmationRequiredError):
                window.controller.restore_backup("x", confirmed=flag)
            with self.assertRaises(ConfirmationRequiredError):
                window.controller.delete_backup("x", confirmed=flag)

    def test_closing_the_dialog_disconnects_it(self):
        window, page, dialog = self.open_dialog()
        dialog.reject()
        self.flush()
        self.assertIsNone(page._copies_dialog)
        window.controller.apply("Trabalho", confirmed=True)
        self.run_all()  # must not touch the closed dialog

    def test_the_settings_button_opens_the_dialog(self):
        window = self.open_window(page="settings")
        page = window.pages["settings"]
        with mock.patch.object(SafetyCopiesDialog, "exec", return_value=0) as shown:
            page.copies_button.click()
            self.run_all()
        shown.assert_called_once()

    def test_apply_and_import_confirmations_no_longer_say_there_is_no_backup(self):
        window = self.open_window()
        with confirm(False) as sure:
            window.pages["profiles"].actions.apply(window, "Gaming")
        self.assertNotIn("sem backup", sure.call_args.args[2])
        self.assertIn("Cópias de segurança", sure.call_args.args[2])


class MessageTests(unittest.TestCase):
    """The texts for the notes and errors."""

    def test_notes(self):
        from kongui.core import KEPT_PREFIX, UNDO_PREFIX

        kept = messages.describe_note(f"{KEPT_PREFIX}20260101-000000-000000-apply")
        self.assertTrue(kept.startswith("Cópia de segurança guardada"))
        self.assertIn("20260101-000000-000000-apply", kept)
        undo = messages.describe_note(f"{UNDO_PREFIX}x-restore")
        self.assertNotIn("Aviso:", undo)
        self.assertEqual(
            messages.describe_note("something else"), "Aviso: something else"
        )

    def test_errors(self):
        from kongui.core import SnapshotError

        text = " ".join(messages.describe_error(SnapshotError("disk full")))
        self.assertIn("operação não foi feita", text)
        self.assertIn("disk full", text)
        self.assertIn(
            "não existe mais",
            " ".join(messages.describe_error(SnapshotNotFoundError("x"))),
        )
        self.assertEqual(
            messages.failure_title("restore_backup", "20260101-000000-000000-apply"),
            "Não foi possível restaurar a cópia de segurança",
        )


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class RealSafetyCopyTests(RealBackendCase):
    """The controller on the real services."""

    def test_apply_then_restore_through_the_controller(self):
        self.controller.save("work")
        write(self.root / ".config/kdeglobals", "UNSAVED")
        self.controller.apply("work", confirmed=True)
        self.assertTrue(self.last().ok, self.last().details)
        self.assertTrue(
            any("Cópia de segurança guardada" in d for d in self.last().details)
        )
        (copy,) = self.backend.list_backups()
        self.controller.restore_backup(copy.id, confirmed=True)
        self.assertTrue(self.last().ok, self.last().details)
        self.assertEqual((self.root / ".config/kdeglobals").read_text(), "UNSAVED")
        self.assertEqual(len(self.backend.list_backups()), 2)
        self.controller.delete_backup(copy.id, confirmed=True)
        self.assertTrue(self.last().ok)
        self.assertEqual(len(self.backend.list_backups()), 1)

    def test_a_copy_failure_is_an_error_and_nothing_is_applied(self):
        self.controller.save("work")
        write(self.root / ".config/kdeglobals", "KEEP")
        with mock.patch(
            "kongui.core.snapshot.shutil.copy2", side_effect=OSError("disk full")
        ):
            self.controller.apply("work", confirmed=True)
        self.assertFalse(self.last().ok)
        self.assertIn("cópia de segurança", " ".join(self.last().details))
        self.assertEqual((self.root / ".config/kdeglobals").read_text(), "KEEP")
        self.assertEqual(self.controller.active_name, "")
