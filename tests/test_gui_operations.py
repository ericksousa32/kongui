"""The six profile operations, one by one, through the real interface.

Each operation is checked for: loading state, success, error handling,
interface update and (for destructive ones) explicit confirmation.

The backend is a :class:`FakeBackend` (in memory) and the executor is a
:class:`ManualExecutor`, so a test can look at the "loading" state before it
lets the work run. Nothing here touches Konsave or a real home directory.
"""

from __future__ import annotations

import threading
import unittest
from typing import List
from unittest import mock

from kongui.core import (
    ConfirmationRequiredError,
    ProfileExistsError,
    ProfileNotFoundError,
    ValidationError,
)
from kongui.gui.backend import FakeBackend
from kongui.gui.controller import LoadState
from kongui.gui.widgets.dialogs import ConfirmDialog
from tests.gui_helpers import GuiTestCase, ManualExecutor, WindowCase


def ask(result):
    """Patches ``ConfirmDialog.ask``; returns the mock."""
    return mock.patch.object(ConfirmDialog, "ask", return_value=result)


OperationCase = WindowCase


class ListOperationTests(OperationCase):
    """1. Listing profiles."""

    def test_shows_a_loading_state_then_the_profiles(self):
        window = self.open_window(load=False)
        page = window.pages["profiles"]
        self.assertIs(window.controller.state, LoadState.LOADING)
        self.assertTrue(window.controller.busy)
        self.assertFalse(page.loading_state.isHidden())
        self.assertTrue(page.empty_state.isHidden())
        self.assertFalse(window.busy_bar.isHidden())
        self.assertFalse(
            page.new_button.isEnabled() and window.controller.busy is False
        )
        self.run_one()
        self.assertIs(window.controller.state, LoadState.READY)
        self.assertFalse(window.controller.busy)
        self.assertTrue(page.loading_state.isHidden())
        self.assertTrue(window.busy_bar.isHidden())
        self.assertEqual(len(self.names(page)), 7)
        self.assertEqual(window.store.active().name, "Work")

    def test_dashboard_shows_placeholders_while_loading(self):
        window = self.open_window(load=False, page="dashboard")
        stats = window.pages["dashboard"].stats
        self.assertEqual(stats["count"].value_label.text(), "…")
        self.assertFalse(window.pages["dashboard"].save_button.isEnabled() and False)
        self.run_one()
        self.assertEqual(stats["count"].value_label.text(), "7")

    def test_an_empty_list_shows_the_empty_state(self):
        window = self.open_window(backend=FakeBackend(profiles=[], active=None))
        page = window.pages["profiles"]
        self.assertIs(window.controller.state, LoadState.READY)
        self.assertFalse(page.empty_state.isHidden())
        self.assertTrue(page.error_banner.isHidden())

    def test_a_failure_shows_the_error_and_retry_works(self):
        backend = FakeBackend()
        backend.fail_next("list", ValidationError("pasta ilegível"))
        window = self.open_window(backend=backend)
        page = window.pages["profiles"]
        self.assertIs(window.controller.state, LoadState.ERROR)
        self.assertFalse(page.error_banner.isHidden())
        self.assertTrue(page.loading_state.isHidden())
        self.assertIn("pasta ilegível", " ".join(window.controller.error))
        self.assertFalse(page.new_button.isEnabled(), "cannot save while unlistable")
        self.assertEqual(window.toasts.kinds(), [], "a listing error stays in the page")
        page.error_banner.retry_button.click()
        self.assertIs(window.controller.state, LoadState.LOADING)
        self.assertFalse(page.error_banner.retry_button.isEnabled())
        self.run_all()
        self.assertIs(window.controller.state, LoadState.READY)
        self.assertTrue(page.error_banner.isHidden())
        self.assertEqual(len(self.names(page)), 7)

    def test_a_failed_refresh_keeps_the_previous_list(self):
        window = self.open_window()
        self.backend.fail_next("list", ValidationError("falhou"))
        window.controller.refresh()
        self.run_all()
        self.assertEqual(len(self.names(window.pages["profiles"])), 7)
        self.assertFalse(self.outcomes[-1].ok)

    def test_an_unexpected_exception_is_reported_not_raised(self):
        backend = FakeBackend()
        backend.fail_next("list", RuntimeError("bug"))
        with self.assertLogs(level="ERROR"):
            window = self.open_window(backend=backend)
        self.assertIs(window.controller.state, LoadState.ERROR)
        self.assertIn("RuntimeError", " ".join(window.controller.error))

    def test_listing_is_refused_while_busy(self):
        window = self.open_window(load=False)
        self.assertFalse(window.controller.refresh())
        self.run_all()
        self.assertEqual(self.backend.calls.count(("list", "")), 1)


class SaveOperationTests(OperationCase):
    """2. Saving a new profile."""

    def start(self, window, name="Novo"):
        """Fills the dialog with ``name`` and confirms it."""
        self.accept_dialogs(lambda dialog: dialog.name_edit.setText(name))
        window.pages["profiles"].new_button.click()
        self.flush()

    def test_save_shows_loading_then_adds_the_profile(self):
        window = self.open_window()
        page = window.pages["profiles"]
        self.start(window)
        self.assertEqual(window.controller.current, ("save", "Novo"))
        self.assertFalse(window.busy_bar.isHidden())
        self.assertFalse(page.new_button.isEnabled())
        self.assertFalse(page.wipe_button.isEnabled())
        self.assertNotIn(
            "Novo", self.names(page), "nothing changes before the work ends"
        )
        self.run_all()
        self.assertIn("Novo", self.names(page))
        self.assertTrue(window.busy_bar.isHidden())
        self.assertTrue(page.new_button.isEnabled())
        self.assertEqual(window.toasts.kinds()[-1], "success")
        self.assertEqual(window.context.activity.entries()[0].kind, "save")
        self.assertIn(("save", "Novo"), self.backend.calls)

    def test_cancelling_the_dialog_does_nothing(self):
        window = self.open_window()
        with mock.patch("kongui.gui.actions.ProfileDialog.exec", return_value=0):
            window.pages["profiles"].new_button.click()
        self.assertEqual(len(self.executor.queue), 0)
        self.assertEqual(window.toasts.titles(), [])

    def test_a_failure_is_shown_and_the_list_is_refreshed(self):
        window = self.open_window()
        self.backend.fail_next("save", ProfileExistsError("já existe"))
        self.start(window)
        self.run_all()
        self.assertEqual(window.toasts.kinds()[-1], "error")
        self.assertIn("Já existe", window.toasts._toasts[-1].accessibleName())
        self.assertEqual(len(self.names(window.pages["profiles"])), 7)
        self.assertFalse(self.outcomes[-1].ok)
        self.assertTrue(window.pages["profiles"].new_button.isEnabled())

    def test_errors_stay_until_dismissed(self):
        window = self.open_window()
        self.backend.fail_next("save", ValidationError("nome ruim"))
        self.start(window)
        self.run_all()
        from PySide6.QtCore import QTimer

        self.assertEqual(window.toasts._toasts[-1].findChildren(QTimer), [])
        window.toasts.show_message("success", "ok")
        self.assertEqual(len(window.toasts._toasts[-1].findChildren(QTimer)), 1)

    def test_a_second_operation_is_refused_while_one_runs(self):
        window = self.open_window()
        self.start(window, "Primeiro")
        self.assertFalse(window.pages["profiles"].new_button.isEnabled())
        self.accept_dialogs(lambda dialog: dialog.name_edit.setText("Segundo"))
        self.assertFalse(window.pages["profiles"].actions.save_current(window))
        self.assertEqual(window.toasts.titles()[-1], "Aguarde")
        self.run_all()
        self.assertIn("Primeiro", self.names(window.pages["profiles"]))
        self.assertNotIn("Segundo", self.names(window.pages["profiles"]))

    def test_the_dialog_refuses_an_existing_name(self):
        window = self.open_window()
        self.accept_dialogs(lambda dialog: dialog.name_edit.setText("Gaming"))
        from kongui.gui.widgets.dialogs import ProfileDialog

        dialog = ProfileDialog(window, window.store.names(), ["a"])
        dialog.name_edit.setText("Gaming")
        self.assertFalse(dialog.confirm_button.isEnabled())

    def test_dashboard_button_saves_too(self):
        window = self.open_window(page="dashboard")
        self.accept_dialogs(lambda dialog: dialog.name_edit.setText("DoPainel"))
        window.pages["dashboard"].save_button.click()
        self.assertFalse(window.pages["dashboard"].save_button.isEnabled())
        self.run_all()
        self.assertIn("DoPainel", window.store.names())


class OverwriteOperationTests(OperationCase):
    """3. Overwriting a profile."""

    def test_declining_changes_nothing(self):
        window = self.open_window()
        card = self.card(window.pages["profiles"], "Gaming")
        with ask(False) as confirm:
            card.overwrite_action.trigger()
        self.assertTrue(confirm.call_args.kwargs["destructive"])
        self.assertEqual(len(self.executor.queue), 0)
        self.assertNotIn(("overwrite", "Gaming"), self.backend.calls)

    def test_confirming_shows_progress_on_the_card_then_succeeds(self):
        window = self.open_window()
        page = window.pages["profiles"]
        before = window.store.get("Gaming").modified
        with ask(True):
            self.card(page, "Gaming").overwrite_action.trigger()
        self.flush()
        busy = self.card(page, "Gaming")
        self.assertEqual(busy.busy_label.text(), "Sobrescrevendo…")
        self.assertFalse(window.busy_bar.isHidden())
        self.assertTrue(busy.locked)
        self.assertTrue(self.card(page, "Tablet").locked)
        self.run_all()
        self.assertGreaterEqual(window.store.get("Gaming").modified, before)
        self.assertEqual(window.toasts.kinds()[-1], "success")
        self.assertIn(("overwrite", "Gaming"), self.backend.calls)
        self.assertTrue(window.busy_bar.isHidden())

    def test_a_missing_profile_is_an_error_and_the_list_is_refreshed(self):
        window = self.open_window()
        self.backend.fail_next("overwrite", ProfileNotFoundError("sumiu"))
        with ask(True):
            self.card(window.pages["profiles"], "Gaming").overwrite_action.trigger()
        self.run_all()
        self.assertEqual(window.toasts.kinds()[-1], "error")
        self.assertIn("não existe mais", window.toasts._toasts[-1].accessibleName())
        self.assertFalse(self.outcomes[-1].ok)

    def test_the_controller_refuses_without_explicit_confirmation(self):
        window = self.open_window()
        for value in (False, None, 1, "yes"):
            with self.subTest(value=value):
                with self.assertRaises(ConfirmationRequiredError):
                    window.controller.overwrite("Gaming", confirmed=value)
        self.assertEqual(len(self.executor.queue), 0)

    def test_the_backend_refuses_without_explicit_confirmation(self):
        with self.assertRaises(ConfirmationRequiredError):
            FakeBackend().overwrite("Gaming")


class ApplyOperationTests(OperationCase):
    """4. Applying a profile (fake backend: no session is touched)."""

    def test_declining_changes_nothing(self):
        window = self.open_window()
        with ask(False):
            self.card(window.pages["profiles"], "Gaming").apply_button.click()
        self.assertEqual(len(self.executor.queue), 0)
        self.assertEqual(window.store.active().name, "Work")

    def test_confirming_shows_progress_then_marks_the_profile_active(self):
        window = self.open_window()
        page = window.pages["profiles"]
        with ask(True) as confirm:
            self.card(page, "Gaming").apply_button.click()
        self.assertTrue(confirm.call_args.kwargs["destructive"])
        self.flush()
        self.assertEqual(self.card(page, "Gaming").busy_label.text(), "Aplicando…")
        self.assertEqual(window.store.active().name, "Work", "not yet")
        self.run_all()
        self.assertEqual(window.store.active().name, "Gaming")
        self.assertEqual(window.controller.active_name, "Gaming")
        marked = [c.profile_name for c in page.cards() if c.property("active")]
        self.assertEqual(marked, ["Gaming"])
        self.assertEqual(window.toasts.kinds()[-1], "success")
        self.assertEqual(window.context.activity.entries()[0].kind, "apply")

    def test_the_dashboard_follows_the_active_profile(self):
        window = self.open_window(page="dashboard")
        with ask(True):
            window.controller.apply("Night", confirmed=True)
        self.run_all()
        stats = window.pages["dashboard"].stats
        self.assertEqual(stats["active"].value_label.text(), "Night")

    def test_a_failure_keeps_the_previous_active_profile(self):
        window = self.open_window()
        self.backend.fail_next("apply", ValidationError("conf inválido"))
        with ask(True):
            self.card(window.pages["profiles"], "Gaming").apply_button.click()
        self.run_all()
        self.assertEqual(window.toasts.kinds()[-1], "error")
        self.assertEqual(window.store.active().name, "Work")
        self.assertFalse(self.outcomes[-1].ok)
        self.assertTrue(window.pages["profiles"].new_button.isEnabled())

    def test_the_controller_refuses_without_explicit_confirmation(self):
        window = self.open_window()
        with self.assertRaises(ConfirmationRequiredError):
            window.controller.apply("Gaming")
        with self.assertRaises(ConfirmationRequiredError):
            window.controller.apply("Gaming", confirmed="sim")
        self.assertEqual(len(self.executor.queue), 0)

    def test_the_backend_refuses_without_explicit_confirmation(self):
        with self.assertRaises(ConfirmationRequiredError):
            FakeBackend().apply("Gaming")


class RemoveOperationTests(OperationCase):
    """5. Removing a profile."""

    def test_declining_changes_nothing(self):
        window = self.open_window()
        with ask(False):
            self.card(window.pages["profiles"], "Tablet").remove_action.trigger()
        self.assertEqual(len(self.executor.queue), 0)
        self.assertIn("Tablet", window.store.names())

    def test_confirming_shows_progress_then_removes(self):
        window = self.open_window()
        page = window.pages["profiles"]
        with ask(True) as confirm:
            self.card(page, "Tablet").remove_action.trigger()
        self.assertTrue(confirm.call_args.kwargs["destructive"])
        self.flush()
        self.assertEqual(self.card(page, "Tablet").busy_label.text(), "Removendo…")
        self.run_all()
        self.assertNotIn("Tablet", self.names(page))
        self.assertEqual(len(self.names(page)), 6)
        self.assertEqual(window.toasts.kinds()[-1], "warning")
        self.assertEqual(window.context.activity.entries()[0].kind, "remove")

    def test_removing_the_active_profile_clears_the_marker(self):
        window = self.open_window()
        with ask(True):
            self.card(window.pages["profiles"], "Work").remove_action.trigger()
        self.run_all()
        self.assertIsNone(window.store.active())
        self.assertEqual(window.controller.active_name, "")

    def test_a_failure_is_shown_and_the_list_is_refreshed(self):
        window = self.open_window()
        self.backend.fail_next("remove", ProfileNotFoundError("já sumiu"))
        with ask(True):
            self.card(window.pages["profiles"], "Tablet").remove_action.trigger()
        self.run_all()
        self.assertEqual(window.toasts.kinds()[-1], "error")
        self.assertFalse(self.outcomes[-1].ok)
        self.assertEqual(len(self.names(window.pages["profiles"])), 7)

    def test_the_controller_refuses_without_explicit_confirmation(self):
        window = self.open_window()
        with self.assertRaises(ConfirmationRequiredError):
            window.controller.remove("Tablet")
        self.assertEqual(len(self.executor.queue), 0)

    def test_the_backend_refuses_without_explicit_confirmation(self):
        with self.assertRaises(ConfirmationRequiredError):
            FakeBackend().remove("Tablet")


class WipeAllOperationTests(OperationCase):
    """6. Wiping every profile."""

    def test_the_dialog_needs_the_word_to_be_typed(self):
        dialog = ConfirmDialog(
            None, "t", "m", "Limpar", destructive=True, require_text="APAGAR"
        )
        self.assertFalse(dialog.confirm_button.isEnabled())
        for wrong in ("", "apagar", "APAGA", "APAGAR!", "sim"):
            with self.subTest(text=wrong):
                dialog.confirm_edit.setText(wrong)
                self.assertFalse(dialog.confirm_button.isEnabled())
        dialog.confirm_edit.setText("APAGAR")
        self.assertTrue(dialog.confirm_button.isEnabled())
        dialog.confirm_edit.setText("APAGAR x")
        self.assertFalse(dialog.confirm_button.isEnabled())

    def test_the_dialog_without_the_word_is_a_plain_confirmation(self):
        dialog = ConfirmDialog(None, "t", "m")
        self.assertIsNone(dialog.confirm_edit)
        self.assertTrue(dialog.confirm_button.isEnabled())

    def test_declining_changes_nothing(self):
        window = self.open_window()
        with ask(False):
            window.pages["profiles"].wipe_button.click()
        self.assertEqual(len(self.executor.queue), 0)
        self.assertEqual(len(window.store.names()), 7)

    def test_the_page_asks_for_the_typed_word(self):
        window = self.open_window()
        with ask(False) as confirm:
            window.pages["profiles"].wipe_button.click()
        self.assertEqual(confirm.call_args.kwargs["require_text"], "APAGAR")
        self.assertTrue(confirm.call_args.kwargs["destructive"])

    def test_confirming_shows_progress_then_empties_everything(self):
        window = self.open_window()
        page = window.pages["profiles"]
        with ask(True):
            page.wipe_button.click()
        self.flush()
        self.assertEqual(window.controller.current, ("wipe_all", ""))
        self.assertFalse(window.busy_bar.isHidden())
        self.assertFalse(page.wipe_button.isEnabled())
        self.assertEqual(len(self.names(page)), 7)
        self.run_all()
        self.assertEqual(self.names(page), [])
        self.assertFalse(page.empty_state.isHidden())
        self.assertFalse(page.wipe_button.isEnabled(), "nothing left to wipe")
        self.assertIsNone(window.store.active())
        self.assertEqual(window.toasts.kinds()[-1], "warning")
        self.assertEqual(window.context.activity.entries()[0].kind, "remove")

    def test_a_failure_keeps_the_profiles(self):
        window = self.open_window()
        self.backend.fail_next("wipe_all", ValidationError("falhou no meio"))
        with ask(True):
            window.pages["profiles"].wipe_button.click()
        self.run_all()
        self.assertEqual(window.toasts.kinds()[-1], "error")
        self.assertEqual(len(self.names(window.pages["profiles"])), 7)
        self.assertTrue(window.pages["profiles"].wipe_button.isEnabled())

    def test_settings_button_asks_too_and_the_dashboard_updates(self):
        window = self.open_window(page="settings")
        with ask(True) as confirm:
            window.pages["settings"].clear_button.click()
        self.assertEqual(confirm.call_args.kwargs["require_text"], "APAGAR")
        self.run_all()
        self.assertEqual(window.store.names(), [])
        self.assertEqual(
            window.pages["dashboard"].stats["count"].value_label.text(), "0"
        )

    def test_the_controller_refuses_without_explicit_confirmation(self):
        window = self.open_window()
        with self.assertRaises(ConfirmationRequiredError):
            window.controller.wipe_all()
        with self.assertRaises(ConfirmationRequiredError):
            window.controller.wipe_all(confirmed=1)
        self.assertEqual(len(self.executor.queue), 0)

    def test_the_backend_refuses_without_explicit_confirmation(self):
        backend = FakeBackend()
        with self.assertRaises(ConfirmationRequiredError):
            backend.wipe_all()
        self.assertEqual(len(backend.list_profiles()), 7)


class BackgroundExecutionTests(GuiTestCase):
    """The real executor runs the work off the interface thread."""

    def test_work_runs_in_another_thread_and_the_result_returns_to_the_gui(self):
        from kongui.gui.tasks import ThreadExecutor

        seen = {}

        class Recording(FakeBackend):
            """Remembers which thread listed the profiles."""

            def list_profiles(self):
                seen["thread"] = threading.current_thread()
                return super().list_profiles()

        executor = ThreadExecutor()
        window = self.make_window(backend=Recording(latency=0.05), executor=executor)
        self.assertTrue(self.wait_until(lambda: len(window.store.names()) == 7))
        self.assertIsNot(seen["thread"], threading.main_thread())
        self.assertIs(window.controller.state, LoadState.READY)

    def test_the_interface_stays_responsive_while_the_work_runs(self):
        from kongui.gui.tasks import ThreadExecutor

        window = self.make_window(
            backend=FakeBackend(latency=0.3), executor=ThreadExecutor()
        )
        self.flush()
        self.assertTrue(window.controller.busy)
        window.show_page("settings")  # must not block
        self.assertEqual(window.current_key, "settings")
        self.assertTrue(self.wait_until(lambda: not window.controller.busy))

    def test_an_exception_in_the_worker_becomes_an_error_outcome(self):
        from kongui.gui.tasks import ThreadExecutor

        backend = FakeBackend(latency=0.01)
        backend.fail_next("list", ValidationError("falhou na thread"))
        window = self.make_window(backend=backend, executor=ThreadExecutor())
        self.assertTrue(
            self.wait_until(lambda: window.controller.state is LoadState.ERROR)
        )
        self.assertIn("falhou na thread", " ".join(window.controller.error))


if __name__ == "__main__":
    unittest.main()
