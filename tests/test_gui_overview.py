"""Overview of the application: every feature of the interface, used once, end to end.

The other GUI tests check each feature in depth, mostly on the in-memory backend or
by calling the controller directly. These tests do the opposite: few of them, and
each one goes through the **real interface** (buttons, menus, dialogs, the drop
area) down to the **real services** and the original Konsave code, in a temporary
``$HOME``, the way a user would chain the features. They answer the question "does
the whole application work together?", not "is every edge case handled?".

Every modal dialog is answered by :class:`ScriptedUser` through its own widgets
(typing in its fields and clicking its buttons), so the real dialog logic runs, for
example the word that must be typed before clearing all profiles. A dialog nobody
expected fails the test.

What each test covers, and which detailed module covers the same feature in depth,
is listed in ``docs/TEST_OVERVIEW.md``.
"""

from __future__ import annotations

import contextlib
import os
import traceback
import zipfile
from pathlib import Path
from typing import Callable, List, Tuple
from unittest import mock

from tests.gui_helpers import HAVE_QT, GuiTestCase
from tests.helpers import install_conf, BASE_CONF, non_root, really_root, write

if HAVE_QT:
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDropEvent
    from PySide6.QtWidgets import QDialog

    from kongui.core import ConfigService, KonsaveEngine, ProfileService
    from kongui.gui.backend import ServiceBackend
    from kongui.gui.controller import LoadState
    from kongui.gui.state import AppSettings
    from kongui.gui.tasks import InlineExecutor
    from kongui.gui.widgets.cards import ActivityRow
    from kongui.gui.widgets.dialogs import (
        ConfirmDialog,
        ConflictDialog,
        DetailsDialog,
        ProfileDialog,
        SafetyCopiesDialog,
    )

Answer = Callable[["QDialog"], None]


class ScriptedUser:
    """Answers modal dialogs in the expected order, through their real widgets.

    ``QDialog.exec`` is replaced while a test runs: instead of blocking, it takes
    the next expected step, checks that the dialog is of the expected class, runs
    the answer (which fills fields and clicks buttons) and returns the dialog's
    result, exactly what ``exec`` returns after a real click.

    Exceptions raised while answering are recorded rather than raised, because a
    dialog opened from a button's slot would otherwise have them swallowed by Qt;
    :meth:`answers` reports them.
    """

    def __init__(self, case: GuiTestCase) -> None:
        """Starts answering for ``case`` (stopped at its cleanup)."""
        self.case = case
        self.steps: List[Tuple[type, Answer]] = []
        self.problems: List[str] = []
        self.seen: List[str] = []
        user = self

        def fake_exec(dialog):
            return user.handle(dialog)

        patcher = mock.patch.object(QDialog, "exec", new=fake_exec)
        patcher.start()
        case.addCleanup(patcher.stop)

    def handle(self, dialog) -> int:
        """Answers one dialog (called instead of ``QDialog.exec``)."""
        name = f"{type(dialog).__name__} “{dialog.windowTitle()}”"
        self.seen.append(name)
        if not self.steps:
            self.problems.append(f"unexpected dialog: {name}")
            return QDialog.DialogCode.Rejected
        kind, answer = self.steps.pop(0)
        if not isinstance(dialog, kind):
            self.problems.append(f"expected a {kind.__name__}, got {name}")
            return QDialog.DialogCode.Rejected
        try:
            answer(dialog)
        except Exception:  # pylint: disable=broad-except
            self.problems.append(f"while answering {name}:\n{traceback.format_exc()}")
        self.case.flush()
        return dialog.result()

    @contextlib.contextmanager
    def answers(self, *steps: Tuple[type, Answer]):
        """Expects exactly these dialogs, in order, during the ``with`` block."""
        self.steps = list(steps)
        self.problems = []
        yield
        self.case.flush()
        left = [kind.__name__ for kind, _ in self.steps]
        self.steps = []
        self.case.assertEqual(self.problems, [], "\n".join(self.problems))
        self.case.assertEqual(left, [], f"dialogs that never opened: {left}")


# ---- answers: what the user types and clicks -------------------------------------


def confirm(dialog) -> None:
    """Clicks the confirm button (which must be enabled)."""
    assert dialog.confirm_button.isEnabled(), "the confirm button is disabled"
    dialog.confirm_button.click()


def new_profile(name: str, description: str = "") -> Answer:
    """Fills the *Save profile* dialog."""

    def answer(dialog) -> None:
        dialog.name_edit.setText(name)
        if description:
            dialog.description_edit.setPlainText(description)
        confirm(dialog)

    return answer


def description(text: str) -> Answer:
    """Fills the *Edit details* dialog."""

    def answer(dialog) -> None:
        dialog.description_edit.setPlainText(text)
        confirm(dialog)

    return answer


def unique_name(dialog) -> None:
    """Picks "Use a unique name" when the exported file already exists."""
    dialog.confirm_button.click()


def typed_word(record: dict) -> Answer:
    """Clears all profiles: first tries without the word, then types it."""

    def answer(dialog) -> None:
        record["enabled_before_typing"] = dialog.confirm_button.isEnabled()
        dialog.confirm_button.click()  # disabled: nothing happens
        record["accepted_before_typing"] = (
            dialog.result() == QDialog.DialogCode.Accepted
        )
        dialog.confirm_edit.setText(dialog.required_text)
        confirm(dialog)

    return answer


def restore_newest(record: dict) -> Answer:
    """In *Safety copies*: restores the newest copy, then closes the dialog."""

    def answer(dialog) -> None:
        record["listed_before"] = dialog.list_widget.count()
        dialog.list_widget.setCurrentRow(0)
        confirm(dialog)  # asks for confirmation (the next step), then restores
        record["listed_after"] = dialog.list_widget.count()
        dialog.cancel_button.click()  # "Close"

    return answer


# ---- shared set-up ------------------------------------------------------------------


@mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "KDE"})
class OverviewCase(GuiTestCase):
    """A real window on the real services, in a temporary home with live files."""

    def setUp(self) -> None:
        super().setUp()
        if really_root():
            self.skipTest("refusing to run file operations as root")
        self.root = Path(os.path.realpath(self.home))
        self.live(kdeglobals="kdeglobals-A", icons="theme-A")
        write(self.root / ".config/gtk-3.0/settings.ini", "[Settings]")
        self.engine = KonsaveEngine(self.root, euid_provider=non_root)
        self.config = ConfigService(self.engine)
        install_conf(self.config, BASE_CONF)
        self.backend = ServiceBackend(ProfileService(self.engine, self.config))
        self.user = ScriptedUser(self)
        self.window = self.make_window(
            backend=self.backend, executor=InlineExecutor(), settings=AppSettings()
        )
        self.outcomes: List = []
        self.window.controller.operation_finished.connect(self.outcomes.append)
        self.flush()

    # -- the live session (inside the temporary home) --

    def live(self, kdeglobals=None, icons=None) -> None:
        """Writes the live files that ``BASE_CONF`` saves and exports."""
        if kdeglobals is not None:
            write(self.root / ".config/kdeglobals", kdeglobals)
        if icons is not None:
            write(self.root / ".local/share/icons/theme.txt", icons)

    def read_live(self, relative: str) -> str:
        """Text of a live file."""
        return (self.root / relative).read_text(encoding="utf-8")

    def profile_dir(self, name: str) -> Path:
        """Folder of a saved profile."""
        return self.engine.profiles_dir / name

    # -- the interface --

    def page(self, key: str):
        """Shows a page and returns it."""
        page = self.window.show_page(key)
        self.flush()
        return page

    def card(self, name: str):
        """The card of a profile on the *Profiles* page."""
        page = self.page("profiles")
        for card in page.cards():
            if card.profile_name == name:
                return card
        self.fail(f"no card for {name!r}: {[c.profile_name for c in page.cards()]}")

    def stat(self, key: str) -> str:
        """Value of a summary card of the dashboard."""
        return self.page("dashboard").stats[key].value_label.text()

    def assert_all_succeeded(self) -> None:
        """Every operation finished so far succeeded."""
        failed = [(o.operation, o.details) for o in self.outcomes if not o.ok]
        self.assertEqual(failed, [])

    def operations(self) -> List[str]:
        """Names of the operations finished so far, in order."""
        return [outcome.operation for outcome in self.outcomes]


# ---- 1. profiles, safety copies, details ---------------------------------------


class ProfileJourneyTests(OverviewCase):
    """Save, apply, go back from the safety copy, edit details, overwrite."""

    def test_save_apply_restore_details_and_overwrite(self):
        # An empty account: the dashboard and the profiles page say so.
        self.assertEqual(self.stat("count"), "0")
        self.assertTrue(self.page("profiles").empty_state.isVisibleTo(self.window))

        # Save the current configuration from the dashboard, with a description.
        with self.user.answers((ProfileDialog, new_profile("Trabalho", "Tema A"))):
            self.page("dashboard").save_button.click()
        self.assertEqual(
            (self.profile_dir("Trabalho") / "configs/kdeglobals").read_text(),
            "kdeglobals-A",
        )
        card = self.card("Trabalho")
        self.assertEqual(card.description_label.text(), "Tema A")
        self.assertIn("configs", self.window.context.store.get("Trabalho").sections)
        self.assertEqual(self.stat("count"), "1")

        # Change the session, then apply the profile from its card.
        self.live(kdeglobals="CHANGED")
        with self.user.answers((ConfirmDialog, confirm)):
            self.card("Trabalho").apply_button.click()
        self.assertEqual(self.read_live(".config/kdeglobals"), "kdeglobals-A")
        self.assertEqual(self.stat("active"), "Trabalho")
        self.assertFalse(self.card("Trabalho").apply_button.isEnabled())  # "In use"
        self.assertEqual(len(self.backend.list_backups()), 1)

        # Go back: Settings → Safety copies → Restore (asks first).
        record: dict = {}
        with self.user.answers(
            (SafetyCopiesDialog, restore_newest(record)), (ConfirmDialog, confirm)
        ):
            self.page("settings").copies_button.click()
        self.assertEqual(self.read_live(".config/kdeglobals"), "CHANGED")
        # The restore stored the state it replaced as a new copy (so it can be
        # undone), and the open dialog reloaded its list.
        self.assertEqual(record, {"listed_before": 1, "listed_after": 2})
        self.assertEqual(len(self.backend.list_backups()), 2)

        # Edit the description from the card menu.
        with self.user.answers((DetailsDialog, description("Tema B"))):
            self.card("Trabalho").details_action.trigger()
        self.assertEqual(
            self.window.context.store.get("Trabalho").description, "Tema B"
        )
        self.assertEqual(self.card("Trabalho").description_label.text(), "Tema B")

        # Overwrite the profile with the current configuration (asks first).
        with self.user.answers((ConfirmDialog, confirm)):
            self.card("Trabalho").overwrite_action.trigger()
        self.assertEqual(
            (self.profile_dir("Trabalho") / "configs/kdeglobals").read_text(),
            "CHANGED",
        )

        # Declining a confirmation changes nothing.
        with self.user.answers((ConfirmDialog, lambda d: d.cancel_button.click())):
            self.card("Trabalho").remove_action.trigger()
        self.assertTrue(self.profile_dir("Trabalho").is_dir())

        self.assert_all_succeeded()
        self.assertEqual(
            self.operations(),
            ["save", "apply", "restore_backup", "set_description", "overwrite"],
        )
        rows = self.page("dashboard").activity_card.findChildren(ActivityRow)
        self.assertGreaterEqual(len(rows), 5)


# ---- 2. export, import, clear all ------------------------------------------------


class TransferJourneyTests(OverviewCase):
    """Export (and its conflict), remove, import by dropping the file, clear all."""

    def test_export_remove_import_and_clear_all(self):
        self.window.controller.save("Trabalho", "Não viaja no .knsv")
        sections = self.window.context.store.get("Trabalho").sections
        destination = self.root / "exportados"
        destination.mkdir()

        # "Export" on the card opens the form with the profile already chosen.
        self.card("Trabalho").export_button.click()
        self.flush()
        self.assertEqual(self.window.current_key, "transfer")
        transfer = self.window.pages["transfer"]
        self.assertEqual(transfer.export_combo.currentData(), "Trabalho")
        transfer.destination_edit.setText(str(destination))
        with self.user.answers():  # nothing exists yet: no question
            transfer.export_button.click()
        archive = destination / "Trabalho.knsv"
        self.assertTrue(zipfile.is_zipfile(archive))

        # Exporting again: the file exists, so the interface asks.
        with self.user.answers((ConflictDialog, unique_name)):
            transfer.export_button.click()
        self.assertTrue(zipfile.is_zipfile(destination / "Trabalho-2.knsv"))
        self.assertEqual(
            archive.read_bytes()[:4], b"PK\x03\x04", "the first file is untouched"
        )

        # Remove the profile from the card menu (asks first).
        with self.user.answers((ConfirmDialog, confirm)):
            self.card("Trabalho").remove_action.trigger()
        self.assertFalse(self.profile_dir("Trabalho").exists())
        self.assertEqual(self.window.context.store.names(), [])

        # Import it back by dropping the file on the import area. The archive's
        # "export" section (icons) is written to the live session, after a copy.
        self.live(icons="theme-B")
        transfer = self.page("transfer")
        self.drop(transfer.drop_zone, archive)
        self.assertEqual(transfer.import_name_edit.text(), "Trabalho")
        self.assertFalse(transfer.file_error.isVisibleTo(self.window))
        self.assertTrue(transfer.import_button.isEnabled())
        with self.user.answers((ConfirmDialog, confirm)):
            transfer.import_button.click()
        imported = self.window.context.store.get("Trabalho")
        self.assertIsNotNone(imported)
        self.assertEqual(imported.sections, sections)
        self.assertEqual(imported.description, "")  # decided: it does not travel
        self.assertEqual(self.read_live(".local/share/icons/theme.txt"), "theme-A")
        self.assertEqual(len(self.backend.list_backups()), 1)  # copy before import
        recent = self.page("transfer").findChildren(ActivityRow)
        self.assertEqual(len(recent), 3)  # two exports and the import

        # Clear all: the word must be typed before the button works.
        record: dict = {}
        with self.user.answers((ConfirmDialog, typed_word(record))):
            self.page("profiles").wipe_button.click()
        self.assertEqual(
            record, {"enabled_before_typing": False, "accepted_before_typing": False}
        )
        self.assertEqual(self.window.context.store.names(), [])
        self.assertEqual(list(self.engine.profiles_dir.iterdir()), [])
        self.assertTrue(self.config.config_path.exists())  # conf.yaml is kept
        self.assertTrue(self.page("profiles").empty_state.isVisibleTo(self.window))

        self.assert_all_succeeded()
        self.assertEqual(
            self.operations(),
            ["save", "export", "export", "remove", "import", "wipe_all"],
        )

    @staticmethod
    def drop(zone, path: Path) -> None:
        """Drops a file on the import area, as a file manager would."""
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path))])
        zone.dropEvent(
            QDropEvent(
                QPointF(5, 5),
                Qt.DropAction.CopyAction,
                mime,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )


# ---- 3. conf.yaml edited by hand decides what a profile holds ----------------------

WIDGETS_GROUP = BASE_CONF.replace(
    "export:",
    "    widgets:\n"
    '        location: "$HOME/.local/share"\n'
    "        entries:\n"
    "            - plasma\n"
    "export:",
)


class HandEditedConfigJourneyTests(OverviewCase):
    """KonGUI has no conf.yaml editor: the user edits the file, as with Konsave."""

    def test_a_group_added_by_hand_is_saved_and_applied(self):
        self.assertNotIn("config", self.window.pages)  # no editor page any more
        self.window.controller.save("Antes")
        write(self.root / ".local/share/plasma/look.txt", "look-A")

        # A broken edit is not checked beforehand: saving fails with Konsave's
        # own reason and leaves no half-made profile.
        install_conf(self.config, "save: [\n")
        with self.user.answers((ProfileDialog, new_profile("Quebrado"))):
            self.page("profiles").new_button.click()
        failed = self.outcomes[-1]
        self.assertFalse(failed.ok)
        self.assertTrue(failed.details, "the notice says why")
        self.assertFalse(self.profile_dir("Quebrado").exists())

        # The user fixes the file, adding a group.
        install_conf(self.config, WIDGETS_GROUP)
        with self.user.answers((ProfileDialog, new_profile("Depois"))):
            self.page("profiles").new_button.click()
        store = self.window.context.store
        self.assertIn("widgets", store.get("Depois").sections)
        self.assertNotIn("widgets", store.get("Antes").sections)
        self.assertEqual(
            (self.profile_dir("Depois") / "widgets/plasma/look.txt").read_text(),
            "look-A",
        )

        # Applying it puts that group's files back (after a safety copy).
        write(self.root / ".local/share/plasma/look.txt", "look-B")
        with self.user.answers((ConfirmDialog, confirm)):
            self.card("Depois").apply_button.click()
        self.assertEqual(self.read_live(".local/share/plasma/look.txt"), "look-A")
        self.assertEqual(len(self.backend.list_backups()), 1)

        self.assertEqual(self.operations(), ["save", "save", "save", "apply"])
        self.assertEqual([o.ok for o in self.outcomes], [True, False, True, True])
        # Nothing besides the user's own file was written next to it.
        names = os.listdir(self.config.config_path.parent)
        self.assertEqual([n for n in names if n.startswith("conf.yaml")], ["conf.yaml"])


# ---- 4. the application as the `kongui` command builds it ------------------------


@mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "KDE"})
class RealApplicationTests(GuiTestCase):
    """The backend of the `kongui` command, a worker thread and saved preferences."""

    def setUp(self) -> None:
        super().setUp()
        if really_root():
            self.skipTest("refusing to run file operations as root")
        self.user = ScriptedUser(self)
        self.settings_file = str(Path(self.home) / "kongui-gui.ini")
        # A home as a desktop session has it (KonGUI refuses to apply a group
        # whose folder and parent folder are both missing).
        for folder in (".config", ".local/share"):
            (Path(self.home) / folder).mkdir(parents=True, exist_ok=True)
        write(Path(self.home) / ".config/kdeglobals", "[General]")

    def open(self):
        """Builds the window the way ``kongui.gui.app.main`` does (no ``exec``)."""
        from kongui.gui import app
        from kongui.gui.main_window import MainWindow

        backend = app.build_backend(False)  # ServiceBackend on $HOME (temporary)
        self.assertIsInstance(backend, ServiceBackend)
        window = MainWindow(AppSettings(self.settings_file), backend)
        window.show()
        self.addCleanup(self.destroy_window, window)
        self.assertTrue(
            self.wait_until(lambda: window.controller.state is LoadState.READY, 10)
        )
        return window

    def test_operations_run_in_the_background_and_preferences_survive_a_restart(self):
        window = self.open()
        outcomes: List = []
        window.controller.operation_finished.connect(outcomes.append)

        # Save: the default conf.yaml is created and the work runs off the
        # interface thread (the window keeps processing events meanwhile).
        with self.user.answers((ProfileDialog, new_profile("Casa"))):
            window.pages["dashboard"].save_button.click()
        self.assertTrue(self.wait_until(lambda: len(outcomes) == 1, 20))
        self.assertTrue(outcomes[0].ok, outcomes[0].details)
        home = Path(self.home)
        self.assertTrue((home / ".config/konsave/conf.yaml").is_file())
        self.assertTrue((home / ".config/konsave/profiles/Casa").is_dir())

        # Apply from the card, also in the background.
        window.show_page("profiles")
        self.flush()
        (card,) = window.pages["profiles"].cards()
        with self.user.answers((ConfirmDialog, confirm)):
            card.apply_button.click()
        self.assertTrue(self.wait_until(lambda: len(outcomes) == 2, 20))
        self.assertTrue(outcomes[1].ok, [(o.operation, o.details) for o in outcomes])
        self.assertEqual(window.context.store.active().name, "Casa")

        # Choose a theme and a language in Settings, then restart.
        settings_page = window.show_page("settings")
        # pylint: disable=protected-access  (the segment buttons have no public name)
        settings_page.theme_control._buttons["dark"].click()
        settings_page.language_control._buttons["en"].click()
        self.flush()
        self.assertEqual(window.top_bar.title_label.text(), "Settings")  # live switch
        self.destroy_window(window)

        again = self.open()
        from kongui.gui import i18n
        from kongui.gui.theme import ThemeMode

        self.assertEqual(i18n.current(), "en")
        self.assertIs(again.theme.mode, ThemeMode.DARK)
        self.assertEqual(again.context.store.names(), ["Casa"])
        self.assertEqual(
            again.pages["dashboard"].stats["count"].value_label.text(), "1"
        )
