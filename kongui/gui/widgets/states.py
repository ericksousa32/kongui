"""Empty-state placeholder."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from kongui.gui import icons
from kongui.gui.theme import get_theme
from kongui.gui.widgets.common import Button, Label


class EmptyState(QWidget):
    """Icon, title, hint and an optional action, centred.

    Signals:
        action_triggered: Emitted when the action button is clicked.
    """

    action_triggered = Signal()

    def __init__(
        self,
        icon_name: str,
        title: str,
        hint: str,
        action_text: Optional[str] = None,
        action_icon: Optional[str] = None,
    ) -> None:
        """Creates the placeholder.

        Args:
            icon_name: Illustration icon.
            title: Short headline.
            hint: One or two sentences explaining what to do.
            action_text: Label of the action button; no button if ``None``.
            action_icon: Icon of the action button.
        """
        super().__init__()
        self._icon_name = icon_name
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 40, 24, 40)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon = QLabel()
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label = Label(title, "h2")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint_label = Label(hint, "muted", wrap=True)
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint_label.setMinimumWidth(320)
        self.hint_label.setMaximumWidth(420)
        layout.addWidget(self._icon)
        layout.addWidget(self.title_label)
        layout.addWidget(self.hint_label, 0, Qt.AlignmentFlag.AlignHCenter)
        self.action: Optional[Button] = None
        if action_text:
            self.action = Button(action_text, variant="primary", icon_name=action_icon)
            self.action.clicked.connect(self.action_triggered)
            layout.addSpacing(6)
            layout.addWidget(self.action, 0, Qt.AlignmentFlag.AlignHCenter)
        get_theme().changed.connect(self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        """Repaints the illustration with the muted colour."""
        self._icon.setPixmap(
            icons.pixmap(self._icon_name, get_theme().tokens.muted, 48)
        )
