"""Import / export page. Transfers are simulated."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import PurePath
from typing import List, Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from kongui.gui.actions import SIMULATED
from kongui.gui.context import AppContext
from kongui.gui.formatting import format_size
from kongui.gui.mock_data import SECTIONS
from kongui.gui.pages.base import Page
from kongui.gui.state import Profile
from kongui.gui.validation import profile_name_problem
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
from kongui.gui.widgets.dropzone import DropZone, knsv_paths
from kongui.gui.widgets.grid import ResponsiveGrid
from kongui.gui.widgets.progress import SimulatedTask
from kongui.gui.widgets.states import EmptyState

#: Archive that "already exists" in the fictitious destination, to show the
#: overwrite warning.
FAKE_EXISTING_ARCHIVE = "Minimalista.knsv"
DEFAULT_DESTINATION = "~/Downloads"
RECENT_LIMIT = 5


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


class TransferPage(Page):  # pylint: disable=too-many-instance-attributes
    """Export a profile to a ``.knsv`` file, or import one."""

    key = "transfer"
    title = "Importar / Exportar"
    subtitle = "Leve seus perfis para outro computador ou faça cópias"
    icon_name = "transfer"

    #: Timer ticks and interval of the fake progress; tests lower them.
    STEPS = 16
    STEP_MS = 30

    def __init__(self, ctx: AppContext) -> None:
        """Builds the page.

        Args:
            ctx: Shared services.
        """
        super().__init__(ctx)
        self._import_path: Optional[str] = None
        self._export_task: Optional[SimulatedTask] = None
        self._import_task: Optional[SimulatedTask] = None

        panels = ResponsiveGrid(min_item_width=380, max_columns=2)
        self.export_card = self._build_export()
        self.import_card = self._build_import()
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
        if not ctx.backend.capabilities.transfer:
            self._disable_for_real_backend()
        self._fill_profiles()
        self._update_export_state()
        self._update_import_state()
        self._build_recent()

    def _disable_for_real_backend(self) -> None:
        """Locks both forms: transfer is not wired to the services yet."""
        self.transfer_notice = Label(
            "Importação e exportação ainda não estão disponíveis nesta versão. "
            "Os formulários abaixo são apenas uma prévia.",
            "muted",
            wrap=True,
        )
        self.body.insertWidget(0, self.transfer_notice)
        self.export_card.setEnabled(False)
        self.import_card.setEnabled(False)

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
                "Gera um arquivo .knsv com o perfil escolhido.",
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
        self.preview_label = Label("", "caption", wrap=True)
        form.addWidget(self.preview_label)
        self.overwrite_check = QCheckBox("Substituir se o arquivo já existir")
        form.addWidget(self.overwrite_check)
        self.export_progress = QProgressBar()
        self.export_progress.setTextVisible(False)
        self.export_progress.hide()
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
        self.overwrite_check.toggled.connect(self._update_export_state)
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

    def _on_export_profile_changed(self) -> None:
        """Suggests the file name after the profile changed."""
        name = self.export_combo.currentData()
        self.filename_edit.setText(str(name) if name else "")

    def _choose_destination(self) -> None:
        """Opens the folder picker."""
        chosen = QFileDialog.getExistingDirectory(self, "Pasta de destino")
        if chosen:
            self.destination_edit.setText(chosen)

    def export_target(self) -> str:
        """Returns the archive path that would be written."""
        folder = self.destination_edit.text().strip() or DEFAULT_DESTINATION
        return f"{folder.rstrip('/')}/{self.filename_edit.text().strip()}.knsv"

    def _export_problem(self) -> Optional[str]:
        """Returns why the export form is not valid, if it is not."""
        if not self.export_combo.currentData():
            return "Escolha um perfil."
        if not self.destination_edit.text().strip():
            return "Informe a pasta de destino."
        return profile_name_problem(self.filename_edit.text())

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
        busy = self._export_task is not None and self._export_task.running
        self.export_button.setEnabled(problem is None and not busy)

    def start_export(self) -> bool:
        """Starts the simulated export.

        Returns:
            bool: ``False`` if the form is invalid or the archive "exists" and
            overwriting is off (an error notification is shown in that case).
        """
        if self._export_problem() is not None:
            return False
        target = self.export_target()
        if (
            target.endswith("/" + FAKE_EXISTING_ARCHIVE)
            and not self.overwrite_check.isChecked()
        ):
            self.ctx.toasts.show_message(
                "error",
                "O arquivo já existe",
                f"{FAKE_EXISTING_ARCHIVE} já está em {self.destination_edit.text().strip()}. "
                "Marque “Substituir” ou escolha outro nome.",
            )
            return False
        name = str(self.export_combo.currentData())
        task = SimulatedTask(self.STEPS, self.STEP_MS, self)
        task.progress.connect(self.export_progress.setValue)
        task.finished.connect(lambda: self._export_done(name, target))
        self._export_task = task
        self.export_progress.setValue(0)
        self.export_progress.show()
        self.export_button.setEnabled(False)
        task.start()
        return True

    def _export_done(self, name: str, target: str) -> None:
        """Finishes the simulated export."""
        self.export_progress.hide()
        self._update_export_state()
        self.ctx.activity.add("export", f"“{name}” exportado para {target}")
        self.ctx.toasts.show_message(
            "success", f"“{name}” exportado", f"{target}\n{SIMULATED}"
        )

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
                "Lê um arquivo .knsv e cria um novo perfil.",
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
        self.contents_row = QHBoxLayout()
        self.contents_row.setSpacing(6)
        form.addLayout(self.contents_row)
        form.addWidget(Label("Nome do perfil importado", "muted"))
        self.import_name_edit = QLineEdit()
        self.import_name_edit.setAccessibleName("Nome do perfil importado")
        form.addWidget(self.import_name_edit)
        self.import_error = Label("", "danger", wrap=True)
        form.addWidget(self.import_error)
        self.apply_after_check = QCheckBox("Aplicar o perfil depois de importar")
        form.addWidget(self.apply_after_check)
        self.import_progress = QProgressBar()
        self.import_progress.setTextVisible(False)
        self.import_progress.hide()
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
        """Selects (or clears) the archive to import.

        The file is not opened: the prototype only shows its name and size.

        Args:
            path: Local path ending in ``.knsv``, or ``None`` to clear.

        Returns:
            bool: ``False`` if the path was refused.
        """
        if path is not None and not knsv_paths([path]):
            self._on_drop_rejected()
            return False
        self._import_path = path
        clear_layout(self.contents_row)
        if path:
            stem = PurePath(path).stem
            size = ""
            try:
                size = f" · {format_size(os.stat(path).st_size / 1048576)}"
            except OSError:
                pass
            self.file_label.setText(f"{PurePath(path).name}{size}")
            self.import_name_edit.setText(stem)
            for section in SECTIONS[:4]:
                self.contents_row.addWidget(Badge(section.split(" (", maxsplit=1)[0]))
            self.contents_row.addWidget(Badge("+1"))
            self.contents_row.addStretch(1)
        else:
            self.import_name_edit.clear()
        self._update_import_state()
        return True

    def _import_problem(self) -> Optional[str]:
        """Returns why the import form is not valid, if it is not."""
        if not self._import_path:
            return "Escolha um arquivo."
        return profile_name_problem(
            self.import_name_edit.text(), self.ctx.store.names()
        )

    def _update_import_state(self) -> None:
        """Refreshes visibility and enabled state of the import form."""
        has_file = self._import_path is not None
        self.drop_zone.setVisible(not has_file)
        self.import_form.setVisible(has_file)
        problem = self._import_problem()
        typed = bool(self.import_name_edit.text())
        self.import_error.setText(problem if has_file and problem and typed else "")
        self.import_error.setVisible(bool(has_file and problem and typed))
        self.import_name_edit.setProperty(
            "invalid", bool(has_file and problem and typed)
        )
        repolish(self.import_name_edit)
        busy = self._import_task is not None and self._import_task.running
        self.import_button.setEnabled(problem is None and not busy)

    def start_import(self) -> bool:
        """Starts the simulated import.

        Returns:
            bool: ``False`` if the form is invalid.
        """
        if self._import_problem() is not None:
            return False
        name = self.import_name_edit.text()
        apply_after = self.apply_after_check.isChecked()
        source = PurePath(self._import_path or "").name
        task = SimulatedTask(self.STEPS, self.STEP_MS, self)
        task.progress.connect(self.import_progress.setValue)
        task.finished.connect(lambda: self._import_done(name, source, apply_after))
        self._import_task = task
        self.import_progress.setValue(0)
        self.import_progress.show()
        self.import_button.setEnabled(False)
        task.start()
        return True

    def _import_done(self, name: str, source: str, apply_after: bool) -> None:
        """Finishes the simulated import."""
        self.import_progress.hide()
        profile = Profile(
            name,
            f"Importado de {source}.",
            SECTIONS[:5],
            round(8.0 + 6.1 * 5, 1),
            datetime.now(),
        )
        self.ctx.controller.demo_import(profile, apply_after)
        self.ctx.activity.add("import", f"“{name}” importado de {source}")
        self.ctx.toasts.show_message("success", f"“{name}” importado", SIMULATED)
        self.set_import_file(None)

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
