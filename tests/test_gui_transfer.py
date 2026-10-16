"""Import and export through the interface (fictitious backend, no real files).

``FakeBackend`` follows the real rules (conflict policies, name checks,
confirmation) and keeps a virtual file system, so the whole form can be
exercised: validation, loading states, confirmations, errors and the refresh
of the interface.
"""

from __future__ import annotations

import dataclasses
import os
import unittest
from unittest import mock

from kongui.core import (
    ArchiveExistsError,
    ConfirmationRequiredError,
    ProfileExistsError,
    ProfileNotFoundError,
    ValidationError,
)
from kongui.gui.backend import ExportProbe, FakeBackend
from kongui.gui.widgets.dialogs import ConfirmDialog, ConflictDialog
from tests.gui_helpers import WindowCase


def confirm(result):
    """Patches ``ConfirmDialog.ask``."""
    return mock.patch.object(ConfirmDialog, "ask", return_value=result)


def conflict(result):
    """Patches ``ConflictDialog.ask``."""
    return mock.patch.object(ConflictDialog, "ask", return_value=result)


class ExportCase(WindowCase):
    """A window on the transfer page."""

    def open_transfer(self, backend=None):
        """Opens the window on the transfer page with the list loaded."""
        window = self.open_window(backend=backend, page="transfer")
        return window, window.pages["transfer"]

    def export(self, page, name=None, policy=None, directory=None, profile=None):
        """Fills the form and presses *Exportar*."""
        if profile:
            page.select_profile(profile)
        if directory is not None:
            page.destination_edit.setText(directory)
        if name is not None:
            page.filename_edit.setText(name)
        if policy:
            page.conflict_combo.setCurrentIndex(page.conflict_combo.findData(policy))
        return page.start_export()

    def exported(self):
        """``(profile, directory, name, policy)`` of the export calls."""
        return [call.args for call in self.spy.call_args_list]

    def spy_export(self):
        """Records the arguments the backend receives."""
        self.spy = mock.Mock(wraps=self.backend.export_profile)
        self.backend.export_profile = self.spy


class ExportFormTests(ExportCase):
    """The export form: profile, folder, file name, policy."""

    def test_defaults(self):
        _, page = self.open_transfer()
        self.assertEqual(page.export_combo.count(), 7)
        self.assertEqual(page.export_combo.currentData(), "Trabalho")
        self.assertEqual(page.filename_edit.text(), "Trabalho")
        self.assertEqual(page.export_target(), "~/Downloads/Trabalho.knsv")
        self.assertEqual(page.conflict_combo.currentData(), "ask")
        self.assertEqual(
            [page.conflict_combo.itemData(i) for i in range(3)],
            ["ask", "unique", "overwrite"],
        )
        self.assertTrue(page.export_button.isEnabled())
        self.assertIn("~/Downloads/Trabalho.knsv", page.preview_label.text())

    def test_changing_the_profile_suggests_the_file_name(self):
        _, page = self.open_transfer()
        page.select_profile("Gaming")
        self.assertEqual(page.filename_edit.text(), "Gaming")
        self.assertEqual(page.export_target(), "~/Downloads/Gaming.knsv")
        self.assertFalse(page.select_profile("Inexistente"))

    def test_invalid_file_names_disable_export(self):
        _, page = self.open_transfer()
        for bad in ("../x", "a/b", "", "x.knsv", "x.zip", "-rf", " x", "."):
            with self.subTest(name=bad):
                page.filename_edit.setText(bad)
                self.assertFalse(page.export_button.isEnabled())
                self.assertFalse(page.start_export())
                self.assertEqual(len(self.executor.queue), 0)
        page.filename_edit.setText("ok")
        self.assertTrue(page.export_button.isEnabled())
        self.assertTrue(page.filename_error.isHidden())
        page.destination_edit.setText("   ")
        self.assertFalse(page.export_button.isEnabled())

    def test_the_name_error_is_explained(self):
        _, page = self.open_transfer()
        page.filename_edit.setText("a/b")
        self.assertFalse(page.filename_error.isHidden())
        self.assertIn("Nome inválido", page.filename_error.text())

    def test_no_profiles_shows_a_hint(self):
        window, page = self.open_transfer()
        self.backend_do(window, "wipe_all", confirmed=True)
        self.run_all()
        self.assertFalse(page.export_empty.isHidden())
        self.assertTrue(page.export_form.isHidden())
        self.backend_do(window, "reset")
        self.run_all()
        self.assertTrue(page.export_empty.isHidden())

    def test_the_profile_list_follows_the_store(self):
        window, page = self.open_transfer()
        page.select_profile("Gaming")
        self.backend_do(window, "remove", "Retrô", confirmed=True)
        self.run_all()
        self.assertEqual(page.export_combo.count(), 6)
        self.assertEqual(page.export_combo.currentData(), "Gaming")

    def test_the_card_button_opens_the_form_with_the_profile(self):
        window = self.open_window(page="profiles")
        card = self.card(window.pages["profiles"], "Noturno")
        card.export_button.click()
        self.assertEqual(window.current_key, "transfer")
        self.assertEqual(window.pages["transfer"].export_combo.currentData(), "Noturno")


class ExportRunTests(ExportCase):
    """Running an export: loading, success, errors."""

    def test_shows_progress_then_notifies_with_the_final_path(self):
        window, page = self.open_transfer()
        self.spy_export()
        self.export(page, directory="~/Backups", name="cópia")
        self.assertEqual(window.controller.current, ("export", "Trabalho"))
        self.assertFalse(page.export_button.isEnabled(), "locked while running")
        self.assertFalse(page.export_progress.isHidden())
        self.assertFalse(window.busy_bar.isHidden())
        self.run_all()
        self.assertTrue(page.export_progress.isHidden())
        self.assertTrue(page.export_button.isEnabled())
        self.assertEqual(window.toasts.kinds()[-1], "success")
        self.assertIn(
            "~/Backups/cópia.knsv", window.toasts._toasts[-1].accessibleName()
        )
        entry = window.context.activity.entries()[0]
        self.assertEqual(entry.kind, "export")
        self.assertEqual(self.exported(), [("Trabalho", "~/Backups", "cópia", "error")])
        self.assertIn("~/Backups/cópia.knsv", self.backend.archives)

    def test_the_arguments_follow_the_original_options(self):
        """-e profile, -d folder, -n name."""
        window, page = self.open_transfer()
        self.spy_export()
        self.export(page, profile="Gaming", directory="/srv/out", name="g1")
        self.run_all()
        self.assertEqual(self.exported(), [("Gaming", "/srv/out", "g1", "error")])
        self.assertEqual(self.outcomes[-1].name, "Gaming")

    def test_a_free_name_uses_the_plain_policy_whatever_was_chosen(self):
        """Nothing exists yet, so nothing may be replaced by accident."""
        window, page = self.open_transfer()
        self.spy_export()
        self.export(page, policy="overwrite", name="novo")
        self.run_all()
        self.assertEqual(self.exported()[-1][3], "error")
        self.export(page, policy="ask", name="novo2")
        self.run_all()
        self.assertEqual(self.exported()[-1][3], "error")
        self.export(page, policy="unique", name="novo3")
        self.run_all()
        self.assertEqual(self.exported()[-1][3], "unique")

    def test_a_second_export_is_refused_while_one_runs(self):
        window, page = self.open_transfer()
        self.export(page, name="um")
        self.assertFalse(page.start_export())
        self.assertEqual(window.toasts.titles()[-1], "Aguarde")
        self.run_all()
        self.assertEqual(
            [c for c in self.backend.calls if c[0] == "export"],
            [("export", "Trabalho")],
        )

    def test_a_service_error_is_shown_and_stays(self):
        window, page = self.open_transfer()
        self.backend.fail_next("export", ArchiveExistsError("already exists: x"))
        self.export(page, name="x")
        self.run_all()
        self.assertEqual(window.toasts.kinds()[-1], "error")
        self.assertIn("Já existe", window.toasts._toasts[-1].accessibleName())
        self.assertFalse(self.outcomes[-1].ok)
        self.assertTrue(page.export_button.isEnabled())

    def test_a_missing_profile_is_reported_and_the_list_refreshed(self):
        window, page = self.open_transfer()
        self.backend.fail_next("export", ProfileNotFoundError("gone"))
        self.export(page, name="x")
        self.run_all()
        self.assertIn("não existe mais", window.toasts._toasts[-1].accessibleName())

    def test_a_permission_error_is_explained_not_called_a_bug(self):
        window, page = self.open_transfer()
        self.backend.fail_next(
            "export", PermissionError(13, "Permission denied", "/root/x")
        )
        with self.assertNoLogs(level="ERROR"):
            self.export(page, name="x", directory="/root")
            self.run_all()
        text = window.toasts._toasts[-1].accessibleName()
        self.assertIn("Sem permissão", text)
        self.assertNotIn("inesperado", text)

    def test_an_unusable_folder_is_explained_before_anything_runs(self):
        for problem, fragment in (
            ("missing", "não existe"),
            ("not_dir", "não é uma pasta"),
            ("not_writable", "permissão de escrita"),
        ):
            with self.subTest(problem=problem):
                window, page = self.open_transfer()
                self.backend.probe_export = lambda d, b, p=problem: ExportProbe(
                    f"{d}/{b}.knsv", p
                )
                self.assertFalse(self.export(page, name="x"))
                self.assertEqual(len(self.executor.queue), 0)
                self.assertIn(fragment, page.export_error.text())
                self.assertFalse(page.export_error.isHidden())
                self.assertEqual(window.toasts.kinds()[-1], "error")
                self.assertEqual(
                    [c for c in self.backend.calls if c[0] == "export"], []
                )


class ExportConflictTests(ExportCase):
    """Never replace a file silently: ask, or make the name unique."""

    def setUp(self):
        super().setUp()
        self.window, self.page = self.open_transfer()
        self.spy_export()
        self.page.select_profile("Minimalista")  # "~/Downloads/Minimalista.knsv" exists

    def run_export(self, policy):
        started = self.export(self.page, policy=policy)
        self.run_all()
        return started

    def test_ask_offers_replace_or_unique_and_cancel_does_nothing(self):
        with conflict("cancel") as dialog, confirm(True) as sure:
            self.assertFalse(self.run_export("ask"))
        self.assertTrue(dialog.call_args.kwargs["allow_replace"])
        self.assertIn("Minimalista-2.knsv", dialog.call_args.args[2])
        sure.assert_not_called()
        self.assertEqual(self.exported(), [])
        self.assertEqual(len(self.backend.archives), 1)

    def test_ask_then_unique(self):
        with conflict("unique"):
            self.assertTrue(self.run_export("ask"))
        self.assertEqual(self.exported()[-1][3], "unique")
        self.assertIn("~/Downloads/Minimalista-2.knsv", self.backend.archives)
        self.assertIn(
            "Minimalista-2.knsv", self.window.toasts._toasts[-1].accessibleName()
        )

    def test_ask_then_replace(self):
        with conflict("overwrite"):
            self.assertTrue(self.run_export("ask"))
        self.assertEqual(self.exported()[-1][3], "overwrite")
        self.assertEqual(self.window.toasts.kinds()[-1], "success")

    def test_unique_policy_does_not_ask(self):
        with conflict("cancel") as dialog, confirm(False) as sure:
            self.assertTrue(self.run_export("unique"))
        dialog.assert_not_called()
        sure.assert_not_called()
        self.assertIn("~/Downloads/Minimalista-2.knsv", self.backend.archives)

    def test_overwrite_policy_asks_for_confirmation(self):
        with confirm(False) as sure:
            self.assertFalse(self.run_export("overwrite"))
        self.assertTrue(sure.call_args.kwargs["destructive"])
        self.assertIn("Minimalista.knsv", sure.call_args.args[2])
        self.assertEqual(self.exported(), [])
        with confirm(True):
            self.assertTrue(self.run_export("overwrite"))
        self.assertEqual(self.exported()[-1][3], "overwrite")

    def test_the_controller_refuses_overwrite_without_confirmation(self):
        for value in (False, None, 1):
            with self.subTest(value=value):
                with self.assertRaises(ConfirmationRequiredError):
                    self.window.controller.export_profile(
                        "Gaming", "~/x", "g", "overwrite", confirmed=value
                    )
        self.assertEqual(len(self.executor.queue), 0)

    def test_the_backend_refuses_to_replace_without_the_policy(self):
        with self.assertRaises(ArchiveExistsError):
            self.backend.export_profile("Minimalista", "~/Downloads", None, "error")

    def test_a_folder_in_the_way_only_allows_a_unique_name(self):
        self.backend.archives.discard("~/Downloads/Minimalista.knsv")
        self.backend.blocked.add("~/Downloads/Minimalista.knsv")
        with conflict("cancel") as dialog:
            self.assertFalse(self.run_export("ask"))
        self.assertFalse(dialog.call_args.kwargs["allow_replace"])
        with confirm(True) as sure:
            self.assertFalse(self.run_export("overwrite"))
        sure.assert_not_called()
        self.assertEqual(self.window.toasts.kinds()[-1], "error")
        self.assertIn("recusada", self.page.export_error.text())
        self.assertEqual(self.exported(), [])
        self.assertTrue(self.run_export("unique"))
        self.assertEqual(self.exported()[-1][3], "unique")


class ImportCase(WindowCase):
    """A window on the transfer page, import side."""

    def open_transfer(self, backend=None):
        """Opens the window on the transfer page with the list loaded."""
        window = self.open_window(backend=backend, page="transfer")
        return window, window.pages["transfer"]

    def choose(self, page, path, finish=True):
        """Selects a file and (by default) lets the background check finish."""
        started = page.set_import_file(path)
        if finish:
            self.run_all()
        return started


class ImportFormTests(ImportCase):
    """Choosing the file and the profile name."""

    def test_only_knsv_files_are_accepted(self):
        window, page = self.open_transfer()
        self.assertFalse(page.set_import_file("/tmp/readme.txt"))
        self.assertEqual(window.toasts.kinds(), ["warning"])
        self.assertFalse(page.drop_zone.isHidden())
        self.assertEqual(len(self.executor.queue), 0)

    def test_the_file_is_checked_in_the_background(self):
        _, page = self.open_transfer()
        self.choose(page, "/home/x/Downloads/Verão.knsv", finish=False)
        self.assertTrue(page.drop_zone.isHidden())
        self.assertFalse(page.import_form.isHidden())
        self.assertIn("verificando", page.file_label.text())
        self.assertFalse(page.import_button.isEnabled())
        self.assertEqual(page.import_name_edit.text(), "Verão")
        self.run_all()
        self.assertNotIn("verificando", page.file_label.text())
        self.assertTrue(page.import_button.isEnabled())

    def test_shows_what_the_archive_holds(self):
        from kongui.gui.widgets.common import Badge

        _, page = self.open_transfer()
        self.choose(page, "/x/Verão.knsv")
        self.assertEqual(len(page.import_form.findChildren(Badge)), 4)
        self.assertIn("gravados direto no sistema", page.import_info.text())
        self.assertIn("sem backup", page.import_info.text())

    def test_an_invalid_archive_is_explained_and_cannot_be_imported(self):
        cases = (
            (ValidationError("archive not found: x"), "não foi encontrado"),
            (ValidationError("not a readable archive: bad"), "não é um .knsv válido"),
            (ValidationError("archive has no conf.yaml"), "não contém o conf.yaml"),
            (ValidationError("unsafe path inside archive: '../x'"), "inseguros"),
            (PermissionError(13, "denied", "/x/a.knsv"), "Sem permissão"),
        )
        for error, fragment in cases:
            with self.subTest(fragment=fragment):
                _, page = self.open_transfer()
                self.backend.fail_next("inspect_archive", error)
                self.choose(page, "/x/a.knsv")
                self.assertFalse(page.file_error.isHidden())
                self.assertIn(fragment, page.file_error.text())
                self.assertFalse(page.import_button.isEnabled())
                self.assertFalse(page.start_import())
                page.clear_file_button.click()
                self.assertTrue(page.file_error.isHidden())

    def test_a_permission_problem_is_not_logged_as_a_bug(self):
        _, page = self.open_transfer()
        self.backend.fail_next("inspect_archive", PermissionError(13, "denied", "/x"))
        with self.assertNoLogs(level="ERROR"):
            self.choose(page, "/x/a.knsv")

    def test_a_stale_check_is_ignored(self):
        _, page = self.open_transfer()
        self.choose(page, "/x/Primeiro.knsv", finish=False)
        self.choose(page, "/x/Segundo.knsv", finish=False)
        self.run_all()
        self.assertEqual(page.import_name_edit.text(), "Segundo")
        self.assertIn("Segundo.knsv", page.file_label.text())

    def test_a_name_already_in_use_is_refused_until_renamed(self):
        _, page = self.open_transfer()
        self.choose(page, "/x/Gaming.knsv")
        self.assertFalse(page.import_button.isEnabled())
        self.assertFalse(page.import_error.isHidden())
        self.assertIn("Já existe", page.import_error.text())
        self.assertFalse(page.start_import())
        page.import_name_edit.setText("Gaming 2")
        self.assertTrue(page.import_button.isEnabled())
        self.assertTrue(page.import_error.isHidden())

    def test_invalid_profile_names_are_refused(self):
        _, page = self.open_transfer()
        self.choose(page, "/x/ok.knsv")
        for bad in ("../x", "a/b", "x.knsv", "-rf", " x", "."):
            with self.subTest(name=bad):
                page.import_name_edit.setText(bad)
                self.assertFalse(page.import_button.isEnabled())
                self.assertFalse(page.import_error.isHidden())
        page.import_name_edit.setText("")
        self.assertFalse(page.import_button.isEnabled())

    def test_the_selection_can_be_changed(self):
        _, page = self.open_transfer()
        self.choose(page, "/x/a.knsv")
        page.apply_after_check.setChecked(True)
        page.clear_file_button.click()
        self.assertFalse(page.drop_zone.isHidden())
        self.assertTrue(page.import_form.isHidden())
        self.assertEqual(page.import_name_edit.text(), "")
        self.assertFalse(page.apply_after_check.isChecked())

    def test_the_drop_zone_signal_selects_the_file(self):
        _, page = self.open_transfer()
        page.drop_zone.file_chosen.emit("/x/Solto.knsv")
        self.run_all()
        self.assertEqual(page.import_name_edit.text(), "Solto")

    def test_real_size_is_shown_but_the_file_is_never_opened(self):
        _, page = self.open_transfer()
        path = os.path.join(self.home, "grande.knsv")
        with open(path, "wb") as handle:
            handle.write(b"\0" * (3 * 1048576))
        with mock.patch(
            "builtins.open", side_effect=AssertionError("must not open files")
        ):
            self.choose(page, path)
        self.assertIn("3,0 MB", page.file_label.text())


class ImportRunTests(ImportCase):
    """Running an import: confirmation, loading, success, errors."""

    def start(self, page, path="/x/Verão.knsv", name=None, apply_after=False):
        self.choose(page, path)
        if name is not None:
            page.import_name_edit.setText(name)
        page.apply_after_check.setChecked(apply_after)

    def test_declining_the_confirmation_does_nothing(self):
        _, page = self.open_transfer()
        self.start(page)
        with confirm(False) as sure:
            self.assertFalse(page.start_import())
        self.assertTrue(sure.call_args.kwargs["destructive"])
        self.assertEqual(len(self.executor.queue), 0)
        self.assertFalse(page.import_form.isHidden(), "the form stays")
        self.assertNotIn(("import", "Verão"), self.backend.calls)

    def test_the_confirmation_says_what_will_be_overwritten(self):
        _, page = self.open_transfer()
        self.start(page, apply_after=True)
        with confirm(False) as sure:
            page.start_import()
        title, text = sure.call_args.args[1:3]
        self.assertIn("Verão", title)
        self.assertIn(
            self.backend.inspect_archive("/x/a.knsv").export_sections[0], text
        )
        self.assertIn("sem backup", text)
        self.assertIn("aplicado", text)

    def test_confirming_shows_progress_then_adds_the_profile(self):
        window, page = self.open_transfer()
        self.start(page)
        with confirm(True):
            self.assertTrue(page.start_import())
        self.assertEqual(window.controller.current, ("import", "Verão"))
        self.assertFalse(page.import_progress.isHidden())
        self.assertFalse(page.import_button.isEnabled())
        self.assertNotIn("Verão", window.store.names())
        self.run_all()
        self.assertIn("Verão", window.store.names())
        self.assertFalse(window.store.get("Verão").active)
        self.assertEqual(window.toasts.kinds()[-1], "success")
        self.assertIn("Verão", window.toasts.titles()[-1])
        self.assertEqual(window.context.activity.entries()[0].kind, "import")
        self.assertFalse(page.drop_zone.isHidden(), "the form resets")
        self.assertTrue(page.import_progress.isHidden())
        self.assertGreaterEqual(page.export_combo.findData("Verão"), 0)

    def test_importing_under_another_name(self):
        window, page = self.open_transfer()
        self.start(page, name="Viagem")
        with confirm(True):
            page.start_import()
        self.run_all()
        self.assertIn(("import", "Viagem"), self.backend.calls)
        self.assertIn("Viagem", window.store.names())
        self.assertNotIn("Verão", window.store.names())

    def test_import_and_apply(self):
        window, page = self.open_transfer()
        self.start(page, path="/x/Escuro.knsv", apply_after=True)
        with confirm(True):
            page.start_import()
        self.run_all()
        self.assertEqual(window.store.active().name, "Escuro")
        self.assertIn(("apply", "Escuro"), self.backend.calls)

    def test_without_apply_the_active_profile_is_unchanged(self):
        window, page = self.open_transfer()
        self.start(page, path="/x/Escuro.knsv")
        with confirm(True):
            page.start_import()
        self.run_all()
        self.assertEqual(window.store.active().name, "Trabalho")
        self.assertNotIn(("apply", "Escuro"), self.backend.calls)

    def test_a_failed_apply_keeps_the_import_and_warns(self):
        window, page = self.open_transfer()
        self.backend.apply = mock.Mock(side_effect=ValidationError("conf quebrado"))
        self.start(page, path="/x/Escuro.knsv", apply_after=True)
        with confirm(True):
            page.start_import()
        self.run_all()
        self.assertIn("Escuro", window.store.names())
        self.assertEqual(window.store.active().name, "Trabalho")
        self.assertTrue(self.outcomes[-1].ok)
        self.assertTrue(
            any("não foi aplicado" in line for line in self.outcomes[-1].details)
        )

    def test_a_service_error_is_shown_and_the_form_stays(self):
        window, page = self.open_transfer()
        self.backend.fail_next("import", ProfileExistsError("exists"))
        self.start(page)
        with confirm(True):
            page.start_import()
        self.run_all()
        self.assertEqual(window.toasts.kinds()[-1], "error")
        self.assertIn("Já existe", window.toasts._toasts[-1].accessibleName())
        self.assertFalse(page.import_form.isHidden())
        self.assertTrue(page.import_button.isEnabled())

    def test_refused_while_another_operation_runs(self):
        window, page = self.open_transfer()
        self.start(page)
        window.controller.refresh()
        self.assertFalse(page.import_button.isEnabled())
        with confirm(True):
            self.assertFalse(page.start_import() or False)
        self.run_all()

    def test_the_controller_refuses_without_explicit_confirmation(self):
        window, _ = self.open_transfer()
        for value in (False, None, 1, "yes"):
            with self.subTest(value=value):
                with self.assertRaises(ConfirmationRequiredError):
                    window.controller.import_profile("/x/a.knsv", "a", confirmed=value)
        self.assertEqual(len(self.executor.queue), 0)

    def test_the_backend_refuses_without_explicit_confirmation(self):
        with self.assertRaises(ConfirmationRequiredError):
            FakeBackend().import_profile("/x/a.knsv")


class TransferAvailabilityTests(ImportCase):
    """A backend that cannot transfer locks the page."""

    def test_forms_are_disabled(self):
        class NoTransfer(FakeBackend):
            """Fake backend without import/export."""

            capabilities = dataclasses.replace(FakeBackend.capabilities, transfer=False)

        _, page = self.open_transfer(backend=NoTransfer())
        self.assertFalse(page.export_card.isEnabled())
        self.assertFalse(page.import_card.isEnabled())
        self.assertFalse(page.transfer_notice.isHidden())


if __name__ == "__main__":
    unittest.main()
