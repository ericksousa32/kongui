"""Tests added by the final audit: each one pins down a reproduced problem.

The names say what was wrong; the docstrings say how it showed up.
"""

import unittest
from unittest import mock

import yaml

from tests.gui_helpers import (
    HAVE_QT,
    GuiTestCase,
    ManualExecutor,
    WindowCase,
    pin_language,
)
from kongui.gui.widgets.dialogs import ChoiceDialog, ConfirmDialog
from tests.helpers import really_root


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


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class EngineVersionTests(GuiTestCase):
    """``konsave --version`` had no graphical equivalent."""

    def backend_with_version(self, version):
        from kongui.core import KonsaveEngine, ProfileService
        from kongui.gui.backend import ServiceBackend

        engine = KonsaveEngine(self.home)
        backend = ServiceBackend(ProfileService(engine))
        patcher = mock.patch.object(
            type(engine),
            "version",
            new_callable=mock.PropertyMock,
            return_value=version,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return backend

    def test_about_page_shows_the_version_of_the_real_engine(self):
        backend = self.backend_with_version("2.2.0")
        self.assertEqual(backend.engine_version, "2.2.0")
        about = self.make_window(backend=backend).pages["about"]
        self.assertEqual(about.info_values["Versão do Konsave"], "2.2.0")

    def test_an_unknown_version_is_hidden_not_shown_as_a_placeholder(self):
        """Running from a source checkout the engine only has ``0+unknown``."""
        from kongui.core.engine import FALLBACK_VERSION

        backend = self.backend_with_version(FALLBACK_VERSION)
        self.assertEqual(backend.engine_version, "")
        about = self.make_window(backend=backend).pages["about"]
        self.assertNotIn("Versão do Konsave", about.info_values)
        self.assertNotIn("0+unknown", str(about.info_values))

    def test_demo_does_not_invent_a_version(self):
        window = self.make_window()
        self.assertEqual(window.backend.engine_version, "")
        self.assertNotIn("Versão do Konsave", window.pages["about"].info_values)


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class ExportFolderCheckTests(GuiTestCase):
    """``probe_export`` touched the disk (up to thousands of stat calls on a
    crowded folder, each one slow on a network mount) in the interface thread."""

    def test_the_check_waits_for_the_background_worker(self):
        executor = ManualExecutor()
        window = self.make_window(executor=executor)
        executor.run_next()  # the first list
        page = window.show_page("transfer")
        real = window.backend.probe_export
        with mock.patch.object(window.backend, "probe_export", wraps=real) as probe:
            self.assertTrue(page.start_export())
            probe.assert_not_called()  # nothing touched the disk yet
            self.assertFalse(page.export_button.isEnabled())
            self.assertFalse(page.start_export())  # no second click while checking
            self.assertIn("Aguarde", window.toasts.titles())
            executor.run_next()
            probe.assert_called_once()
        self.assertFalse(page._probing)
        self.assertEqual(window.controller.current[0], "export")

    def test_a_threaded_executor_runs_it_off_the_interface_thread(self):
        import threading

        from kongui.gui.tasks import ThreadExecutor

        executor = ThreadExecutor()
        self.addCleanup(executor.shutdown)
        window = self.make_window(executor=executor)
        self.assertTrue(self.wait_until(lambda: not window.controller.busy))
        page = window.show_page("transfer")
        seen = []
        real = window.backend.probe_export

        def probe(directory, base):
            seen.append(threading.current_thread())
            return real(directory, base)

        with mock.patch.object(window.backend, "probe_export", probe):
            self.assertTrue(page.start_export())
            self.assertTrue(self.wait_until(lambda: seen))
        self.assertNotIn(threading.main_thread(), seen)
        self.assertTrue(
            self.wait_until(
                lambda: window.controller.current is None and not page._probing
            )
        )

    def test_an_error_while_checking_is_shown_and_unlocks_the_form(self):
        executor = ManualExecutor()
        window = self.make_window(executor=executor)
        executor.run_next()
        page = window.show_page("transfer")
        with mock.patch.object(
            window.backend,
            "probe_export",
            side_effect=PermissionError(13, "negado", "/x"),
        ):
            self.assertTrue(page.start_export())
            executor.run_next()
        self.assertFalse(page._probing)
        self.assertFalse(page.export_error.isHidden())
        self.assertTrue(page.export_button.isEnabled())
        self.assertEqual(window.controller.current, None)


class StaleImportFolderMessageTests(unittest.TestCase):
    """The message told the user to delete a folder without saying which."""

    def setUp(self):
        super().setUp()
        pin_language(self)

    def test_the_folder_is_named(self):
        from kongui.core import ValidationError
        from kongui.gui import messages

        error = ValidationError(
            "stale import folder found, remove it first: /home/u/.config/konsave/temp/p"
        )
        text = " ".join(messages.describe_error(error))
        self.assertIn("abandonada", text)
        self.assertIn("/home/u/.config/konsave/temp/p", text)


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class FreshAccountExportTests(GuiTestCase):
    """import -> export on an account that never ran Konsave (found with the
    real Plasma 6 archive ``tests/profile_test.knsv``)."""

    def test_export_after_import_creates_the_default_config_like_the_cli(self):
        import pathlib
        import shutil

        from kongui.core import KonsaveEngine, ProfileService
        from kongui.gui.backend import ServiceBackend

        home = pathlib.Path(self.home)
        for folder in (".config", ".local/share"):
            (home / folder).mkdir(parents=True, exist_ok=True)
        archive = home / "profile_test.knsv"
        shutil.copy(pathlib.Path(__file__).with_name("profile_test.knsv"), archive)
        engine = KonsaveEngine(home)
        backend = ServiceBackend(ProfileService(engine))
        self.assertFalse(engine.config_file.exists())
        backend.import_profile(str(archive), confirmed=True).raise_for_status()
        self.assertFalse(engine.config_file.exists())  # import does not need it
        result = backend.export_profile("profile_test", str(home), "again", "error")
        self.assertTrue(result.ok, result.message)
        self.assertTrue(engine.config_file.is_file())
        self.assertTrue((home / "again.knsv").is_file())
        # the default conf differs from the Plasma archive's: the user is told
        self.assertTrue(any("differs" in w for w in result.warnings), result.warnings)


FLOW = """save:
  configs: {location: "$HOME/.config", entries: [kdeglobals]}
export: {}
"""


@unittest.skipIf(really_root(), "the demo backend builds a real engine")
@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class ConfigPageFailurePathTests(WindowCase):
    """Failure paths of the conf.yaml editor that no test had walked."""

    def setUp(self):
        super().setUp()
        # Started before any window exists, so it outlives the window's cleanup
        # (a dirty editor asks before closing; a real dialog would block).
        patcher = mock.patch.object(ConfirmDialog, "ask", return_value=True)
        self.confirm = patcher.start()
        self.addCleanup(patcher.stop)

    def open_config(self):
        window = self.open_window(page="config", load=False)
        self.run_all()
        return window, window.pages["config"]

    def sandbox(self):
        return self.backend._config_service("test")  # pylint: disable=protected-access

    def test_an_unreadable_file_shows_the_error_and_offers_no_editing(self):
        self.backend = None
        from kongui.gui.backend import FakeBackend

        backend = FakeBackend()
        with mock.patch.object(
            backend,
            "load_config",
            side_effect=PermissionError(13, "negado", "/x/conf.yaml"),
        ):
            window = self.open_window(backend=backend, page="config", load=False)
            self.run_all()
        page = window.pages["config"]
        self.assertFalse(page.error_banner.isHidden())
        self.assertTrue(page.content.isHidden())
        self.assertFalse(page.save_button.isEnabled())
        self.assertFalse(page.backups_button.isEnabled())
        self.assertFalse(page.save(), "no snapshot, nothing to write")

    def test_a_failing_validation_blocks_saving_and_says_so(self):
        window, page = self.open_config()
        with mock.patch.object(
            window.backend, "check_config", side_effect=RuntimeError("boom")
        ):
            page.validate_now()
            self.run_all()
        self.assertIsNone(page.check)
        self.assertFalse(page.save_button.isEnabled())
        digest = self.sandbox().digest()
        self.assertFalse(page.save())
        self.assertEqual(self.sandbox().digest(), digest)

    def test_saving_while_busy_or_unchecked_writes_nothing(self):
        window, page = self.open_config()
        editor = page.editors["save"]
        editor.add_group("novo")
        editor.insert_text("$HOME")
        digest = self.sandbox().digest()
        # not validated yet: the text changed after the last check
        self.assertFalse(page.save())
        self.assertEqual(self.sandbox().digest(), digest)
        self.run_all()
        # now busy with another operation
        window.controller.refresh()
        self.assertFalse(page.save())
        self.assertFalse(page.restore("conf.yaml.bak-x"), "restore also waits")
        self.run_all()
        self.assertEqual(self.sandbox().digest(), digest)
        self.confirm.assert_not_called()

    def test_nothing_to_save_and_nothing_to_discard_when_clean(self):
        window, page = self.open_config()
        self.run_all()
        self.assertFalse(page.is_dirty)
        self.assertFalse(page.discard())
        self.assertFalse(page.save())
        self.assertIn("Nada a salvar", window.toasts.titles())

    def test_rewriting_without_comments_needs_an_explicit_yes(self):
        window, page = self.open_config()
        self.sandbox().write_text(FLOW)
        page.reload()
        self.run_all()
        editor = page.editors["save"]
        editor.add_group("novo")
        editor.insert_text("$HOME")
        self.run_all()
        self.assertTrue(page._lossy)
        self.assertTrue(
            any(p.code == "comments-lost" for p in page.problems.problems),
            page.problems.problems,
        )
        before = self.sandbox().digest()
        backups = len(self.sandbox().list_backups())  # writing FLOW made one
        self.confirm.return_value = False
        self.assertFalse(page.save())
        self.confirm.assert_called_once()
        self.run_all()
        self.assertEqual(self.sandbox().digest(), before, "declining wrote nothing")
        self.assertEqual(len(self.sandbox().list_backups()), backups)
        self.confirm.return_value = True
        self.assertTrue(page.save())
        self.run_all()
        saved = yaml.safe_load(self.sandbox().read_text())
        self.assertEqual(sorted(saved["save"]), ["configs", "novo"])
        self.assertEqual(saved["save"]["configs"]["entries"], ["kdeglobals"])
        self.assertEqual(len(self.sandbox().list_backups()), backups + 1)

    def test_a_conflict_can_be_forced_through_restore(self):
        window, page = self.open_config()
        self.sandbox().write_text(FLOW)  # makes a backup of the default
        name = self.sandbox().list_backups()[0].name
        page.reload()
        self.run_all()
        self.sandbox().write_text(
            FLOW.replace("kdeglobals", "other")
        )  # behind its back
        with mock.patch.object(ChoiceDialog, "ask", return_value="force"):
            self.assertTrue(page.restore(name))
            self.run_all()
        self.assertIn("configuration file for konsave", self.sandbox().read_text())

    def test_listing_backups_can_fail_without_breaking_the_page(self):
        window, page = self.open_config()
        with mock.patch.object(
            window.backend,
            "list_config_backups",
            side_effect=PermissionError(13, "negado", "/x"),
        ):
            page.open_backups()
            self.run_all()
        self.assertIn("Não foi possível listar os backups", window.toasts.titles())
        self.assertTrue(page.backups_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
