"""Editor of the Konsave ``conf.yaml``.

The page edits a *text*. The section editors (``save`` and ``export``) and the
raw text tab are two views of it: a form edit is turned into small changes of
the text (:func:`kongui.core.apply_model`, which keeps comments, unknown keys
and placeholders), and a text edit is read back into the forms. Nothing is
written until the user presses *Salvar*, and only if the original Konsave
reader accepts the text.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPlainTextEdit,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from kongui.core import (
    ConfigConflictError,
    ConfigModel,
    ConfigParseError,
    ConfigValidationError,
    Problem,
    apply_model,
    parse_model,
)
from kongui.gui import messages
from kongui.gui.backend import ConfigCheck, ConfigSnapshot
from kongui.gui.context import AppContext
from kongui.gui.controller import Outcome
from kongui.gui.pages.base import Page
from kongui.gui.widgets.common import (
    Badge,
    Button,
    Card,
    IconTile,
    Label,
    SegmentedControl,
)
from kongui.gui.widgets.confedit import ProblemList, SectionEditor
from kongui.gui.widgets.dialogs import BackupsDialog, ChoiceDialog, ConfirmDialog
from kongui.gui.widgets.feedback import ErrorBanner

LOG = logging.getLogger(__name__)

KINDS = ("save", "export")
#: Wait after the last keystroke in the text tab before validating.
CHECK_DELAY_MS = 350

INTROS = {
    "save": (
        "Arquivos de configuração que entram no perfil quando você o salva, e "
        "que são copiados de volta ao sistema quando você o aplica."
    ),
    "export": (
        "Itens que não ficam no perfil (temas, ícones, fontes…): só vão para o "
        "arquivo .knsv ao exportar e são gravados no sistema ao importar."
    ),
}


class ConfigPage(
    Page
):  # pylint: disable=too-many-instance-attributes,too-many-public-methods
    """Edits ``~/.config/konsave/conf.yaml`` with validation and backups."""

    key = "config"
    title = "Editar .YAML"
    subtitle = "Edite o conf.yaml com validação, backup e restauração"
    icon_name = "file"

    def __init__(self, ctx: AppContext) -> None:
        """Builds the page.

        Args:
            ctx: Shared services.
        """
        super().__init__(ctx)
        self.snapshot: Optional[ConfigSnapshot] = None
        self.model: Optional[ConfigModel] = None
        self.check: Optional[ConfigCheck] = None
        self.loading = False
        self._text = ""
        self._loaded_text = ""
        self._lossy = False
        self._check_text: Optional[str] = None
        self._check_token = 0
        self._load_token = 0
        self._retry: Optional[Tuple[str, str]] = None
        self._building = False

        self._build_status()
        self.error_banner = ErrorBanner("Não foi possível abrir o conf.yaml")
        self.error_banner.retry_requested.connect(self.reload)
        self.error_banner.hide()
        self.body.addWidget(self.error_banner)

        self.content = QWidget()
        content = QVBoxLayout(self.content)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(16)
        self.body.addWidget(self.content)

        self.view_control = SegmentedControl(
            [
                ("save", "Seção save", "save"),
                ("export", "Seção export", "export"),
                ("text", "Texto (YAML)", "file"),
            ]
        )
        self.view_control.set_value("save")
        self.view_control.selected.connect(self._show_view)
        top = QHBoxLayout()
        top.addWidget(self.view_control)
        top.addStretch(1)
        content.addLayout(top)

        self.stack = QStackedWidget()
        self.editors: Dict[str, SectionEditor] = {}
        for kind in KINDS:
            editor = SectionEditor(kind, INTROS[kind])
            editor.changed.connect(
                lambda groups, k=kind: self._on_section_changed(k, groups)
            )
            self.editors[kind] = editor
            self.stack.addWidget(editor)
        self.text_view = QWidget()
        text_column = QVBoxLayout(self.text_view)
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(8)
        text_column.addWidget(
            Label(
                "Edição avançada do arquivo inteiro. Comentários e chaves "
                "desconhecidas ficam como estão; o que for inválido é apontado "
                "abaixo e impede de salvar.",
                "muted",
                wrap=True,
            )
        )
        self.text_edit = QPlainTextEdit()
        self.text_edit.setAccessibleName("Texto do conf.yaml")
        self.text_edit.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        )
        self.text_edit.setMinimumHeight(320)
        self.text_edit.setTabChangesFocus(True)
        text_column.addWidget(self.text_edit, 1)
        self.stack.addWidget(self.text_view)
        content.addWidget(self.stack, 1)

        self.problems = ProblemList()
        self.problems.goto.connect(self.goto_problem)
        content.addWidget(self.problems)

        self.validate_button = Button("Validar agora", icon_name="check")
        self.backups_button = Button("Backups…", icon_name="clock")
        self.discard_button = Button("Descartar alterações", icon_name="x")
        self.save_button = Button("Salvar", variant="primary", icon_name="save")
        self.validate_button.clicked.connect(self.validate_now)
        self.backups_button.clicked.connect(self.open_backups)
        self.discard_button.clicked.connect(self.discard)
        self.save_button.clicked.connect(self.save)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._start_check)
        self.text_edit.textChanged.connect(self._on_text_edited)
        ctx.controller.operation_finished.connect(self._on_outcome)
        ctx.controller.state_changed.connect(self._sync_buttons)
        self._sync_buttons()
        self.content.hide()

    # ------------------------------------------------------------ structure

    def _build_status(self) -> None:
        """Builds the card with the file path and its state."""
        card = Card()
        row = QHBoxLayout(card)
        row.setContentsMargins(20, 16, 20, 16)
        row.setSpacing(14)
        row.addWidget(IconTile("file", 40))
        column = QVBoxLayout()
        column.setSpacing(2)
        self.path_label = Label("conf.yaml", "h2")
        self.state_label = Label("Carregando…", "muted", wrap=True)
        column.addWidget(self.path_label)
        column.addWidget(self.state_label)
        row.addLayout(column, 1)
        self.dirty_badge = Badge("Alterações não salvas", "warning")
        self.dirty_badge.hide()
        row.addWidget(self.dirty_badge)
        self.body.addWidget(card)
        self.notice_label = Label("", "muted", wrap=True)
        self.notice_label.hide()
        self.body.addWidget(self.notice_label)

    def header_actions(self) -> List[QWidget]:
        """Returns the top-bar buttons."""
        return [
            self.validate_button,
            self.backups_button,
            self.discard_button,
            self.save_button,
        ]

    # ------------------------------------------------------------- state

    @property
    def text(self) -> str:
        """The text being edited."""
        return self._text

    @property
    def is_dirty(self) -> bool:
        """Whether the text differs from what is on disk."""
        return self.snapshot is not None and self._text != self._loaded_text

    def _busy(self) -> bool:
        """Whether an operation of the window is running."""
        return self.ctx.controller.busy

    def can_save(self) -> bool:
        """Whether *Salvar* may write: loaded, checked, and without errors."""
        if self.snapshot is None or self._busy():
            return False
        if not (self.is_dirty or not self.snapshot.exists):
            return False
        return (
            self.check is not None and self._check_text == self._text and self.check.ok
        )

    def _sync_buttons(self) -> None:
        """Enables the buttons that make sense now."""
        loaded = self.snapshot is not None
        idle = not self._busy()
        self.save_button.setEnabled(self.can_save())
        self.discard_button.setEnabled(self.is_dirty and idle)
        self.backups_button.setEnabled(loaded and idle)
        self.validate_button.setEnabled(loaded and idle)
        self.dirty_badge.setVisible(self.is_dirty)

    # ------------------------------------------------------------ loading

    def on_shown(self) -> None:
        """Reads the file when the page appears (unless edits are pending)."""
        if not self.is_dirty:
            self.reload()

    def reload(self) -> None:
        """Reads the file from disk again, dropping nothing the user typed.

        Callers that discard edits do so before calling this.
        """
        self._load_token += 1
        token = self._load_token
        self.loading = True
        self.state_label.setText("Carregando…")
        self.error_banner.hide()
        self.ctx.controller.background(
            self.ctx.backend.load_config,
            lambda value, error: self._on_loaded(token, value, error),
        )

    def _on_loaded(
        self,
        token: int,
        snapshot: Optional[ConfigSnapshot],
        error: Optional[BaseException],
    ) -> None:
        """Shows the file that was read."""
        if token != self._load_token:
            return
        self.loading = False
        if error is not None or snapshot is None:
            lines = messages.describe_error(error) if error else ("Erro desconhecido.",)
            self.error_banner.set_content("Não foi possível abrir o conf.yaml", lines)
            self.error_banner.show()
            self.content.hide()
            self.state_label.setText("Erro ao ler o arquivo")
            self._sync_buttons()
            return
        self.snapshot = snapshot
        self._loaded_text = snapshot.text
        self._lossy = False
        self.path_label.setText(snapshot.path)
        count = len(snapshot.backups)
        state = (
            "O arquivo ainda não existe; ao salvar, ele será criado a partir do "
            "modelo padrão."
            if not snapshot.exists
            else "Arquivo em uso pelo Konsave."
        )
        backups = (
            f" {count} {'backup guardado' if count == 1 else 'backups guardados'}."
            if count
            else " Nenhum backup ainda."
        )
        self.state_label.setText(state + backups)
        notice = ""
        if snapshot.sandbox:
            notice = (
                "Modo de demonstração: você está editando uma cópia temporária do "
                "conf.yaml padrão; o arquivo real não é lido nem alterado."
            )
        self.notice_label.setText(notice)
        self.notice_label.setVisible(bool(notice))
        for editor in self.editors.values():
            editor.set_placeholders(snapshot.keywords, snapshot.functions)
        self.error_banner.hide()
        self.content.show()
        self._set_text(snapshot.text, source="load")
        self._start_check()

    # ------------------------------------------------------------ editing

    def _set_text(
        self, text: str, *, source: str, select: Optional[Dict[str, str]] = None
    ) -> None:
        """Adopts a new text and refreshes every view of it.

        Args:
            text: The new text.
            source: ``load``, ``form`` or ``text`` (the view that produced it).
            select: Group to select per section after the refresh.
        """
        self._text = text
        try:
            self.model = parse_model(text)
        except ConfigParseError:
            self.model = None
        if source != "text":
            self._building = True
            try:
                if self.text_edit.toPlainText() != text:
                    self.text_edit.setPlainText(text)
            finally:
                self._building = False
        for kind, editor in self.editors.items():
            editor.set_available(self.model is not None)
            if self.model is not None:
                chosen = (select or {}).get(kind)
                editor.set_groups(self.model.groups(kind), chosen)
        self.check = None
        self.problems.set_pending()
        self._sync_buttons()

    def _on_section_changed(self, kind: str, groups: Tuple[Any, ...]) -> None:
        """Applies an edit made in a section editor to the text."""
        if self.model is None:
            return
        editor = self.editors[kind]
        chosen = editor.pending_select or editor.current_name()
        editor.pending_select = None
        try:
            result = apply_model(self._text, self.model.with_groups(kind, groups))
        except ConfigParseError as error:
            self.ctx.toasts.show_message(
                "error",
                "Não foi possível aplicar a edição",
                " ".join(messages.describe_error(error)),
            )
            editor.set_groups(self.model.groups(kind))
            return
        if not result.preserved:
            self._lossy = True
        self._set_text(
            result.text, source="form", select={kind: chosen} if chosen else None
        )
        self._start_check()

    def _on_text_edited(self) -> None:
        """Reads the typed text back into the forms and re-validates later."""
        if self._building:
            return
        self._set_text(self.text_edit.toPlainText(), source="text")
        self._timer.start(CHECK_DELAY_MS)

    def commit_fields(self) -> None:
        """Applies what is typed in the form fields (before saving)."""
        if self.model is None:
            return
        for editor in self.editors.values():
            editor.commit()

    def _show_view(self, value: str) -> None:
        """Switches between the sections and the text."""
        self.commit_fields()
        self.view_control.set_value(value)
        if value == "text":
            self.stack.setCurrentWidget(self.text_view)
        else:
            self.stack.setCurrentWidget(self.editors[value])

    def show_view(self, value: str) -> None:
        """Shows ``save``, ``export`` or ``text``."""
        self._show_view(value)

    def current_view(self) -> str:
        """Which of ``save``, ``export`` or ``text`` is visible."""
        return self.view_control.value() or "save"

    # ------------------------------------------------------------ checking

    def validate_now(self) -> None:
        """Validates the current text at once."""
        self.commit_fields()
        self._timer.stop()
        self._start_check()

    def _start_check(self) -> None:
        """Validates the current text in the background."""
        if self.snapshot is None:
            return
        self._timer.stop()
        self._check_token += 1
        token = self._check_token
        text = self._text
        self.problems.set_pending()
        self.ctx.controller.background(
            lambda: self.ctx.backend.check_config(text),
            lambda value, error: self._on_checked(token, text, value, error),
        )

    def _on_checked(
        self,
        token: int,
        text: str,
        value: Optional[ConfigCheck],
        error: Optional[BaseException],
    ) -> None:
        """Shows the findings, unless the text moved on meanwhile."""
        if token != self._check_token:
            return
        if error is not None or value is None:
            self.check = None
            self.problems.set_failure(
                messages.describe_error(error) if error else ("Erro desconhecido.",)
            )
            self._sync_buttons()
            return
        self.check = value
        self._check_text = text
        extra: List[Problem] = []
        if self._lossy:
            extra.append(
                Problem(
                    "warning",
                    "comments-lost",
                    (),
                    "comments could not be kept",
                )
            )
        self.problems.set_problems(tuple(value.problems) + tuple(extra))
        for kind, editor in self.editors.items():
            editor.set_resolved(
                {name: path for (k, name), path in value.resolved.items() if k == kind}
            )
        self._sync_buttons()

    # ------------------------------------------------------------ navigation

    def goto_problem(self, problem: Problem) -> None:
        """Shows where a finding is: the form field, or the text line."""
        path = tuple(problem.path)
        if self.model is not None and path and path[0] in KINDS:
            kind = str(path[0])
            self._show_view(kind)
            editor = self.editors[kind]
            if len(path) > 1 and editor.select_group(str(path[1])):
                field = str(path[2]) if len(path) > 2 else "name"
                index = path[3] if len(path) > 3 and isinstance(path[3], int) else None
                editor.focus_field(field, index)
                return
            return
        self._show_view("text")
        line = max((problem.line or 1) - 1, 0)
        block = self.text_edit.document().findBlockByNumber(line)
        cursor = QTextCursor(block)
        cursor.movePosition(
            QTextCursor.MoveOperation.Right,
            QTextCursor.MoveMode.MoveAnchor,
            max((problem.column or 1) - 1, 0),
        )
        self.text_edit.setTextCursor(cursor)
        self.text_edit.setFocus()

    # ------------------------------------------------------------ actions

    def save(self, force: bool = False) -> bool:
        """Writes the file if the text is valid.

        Args:
            force: Write even if the file changed on disk meanwhile.

        Returns:
            bool: Whether a write was started.
        """
        self.commit_fields()
        refusal = self._save_refusal()
        if refusal is not None:
            kind, title, text = refusal
            if title:
                self.ctx.toasts.show_message(kind, title, text)
            return False
        assert self.snapshot is not None
        if self._lossy and not ConfirmDialog.ask(
            self.window(),
            "Salvar sem os comentários?",
            "Esta edição não pôde manter os comentários do arquivo. As chaves "
            "desconhecidas continuam, mas os comentários serão perdidos (o "
            "arquivo anterior fica guardado como backup).",
            "Salvar assim mesmo",
            destructive=True,
        ):
            return False
        self._retry = ("save", self._text)
        return self.ctx.controller.save_config(
            self._text, self.snapshot.digest, force=force
        )

    def _save_refusal(self) -> Optional[Tuple[str, str, str]]:
        """Says why saving must not start now, or ``None`` if it may.

        Returns:
            Optional[Tuple[str, str, str]]: ``(toast kind, title, text)``; an
            empty title means "say nothing".
        """
        if self.snapshot is None:
            return ("info", "", "")
        if self._busy():
            return ("info", "Aguarde", "Outra operação ainda está em andamento.")
        if self.check is None or self._check_text != self._text:
            self.validate_now()
            return ("info", "Verificando o arquivo", "Salve de novo quando terminar.")
        if not self.check.ok:
            return (
                "error",
                "O conf.yaml tem erros e não foi salvo",
                "Corrija os itens em vermelho abaixo. Nada foi gravado.",
            )
        if not (self.is_dirty or not self.snapshot.exists):
            return ("info", "Nada a salvar", "O arquivo já está como você o deixou.")
        return None

    def discard(self, confirm: bool = True) -> bool:
        """Drops the edits and shows the file as it is on disk (cancel).

        Args:
            confirm: Ask first.

        Returns:
            bool: Whether the edits were dropped.
        """
        if not self.is_dirty:
            return False
        if confirm and not ConfirmDialog.ask(
            self.window(),
            "Descartar as alterações?",
            "As alterações feitas aqui, ainda não salvas, serão perdidas. O arquivo "
            "no disco não foi tocado.",
            "Descartar",
            destructive=True,
        ):
            return False
        self._lossy = False
        self._set_text(self._loaded_text, source="load")
        self._start_check()
        return True

    def confirm_leave(self, parent: QWidget) -> bool:
        """Asks before leaving the page (or closing) with unsaved edits."""
        if not self.is_dirty:
            return True
        return ConfirmDialog.ask(
            parent,
            "Sair sem salvar o conf.yaml?",
            "Há alterações não salvas no editor. Se sair agora, elas serão "
            "perdidas; nada foi gravado.",
            "Sair sem salvar",
            destructive=True,
        )

    def open_backups(self) -> None:
        """Lists the backups and offers to restore one."""
        self.ctx.controller.background(
            self.ctx.backend.list_config_backups, self._show_backups
        )

    def _read_backup(self, name: str, on_done) -> None:
        """Reads one backup in the background (for the preview)."""
        self.ctx.controller.background(
            lambda: self.ctx.backend.read_config_backup(name), on_done
        )

    def _show_backups(self, backups, error: Optional[BaseException]) -> None:
        """Opens the backups dialog."""
        if error is not None:
            self.ctx.toasts.show_message(
                "error",
                "Não foi possível listar os backups",
                " ".join(messages.describe_error(error)),
            )
            return
        dialog = BackupsDialog(self.window(), backups, self._read_backup)
        dialog.exec()
        if dialog.chosen:
            self.restore(dialog.chosen)

    def restore(self, name: str, force: bool = False) -> bool:
        """Restores a backup after confirmation.

        Args:
            name: Backup file name.
            force: Write even if the file changed on disk meanwhile.

        Returns:
            bool: Whether a restore was started.
        """
        if self.snapshot is None or self._busy():
            return False
        lost = (
            " As alterações não salvas no editor também serão perdidas."
            if self.is_dirty
            else ""
        )
        if not force and not ConfirmDialog.ask(
            self.window(),
            "Restaurar este backup?",
            "O conf.yaml atual será substituído pelo conteúdo do backup. Uma cópia "
            "do arquivo atual é guardada como novo backup, então dá para voltar."
            + lost,
            "Restaurar",
            destructive=True,
        ):
            return False
        self._retry = ("restore", name)
        return self.ctx.controller.restore_config(
            name, self.snapshot.digest, force=force
        )

    # ------------------------------------------------------------ outcomes

    def _on_outcome(self, outcome: Outcome) -> None:
        """Reacts to a finished write: reload, resolve a conflict, show errors."""
        if outcome.operation not in ("save_config", "restore_config"):
            return
        if outcome.ok:
            self._lossy = False
            self._loaded_text = self._text
            self.reload()
            return
        error = outcome.error
        if isinstance(error, ConfigConflictError):
            self._resolve_conflict()
        elif isinstance(error, ConfigValidationError) and error.report is not None:
            self.check = ConfigCheck(error.report.problems)
            self._check_text = self._text
            self.problems.set_problems(error.report.problems)
            self._sync_buttons()

    def _resolve_conflict(self) -> None:
        """Asks what to do when the file changed on disk after loading."""
        choice = ChoiceDialog.ask(
            self.window(),
            "O conf.yaml mudou no disco",
            "Outro programa alterou o arquivo depois que ele foi aberto aqui. "
            "Você pode recarregar a versão do disco (descartando o que está no "
            "editor), gravar mesmo assim (o arquivo do disco fica guardado como "
            "backup) ou cancelar e decidir depois.",
            [
                ("reload", "Recarregar do disco", "default"),
                ("force", "Gravar mesmo assim", "danger-solid"),
            ],
        )
        if choice == "reload":
            self._lossy = False
            self._set_text(self._loaded_text, source="load")
            self.reload()
        elif choice == "force" and self._retry is not None:
            kind, value = self._retry
            if kind == "save":
                self.save(force=True)
            else:
                self.restore(value, force=True)
