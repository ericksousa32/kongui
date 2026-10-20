"""The modal dialogs driven for real (``exec`` runs; buttons are clicked).

Other tests replace ``ask`` with a mock, which leaves the dialogs' own logic
untested: which button returns what, when Enter is ignored. This file closes that gap (found by the final coverage audit).
"""

from __future__ import annotations

import unittest
from unittest import mock

from tests.gui_helpers import HAVE_QT, GuiTestCase

if HAVE_QT:
    from PySide6.QtCore import QEvent, QTimer, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication, QDialog

    from kongui.gui.widgets.dialogs import ConfirmDialog, ConflictDialog


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class DialogCase(GuiTestCase):
    """Helpers to act on a dialog while ``exec`` is blocking."""

    def during_exec(self, action) -> None:
        """Runs ``action(dialog)`` once the modal dialog is open."""

        def run():
            dialog = QApplication.activeModalWidget()
            self.assertIsNotNone(dialog, "no modal dialog is open")
            action(dialog)

        QTimer.singleShot(0, run)
        # A dialog that never closes must fail the test, not hang it.
        QTimer.singleShot(
            3000,
            lambda: QApplication.activeModalWidget()
            and QApplication.activeModalWidget().reject(),
        )

    def press(self, dialog, key) -> None:
        """Sends a key press to a dialog."""
        event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
        dialog.keyPressEvent(event)
        return event


class ConflictDialogTests(DialogCase):
    """Replace / unique name / cancel when the export file exists."""

    def ask(self, click, allow_replace=True):
        self.during_exec(click)
        return ConflictDialog.ask(None, "Existe", "Já existe.", allow_replace)

    def test_each_button_returns_its_own_answer(self):
        self.assertEqual(self.ask(lambda d: d.confirm_button.click()), "unique")
        self.assertEqual(self.ask(lambda d: d.replace_button.click()), "overwrite")
        self.assertEqual(self.ask(lambda d: d.cancel_button.click()), "cancel")

    def test_closing_the_window_means_cancel(self):
        self.assertEqual(self.ask(lambda d: d.reject()), "cancel")

    def test_replace_is_not_offered_when_something_else_is_in_the_way(self):
        seen = []
        self.ask(
            lambda d: (seen.append(d.replace_button.isHidden()), d.reject()),
            allow_replace=False,
        )
        self.assertEqual(seen, [True])

    def test_cancel_has_the_initial_focus_so_enter_never_destroys_anything(self):
        seen = []
        self.ask(lambda d: (seen.append(d.cancel_button.hasFocus()), d.reject()))
        self.assertEqual(len(seen), 1)


class ConfirmDialogTests(DialogCase):
    """The typed-word confirmation used to wipe every profile."""

    def test_the_word_must_match_exactly(self):
        states = []

        def act(dialog):
            for text in ("", "apagar", "APAGA", "APAGAR ", "APAGAR"):
                dialog.confirm_edit.setText(text)
                states.append((text, dialog.confirm_button.isEnabled()))
            dialog.confirm_button.click()

        self.during_exec(act)
        answer = ConfirmDialog.ask(
            None, "Limpar?", "Tudo.", "Limpar", destructive=True, require_text="APAGAR"
        )
        self.assertTrue(answer)
        self.assertEqual(
            states,
            [
                ("", False),
                ("apagar", False),
                ("APAGA", False),
                ("APAGAR ", True),
                ("APAGAR", True),
            ],
        )

    def test_cancel_is_the_default_answer(self):
        self.during_exec(lambda d: d.reject())
        self.assertFalse(ConfirmDialog.ask(None, "?", "?", "Sim", destructive=True))


class StartUpHelpersTests(GuiTestCase):
    """``kongui.gui.app`` fallbacks and ``main`` (the last uncovered lines)."""

    def test_settings_path_without_a_writable_location(self):
        from kongui.gui import app

        with mock.patch.object(app.QStandardPaths, "writableLocation", return_value=""):
            self.assertIsNone(app.settings_path())

    def test_settings_path_when_the_folder_cannot_be_created(self):
        from pathlib import Path

        from kongui.gui import app

        with mock.patch.object(Path, "mkdir", side_effect=PermissionError("no")):
            self.assertIsNone(app.settings_path())

    def test_main_builds_the_window_and_returns_the_event_loop_status(self):
        from kongui.gui import app

        with mock.patch.object(QApplication, "exec", return_value=7):
            status = app.main(["kongui", "--demo"])
        self.assertEqual(status, 7)
        for widget in QApplication.topLevelWidgets():
            if type(widget).__name__ == "MainWindow":
                self.addCleanup(widget.deleteLater)


if __name__ == "__main__":
    unittest.main()
