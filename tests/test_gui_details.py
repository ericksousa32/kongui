"""Profile description and sections in the interface, on the real backend.

Everything runs in a temporary home with the real Konsave services (no demo
data). The persistence rules are tested in ``tests.test_profile_details``; this
file checks what the user sees and the dialogs.
"""

from __future__ import annotations

import errno
import json
import unittest
from unittest import mock

from PySide6.QtWidgets import QDialog

from kongui.core.profilemeta import META_FILENAME
from kongui.gui.widgets.common import Badge
from kongui.gui.widgets.dialogs import DetailsDialog, ProfileDialog
from tests.helpers import write
from tests.test_gui_real_backend import RealBackendCase
from tests.test_profile_details import TWO_GROUPS


def full_disk():
    """Makes the next description write fail as if the disk were full."""
    return mock.patch(
        "kongui.core.profilemeta.os.replace",
        side_effect=OSError(errno.ENOSPC, "No space left on device"),
    )


class DetailsControllerTests(RealBackendCase):
    """What the controller reports when descriptions are saved or edited."""

    LANGUAGE = "en_US"

    def test_a_saved_description_reaches_the_list(self):
        self.controller.save("work", "Dark theme", ())
        self.assertTrue(self.last().ok)
        self.assertFalse(self.last().warning)
        profile = self.store.get("work")
        self.assertEqual(profile.description, "Dark theme")
        self.assertEqual(profile.sections, ("configs",))

    def test_editing_and_clearing(self):
        self.controller.save("work", "First", ())
        self.controller.set_description("work", "Second")
        self.assertEqual(self.last().title, "Details of “work” updated")
        self.assertEqual(self.store.get("work").description, "Second")
        self.controller.set_description("work", "")
        self.assertTrue(self.last().ok)
        self.assertEqual(self.store.get("work").description, "")

    def test_a_save_without_its_description_is_a_warning(self):
        with full_disk():
            self.controller.save("work", "Lost", ())
        outcome = self.last()
        self.assertTrue(outcome.ok, "the profile exists")
        self.assertTrue(outcome.warning)
        self.assertEqual(outcome.title, "Profile “work” saved, but not its description")
        self.assertIn("could not be written", " ".join(outcome.details))
        self.assertIsNotNone(self.store.get("work"))
        self.assertEqual(self.store.get("work").description, "")

    def test_a_failed_edit_is_an_error_and_keeps_the_old_text(self):
        self.controller.save("work", "Old", ())
        with full_disk():
            self.controller.set_description("work", "New")
        outcome = self.last()
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.title, "Could not update the details of “work”")
        self.assertIn("ran out of free space", " ".join(outcome.details))
        self.assertEqual(self.store.get("work").description, "Old")

    def test_a_too_long_description_is_explained(self):
        self.controller.save("work", "", ())
        self.controller.set_description("work", "x" * 501)
        self.assertFalse(self.last().ok)
        self.assertIn(
            "The description is too long (at most 500 characters).",
            self.last().details,
        )

    def test_a_missing_profile_is_reported(self):
        self.controller.set_description("ghost", "x")
        self.assertFalse(self.last().ok)


class DetailsWindowTests(RealBackendCase):
    """The profiles page, the card menu and the dialogs."""

    LANGUAGE = "en_US"

    def setUp(self):
        super().setUp()
        self.service.save("work", description="Current").raise_for_status()
        self.window = self.make_window(backend=self.backend)
        self.window.controller.refresh()
        self.flush()
        self.page = self.window.pages["profiles"]
        self.finished = []
        self.window.controller.operation_finished.connect(self.finished.append)

    def card(self, name="work"):
        return next(c for c in self.page.cards() if c.profile_name == name)

    def edit(self, accept, text=None, seen=None):
        """Opens "Edit details" with a dialog that behaves as told."""

        def fake_exec(dialog):
            if seen is not None:
                seen.append(dialog.description_edit.toPlainText())
            if text is not None:
                dialog.description_edit.setPlainText(text)
            return (
                QDialog.DialogCode.Accepted if accept else QDialog.DialogCode.Rejected
            )

        with mock.patch.object(DetailsDialog, "exec", new=fake_exec):
            self.card().details_action.trigger()
        self.flush()

    def test_the_card_shows_the_description(self):
        self.assertEqual(self.card().description_label.text(), "Current")

    def test_the_dialog_opens_with_the_current_text_and_saves_the_new_one(self):
        seen = []
        self.edit(accept=True, text="Changed", seen=seen)
        self.assertEqual(seen, ["Current"])
        self.assertEqual(self.card().description_label.text(), "Changed")
        stored = json.loads((self.folder("work") / META_FILENAME).read_text("utf-8"))
        self.assertEqual(stored["description"], "Changed")

    def test_cancelling_keeps_everything(self):
        self.edit(accept=False, text="Never saved")
        self.assertEqual(self.finished, [], "no operation was started")
        self.assertEqual(self.card().description_label.text(), "Current")
        stored = json.loads((self.folder("work") / META_FILENAME).read_text("utf-8"))
        self.assertEqual(stored["description"], "Current")

    def test_an_empty_description_is_accepted_and_the_card_stays_usable(self):
        self.edit(accept=True, text="   ")
        self.assertIsNone(self.card().description_label)
        self.assertFalse((self.folder("work") / META_FILENAME).exists())
        self.assertTrue(self.card().apply_button.isEnabled())

    def test_markup_is_shown_as_plain_text(self):
        self.edit(accept=True, text="<b>bold</b> <img src='x'>")
        label = self.card().description_label
        self.assertEqual(label.text(), "<b>bold</b> <img src='x'>")
        from PySide6.QtCore import Qt

        self.assertEqual(label.textFormat(), Qt.TextFormat.PlainText)

    def test_the_dialog_refuses_a_text_that_is_too_long(self):
        dialog = DetailsDialog(None, "work", "ok")
        self.assertTrue(dialog.confirm_button.isEnabled())
        dialog.description_edit.setPlainText("x" * 501)
        self.assertFalse(dialog.confirm_button.isEnabled())
        self.assertIn("too long", dialog.error_label.text())

    def test_the_save_dialog_asks_for_a_description_but_not_for_sections(self):
        seen = {}

        def fake_exec(dialog):
            seen["checks"] = len(dialog.section_checks)
            seen["description"] = dialog.description_edit.isVisibleTo(dialog)
            dialog.name_edit.setText("second")
            dialog.description_edit.setPlainText("From the dialog")
            return QDialog.DialogCode.Accepted

        with mock.patch.object(ProfileDialog, "exec", new=fake_exec):
            self.page.new_button.click()
        self.flush()
        self.assertEqual(seen, {"checks": 0, "description": True})
        self.assertEqual(self.window.store.get("second").description, "From the dialog")

    def test_a_save_without_its_description_shows_a_warning_toast(self):
        def fake_exec(dialog):
            dialog.name_edit.setText("second")
            dialog.description_edit.setPlainText("Will fail")
            return QDialog.DialogCode.Accepted

        with mock.patch.object(ProfileDialog, "exec", new=fake_exec), full_disk():
            self.page.new_button.click()
        self.flush()
        toast = self.window.toasts._toasts[-1]
        self.assertEqual(toast.kind, "warning")
        self.assertIn("not its description", toast.accessibleName())

    def test_a_failed_edit_shows_an_error_toast(self):
        with full_disk():
            self.edit(accept=True, text="New")
        self.assertEqual(self.window.toasts._toasts[-1].kind, "error")
        self.assertEqual(self.card().description_label.text(), "Current")


class SectionChipsTests(RealBackendCase):
    """The sections shown on the cards: friendly names, no empty groups."""

    LANGUAGE = "en_US"

    def chips(self, card):
        return [badge.text() for badge in card.findChildren(Badge)]

    def test_known_groups_get_friendly_names_and_empty_ones_are_hidden(self):
        self.config.write_text(TWO_GROUPS)
        self.service.save("work").raise_for_status()
        window = self.make_window(backend=self.backend)
        window.controller.refresh()
        self.flush()
        card = window.pages["profiles"].cards()[0]
        self.assertEqual(self.chips(card), ["Desktop settings"])

    def test_unknown_groups_keep_their_own_name(self):
        self.config.write_text(
            'save:\n  my_vim:\n    location: "$HOME/.config"\n    entries:\n      - vimrc\n'
            'export:\n  share_folder:\n    location: "$HOME/.local/share"\n    entries: []\n'
        )
        write(self.root / ".config/vimrc", "set number")
        self.service.save("editor").raise_for_status()
        window = self.make_window(backend=self.backend)
        window.controller.refresh()
        self.flush()
        card = window.pages["profiles"].cards()[0]
        self.assertEqual(self.chips(card), ["my_vim"])

    def test_the_search_finds_by_description_and_by_friendly_section(self):
        self.service.save("work", description="Single panel").raise_for_status()
        self.service.save("other").raise_for_status()
        window = self.make_window(backend=self.backend)
        window.controller.refresh()
        self.flush()
        page = window.pages["profiles"]
        for query, expected in (
            ("single panel", ["work"]),
            ("desktop settings", ["other", "work"]),
            ("configs", ["other", "work"]),
        ):
            with self.subTest(query=query):
                page.search.setText(query)
                self.flush()
                self.assertEqual(sorted(c.profile_name for c in page.cards()), expected)

    def test_the_friendly_name_follows_the_language(self):
        self.service.save("work").raise_for_status()
        window = self.make_window(backend=self.backend)
        window.controller.refresh()
        self.flush()
        window.settings.set("language", "pt_BR")
        self.flush()
        window.controller.refresh()
        self.flush()
        card = window.pages["profiles"].cards()[0]
        self.assertEqual(self.chips(card), ["Configurações da área de trabalho"])


class DemoBackendTests(unittest.TestCase):
    """The demo backend offers the same editing, on its fictitious data."""

    def test_editing_a_fictitious_description(self):
        from kongui.core import ProfileNotFoundError, ValidationError
        from kongui.gui.backend import FakeBackend

        backend = FakeBackend()
        self.assertTrue(backend.capabilities.descriptions)
        backend.set_description("Work", "  Edited  ")
        work = next(p for p in backend.list_profiles() if p.name == "Work")
        self.assertEqual(work.description, "Edited")
        with self.assertRaises(ValidationError):
            backend.set_description("Work", "x" * 501)
        with self.assertRaises(ProfileNotFoundError):
            backend.set_description("Nope", "x")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
