"""Support code of the connected interface: messages, executors, backends, widgets."""

from __future__ import annotations

import threading
import unittest
from datetime import datetime

from kongui.core import (
    ConfigMissingError,
    ConfirmationRequiredError,
    OperationFailedError,
    OperationResult,
    ProfileExistsError,
    ProfileInvalidError,
    ProfileNotFoundError,
    RunningAsRootError,
    ValidationError,
)
from kongui.gui import messages
from kongui.gui.backend import FakeBackend, ProfileBackend, ServiceBackend
from kongui.gui.state import Profile, ProfileStore
from kongui.gui.tasks import InlineExecutor, ThreadExecutor
from tests.gui_helpers import GuiTestCase, ManualExecutor


class MessagesTests(unittest.TestCase):
    """pt-BR texts for results and errors."""

    def test_known_errors_have_friendly_texts(self):
        cases = {
            RunningAsRootError("x"): "root",
            ProfileExistsError("x"): "Já existe",
            ProfileNotFoundError("x"): "não existe mais",
            ProfileInvalidError("x"): "incompleto",
            ConfigMissingError("x"): "conf.yaml",
            ConfirmationRequiredError("x"): "confirmação",
            ValidationError("nome ruim"): "nome ruim",
        }
        for error, fragment in cases.items():
            with self.subTest(error=type(error).__name__):
                self.assertIn(fragment, " ".join(messages.describe_error(error)))

    def test_unknown_errors_show_their_type(self):
        text = " ".join(messages.describe_error(ZeroDivisionError("zero")))
        self.assertIn("ZeroDivisionError", text)
        self.assertIn("zero", text)

    def test_failed_results_list_message_errors_and_warnings(self):
        result = OperationResult(
            "apply", False, "falhou", errors=("e1", "e2"), warnings=("w1",)
        )
        lines = messages.describe_result(result)
        self.assertEqual(lines[0], "falhou")
        self.assertIn("e1", lines)
        self.assertIn("Aviso: w1", lines)
        self.assertEqual(messages.describe_error(OperationFailedError(result)), lines)

    def test_long_lists_are_cut_with_a_count(self):
        result = OperationResult(
            "apply", False, "m", errors=tuple(str(i) for i in range(9))
        )
        lines = messages.describe_result(result)
        self.assertEqual(len(lines), 5)
        self.assertIn("mais", lines[-1])

    def test_titles(self):
        self.assertEqual(messages.success_title("save", "A"), "Perfil “A” salvo")
        self.assertEqual(
            messages.failure_title("apply", "A"),
            "Não foi possível aplicar o perfil “A”",
        )
        self.assertEqual(
            messages.failure_title("wipe_all", ""), "Não foi possível limpar os perfis"
        )
        self.assertEqual(
            messages.failure_title("???", ""), "Não foi possível concluir a operação"
        )

    def test_every_operation_has_a_verb_and_a_success_text(self):
        for operation in ("save", "overwrite", "apply", "remove", "wipe_all"):
            with self.subTest(operation=operation):
                self.assertIn(operation, messages.VERBS)
                self.assertIn(operation, messages.SUCCESS)

    def test_apply_has_a_hint_only_on_success(self):
        self.assertIsNotNone(messages.outcome_hint("apply", True))
        self.assertIsNone(messages.outcome_hint("apply", False))
        self.assertIsNone(messages.outcome_hint("save", True))


class FakeBackendTests(unittest.TestCase):
    """The in-memory backend follows the real rules."""

    def test_capabilities(self):
        self.assertTrue(FakeBackend.capabilities.demo)
        self.assertFalse(ServiceBackend.capabilities.demo)
        self.assertTrue(ServiceBackend.capabilities.transfer)
        self.assertFalse(ServiceBackend.capabilities.duplicate)

    def test_an_empty_list_is_respected(self):
        self.assertEqual(FakeBackend(profiles=[]).list_profiles(), [])

    def test_save_rejects_an_existing_name(self):
        backend = FakeBackend()
        backend.save("Novo")
        with self.assertRaises(ProfileExistsError):
            backend.save("Novo")

    def test_missing_profiles_raise(self):
        backend = FakeBackend()
        for call in (
            lambda: backend.overwrite("x", confirmed=True),
            lambda: backend.apply("x", confirmed=True),
            lambda: backend.remove("x", confirmed=True),
            lambda: backend.duplicate("x"),
        ):
            with self.assertRaises(ProfileNotFoundError):
                call()

    def test_fail_next_fires_once(self):
        backend = FakeBackend()
        backend.fail_next("list", ValidationError("x"))
        with self.assertRaises(ValidationError):
            backend.list_profiles()
        self.assertEqual(len(backend.list_profiles()), 7)

    def test_reset_restores_the_original_profiles(self):
        backend = FakeBackend()
        backend.wipe_all(confirmed=True)
        backend.reset()
        self.assertEqual(len(backend.list_profiles()), 7)

    def test_duplicate_finds_a_free_name(self):
        backend = FakeBackend()
        backend.duplicate("Gaming")
        backend.duplicate("Gaming")
        names = [p.name for p in backend.list_profiles()]
        self.assertIn("Gaming (cópia)", names)
        self.assertIn("Gaming (cópia 2)", names)

    def test_calls_are_recorded(self):
        backend = FakeBackend()
        backend.list_profiles()
        backend.save("A")
        self.assertEqual(backend.calls, [("list", ""), ("save", "A")])

    def test_the_base_backend_refuses_optional_calls(self):
        from kongui.core import NotImplementedOperationError

        class Minimal(ProfileBackend):
            """Implements only the required operations."""

            capabilities = FakeBackend.capabilities

            def list_profiles(self):
                return []

            save = overwrite = apply = remove = wipe_all = list_profiles

        backend = Minimal()
        for call in (
            lambda: backend.duplicate("x"),
            lambda: backend.inspect_archive("x.knsv"),
            lambda: backend.probe_export("/x", "y"),
            lambda: backend.export_profile("x", "/x"),
            lambda: backend.import_profile("x.knsv"),
            backend.reset,
        ):
            with self.assertRaises(NotImplementedOperationError):
                call()
        self.assertIsInstance(backend, ProfileBackend)


class ProfileStoreTests(unittest.TestCase):
    """The view model only announces real changes."""

    def test_replace_reports_changes(self):
        store = ProfileStore()
        seen = []
        store.changed.connect(lambda: seen.append(1))
        items = [Profile("a", "", (), 1.0, None)]
        self.assertTrue(store.replace(items))
        self.assertFalse(store.replace(list(items)))
        self.assertEqual(seen, [1])
        self.assertEqual(store.names(), ["a"])


class ExecutorTests(GuiTestCase):
    """Inline, manual and threaded executors."""

    def test_inline_runs_at_once_and_reports_errors(self):
        got = []
        InlineExecutor().submit(
            lambda: 3, lambda value, error: got.append((value, error))
        )
        boom = ValueError("x")

        def fail():
            raise boom

        InlineExecutor().submit(fail, lambda value, error: got.append((value, error)))
        self.assertEqual(got, [(3, None), (None, boom)])

    def test_manual_waits_until_told(self):
        executor = ManualExecutor()
        got = []
        executor.submit(lambda: 1, lambda value, error: got.append(value))
        self.assertEqual(got, [])
        self.assertTrue(executor.run_next())
        self.assertEqual(got, [1])
        self.assertFalse(executor.run_next())

    def test_thread_executor_runs_in_order_off_the_gui_thread(self):
        executor = ThreadExecutor()
        got = []
        threads = []

        def work(number):
            def run():
                threads.append(threading.current_thread())
                return number

            return run

        for number in (1, 2, 3):
            executor.submit(
                work(number), lambda value, error: got.append((value, error))
            )
        self.assertTrue(self.wait_until(lambda: len(got) == 3))
        self.assertEqual(got, [(1, None), (2, None), (3, None)])
        self.assertNotIn(threading.main_thread(), threads)
        self.assertTrue(executor.shutdown())

    def test_thread_executor_delivers_errors(self):
        executor = ThreadExecutor()
        got = []

        def fail():
            raise ValueError("na thread")

        executor.submit(fail, lambda value, error: got.append(error))
        self.assertTrue(self.wait_until(lambda: got))
        self.assertIsInstance(got[0], ValueError)
        executor.shutdown()


class FeedbackWidgetTests(GuiTestCase):
    """Busy bar, error banner and dialog variants."""

    def test_busy_bar_toggles(self):
        from kongui.gui.widgets.feedback import BusyBar

        bar = BusyBar()
        self.assertTrue(bar.isHidden())
        bar.set_busy(True)
        self.assertFalse(bar.isHidden())
        self.assertEqual((bar.minimum(), bar.maximum()), (0, 0), "indeterminate")
        bar.set_busy(False)
        self.assertTrue(bar.isHidden())

    def test_error_banner_shows_lines_and_emits_retry(self):
        from kongui.gui.widgets.feedback import ErrorBanner

        banner = ErrorBanner()
        seen = []
        banner.retry_requested.connect(lambda: seen.append(1))
        banner.set_content("Falhou", ["linha 1", "linha 2"])
        self.assertEqual(banner.title_label.text(), "Falhou")
        self.assertEqual(banner.accessibleName(), "Falhou")
        banner.set_content("Falhou", ["única"])
        from kongui.gui.widgets.common import Label

        self.assertEqual(len(banner.findChildren(Label)), 2)
        banner.retry_button.click()
        self.assertEqual(seen, [1])

    def test_profile_dialog_without_details_only_asks_the_name(self):
        from kongui.gui.widgets.dialogs import ProfileDialog

        dialog = ProfileDialog(None, ["a"], ["S1", "S2"], ask_details=False)
        self.assertEqual(dialog.section_checks, [])
        self.assertFalse(dialog.confirm_button.isEnabled())
        dialog.name_edit.setText("novo")
        self.assertTrue(dialog.confirm_button.isEnabled())
        self.assertEqual(dialog.values(), ("novo", "", ()))
        dialog.name_edit.setText("a")
        self.assertFalse(dialog.confirm_button.isEnabled())

    def test_profile_card_busy_and_capability_variants(self):
        from kongui.gui.widgets.cards import ProfileCard

        profile = Profile("A", "", (), 1.0, datetime.now())
        card = ProfileCard(profile, locked=True, busy_text="Aplicando…")
        self.assertEqual(card.busy_label.text(), "Aplicando…")
        self.assertTrue(card.locked)
        plain = ProfileCard(profile, can_export=False, can_duplicate=False)
        self.assertIsNone(plain.export_button)
        self.assertIsNone(plain.duplicate_action)


if __name__ == "__main__":
    unittest.main()
