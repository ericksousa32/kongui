"""Loading and error indicators."""

from __future__ import annotations

from typing import Iterable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QProgressBar, QVBoxLayout

from kongui.gui import i18n
from kongui.gui.widgets.common import Button, Card, IconTile, Label, clear_layout


class BusyBar(QProgressBar):
    """Thin indeterminate bar shown while an operation runs."""

    def __init__(self) -> None:
        """Creates the bar, hidden."""
        super().__init__()
        self.setRange(0, 0)
        self.setTextVisible(False)
        self.setFixedHeight(3)
        i18n.bind(
            self, lambda: self.setAccessibleName(self.tr("Operation in progress"))
        )
        self.hide()

    def set_busy(self, busy: bool) -> None:
        """Shows or hides the bar.

        Args:
            busy: Whether an operation is running.
        """
        self.setVisible(busy)


class WaitBanner(Card):
    """Strip shown while an operation waits for another process's lock.

    Signals:
        cancel_requested: The "cancel wait" button was clicked.
    """

    cancel_requested = Signal()

    def __init__(self) -> None:
        """Creates the banner, hidden."""
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 10, 20, 10)
        row.setSpacing(14)
        row.addWidget(IconTile("clock", 32), 0, Qt.AlignmentFlag.AlignVCenter)
        self._column = QVBoxLayout()
        self._column.setSpacing(2)
        self.title_label = Label("", "h2")
        self._column.addWidget(self.title_label)
        self._lines = QVBoxLayout()
        self._lines.setSpacing(2)
        self._column.addLayout(self._lines)
        row.addLayout(self._column, 1)
        self._cancelling = False
        self.cancel_button = Button(self._cancel_text, variant="danger")
        self.cancel_button.clicked.connect(self.cancel_requested)
        row.addWidget(self.cancel_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.hide()

    def set_waiting(
        self,
        waiting: bool,
        title: str = "",
        lines: Iterable[str] = (),
        *,
        cancelling=False,
    ) -> None:
        """Shows or hides the banner.

        Args:
            waiting: Whether an operation is waiting.
            title: Headline.
            lines: Explanation lines.
            cancelling: The user already asked to stop; the button is disabled.
        """
        self.setVisible(waiting)
        if not waiting:
            return
        self.title_label.setText(title)
        clear_layout(self._lines)
        for line in lines:
            self._lines.addWidget(Label(line, "muted", wrap=True))
        self.cancel_button.setEnabled(not cancelling)
        self._cancelling = cancelling
        self.cancel_button.setText(self._cancel_text())
        self.setAccessibleName(title)

    def _cancel_text(self) -> str:
        """Label of the cancel button for the current state and language."""
        if self._cancelling:
            return self.tr("Cancelling…")
        return self.tr("Cancel wait")


class ErrorBanner(Card):
    """A card that explains a failure and offers to try again.

    Signals:
        retry_requested: The retry button was clicked.
    """

    retry_requested = Signal()

    def __init__(self, title: Optional[str] = None) -> None:
        """Creates the banner, empty.

        Args:
            title: Headline; defaults to "Something went wrong".
        """
        super().__init__()
        title = title or self.tr("Something went wrong")
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
        self.retry_button = Button(lambda: self.tr("Try again"), icon_name="refresh")
        self.retry_button.clicked.connect(self.retry_requested)
        row.addWidget(self.retry_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.setAccessibleName(title)

    def set_title(self, title: str) -> None:
        """Changes only the headline (for example after a language change).

        Args:
            title: Headline; also the accessible name of the banner.
        """
        self.title_label.setText(title)
        self.setAccessibleName(title)

    def set_content(self, title: str, lines: Iterable[str]) -> None:
        """Updates the text.

        Args:
            title: Headline.
            lines: Explanation lines.
        """
        self.set_title(title)
        clear_layout(self._lines)
        for line in lines:
            self._lines.addWidget(Label(line, "muted", wrap=True))
