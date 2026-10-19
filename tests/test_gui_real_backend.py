"""The six operations against the *real* services, inside a temporary home.

``ServiceBackend`` drives ``ProfileService`` and, through it, the original
Konsave code. Everything happens below a private temporary ``$HOME``: the real
session is never read or written. Applying a profile only rewrites the files of
that temporary home. The tests refuse to run when the process is really root.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from typing import List

from kongui.core import ConfigService, KonsaveEngine, ProfileService
from kongui.gui.backend import ServiceBackend
from kongui.gui.controller import LoadState, ProfileController
from kongui.gui.state import AppSettings, ProfileStore
from kongui.gui.tasks import InlineExecutor
from tests.gui_helpers import GuiTestCase
from tests.helpers import BASE_CONF, make_knsv, no_logs, non_root, really_root, write


def snapshot_dir(folder):
    """Relative path -> bytes (``None`` for folders) below ``folder``."""
    result = {}
    for base, dirs, files in os.walk(folder):
        for name in dirs:
            result[os.path.relpath(os.path.join(base, name), folder)] = None
        for name in files:
            full = os.path.join(base, name)
            with open(full, "rb") as handle:
                result[os.path.relpath(full, folder)] = handle.read()
    return result


class RealBackendCase(GuiTestCase):
    """A temporary home with a Konsave configuration and a controller on it."""

    def setUp(self):
        super().setUp()
        if really_root():
            self.skipTest("refusing to run file operations as root")
        self.root = Path(os.path.realpath(self.home))
        (self.root / ".config").mkdir(exist_ok=True)
        (self.root / ".local/share").mkdir(parents=True, exist_ok=True)
        engine = KonsaveEngine(self.root, euid_provider=non_root)
        self.config = ConfigService(engine)
        self.config.write_text(BASE_CONF)
        self.engine = engine
        self.service = ProfileService(engine, self.config)
        self.backend = ServiceBackend(self.service)
        self.live()
        self.store = ProfileStore()
        self.controller = ProfileController(
            self.backend, InlineExecutor(), self.store, AppSettings()
        )
        self.outcomes: List = []
        self.controller.operation_finished.connect(self.outcomes.append)

    def live(self, text="kdeglobals-A"):
        """Writes the live files that ``BASE_CONF`` saves."""
        write(self.root / ".config/kdeglobals", text)
        write(self.root / ".config/gtk-3.0/settings.ini", "[Settings]")
        write(self.root / ".local/share/icons/theme.txt", "theme-A")

    def last(self):
        """The most recent outcome."""
        return self.outcomes[-1]

    def folder(self, name):
        """Folder of a saved profile."""
        return self.engine.profiles_dir / name


class RealListTests(RealBackendCase):
    """1. Listing."""

    def test_empty_home_lists_nothing(self):
        self.controller.refresh()
        self.assertIs(self.controller.state, LoadState.READY)
        self.assertEqual(self.store.names(), [])

    def test_lists_saved_profiles_with_size_and_date(self):
        self.service.save("b").raise_for_status()
        self.service.save("a").raise_for_status()
        self.controller.refresh()
        self.assertEqual(self.store.names(), ["a", "b"])
        profile = self.store.get("a")
        self.assertGreater(profile.size_mb, -1)
        self.assertGreater(profile.modified.year, 2000)
        self.assertEqual(profile.description, "")

    def test_a_failing_listing_is_reported(self):
        original = self.service.list_profiles

        def boom():
            raise PermissionError(13, "Permission denied", "/x")

        self.service.list_profiles = boom
        try:
            with no_logs(self, "ERROR"):
                self.controller.refresh()
        finally:
            self.service.list_profiles = original
        self.assertIs(self.controller.state, LoadState.ERROR)
        self.assertIn("Sem permissão", " ".join(self.controller.error))


class RealSaveTests(RealBackendCase):
    """2. Saving."""

    def test_save_creates_the_profile_folder(self):
        self.assertTrue(self.controller.save("work"))
        self.assertTrue(self.last().ok, self.last().details)
        self.assertEqual(
            (self.folder("work") / "configs/kdeglobals").read_text(), "kdeglobals-A"
        )
        self.assertEqual(self.store.names(), ["work"])

    def test_save_without_a_config_creates_the_default_one(self):
        self.config.config_path.unlink()
        self.assertTrue(self.controller.save("first"))
        self.assertTrue(self.last().ok, self.last().details)
        self.assertTrue(self.config.config_path.exists())
        self.assertEqual(self.store.names(), ["first"])

    def test_saving_an_existing_name_is_an_error_and_keeps_the_old_one(self):
        self.controller.save("work")
        write(self.root / ".config/kdeglobals", "NEWER")
        self.controller.save("work")
        self.assertFalse(self.last().ok)
        self.assertIn("Já existe", " ".join(self.last().details))
        self.assertEqual(
            (self.folder("work") / "configs/kdeglobals").read_text(), "kdeglobals-A"
        )

    def test_dangerous_names_are_refused_before_touching_the_disk(self):
        for bad in ("../x", "a/b", "", "-rf", "x" * 300):
            with self.subTest(name=bad):
                self.controller.save(bad)
                self.assertFalse(self.last().ok)
        self.assertEqual(self.store.names(), [])


class RealOverwriteTests(RealBackendCase):
    """3. Overwriting (a real replacement, not Konsave's merge)."""

    def test_overwrite_replaces_the_content(self):
        self.controller.save("work")
        write(self.folder("work") / "configs/stale.txt", "old")
        write(self.root / ".config/kdeglobals", "kdeglobals-B")
        self.assertTrue(self.controller.overwrite("work", confirmed=True))
        self.assertTrue(self.last().ok, self.last().details)
        self.assertEqual(
            (self.folder("work") / "configs/kdeglobals").read_text(), "kdeglobals-B"
        )
        self.assertFalse((self.folder("work") / "configs/stale.txt").exists())

    def test_overwrite_leaves_no_temporary_folder_and_other_profiles_alone(self):
        self.controller.save("work")
        self.controller.save("other")
        self.controller.overwrite("work", confirmed=True)
        self.assertEqual(
            sorted(os.listdir(self.engine.profiles_dir)), ["other", "work"]
        )
        self.assertEqual(self.store.names(), ["other", "work"])

    def test_overwriting_a_missing_profile_is_an_error(self):
        self.controller.overwrite("ghost", confirmed=True)
        self.assertFalse(self.last().ok)
        self.assertEqual(self.store.names(), [])

    def test_needs_explicit_confirmation(self):
        from kongui.core import ConfirmationRequiredError

        self.controller.save("work")
        with self.assertRaises(ConfirmationRequiredError):
            self.controller.overwrite("work")
        with self.assertRaises(ConfirmationRequiredError):
            self.backend.overwrite("work")


class RealApplyTests(RealBackendCase):
    """4. Applying (to the temporary home only)."""

    def test_apply_restores_the_saved_files(self):
        self.controller.save("work")
        write(self.root / ".config/kdeglobals", "CHANGED-LATER")
        self.assertTrue(self.controller.apply("work", confirmed=True))
        self.assertTrue(self.last().ok, self.last().details)
        self.assertEqual((self.root / ".config/kdeglobals").read_text(), "kdeglobals-A")
        self.assertEqual(self.store.active().name, "work")

    def test_a_refused_apply_says_why(self):
        # Found by tests.test_gui_overview: the refusal reached the interface
        # with an empty explanation.
        self.controller.save("work")
        conf = self.folder("work") / "conf.yaml"
        conf.write_text(
            conf.read_text().replace('"$HOME/.config"', '"$HOME/gone/deeper"')
        )
        self.controller.apply("work", confirmed=True)
        self.assertFalse(self.last().ok)
        self.assertIn("nor its parent exists", " ".join(self.last().details))

    def test_applying_a_missing_profile_is_an_error_and_changes_nothing(self):
        write(self.root / ".config/kdeglobals", "KEEP")
        self.controller.apply("ghost", confirmed=True)
        self.assertFalse(self.last().ok)
        self.assertEqual((self.root / ".config/kdeglobals").read_text(), "KEEP")
        self.assertEqual(self.controller.active_name, "")

    def test_a_profile_without_a_config_is_refused(self):
        self.controller.save("work")
        (self.folder("work") / "conf.yaml").unlink()
        write(self.root / ".config/kdeglobals", "KEEP")
        self.controller.apply("work", confirmed=True)
        self.assertFalse(self.last().ok)
        self.assertEqual((self.root / ".config/kdeglobals").read_text(), "KEEP")

    def test_needs_explicit_confirmation(self):
        from kongui.core import ConfirmationRequiredError

        self.controller.save("work")
        write(self.root / ".config/kdeglobals", "KEEP")
        with self.assertRaises(ConfirmationRequiredError):
            self.controller.apply("work")
        with self.assertRaises(ConfirmationRequiredError):
            self.backend.apply("work", confirmed="yes")
        self.assertEqual((self.root / ".config/kdeglobals").read_text(), "KEEP")

    def test_the_active_profile_is_remembered_in_the_settings(self):
        settings = AppSettings()
        controller = ProfileController(
            self.backend, InlineExecutor(), ProfileStore(), settings
        )
        self.controller.save("work")
        controller.refresh()
        controller.apply("work", confirmed=True)
        self.assertEqual(settings.get("last_applied"), "work")


class RealRemoveTests(RealBackendCase):
    """5. Removing."""

    def test_remove_deletes_only_that_profile(self):
        self.controller.save("a")
        self.controller.save("b")
        self.assertTrue(self.controller.remove("a", confirmed=True))
        self.assertTrue(self.last().ok, self.last().details)
        self.assertFalse(self.folder("a").exists())
        self.assertTrue(self.folder("b").exists())
        self.assertEqual(self.store.names(), ["b"])

    def test_removing_a_missing_profile_is_an_error(self):
        self.controller.remove("ghost", confirmed=True)
        self.assertFalse(self.last().ok)

    def test_does_not_touch_the_live_files(self):
        self.controller.save("a")
        self.controller.remove("a", confirmed=True)
        self.assertEqual((self.root / ".config/kdeglobals").read_text(), "kdeglobals-A")

    def test_needs_explicit_confirmation(self):
        from kongui.core import ConfirmationRequiredError

        self.controller.save("a")
        with self.assertRaises(ConfirmationRequiredError):
            self.controller.remove("a")
        self.assertTrue(self.folder("a").exists())


class RealWipeTests(RealBackendCase):
    """6. Wiping every profile."""

    def test_wipe_removes_every_profile_and_keeps_the_config(self):
        self.controller.save("a")
        self.controller.save("b")
        self.assertTrue(self.controller.wipe_all(confirmed=True))
        self.assertTrue(self.last().ok, self.last().details)
        self.assertEqual(self.store.names(), [])
        self.assertEqual(os.listdir(self.engine.profiles_dir), [])
        self.assertTrue(self.config.config_path.exists())

    def test_wiping_nothing_is_not_an_error(self):
        self.controller.wipe_all(confirmed=True)
        self.assertTrue(self.last().ok, self.last().details)

    def test_needs_explicit_confirmation(self):
        from kongui.core import ConfirmationRequiredError

        self.controller.save("a")
        with self.assertRaises(ConfirmationRequiredError):
            self.controller.wipe_all()
        with self.assertRaises(ConfirmationRequiredError):
            self.backend.wipe_all(confirmed=1)
        self.assertEqual(self.store.names(), ["a"])


class RealWindowFlowTests(RealBackendCase):
    """The whole interface on the real backend: save, overwrite, remove, wipe."""

    def test_buttons_drive_the_real_services(self):
        from unittest import mock

        from kongui.gui.widgets.dialogs import ConfirmDialog

        window = self.make_window(backend=self.backend)
        window.show_page("profiles")
        self.flush()
        page = window.pages["profiles"]
        self.assertFalse(page.empty_state.isHidden())
        self.accept_dialogs(lambda d: d.name_edit.setText("Real"))
        page.new_button.click()
        self.flush()
        self.assertEqual([c.profile_name for c in page.cards()], ["Real"])
        self.assertTrue(self.folder("Real").is_dir())
        card = page.cards()[0]
        self.assertIsNone(card.duplicate_action)
        self.assertIsNotNone(card.export_button, "export is available")
        with mock.patch.object(ConfirmDialog, "ask", return_value=True):
            card.overwrite_action.trigger()
            self.flush()
            page.cards()[0].remove_action.trigger()
            self.flush()
        self.assertEqual(page.cards(), [])
        self.assertEqual(os.listdir(self.engine.profiles_dir), [])

    def test_export_wipe_import_round_trip_through_the_interface(self):
        import hashlib
        import zipfile
        from unittest import mock

        from kongui.gui.widgets.dialogs import ConfirmDialog, ConflictDialog

        self.controller.save("work")
        window = self.make_window(backend=self.backend)
        window.show_page("transfer")
        self.flush()
        page = window.pages["transfer"]
        out = self.root / "out"
        out.mkdir()
        before = snapshot_dir(self.folder("work"))

        page.destination_edit.setText(str(out))
        self.assertTrue(page.start_export())
        archive = out / "work.knsv"
        self.assertTrue(archive.is_file())
        self.assertIn("work.knsv", window.toasts._toasts[-1].accessibleName())
        with zipfile.ZipFile(archive) as handle:
            self.assertIn("conf.yaml", handle.namelist())
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()

        # the same name again: asking never replaces silently
        with mock.patch.object(ConflictDialog, "ask", return_value="cancel") as ask:
            self.assertFalse(page.start_export())
        self.assertTrue(ask.called)
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), digest)
        with mock.patch.object(ConflictDialog, "ask", return_value="unique"):
            self.assertTrue(page.start_export())
        self.assertEqual(sorted(os.listdir(out)), ["work-2.knsv", "work.knsv"])
        with mock.patch.object(ConflictDialog, "ask", return_value="cancel"):
            self.assertFalse(page.start_export())
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), digest)

        # wipe, then bring the profile back from the file
        window.controller.wipe_all(confirmed=True)
        self.flush()
        self.assertEqual(window.store.names(), [])
        self.assertTrue(page.set_import_file(str(archive)))
        self.flush()
        self.assertEqual(page.import_name_edit.text(), "work")
        self.assertTrue(page.import_button.isEnabled(), page.file_error.text())
        with mock.patch.object(ConfirmDialog, "ask", return_value=True) as sure:
            self.assertTrue(page.start_import())
        self.assertTrue(sure.call_args.kwargs["destructive"])
        self.flush()
        self.assertEqual(window.store.names(), ["work"])
        self.assertEqual(snapshot_dir(self.folder("work")), before)
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), digest)
        self.assertEqual(window.toasts.kinds()[-1], "success")
        self.assertFalse(page.drop_zone.isHidden())

    def test_import_with_a_new_name_and_apply_after(self):
        from unittest import mock

        from kongui.gui.widgets.dialogs import ConfirmDialog

        self.controller.save("work")
        archive = self.backend.export_profile("work", str(self.root)).path
        write(self.root / ".config/kdeglobals", "CHANGED")
        window = self.make_window(backend=self.backend)
        window.show_page("transfer")
        page = window.pages["transfer"]
        page.set_import_file(str(archive))
        self.flush()
        page.import_name_edit.setText("viagem")
        page.apply_after_check.setChecked(True)
        with mock.patch.object(ConfirmDialog, "ask", return_value=True):
            self.assertTrue(page.start_import())
        self.flush()
        self.assertEqual(sorted(window.store.names()), ["viagem", "work"])
        self.assertEqual(window.store.active().name, "viagem")
        self.assertEqual((self.root / ".config/kdeglobals").read_text(), "kdeglobals-A")
        self.assertEqual(self.folder("viagem").is_dir(), True)

    def test_import_errors_are_shown_without_touching_anything(self):
        from unittest import mock

        from kongui.gui.widgets.dialogs import ConfirmDialog

        window = self.make_window(backend=self.backend)
        window.show_page("transfer")
        page = window.pages["transfer"]
        before = snapshot_dir(self.root)
        for label, make, fragment in (
            ("missing", lambda: self.root / "ghost.knsv", "não foi encontrado"),
            (
                "not a zip",
                lambda: write(self.root / "fake.knsv", "no"),
                "não é um .knsv",
            ),
            (
                "no conf",
                lambda: make_knsv(self.root / "nc.knsv", {"save/a": "x"}),
                "conf.yaml",
            ),
        ):
            with self.subTest(case=label):
                before = snapshot_dir(self.root)
                page.set_import_file(str(make()))
                self.flush()
                self.assertIn(fragment, page.file_error.text())
                self.assertFalse(page.import_button.isEnabled())
                with mock.patch.object(ConfirmDialog, "ask") as sure:
                    self.assertFalse(page.start_import())
                sure.assert_not_called()
                page.clear_file_button.click()
                os.path.exists(self.root / "ghost.knsv")
        self.assertEqual(self.store.names(), [])

    def test_export_errors_are_shown_without_writing(self):
        window = self.make_window(backend=self.backend)
        window.show_page("transfer")
        page = window.pages["transfer"]
        self.controller.save("work")
        window.controller.refresh()
        self.flush()
        out = self.root / "out"
        for directory, fragment in (
            (str(self.root / "missing"), "não existe"),
            (str(write(self.root / "plain.txt")), "não é uma pasta"),
        ):
            with self.subTest(directory=directory):
                page.destination_edit.setText(directory)
                self.assertFalse(page.start_export())
                self.assertIn(fragment, page.export_error.text())
        self.assertFalse(out.exists())

    def test_wording_does_not_claim_fictitious_data(self):
        from kongui.gui.widgets.common import Badge, Label

        window = self.make_window(backend=self.backend)
        texts = [w.text() for w in window.sidebar.findChildren(Label)]
        self.assertIn("perfis reais", " ".join(texts))
        self.assertNotIn("dados fictícios", " ".join(texts))
        badges = [b.text() for b in window.pages["about"].findChildren(Badge)]
        self.assertIn("Em desenvolvimento", badges)
        self.assertNotIn("Protótipo visual", badges)

    def test_transfer_is_available_and_demo_controls_are_not(self):
        window = self.make_window(backend=self.backend)
        window.show_page("transfer")
        self.flush()
        page = window.pages["transfer"]
        self.assertTrue(page.export_card.isEnabled())
        self.assertTrue(page.import_card.isEnabled())
        self.assertFalse(hasattr(page, "transfer_notice"))
        self.assertIsNone(window.pages["settings"].clear_button)
        self.assertEqual(window.context.activity.entries(), [])


if __name__ == "__main__":
    unittest.main()
