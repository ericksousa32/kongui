"""The modal dialogs driven for real (``exec`` runs; buttons are clicked).

Other tests replace ``ask`` with a mock, which leaves the dialogs' own logic
untested: which button returns what, when Enter is ignored, how the backup
preview loads. This file closes that gap (found by the final coverage audit).
"""

from __future__ import annotations

import unittest
from datetime import datetime
from unittest import mock

from tests.gui_helpers import HAVE_QT, GuiTestCase

if HAVE_QT:
    from PySide6.QtCore import QEvent, QTimer, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication, QDialog

    from kongui.core import BackupInfo
    from kongui.gui.widgets.dialogs import (
        BackupsDialog,
        ChoiceDialog,
        ConfirmDialog,
        ConflictDialog,
        GroupNameDialog,
    )


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


class ChoiceDialogTests(DialogCase):
    """The conf.yaml conflict dialog: reload from disk or write anyway."""

    CHOICES = [("reload", "Recarregar", "default"), ("force", "Gravar", "danger-solid")]

    def ask(self, click):
        self.during_exec(click)
        return ChoiceDialog.ask(None, "Mudou", "O arquivo mudou.", self.CHOICES)

    def test_each_choice_returns_its_key(self):
        self.assertEqual(
            self.ask(lambda d: d.choice_buttons["reload"].click()), "reload"
        )
        self.assertEqual(self.ask(lambda d: d.choice_buttons["force"].click()), "force")

    def test_cancel_and_close_return_cancel(self):
        self.assertEqual(self.ask(lambda d: d.cancel_button.click()), "cancel")
        self.assertEqual(self.ask(lambda d: d.reject()), "cancel")

    def test_there_is_no_plain_confirm_button(self):
        seen = []
        self.ask(lambda d: (seen.append(d.confirm_button.isHidden()), d.reject()))
        self.assertEqual(seen, [True])


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


class GroupNameDialogTests(DialogCase):
    """Names of ``save``/``export`` groups are folder names."""

    def test_validation_follows_the_rules_as_you_type(self):
        dialog = GroupNameDialog(None, ["configs"])
        self.assertFalse(dialog.confirm_button.isEnabled())
        self.assertTrue(dialog.error_label.isHidden(), "no scolding before typing")
        for bad, fragment in (
            ("a/b", "sem “/”"),
            ("..", "sem “/”"),
            (".", "sem “/”"),
            ("configs", "Já existe"),
            ("   ", "Informe"),
        ):
            dialog.name_edit.setText(bad)
            self.assertFalse(dialog.confirm_button.isEnabled(), bad)
            self.assertIn(fragment, dialog.error_label.text(), bad)
        for good in ("novo", "meu grupo", "configuração ç", "a.b"):
            dialog.name_edit.setText(good)
            self.assertTrue(dialog.confirm_button.isEnabled(), good)
            self.assertTrue(dialog.error_label.isHidden())

    def test_enter_is_ignored_until_the_name_is_valid(self):
        dialog = GroupNameDialog(None, [])
        dialog.name_edit.setText("a/b")
        event = self.press(dialog, Qt.Key.Key_Return)
        self.assertFalse(event.isAccepted())
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
        dialog.name_edit.setText("ok")
        self.assertTrue(dialog.confirm_button.isEnabled())

    def test_ask_returns_the_name_or_none(self):
        def type_and_confirm(dialog):
            dialog.name_edit.setText("novo")
            dialog.confirm_button.click()

        self.during_exec(type_and_confirm)
        self.assertEqual(GroupNameDialog.ask(None, ["configs"]), "novo")
        self.during_exec(lambda d: d.cancel_button.click())
        self.assertIsNone(GroupNameDialog.ask(None, []))


class BackupsDialogTests(DialogCase):
    """Preview and restore of the saved ``conf.yaml`` versions."""

    @staticmethod
    def infos(*names):
        return [
            BackupInfo(name, None, datetime(2026, 10, 16, 21, 0, index), 100 + index)
            for index, name in enumerate(names)
        ]

    def make(self, *names):
        self.requests = []
        dialog = BackupsDialog(
            None,
            self.infos(*names),
            lambda name, done: self.requests.append((name, done)),
        )
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_empty_list_says_so_and_cannot_restore(self):
        dialog = self.make()
        self.assertFalse(dialog.empty_label.isHidden())
        self.assertTrue(dialog.list_widget.isHidden())
        self.assertFalse(dialog.confirm_button.isEnabled())
        self.assertIsNone(dialog.selected_name())

    def test_first_backup_is_previewed_and_restore_waits_for_it(self):
        dialog = self.make("conf.yaml.bak-2", "conf.yaml.bak-1")
        self.assertEqual([name for name, _ in self.requests], ["conf.yaml.bak-2"])
        self.assertEqual(dialog.preview.toPlainText(), "Carregando…")
        self.assertFalse(dialog.confirm_button.isEnabled())
        self.requests[0][1]("save: {}\nexport: {}\n", None)
        self.assertEqual(dialog.preview.toPlainText(), "save: {}\nexport: {}\n")
        self.assertTrue(dialog.confirm_button.isEnabled())

    def test_a_late_answer_for_another_row_is_ignored(self):
        dialog = self.make("a", "b")
        dialog.list_widget.setCurrentRow(1)
        self.assertEqual([name for name, _ in self.requests], ["a", "b"])
        self.requests[0][1]("texto de a", None)  # stale
        self.assertEqual(dialog.preview.toPlainText(), "Carregando…")
        self.assertFalse(dialog.confirm_button.isEnabled())
        self.requests[1][1]("texto de b", None)
        self.assertEqual(dialog.preview.toPlainText(), "texto de b")

    def test_a_read_error_is_shown_and_blocks_restoring(self):
        dialog = self.make("a")
        self.requests[0][1](None, PermissionError("negado"))
        self.assertIn("Não foi possível ler este backup", dialog.status_label.text())
        self.assertFalse(dialog.confirm_button.isEnabled())
        self.requests[0][1](None, None)
        self.assertFalse(dialog.confirm_button.isEnabled())

    def test_restore_returns_the_highlighted_backup(self):
        dialog = self.make("conf.yaml.bak-2", "conf.yaml.bak-1")
        dialog.list_widget.setCurrentRow(1)
        self.requests[1][1]("antigo", None)
        dialog.confirm_button.click()
        self.assertEqual(dialog.chosen, "conf.yaml.bak-1")
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)

    def test_closing_chooses_nothing(self):
        dialog = self.make("a")
        self.requests[0][1]("x", None)
        dialog.cancel_button.click()
        self.assertIsNone(dialog.chosen)
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)


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
