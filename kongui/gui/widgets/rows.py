"""A label + description on the left and a control on the right."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from kongui.gui.i18n import Text
from kongui.gui.widgets.common import Label


class SettingRow(QWidget):
    """One line of a settings or information list."""

    def __init__(self, title: Text, description: Text, control: QWidget) -> None:
        """Creates the row.

        Args:
            title: Main text (a string or a function returning it).
            description: Smaller explanation under the title; may be empty
                (a string or a function returning it).
            control: Widget placed at the right edge.
        """
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 6, 0, 6)
        row.setSpacing(16)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        texts.addWidget(Label(title))
        if description:  # a function is always a non-empty text
            texts.addWidget(Label(description, "caption", wrap=True))
        row.addLayout(texts, 1)
        row.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        self.control = control
