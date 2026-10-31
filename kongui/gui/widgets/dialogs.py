"""Modal dialogs."""

from __future__ import annotations

from typing import Any, Callable, Collection, List, Optional, Sequence, Tuple

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from kongui.core import CATEGORY_DEPENDENCIES, MAX_DESCRIPTION_CHARS
from kongui.gui.formatting import format_datetime, format_kib
from kongui.gui.messages import section_label
from kongui.gui.validation import profile_name_problem
from kongui.gui.widgets.common import Button, Label, repolish


class BaseDialog(QDialog):
    """Dialog frame with a title, a body area and a button row."""

    def __init__(
        self, parent: Optional[QWidget], title: str, confirm_text: str, variant: str
    ):
        """Creates the dialog.

        Args:
            parent: Parent window.
            title: Window title and heading.
            confirm_text: Label of the confirm button.
            variant: Button variant of the confirm button.
        """
        super().__init__(parent)
        self.setObjectName("Dialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(440)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 22, 24, 20)
        outer.setSpacing(14)
        outer.addWidget(Label(title, "h2"))
        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        outer.addLayout(self.body)
        outer.addStretch(1)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)
        self.cancel_button = Button(self.tr("Cancel"))
        self.confirm_button = Button(confirm_text, variant=variant)
        self.confirm_button.setDefault(True)
        self.cancel_button.clicked.connect(self.reject)
        self.confirm_button.clicked.connect(self.accept)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.confirm_button)
        self.button_row = buttons
        outer.addLayout(buttons)


class ConfirmDialog(BaseDialog):
    """Asks the user to confirm an action."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        parent: Optional[QWidget],
        title: str,
        message: str,
        confirm_text: str = "",
        *,
        destructive: bool = False,
        require_text: str = "",
    ) -> None:
        """Creates the dialog.

        Args:
            parent: Parent window.
            title: Heading.
            message: Explanation of what will happen.
            confirm_text: Label of the confirm button; defaults to "Confirm".
            destructive: Use the red button style for irreversible actions.
            require_text: Word that must be typed exactly before the confirm
                button is enabled (for the most destructive actions).
        """
        super().__init__(
            parent,
            title,
            confirm_text or self.tr("Confirm"),
            "danger-solid" if destructive else "primary",
        )
        self.message_label = Label(message, wrap=True)
        self.body.addWidget(self.message_label)
        self.required_text = require_text
        self.confirm_edit: Optional[QLineEdit] = None
        if require_text:
            self.body.addWidget(
                Label(
                    self.tr("Type {word} to confirm:").format(word=require_text),
                    "muted",
                )
            )
            self.confirm_edit = QLineEdit()
            self.confirm_edit.setAccessibleName(
                self.tr("Type {word} to confirm").format(word=require_text)
            )
            self.confirm_edit.textChanged.connect(self._check_text)
            self.body.addWidget(self.confirm_edit)
            self.confirm_button.setEnabled(False)
        self.cancel_button.setFocus()

    def _check_text(self, text: str) -> None:
        """Enables the confirm button only when the typed word matches."""
        self.confirm_button.setEnabled(text.strip() == self.required_text)

    @classmethod
    def ask(  # pylint: disable=too-many-arguments
        cls,
        parent: Optional[QWidget],
        title: str,
        message: str,
        confirm_text: str = "",
        *,
        destructive: bool = False,
        require_text: str = "",
    ) -> bool:
        """Shows the dialog and waits.

        Args:
            parent: Parent window.
            title: Heading.
            message: Explanation.
            confirm_text: Label of the confirm button; defaults to "Confirm".
            destructive: Use the red button style.
            require_text: Word the user must type to enable the confirm button.

        Returns:
            bool: ``True`` only if the user confirmed.
        """
        dialog = cls(
            parent,
            title,
            message,
            confirm_text,
            destructive=destructive,
            require_text=require_text,
        )
        return dialog.exec() == QDialog.DialogCode.Accepted


class ConflictDialog(BaseDialog):
    """Asks what to do when the exported file already exists.

    After ``exec()``, :attr:`choice` is ``"cancel"``, ``"unique"`` (save under a
    free name) or ``"overwrite"`` (replace the existing file).
    """

    def __init__(
        self, parent: Optional[QWidget], title: str, message: str, allow_replace: bool
    ) -> None:
        """Creates the dialog.

        Args:
            parent: Parent window.
            title: Heading.
            message: Explanation of what exists.
            allow_replace: Offer "Replace" (not when a folder or ``.zip``
                with that name is in the way: the original would delete it).
        """
        super().__init__(parent, title, self.tr("Use a unique name"), "primary")
        self.choice = "cancel"
        self.body.addWidget(Label(message, wrap=True))
        self.replace_button = Button(self.tr("Replace"), variant="danger-solid")
        self.replace_button.setVisible(allow_replace)
        self.button_row.insertWidget(self.button_row.count() - 1, self.replace_button)
        self.confirm_button.clicked.connect(lambda: self._pick("unique"))
        self.replace_button.clicked.connect(lambda: self._pick("overwrite"))
        self.cancel_button.setFocus()

    def _pick(self, choice: str) -> None:
        """Records the choice (the button also closes the dialog)."""
        self.choice = choice
        if choice == "overwrite":
            self.accept()

    @classmethod
    def ask(
        cls,
        parent: Optional[QWidget],
        title: str,
        message: str,
        allow_replace: bool = True,
    ) -> str:
        """Shows the dialog and waits.

        Args:
            parent: Parent window.
            title: Heading.
            message: Explanation.
            allow_replace: Offer "Replace".

        Returns:
            str: ``cancel``, ``unique`` or ``overwrite``.
        """
        dialog = cls(parent, title, message, allow_replace)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return "cancel"
        return dialog.choice


class ProfileDialog(BaseDialog):
    """Collects the name, description and sections of a new profile."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        parent: Optional[QWidget],
        existing_names: Collection[str],
        sections: Sequence[str],
        *,
        title: str = "",
        confirm_text: str = "",
        ask_details: bool = True,
        ask_sections: Optional[bool] = None,
    ) -> None:
        """Creates the dialog.

        Args:
            parent: Parent window.
            existing_names: Names that cannot be reused.
            sections: Section names offered as check boxes (all start checked).
            title: Heading; defaults to "Save current profile".
            confirm_text: Label of the confirm button; defaults to "Save".
            ask_details: Show the description box. Off when the backend cannot
                store descriptions.
            ask_sections: Show the section check boxes. ``None`` (the default)
                follows ``ask_details``.
        """
        super().__init__(
            parent,
            title or self.tr("Save current profile"),
            confirm_text or self.tr("Save"),
            "primary",
        )
        self._existing = set(existing_names)
        self.body.addWidget(Label(self.tr("Name"), "muted"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(self.tr("E.g.: Work"))
        self.name_edit.setAccessibleName(self.tr("Profile name"))
        self.body.addWidget(self.name_edit)
        self.error_label = Label("", "danger", wrap=True)
        self.body.addWidget(self.error_label)
        self.description_edit = QPlainTextEdit()
        self.description_edit.setFixedHeight(64)
        self.description_edit.setAccessibleName(self.tr("Profile description"))
        self.section_checks: List[QCheckBox] = []
        self.warning_label = Label("", "muted", wrap=True)
        if ask_details:
            self.body.addWidget(Label(self.tr("Description (optional)"), "muted"))
            self.body.addWidget(self.description_edit)
            self.description_edit.textChanged.connect(self._update)
        if ask_details if ask_sections is None else ask_sections:
            self.body.addWidget(Label(self.tr("What to include"), "muted"))
            picker_buttons = QHBoxLayout()
            select_all = Button(self.tr("Select all"), variant="ghost")
            clear_all = Button(self.tr("Clear all"), variant="ghost")
            select_all.clicked.connect(lambda: self._check_all(True))
            clear_all.clicked.connect(lambda: self._check_all(False))
            picker_buttons.addWidget(select_all)
            picker_buttons.addWidget(clear_all)
            picker_buttons.addStretch(1)
            self.body.addLayout(picker_buttons)
            for section in sections:
                check = QCheckBox(section_label(section))
                check.setProperty("sectionKey", section)
                check.setChecked(True)
                check.toggled.connect(self._update)
                self.body.addWidget(check)
                self.section_checks.append(check)
            self.body.addWidget(self.warning_label)
        self.name_edit.textChanged.connect(self._update)
        self._update()
        self.name_edit.setFocus()

    def _check_all(self, checked: bool) -> None:
        """Checks or unchecks every section box at once."""
        for check in self.section_checks:
            check.setChecked(checked)

    def _chosen_keys(self) -> Tuple[str, ...]:
        """Keys (not labels) of the currently checked section boxes."""
        return tuple(
            check.property("sectionKey")
            for check in self.section_checks
            if check.isChecked()
        )

    def _missing_dependencies(self) -> Tuple[str, ...]:
        """Keys chosen whose dependency (``CATEGORY_DEPENDENCIES``) is not."""
        chosen = set(self._chosen_keys())
        missing = []
        for key in self._chosen_keys():
            for needed in CATEGORY_DEPENDENCIES.get(key, ()):
                if needed not in chosen and needed not in missing:
                    missing.append(needed)
        return tuple(missing)

    def validation_error(self) -> Optional[str]:
        """Returns the first problem with the form, or ``None``."""
        problem = profile_name_problem(self.name_edit.text(), self._existing)
        if problem:
            return problem
        if description_problem(self.description_edit.toPlainText()):
            return description_problem(self.description_edit.toPlainText())
        if self._no_section_chosen():
            return self.tr("Choose at least one section.")
        return None

    def _no_section_chosen(self) -> bool:
        """Whether there are section check boxes and none is checked."""
        return bool(self.section_checks) and not any(
            check.isChecked() for check in self.section_checks
        )

    def _update(self) -> None:
        """Refreshes the error text, the dependency warning and the confirm button."""
        error = self.validation_error()
        typed = bool(self.name_edit.text())
        # Do not scold before the user typed anything.
        shown = (
            error
            if error
            and (
                typed
                or self._no_section_chosen()
                or description_problem(self.description_edit.toPlainText())
            )
            else ""
        )
        self.error_label.setText(shown)
        self.error_label.setVisible(bool(shown))
        self.name_edit.setProperty("invalid", bool(error and typed))
        repolish(self.name_edit)
        if self.section_checks:
            missing = self._missing_dependencies()
            if missing:
                names = ", ".join(section_label(key) for key in missing)
                self.warning_label.setText(
                    self.tr("Also select: {names} (needed by your choices).").format(
                        names=names
                    )
                )
            else:
                chosen = ", ".join(
                    section_label(key) for key in self._chosen_keys()
                ) or self.tr("nothing yet")
                self.warning_label.setText(self.tr("Will include: {names}.").format(
                    names=chosen
                ))
            self.warning_label.setVisible(True)
        self.confirm_button.setEnabled(error is None)

    def values(self) -> Tuple[str, str, Tuple[str, ...]]:
        """Returns what the user entered.

        Returns:
            Tuple[str, str, Tuple[str, ...]]: Name, description and the checked
            section keys (``kongui.core.categories.CATEGORIES`` members, or
            whatever keys were passed in).
        """
        return (
            self.name_edit.text(),
            self.description_edit.toPlainText().strip(),
            self._chosen_keys(),
        )

    def keyPressEvent(self, event) -> None:  # pylint: disable=invalid-name
        """Ignores Enter while the form is invalid."""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
            self.confirm_button.isEnabled()
        ):
            event.ignore()
            return
        super().keyPressEvent(event)


def description_problem(text: str) -> Optional[str]:
    """Returns what is wrong with a profile description, or ``None``.

    Args:
        text: The text typed by the user.

    Returns:
        Optional[str]: A sentence in the interface language when the text is
        longer than :data:`~kongui.core.MAX_DESCRIPTION_CHARS` characters.
    """
    if len(text.strip()) > MAX_DESCRIPTION_CHARS:
        return QCoreApplication.translate(
            "ProfileDialog",
            "The description is too long (at most {limit} characters).",
        ).format(limit=MAX_DESCRIPTION_CHARS)
    return None


class DetailsDialog(BaseDialog):
    """Edits the description of an existing profile."""

    def __init__(
        self, parent: Optional[QWidget], profile_name: str, description: str = ""
    ) -> None:
        """Creates the dialog.

        Args:
            parent: Parent window.
            profile_name: Profile being edited (shown, not editable).
            description: Current description.
        """
        super().__init__(
            parent,
            self.tr("Edit details"),
            self.tr("Save"),
            "primary",
        )
        self.profile_name = profile_name
        self.body.addWidget(Label(profile_name, "h2"))
        self.body.addWidget(Label(self.tr("Description"), "muted"))
        self.description_edit = QPlainTextEdit()
        self.description_edit.setFixedHeight(96)
        self.description_edit.setAccessibleName(self.tr("Profile description"))
        self.description_edit.setPlainText(description)
        self.body.addWidget(self.description_edit)
        self.error_label = Label("", "danger", wrap=True)
        self.body.addWidget(self.error_label)
        self.description_edit.textChanged.connect(self._update)
        self._update()
        self.description_edit.setFocus()

    def _update(self) -> None:
        """Refreshes the error text and the save button."""
        problem = description_problem(self.description_edit.toPlainText())
        self.error_label.setText(problem or "")
        self.error_label.setVisible(bool(problem))
        self.confirm_button.setEnabled(problem is None)

    def value(self) -> str:
        """Returns the text the user typed (surrounding blanks removed)."""
        return self.description_edit.toPlainText().strip()


class SafetyCopiesDialog(BaseDialog):
    """Lists the safety copies made before apply/import and acts on one.

    The dialog never talks to the backend: it asks for the action through the
    ``on_restore`` / ``on_delete`` callbacks and is refilled with
    :meth:`set_copies` (after each operation).
    """

    def __init__(
        self,
        parent: Optional[QWidget],
        on_restore: Callable[[Any], None],
        on_delete: Callable[[Any], None],
    ) -> None:
        """Creates the dialog (empty, in the loading state).

        Args:
            parent: Parent window.
            on_restore: Called with the selected ``SnapshotInfo``.
            on_delete: Called with the selected ``SnapshotInfo``.
        """
        super().__init__(
            parent, self.tr("Safety copies"), self.tr("Restore"), "primary"
        )
        self.cancel_button.setText(self.tr("Close"))
        self.setMinimumWidth(640)
        self._copies: List[Any] = []
        self._on_restore = on_restore
        self._on_delete = on_delete
        self.body.addWidget(
            Label(
                self.tr(
                    "Before applying a profile or importing a file, KonGUI copies "
                    "the files that would be overwritten. They are never deleted "
                    "automatically: delete the ones you no longer need."
                ),
                "muted",
                wrap=True,
            )
        )
        self.list_widget = QListWidget()
        self.list_widget.setAccessibleName(self.tr("Available safety copies"))
        self.list_widget.setMinimumHeight(180)
        self.body.addWidget(self.list_widget)
        self.status_label = Label(self.tr("Loading…"), "muted", wrap=True)
        self.body.addWidget(self.status_label)
        self.delete_button = Button(
            self.tr("Delete"), variant="danger", icon_name="trash"
        )
        self.delete_button.setAccessibleName(self.tr("Delete the selected copy"))
        self.button_row.insertWidget(1, self.delete_button)
        self.confirm_button.clicked.disconnect()
        self.confirm_button.clicked.connect(self._restore)
        self.delete_button.clicked.connect(self._delete)
        self.list_widget.currentRowChanged.connect(lambda _row: self._sync())
        self._busy = False
        self._sync()

    def selected(self) -> Optional[Any]:
        """The highlighted copy, if any."""
        row = self.list_widget.currentRow()
        return self._copies[row] if 0 <= row < len(self._copies) else None

    def set_busy(self, busy: bool) -> None:
        """Locks the buttons while an operation runs."""
        self._busy = busy
        self._sync()

    def set_error(self, lines: Sequence[str]) -> None:
        """Shows why the list could not be read."""
        self._copies = []
        self.list_widget.clear()
        self.status_label.setText(" ".join(lines))
        self._sync()

    def set_copies(self, copies: Sequence[Any]) -> None:
        """Shows the copies (newest first), keeping the selection if possible."""
        previous = self.selected()
        self._copies = list(copies)
        self.list_widget.clear()
        for copy in self._copies:
            when = format_datetime(copy.created)
            if copy.problem:
                text = self.tr("{when}  ·  unreadable: {problem}").format(
                    when=when, problem=copy.problem
                )
            else:
                text = self.tr(
                    "{when}  ·  {what}  ·  {replaced} replaced, {created} created"
                    "  ·  {size}"
                ).format(
                    when=when,
                    what=self._what(copy),
                    replaced=copy.replaced,
                    created=copy.created_files,
                    size=format_kib(copy.size_bytes),
                )
            self.list_widget.addItem(QListWidgetItem(text))
        self.status_label.setText(
            "" if self._copies else self.tr("There are no copies yet.")
        )
        if self._copies:
            row = 0
            if previous is not None:
                row = next(
                    (i for i, c in enumerate(self._copies) if c.id == previous.id), 0
                )
            self.list_widget.setCurrentRow(row)
        self._sync()

    def _what(self, copy: Any) -> str:
        """Says which operation a safety copy was made before."""
        if copy.operation == "apply":
            return self.tr("Before applying “{profile}”").format(profile=copy.profile)
        if copy.operation == "import":
            return self.tr("Before importing “{profile}”").format(profile=copy.profile)
        return self.tr("Before restoring")

    def _sync(self) -> None:
        """Enables the buttons that make sense now."""
        copy = self.selected()
        usable = copy is not None and not self._busy
        self.confirm_button.setEnabled(usable and not copy.problem)
        self.delete_button.setEnabled(usable)

    def _restore(self) -> None:
        """Asks the owner to restore the selected copy."""
        copy = self.selected()
        if copy is not None and not self._busy:
            self._on_restore(copy)

    def _delete(self) -> None:
        """Asks the owner to delete the selected copy."""
        copy = self.selected()
        if copy is not None and not self._busy:
            self._on_delete(copy)
