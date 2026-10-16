"""Search box."""

from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLineEdit

from kongui.gui import icons
from kongui.gui.theme import get_theme


class SearchField(QLineEdit):
    """A line edit with a magnifier and a clear button."""

    def __init__(self, placeholder: str = "Buscar") -> None:
        """Creates the field.

        Args:
            placeholder: Placeholder text, also used as the accessible name.
        """
        super().__init__()
        self.setObjectName("SearchField")
        self.setPlaceholderText(placeholder)
        self.setAccessibleName(placeholder)
        self.setClearButtonEnabled(True)
        self._action = QAction(self)
        self.addAction(self._action, QLineEdit.ActionPosition.LeadingPosition)
        get_theme().changed.connect(self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        """Repaints the magnifier."""
        self._action.setIcon(icons.icon("search", get_theme().tokens.muted, 16))
