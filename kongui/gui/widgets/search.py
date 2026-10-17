"""Search box."""

from __future__ import annotations

from typing import Optional

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLineEdit

from kongui.gui import i18n, icons
from kongui.gui.i18n import Text, resolve_text
from kongui.gui.theme import get_theme


class SearchField(QLineEdit):
    """A line edit with a magnifier and a clear button."""

    def __init__(self, placeholder: Optional[Text] = None) -> None:
        """Creates the field.

        Args:
            placeholder: Placeholder text (or a function returning it), also
                used as the accessible name. Defaults to "Search".
        """
        super().__init__()
        self.setObjectName("SearchField")
        self._placeholder: Text = placeholder or (lambda: self.tr("Search"))
        i18n.bind(self, self._apply_placeholder)
        self.setClearButtonEnabled(True)
        self._action = QAction(self)
        self.addAction(self._action, QLineEdit.ActionPosition.LeadingPosition)
        get_theme().changed.connect(self._refresh)
        self._refresh()

    def _apply_placeholder(self) -> None:
        """Sets the placeholder and accessible name in the current language."""
        text = resolve_text(self._placeholder)
        self.setPlaceholderText(text)
        self.setAccessibleName(text)

    def _refresh(self) -> None:
        """Repaints the magnifier."""
        self._action.setIcon(icons.icon("search", get_theme().tokens.muted, 16))
