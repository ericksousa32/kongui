"""Loading and error indicators."""

from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QProgressBar, QVBoxLayout

from kongui.gui.widgets.common import Button, Card, IconTile, Label, clear_layout


class BusyBar(QProgressBar):
    """Thin indeterminate bar shown while an operation runs."""

    def __init__(self) -> None:
        """Creates the bar, hidden."""
        super().__init__()
        self.setRange(0, 0)
        self.setTextVisible(False)
        self.setFixedHeight(3)
        self.setAccessibleName("Operação em andamento")
        self.hide()

    def set_busy(self, busy: bool) -> None:
        """Shows or hides the bar.

        Args:
            busy: Whether an operation is running.
        """
        self.setVisible(busy)


class ErrorBanner(Card):
    """A card that explains a failure and offers to try again.

    Signals:
        retry_requested: The retry button was clicked.
    """

    retry_requested = Signal()

    def __init__(self, title: str = "Algo deu errado") -> None:
        """Creates the banner, empty.

        Args:
            title: Headline.
        """
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 16, 20, 16)
        row.setSpacing(14)
        row.addWidget(IconTile("warning", 40), 0, Qt.AlignmentFlag.AlignTop)
        self._column = QVBoxLayout()
        self._column.setSpacing(4)
        self.title_label = Label(title, "h2")
        self._column.addWidget(self.title_label)
        self._lines = QVBoxLayout()
        self._lines.setSpacing(2)
        self._column.addLayout(self._lines)
        row.addLayout(self._column, 1)
        self.retry_button = Button("Tentar novamente", icon_name="refresh")
        self.retry_button.clicked.connect(self.retry_requested)
        row.addWidget(self.retry_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.setAccessibleName(title)

    def set_content(self, title: str, lines: Iterable[str]) -> None:
        """Updates the text.

        Args:
            title: Headline.
            lines: Explanation lines.
        """
        self.title_label.setText(title)
        clear_layout(self._lines)
        for line in lines:
            self._lines.addWidget(Label(line, "muted", wrap=True))
        self.setAccessibleName(title)
