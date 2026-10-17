"""User actions on profiles: ask first, then call the controller.

* :class:`ProfileActions` opens the dialogs (name, confirmation) and starts the
  operation. Destructive operations are *never* started without the user
  pressing the confirm button; the controller refuses them otherwise.
* :class:`OutcomeNotifier` turns every finished operation into a notification
  and an activity entry. It exists once per window.
"""

from __future__ import annotations


from PySide6.QtCore import QCoreApplication, QObject
from PySide6.QtWidgets import QDialog, QWidget

from kongui.core import LockCancelledError
from kongui.gui.context import AppContext
from kongui.gui.controller import Outcome
from kongui.gui.formatting import format_datetime
from kongui.gui.mock_data import sections as demo_sections
from kongui.gui.widgets.dialogs import ConfirmDialog, ProfileDialog


def simulated_note() -> str:
    """Line added to the notice of an operation that only ran in demo mode."""
    return QCoreApplication.translate(
        "ProfileActions", "Simulation: nothing was changed in the system."
    )


def wipe_word() -> str:
    """Word the user must type to wipe every profile (in the current language)."""
    return QCoreApplication.translate("ProfileActions", "DELETE")


_ACTIVITY_KIND = {
    "save": "save",
    "overwrite": "save",
    "duplicate": "save",
    "apply": "apply",
    "remove": "remove",
    "wipe_all": "remove",
    "import": "import",
    "export": "export",
    "restore_backup": "apply",
    "delete_backup": "remove",
}


class ProfileActions(QObject):
    """Dialogs plus controller calls for each profile operation."""

    def __init__(self, ctx: AppContext) -> None:
        """Creates the helper.

        Args:
            ctx: Shared services.
        """
        super().__init__()
        self.ctx = ctx

    @property
    def _demo(self) -> bool:
        """Whether the fictitious backend is in use."""
        return self.ctx.backend.capabilities.demo

    def _dispatched(self, started: bool) -> bool:
        """Tells the user when an operation could not start."""
        if not started:
            self.ctx.toasts.show_message(
                "info",
                QCoreApplication.translate("ProfileActions", "Wait"),
                QCoreApplication.translate(
                    "ProfileActions", "Another operation is still in progress."
                ),
            )
        return started

    def _demo_note(self, kind: str = "nothing") -> str:
        """Returns the prototype remark to append to a confirmation, or ``""``.

        Args:
            kind: ``"nothing"`` when nothing at all changes in demo mode,
                ``"list"`` when only the fictitious list changes.
        """
        if not self._demo:
            return ""
        if kind == "list":
            return " " + QCoreApplication.translate(
                "ProfileActions", "(Prototype: only the fictitious list changes.)"
            )
        return " " + QCoreApplication.translate(
            "ProfileActions", "(Prototype: nothing will be changed.)"
        )

    def save_current(self, parent: QWidget) -> bool:
        """Asks for a name and saves the current configuration as a new profile.

        Args:
            parent: Window used as dialog parent.

        Returns:
            bool: Whether an operation was started.
        """
        caps = self.ctx.backend.capabilities
        dialog = ProfileDialog(
            parent,
            self.ctx.store.names(),
            demo_sections(),
            ask_details=caps.descriptions,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        name, description, chosen = dialog.values()
        return self._dispatched(self.ctx.controller.save(name, description, chosen))

    def overwrite(self, parent: QWidget, name: str) -> bool:
        """Replaces a profile with the current configuration, after confirmation.

        Args:
            parent: Window used as dialog parent.
            name: Existing profile.

        Returns:
            bool: Whether an operation was started.
        """
        if not ConfirmDialog.ask(
            parent,
            self.tr("Overwrite “{name}”?").format(name=name),
            self.tr(
                "The profile will be replaced by the current Plasma "
                "configuration. The old content is lost and there is no undo."
            )
            + self._demo_note(),
            self.tr("Overwrite"),
            destructive=True,
        ):
            return False
        return self._dispatched(self.ctx.controller.overwrite(name, confirmed=True))

    def apply(self, parent: QWidget, name: str) -> bool:
        """Applies a profile to the session, after confirmation.

        Args:
            parent: Window used as dialog parent.
            name: Existing profile.

        Returns:
            bool: Whether an operation was started.
        """
        if not ConfirmDialog.ask(
            parent,
            self.tr("Apply “{name}”?").format(name=name),
            self.tr(
                "The current configuration files will be replaced by those of "
                "this profile."
            )
            + " "
            + self.tr(
                "Before that, the files that will be overwritten are copied; you "
                "can go back in Settings → Safety copies."
            )
            + self._demo_note(),
            self.tr("Apply"),
            destructive=True,
        ):
            return False
        return self._dispatched(self.ctx.controller.apply(name, confirmed=True))

    def remove(self, parent: QWidget, name: str) -> bool:
        """Removes a profile, after confirmation.

        Args:
            parent: Window used as dialog parent.
            name: Existing profile.

        Returns:
            bool: Whether an operation was started.
        """
        if not ConfirmDialog.ask(
            parent,
            self.tr("Remove “{name}”?").format(name=name),
            self.tr("The profile will be deleted and cannot be recovered.")
            + self._demo_note("list"),
            self.tr("Remove"),
            destructive=True,
        ):
            return False
        return self._dispatched(self.ctx.controller.remove(name, confirmed=True))

    def wipe_all(self, parent: QWidget) -> bool:
        """Removes every profile; the user must type :data:`WIPE_WORD`.

        Args:
            parent: Window used as dialog parent.

        Returns:
            bool: Whether an operation was started.
        """
        count = len(self.ctx.store.names())
        if not ConfirmDialog.ask(
            parent,
            self.tr("Clear all profiles?"),
            self.tr(
                "The %n saved profile(s) will be deleted and cannot be recovered.",
                "",
                count,
            )
            + " "
            + self.tr("Konsave's conf.yaml is kept.")
            + self._demo_note("list"),
            self.tr("Clear all"),
            destructive=True,
            require_text=wipe_word(),
        ):
            return False
        return self._dispatched(self.ctx.controller.wipe_all(confirmed=True))

    def restore_backup(self, parent: QWidget, copy) -> bool:
        """Restores a safety copy, after confirmation.

        Args:
            parent: Window used as dialog parent.
            copy: The ``SnapshotInfo`` to restore.

        Returns:
            bool: Whether an operation was started.
        """
        if not ConfirmDialog.ask(
            parent,
            self.tr("Restore this safety copy?"),
            self._restore_message(copy) + self._demo_note(),
            self.tr("Restore"),
            destructive=True,
        ):
            return False
        return self._dispatched(
            self.ctx.controller.restore_backup(copy.id, confirmed=True)
        )

    def _restore_message(self, copy) -> str:
        """Explains what restoring a safety copy does."""
        when = format_datetime(copy.created)
        if copy.created_files:
            first = self.tr(
                "The {replaced} stored file(s) go back to what they were on "
                "{when} and the {created} file(s) created later are removed."
            ).format(replaced=copy.replaced, when=when, created=copy.created_files)
        else:
            first = self.tr(
                "The {replaced} stored file(s) go back to what they were on {when}."
            ).format(replaced=copy.replaced, when=when)
        return (
            first
            + " "
            + self.tr(
                "Changes made to those files after that will be lost; the current "
                "state is stored as a new copy, so it can be undone."
            )
        )

    def delete_backup(self, parent: QWidget, copy) -> bool:
        """Deletes a safety copy, after confirmation.

        Args:
            parent: Window used as dialog parent.
            copy: The ``SnapshotInfo`` to delete.

        Returns:
            bool: Whether an operation was started.
        """
        if not ConfirmDialog.ask(
            parent,
            self.tr("Delete this safety copy?"),
            self.tr("The copy will be deleted and cannot be recovered.")
            + self._demo_note("list"),
            self.tr("Delete"),
            destructive=True,
        ):
            return False
        return self._dispatched(
            self.ctx.controller.delete_backup(copy.id, confirmed=True)
        )

    def duplicate(self, name: str) -> bool:
        """Duplicates a profile (demo backend only).

        Args:
            name: Existing profile.

        Returns:
            bool: Whether an operation was started.
        """
        return self._dispatched(self.ctx.controller.duplicate(name))


class OutcomeNotifier(QObject):
    """Shows a notification and logs an activity for each finished operation."""

    def __init__(self, ctx: AppContext) -> None:
        """Connects to the controller.

        Args:
            ctx: Shared services.
        """
        super().__init__()
        self.ctx = ctx
        ctx.controller.operation_finished.connect(self.on_finished)

    def on_finished(self, outcome: Outcome) -> None:
        """Reports an outcome.

        Args:
            outcome: What happened.
        """
        demo = self.ctx.backend.capabilities.demo
        if outcome.operation == "list":
            # A failed listing is shown inside the page, with a retry button.
            return
        details = list(outcome.details)
        if outcome.ok and demo:
            details.append(simulated_note())
        text = "\n".join(details)
        if outcome.ok:
            kind = (
                "warning" if outcome.operation in ("remove", "wipe_all") else "success"
            )
            self.ctx.toasts.show_message(kind, outcome.title, text)
            activity = _ACTIVITY_KIND.get(outcome.operation)
            if activity:
                self.ctx.activity.add(activity, outcome.title)
        elif isinstance(outcome.error, LockCancelledError):
            self.ctx.toasts.show_message(
                "info",
                self.tr("Wait cancelled"),
                self.tr("Nothing was changed."),
                seconds=None,
            )
        else:
            self.ctx.toasts.show_message("error", outcome.title, text, seconds=0)


__all__ = ["ProfileActions", "OutcomeNotifier", "simulated_note", "wipe_word"]
