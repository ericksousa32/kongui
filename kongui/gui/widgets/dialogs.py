"""Modal dialogs."""

from __future__ import annotations

from typing import Collection, List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

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
        self.cancel_button = Button("Cancelar")
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
        confirm_text: str = "Confirmar",
        *,
        destructive: bool = False,
        require_text: str = "",
    ) -> None:
        """Creates the dialog.

        Args:
            parent: Parent window.
            title: Heading.
            message: Explanation of what will happen.
            confirm_text: Label of the confirm button.
            destructive: Use the red button style for irreversible actions.
            require_text: Word that must be typed exactly before the confirm
                button is enabled (for the most destructive actions).
        """
        super().__init__(
            parent, title, confirm_text, "danger-solid" if destructive else "primary"
        )
        self.message_label = Label(message, wrap=True)
        self.body.addWidget(self.message_label)
        self.required_text = require_text
        self.confirm_edit: Optional[QLineEdit] = None
        if require_text:
            self.body.addWidget(
                Label(f"Digite {require_text} para confirmar:", "muted")
            )
            self.confirm_edit = QLineEdit()
            self.confirm_edit.setAccessibleName(f"Digite {require_text} para confirmar")
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
        confirm_text: str = "Confirmar",
        *,
        destructive: bool = False,
        require_text: str = "",
    ) -> bool:
        """Shows the dialog and waits.

        Args:
            parent: Parent window.
            title: Heading.
            message: Explanation.
            confirm_text: Label of the confirm button.
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
            allow_replace: Offer "Substituir" (not when a folder or ``.zip``
                with that name is in the way: the original would delete it).
        """
        super().__init__(parent, title, "Usar nome único", "primary")
        self.choice = "cancel"
        self.body.addWidget(Label(message, wrap=True))
        self.replace_button = Button("Substituir", variant="danger-solid")
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
            allow_replace: Offer "Substituir".

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
        title: str = "Salvar perfil atual",
        confirm_text: str = "Salvar",
        ask_details: bool = True,
    ) -> None:
        """Creates the dialog.

        Args:
            parent: Parent window.
            existing_names: Names that cannot be reused.
            sections: Section names offered as check boxes (all start checked).
            title: Heading.
            confirm_text: Label of the confirm button.
            ask_details: Show the description and the section check boxes. Off
                when the backend cannot store them (only the name is asked).
        """
        super().__init__(parent, title, confirm_text, "primary")
        self._existing = set(existing_names)
        self.body.addWidget(Label("Nome", "muted"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Ex.: Trabalho")
        self.name_edit.setAccessibleName("Nome do perfil")
        self.body.addWidget(self.name_edit)
        self.error_label = Label("", "danger", wrap=True)
        self.body.addWidget(self.error_label)
        self.description_edit = QPlainTextEdit()
        self.description_edit.setFixedHeight(64)
        self.description_edit.setAccessibleName("Descrição do perfil")
        self.section_checks: List[QCheckBox] = []
        if ask_details:
            self.body.addWidget(Label("Descrição (opcional)", "muted"))
            self.body.addWidget(self.description_edit)
            self.body.addWidget(Label("O que incluir", "muted"))
            for section in sections:
                check = QCheckBox(section)
                check.setChecked(True)
                check.toggled.connect(self._update)
                self.body.addWidget(check)
                self.section_checks.append(check)
        self.name_edit.textChanged.connect(self._update)
        self._update()
        self.name_edit.setFocus()

    def validation_error(self) -> Optional[str]:
        """Returns the first problem with the form, or ``None``."""
        problem = profile_name_problem(self.name_edit.text(), self._existing)
        if problem:
            return problem
        if self.section_checks and not any(
            check.isChecked() for check in self.section_checks
        ):
            return "Escolha ao menos uma seção."
        return None

    def _update(self) -> None:
        """Refreshes the error text and the confirm button."""
        error = self.validation_error()
        typed = bool(self.name_edit.text())
        # Do not scold before the user typed anything.
        shown = error if error and (typed or "seção" in error) else ""
        self.error_label.setText(shown)
        self.error_label.setVisible(bool(shown))
        self.name_edit.setProperty("invalid", bool(error and typed))
        repolish(self.name_edit)
        self.confirm_button.setEnabled(error is None)

    def values(self) -> Tuple[str, str, Tuple[str, ...]]:
        """Returns what the user entered.

        Returns:
            Tuple[str, str, Tuple[str, ...]]: Name, description and the checked
            sections.
        """
        chosen = tuple(
            check.text() for check in self.section_checks if check.isChecked()
        )
        return (
            self.name_edit.text(),
            self.description_edit.toPlainText().strip(),
            chosen,
        )

    def keyPressEvent(self, event) -> None:  # pylint: disable=invalid-name
        """Ignores Enter while the form is invalid."""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
            self.confirm_button.isEnabled()
        ):
            event.ignore()
            return
        super().keyPressEvent(event)
