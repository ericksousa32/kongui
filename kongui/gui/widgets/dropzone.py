"""Drop target for ``.knsv`` files."""

from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from kongui.gui import i18n, icons
from kongui.gui.theme import get_theme
from kongui.gui.widgets.common import Button, Label, repolish

EXTENSION = ".knsv"


def knsv_paths(paths: List[str]) -> List[str]:
    """Keeps the paths that end in ``.knsv`` (case-insensitive).

    Args:
        paths: Local file paths.

    Returns:
        List[str]: The accepted paths, in order.
    """
    return [path for path in paths if path.lower().endswith(EXTENSION)]


class DropZone(QFrame):
    """Dashed area that accepts dragged files or a click on its button.

    Signals:
        file_chosen: A ``.knsv`` path was dropped.
        file_rejected: A drop contained no ``.knsv`` file.
        browse_requested: The "choose file" button was clicked.
    """

    file_chosen = Signal(str)
    file_rejected = Signal()
    browse_requested = Signal()

    def __init__(self) -> None:
        """Creates the drop zone."""
        super().__init__()
        self.setObjectName("DropZone")
        self.setProperty("dragging", False)
        self.setAcceptDrops(True)
        i18n.bind(
            self,
            lambda: self.setAccessibleName(self.tr("Area to drop a .knsv file")),
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 26, 20, 26)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon = QLabel()
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon)
        title = Label(lambda: self.tr("Drag a .knsv file here"), "h2")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        or_label = Label(lambda: self.tr("or"), "muted")
        or_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(or_label)
        self.browse_button = Button(lambda: self.tr("Choose file…"), icon_name="folder")
        self.browse_button.clicked.connect(self.browse_requested)
        layout.addWidget(self.browse_button, 0, Qt.AlignmentFlag.AlignHCenter)
        get_theme().changed.connect(self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        """Repaints the illustration."""
        self._icon.setPixmap(icons.pixmap("import", get_theme().tokens.muted, 36))

    def _set_dragging(self, dragging: bool) -> None:
        """Highlights the zone while a drag hovers it."""
        self.setProperty("dragging", dragging)
        repolish(self)

    def dragEnterEvent(
        self, event: QDragEnterEvent
    ) -> None:  # pylint: disable=invalid-name
        """Accepts drags that carry local files."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_dragging(True)
        else:
            event.ignore()

    def dragLeaveEvent(
        self, event: QDragLeaveEvent
    ) -> None:  # pylint: disable=invalid-name
        """Removes the highlight."""
        self._set_dragging(False)
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:  # pylint: disable=invalid-name
        """Emits the first dropped ``.knsv`` file."""
        self._set_dragging(False)
        paths = [
            url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()
        ]
        accepted = knsv_paths(paths)
        if accepted:
            event.acceptProposedAction()
            self.file_chosen.emit(accepted[0])
        else:
            event.ignore()
            self.file_rejected.emit()
