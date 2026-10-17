"""Import / export page.

Export covers the original options ``-e`` (profile), ``-d`` (folder), ``-n``
(file name) and ``-f`` (what to do when the file exists); import covers ``-i``
(file). The original import takes the profile name from the file name and has
no other option; here the user may pick another name (see
``ServiceBackend.import_profile``) and may apply the profile afterwards.
"""

from __future__ import annotations

import os
from pathlib import PurePath
from typing import List, Optional, Tuple

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QSizePolicy,
    QVBoxLayout,
    QCheckBox,
    QWidget,
)

from kongui.gui import messages
from kongui.gui.backend import ArchiveInfo
from kongui.gui.context import AppContext
from kongui.gui.formatting import format_size
from kongui.gui.pages.base import Page
from kongui.gui.validation import archive_name_problem, profile_name_problem
from kongui.gui.widgets.cards import ActivityRow
from kongui.gui.widgets.common import (
    Badge,
    Button,
    Card,
    IconTile,
    Label,
    Separator,
    clear_layout,
    repolish,
)
from kongui.gui.widgets.dialogs import ConfirmDialog, ConflictDialog
from kongui.gui.widgets.dropzone import DropZone, knsv_paths
from kongui.gui.widgets.feedback import BusyBar
from kongui.gui.widgets.grid import ResponsiveGrid
from kongui.gui.widgets.states import EmptyState

DEFAULT_DESTINATION = "~/Downloads"
RECENT_LIMIT = 5
MAX_BADGES = 3

#: Choices for "if the file already exists": ``(key, label)``.
CONFLICT_CHOICES: Tuple[Tuple[str, str], ...] = (
    ("ask", "Perguntar o que fazer"),
    ("unique", "Criar um nome único"),
    ("overwrite", "Substituir (pede confirmação)"),
)

FOLDER_PROBLEMS = {
    "missing": "A pasta de destino não existe.",
    "not_dir": "O destino não é uma pasta.",
    "not_writable": "Sem permissão de escrita na pasta de destino.",
}


def _short(section: str) -> str:
    """Section name without the explanation in parentheses."""
    return section.split(" (", maxsplit=1)[0]


def _card_header(icon_name: str, title: str, subtitle: str) -> QHBoxLayout:
    """Builds the icon + title row at the top of a card."""
    row = QHBoxLayout()
    row.setSpacing(12)
    row.addWidget(IconTile(icon_name, 40))
    texts = QVBoxLayout()
    texts.setSpacing(0)
    texts.addWidget(Label(title, "h2"))
    texts.addWidget(Label(subtitle, "caption", wrap=True))
    row.addLayout(texts, 1)
    return row


class TransferPage(
    Page
):  # pylint: disable=too-many-instance-attributes,too-many-public-methods
    """Export a profile to a ``.knsv`` file, or import one."""

    key = "transfer"
    title = "Importar / Exportar"
    subtitle = "Leve seus perfis para outro computador ou faça cópias"
    icon_name = "transfer"

    def __init__(self, ctx: AppContext) -> None:
        """Builds the page.

        Args:
            ctx: Shared services.
        """
        super().__init__(ctx)
        self._import_path: Optional[str] = None
        self._archive: Optional[ArchiveInfo] = None
        self._archive_error: Tuple[str, ...] = ()
        self._inspecting = False
        self._probing = False
        self._probe_outcome: Optional[bool] = None
        self._inspect_token = 0

        panels = ResponsiveGrid(min_item_width=380, max_columns=2)
        self.export_card = self._build_export()
        self.import_card = self._build_import()
        for card in (self.export_card, self.import_card):
            # Equal columns whatever the content: only the grid decides the width.
            card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        panels.set_items([self.export_card, self.import_card])
        self.body.addWidget(panels)

        self.recent_card = Card()
        self.recent_layout = QVBoxLayout(self.recent_card)
        self.recent_layout.setContentsMargins(20, 18, 20, 18)
        self.recent_layout.setSpacing(2)
        self.body.addWidget(self.recent_card)
        self.body.addStretch(1)

        ctx.store.changed.connect(self._on_store_changed)
        ctx.activity.changed.connect(self._build_recent)
        ctx.controller.state_changed.connect(self._on_controller_changed)
        ctx.controller.operation_finished.connect(self._on_finished)
        if not ctx.backend.capabilities.transfer:
            self._disable_without_transfer()
        self._fill_profiles()
        self._update_export_state()
        self._update_import_state()
        self._build_recent()

    def _disable_without_transfer(self) -> None:
        """Locks both forms for a backend that cannot transfer."""
        self.transfer_notice = Label(
            "Importação e exportação não estão disponíveis neste modo.",
            "muted",
            wrap=True,
        )
        self.body.insertWidget(0, self.transfer_notice)
        self.export_card.setEnabled(False)
        self.import_card.setEnabled(False)

    # ---- shared -----------------------------------------------------------------

    def _on_controller_changed(self) -> None:
        """Shows the busy bar of the running transfer and locks the buttons."""
        running = self.ctx.controller.current
        operation = running[0] if running else ""
        self.export_progress.set_busy(operation == "export")
        self.import_progress.set_busy(operation == "import")
        self._update_export_state()
        self._update_import_state()

    def _on_finished(self, outcome) -> None:
        """Resets the import form after a successful import."""
        if outcome.operation == "import" and outcome.ok:
            self.set_import_file(None)
        elif outcome.operation == "import":
            self._update_import_state()

    # ---- export -----------------------------------------------------------------

    def _build_export(self) -> Card:
        """Creates the export card."""
        card = Card()
        outer = QVBoxLayout(card)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(10)
        outer.addLayout(
            _card_header(
                "export",
                "Exportar perfil",
                "Gera um arquivo .knsv (o mesmo formato do Konsave) com o perfil escolhido.",
            )
        )
        outer.addWidget(Separator())
        self.export_empty = EmptyState(
            "profiles",
            "Nada para exportar",
            "Crie um perfil primeiro na página Perfis.",
        )
        outer.addWidget(self.export_empty)
        self.export_form = QWidget()
        form = QVBoxLayout(self.export_form)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)
        form.addWidget(Label("Perfil", "muted"))
        self.export_combo = QComboBox()
        self.export_combo.setAccessibleName("Perfil a exportar")
        form.addWidget(self.export_combo)
        form.addWidget(Label("Pasta de destino", "muted"))
        destination = QHBoxLayout()
        self.destination_edit = QLineEdit(DEFAULT_DESTINATION)
        self.destination_edit.setAccessibleName("Pasta de destino")
        self.browse_destination = Button("Escolher…", icon_name="folder")
        destination.addWidget(self.destination_edit, 1)
        destination.addWidget(self.browse_destination)
        form.addLayout(destination)
        form.addWidget(Label("Nome do arquivo (sem extensão)", "muted"))
        self.filename_edit = QLineEdit()
        self.filename_edit.setAccessibleName("Nome do arquivo")
        form.addWidget(self.filename_edit)
        self.filename_error = Label("", "danger", wrap=True)
        form.addWidget(self.filename_error)
        form.addWidget(Label("Se o arquivo já existir", "muted"))
        self.conflict_combo = QComboBox()
        self.conflict_combo.setAccessibleName("Se o arquivo já existir")
        for key, label in CONFLICT_CHOICES:
            self.conflict_combo.addItem(label, key)
        form.addWidget(self.conflict_combo)
        self.preview_label = Label("", "caption", wrap=True)
        form.addWidget(self.preview_label)
        self.export_error = Label("", "danger", wrap=True)
        self.export_error.hide()
        form.addWidget(self.export_error)
        self.export_progress = BusyBar()
        form.addWidget(self.export_progress)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.export_button = Button("Exportar", variant="primary", icon_name="export")
        buttons.addWidget(self.export_button)
        form.addLayout(buttons)
        outer.addWidget(self.export_form)
        outer.addStretch(1)

        self.export_combo.currentIndexChanged.connect(self._on_export_profile_changed)
        self.destination_edit.textChanged.connect(self._update_export_state)
        self.filename_edit.textChanged.connect(self._update_export_state)
        self.conflict_combo.currentIndexChanged.connect(self._update_export_state)
        self.browse_destination.clicked.connect(self._choose_destination)
        self.export_button.clicked.connect(self.start_export)
        return card

    def select_profile(self, name: str) -> bool:
        """Selects a profile in the export form.

        Args:
            name: Profile name.

        Returns:
            bool: ``False`` if the profile is not in the list.
        """
        index = self.export_combo.findData(name)
        if index < 0:
            return False
        self.export_combo.setCurrentIndex(index)
        return True

    def _fill_profiles(self) -> None:
        """Reloads the profile combo, keeping the selection when possible."""
        current = self.export_combo.currentData()
        if current is None:
            active = self.ctx.store.active()
            current = active.name if active else None
        self.export_combo.blockSignals(True)
        self.export_combo.clear()
        for name in self.ctx.store.names():
            self.export_combo.addItem(name, name)
        index = self.export_combo.findData(current)
        self.export_combo.setCurrentIndex(max(0, index))
        self.export_combo.blockSignals(False)
        self._on_export_profile_changed()

    def _on_store_changed(self) -> None:
        """Keeps the profile combo in sync with the store."""
        self._fill_profiles()
        self._update_export_state()
        self._update_import_state()

    def _on_export_profile_changed(self) -> None:
        """Suggests the file name after the profile changed."""
        name = self.export_combo.currentData()
        self.filename_edit.setText(str(name) if name else "")

    def _choose_destination(self) -> None:
        """Opens the folder picker."""
        start = os.path.expanduser(self.destination_edit.text().strip() or "~")
        chosen = QFileDialog.getExistingDirectory(self, "Pasta de destino", start)
        if chosen:
            self.destination_edit.setText(chosen)

    def export_target(self) -> str:
        """Returns the archive path that would be written (plain policy)."""
        folder = self.destination_edit.text().strip() or DEFAULT_DESTINATION
        return f"{folder.rstrip('/')}/{self.filename_edit.text().strip()}.knsv"

    def _export_problem(self) -> Optional[str]:
        """Returns why the export form is not valid, if it is not."""
        if not self.export_combo.currentData():
            return "Escolha um perfil."
        if not self.destination_edit.text().strip():
            return "Informe a pasta de destino."
        return archive_name_problem(self.filename_edit.text())

    def _update_export_state(self) -> None:
        """Refreshes the visibility and enabled state of the export form."""
        has_profiles = bool(self.ctx.store.names())
        self.export_form.setVisible(has_profiles)
        self.export_empty.setVisible(not has_profiles)
        problem = self._export_problem()
        typed = bool(self.filename_edit.text())
        self.filename_error.setText(problem if problem and typed else "")
        self.filename_error.setVisible(bool(problem and typed))
        self.filename_edit.setProperty("invalid", bool(problem and typed))
        repolish(self.filename_edit)
        self.preview_label.setText(
            f"Arquivo final: {self.export_target()}" if not problem else ""
        )
        self.export_error.hide()
        self.export_button.setEnabled(
            problem is None and not self.ctx.controller.busy and not self._probing
        )

    def _export_policy(self, probe) -> Optional[str]:
        """Decides the conflict policy for this export, asking when needed.

        A file is never replaced without an explicit answer, and when nothing
        exists yet the plain ``error`` policy is used so that a file created in
        the meantime is not overwritten silently.

        Args:
            probe: The :class:`~kongui.gui.backend.ExportProbe` of the target.

        Returns:
            Optional[str]: ``error``, ``unique`` or ``overwrite``; ``None`` if
            the user cancelled or the export is not possible.
        """
        choice = str(self.conflict_combo.currentData())
        if not probe.conflict:
            return "unique" if choice == "unique" else "error"
        if choice == "unique":
            return "unique"
        blocked = probe.conflict == "blocked"
        if choice == "overwrite" and blocked:
            self._export_failed(
                "Já existe uma pasta, um .zip ou outro item com esse nome no destino. "
                "O Konsave o apagaria, por isso a substituição foi recusada. "
                "Escolha outro nome ou “Criar um nome único”."
            )
            return None
        window = self.window()
        if choice == "overwrite":
            if ConfirmDialog.ask(
                window,
                "Substituir o arquivo existente?",
                f"{probe.path} já existe e será substituído. O conteúdo antigo "
                "é perdido e não há desfazer.",
                "Substituir",
                destructive=True,
            ):
                return "overwrite"
            return None
        what = (
            "Já existe uma pasta, um .zip ou outro item com esse nome."
            if blocked
            else f"O arquivo {probe.path} já existe."
        )
        answer = ConflictDialog.ask(
            window,
            "O arquivo já existe",
            f"{what}\nNovo nome sugerido: {probe.unique_path}",
            allow_replace=not blocked,
        )
        return None if answer == "cancel" else answer

    def _export_failed(self, text: str) -> None:
        """Shows why an export could not start."""
        self.export_error.setText(text)
        self.export_error.show()
        self.ctx.toasts.show_message(
            "error", "Não foi possível exportar o perfil", text, seconds=0
        )

    def start_export(self) -> bool:
        """Checks the target, asks when something would be replaced, and exports.

        Looking at the output folder touches the disk (a slow or stalled mount
        would freeze the window), so the check runs in the background and the
        rest continues when it is back (:meth:`_on_probed`).

        Returns:
            bool: ``False`` if the form is invalid, another operation (or
            another check) is running, or, when the check finished at once
            (tests, scripts), the folder is unusable or the user cancelled.
            ``True`` if the export started or the check is still running.
        """
        if self._export_problem() is not None:
            return False
        controller = self.ctx.controller
        if controller.busy or self._probing:
            self.ctx.toasts.show_message(
                "info", "Aguarde", "Outra operação ainda está em andamento."
            )
            return False
        name = str(self.export_combo.currentData())
        directory = self.destination_edit.text().strip()
        base = self.filename_edit.text()
        self._probing = True
        self._probe_outcome = None
        self._update_export_state()
        backend = self.ctx.backend
        controller.background(
            lambda: backend.probe_export(directory, base),
            lambda probe, error: self._on_probed(name, directory, base, probe, error),
        )
        return True if self._probe_outcome is None else self._probe_outcome

    def _on_probed(
        self,
        name: str,
        directory: str,
        base: str,
        probe,
        error: Optional[BaseException],
    ) -> None:
        """Continues an export once the output folder has been looked at."""
        self._probing = False
        # Refresh first: it hides the previous error, and the continuation may
        # show a new one (or start the export, which locks the form itself).
        self._update_export_state()
        self._probe_outcome = False
        self._probe_outcome = self._export_after_probe(
            name, directory, base, probe, error
        )

    def _export_after_probe(
        self,
        name: str,
        directory: str,
        base: str,
        probe,
        error: Optional[BaseException],
    ) -> bool:
        """Applies the conflict policy to the probe and starts the export."""
        if error is not None or probe is None:
            self._export_failed(
                " ".join(messages.describe_error(error))
                if error is not None
                else "Não foi possível verificar a pasta de destino."
            )
            return False
        if probe.folder_problem:
            self._export_failed(
                FOLDER_PROBLEMS.get(probe.folder_problem, "Pasta de destino inválida.")
            )
            return False
        policy = self._export_policy(probe)
        if policy is None:
            return False
        started = self.ctx.controller.export_profile(
            name,
            directory,
            base,
            policy,
            confirmed=policy == "overwrite",
        )
        if not started:
            self.ctx.toasts.show_message(
                "info", "Aguarde", "Outra operação ainda está em andamento."
            )
        return started

    # ---- import -----------------------------------------------------------------

    def _build_import(self) -> Card:
        """Creates the import card."""
        card = Card()
        outer = QVBoxLayout(card)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(10)
        outer.addLayout(
            _card_header(
                "import",
                "Importar perfil",
                "Lê um arquivo .knsv do Konsave e cria um novo perfil.",
            )
        )
        outer.addWidget(Separator())
        self.drop_zone = DropZone()
        outer.addWidget(self.drop_zone)
        self.import_form = QWidget()
        form = QVBoxLayout(self.import_form)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)
        file_row = QHBoxLayout()
        self.file_label = Label("", wrap=True)
        self.clear_file_button = Button("Trocar", variant="ghost", icon_name="x")
        file_row.addWidget(self.file_label, 1)
        file_row.addWidget(self.clear_file_button)
        form.addLayout(file_row)
        self.file_error = Label("", "danger", wrap=True)
        form.addWidget(self.file_error)
        self.contents_row = QHBoxLayout()
        self.contents_row.setSpacing(6)
        form.addLayout(self.contents_row)
        self.import_info = Label("", "caption", wrap=True)
        form.addWidget(self.import_info)
        form.addWidget(Label("Nome do perfil importado", "muted"))
        self.import_name_edit = QLineEdit()
        self.import_name_edit.setAccessibleName("Nome do perfil importado")
        form.addWidget(self.import_name_edit)
        self.import_error = Label("", "danger", wrap=True)
        form.addWidget(self.import_error)
        self.apply_after_check = QCheckBox("Aplicar o perfil depois de importar")
        form.addWidget(self.apply_after_check)
        self.import_progress = BusyBar()
        form.addWidget(self.import_progress)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.import_button = Button("Importar", variant="primary", icon_name="import")
        buttons.addWidget(self.import_button)
        form.addLayout(buttons)
        outer.addWidget(self.import_form)
        outer.addStretch(1)

        self.drop_zone.browse_requested.connect(self._choose_file)
        self.drop_zone.file_chosen.connect(self.set_import_file)
        self.drop_zone.file_rejected.connect(self._on_drop_rejected)
        self.clear_file_button.clicked.connect(lambda: self.set_import_file(None))
        self.import_name_edit.textChanged.connect(self._update_import_state)
        self.import_button.clicked.connect(self.start_import)
        return card

    def _choose_file(self) -> None:
        """Opens the file picker."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Escolher arquivo", "", "Perfis Konsave (*.knsv)"
        )
        if path:
            self.set_import_file(path)

    def _on_drop_rejected(self) -> None:
        """Warns about a drop without ``.knsv`` files."""
        self.ctx.toasts.show_message(
            "warning", "Arquivo não suportado", "Solte um arquivo com a extensão .knsv."
        )

    def set_import_file(self, path: Optional[str]) -> bool:
        """Selects (or clears) the archive to import and checks it.

        The file is only read, never extracted: the check runs in the
        background and fills in what the archive holds or why it is unusable.

        Args:
            path: Local path ending in ``.knsv``, or ``None`` to clear.

        Returns:
            bool: ``False`` if the path was refused.
        """
        if path is not None and not knsv_paths([path]):
            self._on_drop_rejected()
            return False
        self._inspect_token += 1
        self._import_path = path
        self._archive = None
        self._archive_error = ()
        self._inspecting = path is not None
        if path:
            self.import_name_edit.setText(PurePath(path).stem)
            token = self._inspect_token
            self.ctx.controller.inspect_archive(
                path, lambda info, error: self._on_inspected(token, info, error)
            )
        else:
            self.import_name_edit.clear()
            self.apply_after_check.setChecked(False)
        self._update_import_state()
        return True

    def _on_inspected(
        self,
        token: int,
        info: Optional[ArchiveInfo],
        error: Optional[BaseException],
    ) -> None:
        """Receives the result of the background check (ignores stale ones)."""
        if token != self._inspect_token:
            return
        self._inspecting = False
        self._archive = info
        self._archive_error = (
            messages.describe_error(error) if error is not None else ()
        )
        self._update_import_state()

    def _import_problem(self) -> Optional[str]:
        """Returns why the import form is not valid, if it is not."""
        if not self._import_path:
            return "Escolha um arquivo."
        if self._inspecting:
            return "Verificando o arquivo…"
        if self._archive_error:
            return " ".join(self._archive_error)
        return profile_name_problem(
            self.import_name_edit.text(), self.ctx.store.names()
        )

    def _fill_contents(self) -> None:
        """Shows what the selected archive holds."""
        clear_layout(self.contents_row)
        info = self._archive
        if info is None:
            self.import_info.setText("")
            return
        names = [_short(section) for section in info.save_sections]
        for name in names[:MAX_BADGES]:
            self.contents_row.addWidget(Badge(name))
        if len(names) > MAX_BADGES:
            self.contents_row.addWidget(Badge(f"+{len(names) - MAX_BADGES}"))
        self.contents_row.addStretch(1)
        if info.export_sections:
            self.import_info.setText(
                "Ao importar, arquivos das seções "
                + ", ".join(_short(name) for name in info.export_sections)
                + " são gravados direto no sistema, sem backup."
            )
        else:
            self.import_info.setText("Este arquivo não grava nada fora dos perfis.")
        if info.warnings:
            self.import_info.setText(
                self.import_info.text()
                + "\n"
                + "\n".join(
                    f"Aviso: {messages.describe_warning(line)}"
                    for line in info.warnings
                )
            )

    def _update_import_state(self) -> None:
        """Refreshes visibility and enabled state of the import form."""
        has_file = self._import_path is not None
        self.drop_zone.setVisible(not has_file)
        self.import_form.setVisible(has_file)
        if has_file:
            size = f" · {format_size(self._archive.size_mb)}" if self._archive else ""
            checking = " · verificando…" if self._inspecting else ""
            self.file_label.setText(
                f"{PurePath(self._import_path or '').name}{size}{checking}"
            )
        self.file_error.setText(" ".join(self._archive_error))
        self.file_error.setVisible(bool(self._archive_error))
        self._fill_contents()
        problem = self._import_problem()
        typed = self.import_name_edit.text()
        name_problem = ""
        if has_file and typed and not self._archive_error and not self._inspecting:
            name_problem = profile_name_problem(typed, self.ctx.store.names()) or ""
        self.import_error.setText(name_problem)
        self.import_error.setVisible(bool(name_problem))
        self.import_name_edit.setProperty("invalid", bool(name_problem))
        repolish(self.import_name_edit)
        self.import_button.setEnabled(problem is None and not self.ctx.controller.busy)

    def start_import(self) -> bool:
        """Asks for confirmation and imports the selected archive.

        Importing writes files into the live system, so it always asks.

        Returns:
            bool: ``True`` if an import was started. ``False`` if the form is
            invalid, the user declined, or another operation is running.
        """
        if self._import_problem() is not None or self._import_path is None:
            return False
        name = self.import_name_edit.text()
        apply_after = self.apply_after_check.isChecked()
        info = self._archive
        writes = (
            "Os arquivos das seções "
            + ", ".join(_short(name) for name in info.export_sections)
            + " serão "
            if info and info.export_sections
            else "Os arquivos do perfil serão "
        )
        demo = self.ctx.backend.capabilities.demo
        if not ConfirmDialog.ask(
            self.window(),
            f"Importar “{name}”?",
            f"{writes}gravados no sistema, substituindo os atuais, sem backup. "
            "O perfil também será salvo na sua lista."
            + (" O perfil será aplicado em seguida." if apply_after else "")
            + (" (Protótipo: nada será alterado.)" if demo else ""),
            "Importar",
            destructive=True,
        ):
            return False
        started = self.ctx.controller.import_profile(
            self._import_path, name, apply_after, confirmed=True
        )
        if not started:
            self.ctx.toasts.show_message(
                "info", "Aguarde", "Outra operação ainda está em andamento."
            )
        return started

    # ---- recent -----------------------------------------------------------------

    def _build_recent(self) -> None:
        """Rebuilds the list of recent transfers."""
        clear_layout(self.recent_layout)
        self.recent_layout.addWidget(self.section_title("Transferências recentes"))
        rows: List = [
            entry
            for entry in self.ctx.activity.entries()
            if entry.kind in ("export", "import")
        ][:RECENT_LIMIT]
        if not rows:
            self.recent_layout.addWidget(Label("Nenhuma transferência ainda.", "muted"))
            return
        for entry in rows:
            self.recent_layout.addWidget(ActivityRow(entry))


__all__ = ["TransferPage"]
