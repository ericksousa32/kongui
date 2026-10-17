"""Modal dialogs."""

from __future__ import annotations

from typing import Any, Callable, Collection, List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt
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

from kongui.gui.validation import group_name_problem, profile_name_problem
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


class ChoiceDialog(BaseDialog):
    """Offers a few named ways forward and a cancel.

    After ``exec()``, :attr:`choice` is the key of the button pressed, or
    ``"cancel"``.
    """

    def __init__(
        self,
        parent: Optional[QWidget],
        title: str,
        message: str,
        choices: Sequence[Tuple[str, str, str]],
    ) -> None:
        """Creates the dialog.

        Args:
            parent: Parent window.
            title: Heading.
            message: Explanation.
            choices: ``(key, label, variant)`` buttons, left to right.
        """
        super().__init__(parent, title, "", "primary")
        self.choice = "cancel"
        self.body.addWidget(Label(message, wrap=True))
        self.confirm_button.hide()
        self.choice_buttons = {}
        for key, label, variant in choices:
            button = Button(label, variant=variant)
            button.clicked.connect(lambda _checked=False, k=key: self._pick(k))
            self.button_row.insertWidget(self.button_row.count() - 1, button)
            self.choice_buttons[key] = button
        self.cancel_button.setFocus()

    def _pick(self, key: str) -> None:
        """Records the choice and closes."""
        self.choice = key
        self.accept()

    @classmethod
    def ask(
        cls,
        parent: Optional[QWidget],
        title: str,
        message: str,
        choices: Sequence[Tuple[str, str, str]],
    ) -> str:
        """Shows the dialog and waits.

        Returns:
            str: The key of the chosen button, or ``cancel``.
        """
        dialog = cls(parent, title, message, choices)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return "cancel"
        return dialog.choice


class GroupNameDialog(BaseDialog):
    """Asks for the name of a new ``save``/``export`` group."""

    def __init__(
        self,
        parent: Optional[QWidget],
        existing: Collection[str],
        *,
        title: str = "Novo grupo",
        confirm_text: str = "Adicionar",
    ) -> None:
        """Creates the dialog.

        Args:
            parent: Parent window.
            existing: Names already used in the section.
            title: Heading.
            confirm_text: Label of the confirm button.
        """
        super().__init__(parent, title, confirm_text, "primary")
        self._existing = set(existing)
        self.body.addWidget(
            Label(
                "O nome do grupo é também o nome da pasta dentro do perfil salvo.",
                "muted",
                wrap=True,
            )
        )
        self.name_edit = QLineEdit()
        self.name_edit.setAccessibleName("Nome do grupo")
        self.name_edit.setPlaceholderText("Ex.: configs")
        self.body.addWidget(self.name_edit)
        self.error_label = Label("", "danger", wrap=True)
        self.body.addWidget(self.error_label)
        self.name_edit.textChanged.connect(self._update)
        self._update()
        self.name_edit.setFocus()

    def _update(self) -> None:
        """Refreshes the error text and the confirm button."""
        error = group_name_problem(self.name_edit.text(), self._existing)
        typed = bool(self.name_edit.text())
        self.error_label.setText(error if error and typed else "")
        self.error_label.setVisible(bool(error and typed))
        self.confirm_button.setEnabled(error is None)

    def keyPressEvent(self, event) -> None:  # pylint: disable=invalid-name
        """Ignores Enter while the name is invalid."""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
            self.confirm_button.isEnabled()
        ):
            event.ignore()
            return
        super().keyPressEvent(event)

    @classmethod
    def ask(cls, parent: Optional[QWidget], existing: Collection[str]) -> Optional[str]:
        """Shows the dialog and waits.

        Returns:
            Optional[str]: The name, or ``None`` if cancelled.
        """
        dialog = cls(parent, existing)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.name_edit.text()


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
        super().__init__(parent, "Cópias de segurança", "Restaurar", "primary")
        self.cancel_button.setText("Fechar")
        self.setMinimumWidth(640)
        self._copies: List[Any] = []
        self._on_restore = on_restore
        self._on_delete = on_delete
        self.body.addWidget(
            Label(
                "Antes de aplicar um perfil ou importar um arquivo, o KonGUI copia "
                "os arquivos que seriam sobrescritos. Elas nunca são apagadas "
                "sozinhas: apague as que não precisa mais.",
                "muted",
                wrap=True,
            )
        )
        self.list_widget = QListWidget()
        self.list_widget.setAccessibleName("Cópias de segurança disponíveis")
        self.list_widget.setMinimumHeight(180)
        self.body.addWidget(self.list_widget)
        self.status_label = Label("Carregando…", "muted", wrap=True)
        self.body.addWidget(self.status_label)
        self.delete_button = Button("Apagar", variant="danger", icon_name="trash")
        self.delete_button.setAccessibleName("Apagar a cópia selecionada")
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
        words = {"apply": "Antes de aplicar", "import": "Antes de importar"}
        for copy in self._copies:
            size = f"{copy.size_bytes / 1024:.1f} KB".replace(".", ",")
            if copy.problem:
                text = f"{copy.created:%d/%m/%Y %H:%M:%S}  ·  ilegível: {copy.problem}"
            else:
                what = words.get(copy.operation, "Antes de restaurar")
                text = (
                    f"{copy.created:%d/%m/%Y %H:%M:%S}  ·  {what}"
                    + (f" “{copy.profile}”" if copy.operation != "restore" else "")
                    + f"  ·  {copy.replaced} substituído(s), "
                    f"{copy.created_files} criado(s)  ·  {size}"
                )
            self.list_widget.addItem(QListWidgetItem(text))
        self.status_label.setText("" if self._copies else "Ainda não há cópias.")
        if self._copies:
            row = 0
            if previous is not None:
                row = next(
                    (i for i, c in enumerate(self._copies) if c.id == previous.id), 0
                )
            self.list_widget.setCurrentRow(row)
        self._sync()

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


class BackupsDialog(BaseDialog):
    """Lists the saved previous versions of ``conf.yaml`` and previews them.

    After ``exec()``, :attr:`chosen` is the backup to restore, or ``None``.
    """

    def __init__(
        self,
        parent: Optional[QWidget],
        backups: Sequence[Any],
        loader: Callable[
            [str, Callable[[Optional[str], Optional[BaseException]], None]], None
        ],
    ) -> None:
        """Creates the dialog.

        Args:
            parent: Parent window.
            backups: ``BackupInfo`` items, newest first.
            loader: ``loader(name, on_done)`` reads a backup in the background
                and calls ``on_done(text, error)`` in the interface thread.
        """
        super().__init__(
            parent, "Backups do conf.yaml", "Restaurar este backup", "primary"
        )
        self.cancel_button.setText("Fechar")
        self.setMinimumWidth(640)
        self.chosen: Optional[str] = None
        self._loader = loader
        self._token = 0
        self._names: List[str] = []
        self.body.addWidget(
            Label(
                "Cada vez que o conf.yaml é salvo ou restaurado, a versão anterior é "
                "guardada ao lado dele. Restaurar também guarda a versão atual.",
                "muted",
                wrap=True,
            )
        )
        self.list_widget = QListWidget()
        self.list_widget.setAccessibleName("Backups disponíveis")
        self.list_widget.setMaximumHeight(150)
        self.body.addWidget(self.list_widget)
        self.empty_label = Label("Ainda não há backups.", "muted")
        self.body.addWidget(self.empty_label)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMinimumHeight(200)
        self.preview.setAccessibleName("Conteúdo do backup")
        self.body.addWidget(self.preview)
        self.status_label = Label("", "danger", wrap=True)
        self.body.addWidget(self.status_label)
        for info in backups:
            size = f"{info.size_bytes / 1024:.1f} KB".replace(".", ",")
            item = QListWidgetItem(
                f"{info.created.strftime('%d/%m/%Y %H:%M:%S')}  ·  {size}  ·  {info.name}"
            )
            self.list_widget.addItem(item)
            self._names.append(info.name)
        self.list_widget.setVisible(bool(self._names))
        self.empty_label.setVisible(not self._names)
        self.preview.setVisible(bool(self._names))
        self.confirm_button.setEnabled(False)
        self.list_widget.currentRowChanged.connect(self._select)
        self.confirm_button.clicked.disconnect()
        self.confirm_button.clicked.connect(self._restore)
        if self._names:
            self.list_widget.setCurrentRow(0)

    def selected_name(self) -> Optional[str]:
        """The backup highlighted in the list, if any."""
        row = self.list_widget.currentRow()
        return self._names[row] if 0 <= row < len(self._names) else None

    def _select(self, row: int) -> None:
        """Loads the preview of the highlighted backup."""
        self._token += 1
        token = self._token
        self.status_label.setText("")
        self.preview.setPlainText("")
        self.confirm_button.setEnabled(False)
        if not 0 <= row < len(self._names):
            return
        name = self._names[row]
        self.preview.setPlainText("Carregando…")
        self._loader(name, lambda text, error: self._loaded(token, text, error))

    def _loaded(
        self, token: int, text: Optional[str], error: Optional[BaseException]
    ) -> None:
        """Shows the preview unless the selection moved on."""
        if token != self._token:
            return
        if error is not None or text is None:
            self.preview.setPlainText("")
            self.status_label.setText(
                "Não foi possível ler este backup: "
                + (str(error) or "erro desconhecido")
            )
            return
        self.preview.setPlainText(text)
        self.confirm_button.setEnabled(True)

    def _restore(self) -> None:
        """Records the backup to restore and closes."""
        self.chosen = self.selected_name()
        if self.chosen is not None:
            self.accept()
