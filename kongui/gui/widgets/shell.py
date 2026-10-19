"""Fixed side navigation and the top bar."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import kongui
from kongui.gui import i18n, icons
from kongui.gui.i18n import Text, resolve_text
from kongui.gui.theme import get_theme
from kongui.gui.widgets.common import Badge, Button, Label


class Sidebar(QFrame):
    """Navigation column with icons and labels, always visible.

    Signals:
        page_requested: Emitted with the page key when a button is clicked.
        theme_toggle_requested: Emitted by the light/dark shortcut button.
    """

    page_requested = Signal(str)
    theme_toggle_requested = Signal()
    WIDTH = 232

    def __init__(self, demo: bool = True) -> None:
        """Creates the empty sidebar; add items with :meth:`add_item`.

        Args:
            demo: Show the "prototype / fictitious data" footer.
        """
        super().__init__()
        self.setObjectName("Sidebar")
        self.setFixedWidth(self.WIDTH)
        self._buttons: Dict[str, QToolButton] = {}
        self._icon_names: Dict[str, str] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 18, 14, 14)
        outer.setSpacing(4)
        brand = QHBoxLayout()
        brand.setContentsMargins(6, 0, 6, 0)
        brand.setSpacing(10)
        mark = QFrame()
        mark.setObjectName("BrandMark")
        mark.setFixedSize(34, 34)
        mark_layout = QHBoxLayout(mark)
        mark_layout.setContentsMargins(0, 0, 0, 0)
        self._mark_icon = QLabel()
        self._mark_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark_layout.addWidget(self._mark_icon)
        brand.addWidget(mark)
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(Label("KonGUI", "brand"))
        names.addWidget(Label(lambda: self.tr("for Konsave"), "caption"))
        brand.addLayout(names, 1)
        outer.addLayout(brand)
        outer.addSpacing(18)

        self._nav = QVBoxLayout()
        self._nav.setSpacing(4)
        outer.addLayout(self._nav)
        outer.addStretch(1)

        footer = QHBoxLayout()
        footer.setContentsMargins(6, 0, 0, 0)
        stack = QVBoxLayout()
        stack.setSpacing(2)
        if demo:
            stack.addWidget(
                Badge(lambda: self.tr("Prototype"), "warning"),
                0,
                Qt.AlignmentFlag.AlignLeft,
            )
            stack.addWidget(
                Label(
                    lambda: self.tr("{version} · fictitious data").format(
                        version=kongui.version_label()
                    ),
                    "caption",
                )
            )
        else:
            stack.addWidget(
                Label(
                    lambda: self.tr("{version} · real profiles").format(
                        version=kongui.version_label()
                    ),
                    "caption",
                )
            )
        footer.addLayout(stack, 1)
        self.theme_button = Button(
            variant="icon",
            icon_name="moon",
            tooltip=lambda: self.tr("Switch between light and dark theme"),
        )
        self.theme_button.clicked.connect(self.theme_toggle_requested)
        footer.addWidget(self.theme_button, 0, Qt.AlignmentFlag.AlignBottom)
        outer.addLayout(footer)

        get_theme().changed.connect(self._refresh)
        self._refresh()

    def add_item(
        self, key: str, label: Text, icon_name: str, shortcut_hint: str = ""
    ) -> None:
        """Adds a navigation button.

        Args:
            key: Page key emitted on click.
            label: Visible text, or a function returning it in the current
                language (the button follows language changes).
            icon_name: Icon name.
            shortcut_hint: Shortcut shown in the tooltip.
        """
        button = QToolButton()
        button.setObjectName("NavButton")
        button.setCheckable(True)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setIconSize(QSize(20, 20))
        button.setFixedHeight(42)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        i18n.bind(button, lambda: self._set_label(button, label, shortcut_hint))
        button.clicked.connect(
            lambda _checked=False, k=key: self.page_requested.emit(k)
        )
        self._group.addButton(button)
        self._nav.addWidget(button)
        self._buttons[key] = button
        self._icon_names[key] = icon_name
        self._refresh()

    @staticmethod
    def _set_label(button: QToolButton, label: Text, shortcut_hint: str) -> None:
        """Sets the text, accessible name and tooltip of a navigation button."""
        text = resolve_text(label)
        button.setText(text)
        button.setAccessibleName(text)
        button.setToolTip(f"{text} ({shortcut_hint})" if shortcut_hint else text)

    def keys(self) -> List[str]:
        """Returns the page keys in display order."""
        return list(self._buttons)

    def button(self, key: str) -> QToolButton:
        """Returns the button of a page.

        Args:
            key: Page key.

        Returns:
            QToolButton: The button.
        """
        return self._buttons[key]

    def current_key(self) -> Optional[str]:
        """Returns the key of the checked button, if any."""
        return next(
            (key for key, button in self._buttons.items() if button.isChecked()), None
        )

    def set_current(self, key: str) -> None:
        """Checks one button without emitting ``page_requested``.

        Args:
            key: Page key.
        """
        self._buttons[key].setChecked(True)

    def _refresh(self) -> None:
        """Repaints icons for the current theme."""
        tokens = get_theme().tokens
        for key, button in self._buttons.items():
            button.setIcon(
                icons.icon(self._icon_names[key], tokens.muted, 20, tokens.accent)
            )
        self._mark_icon.setPixmap(icons.pixmap("profiles", tokens.on_accent, 20))
        self.theme_button.set_icon_name("sun" if tokens.dark else "moon")


class TopBar(QFrame):
    """Page title, subtitle and the contextual actions of the current page."""

    def __init__(self) -> None:
        """Creates the bar."""
        super().__init__()
        self.setObjectName("TopBar")
        self.setFixedHeight(76)
        row = QHBoxLayout(self)
        row.setContentsMargins(28, 0, 28, 0)
        row.setSpacing(16)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addStretch(1)
        self.title_label = Label("", "title")
        self.subtitle_label = Label("", "muted")
        titles.addWidget(self.title_label)
        titles.addWidget(self.subtitle_label)
        titles.addStretch(1)
        row.addLayout(titles, 1)
        self._actions = QHBoxLayout()
        self._actions.setSpacing(8)
        row.addLayout(self._actions)
        self._current: List[QWidget] = []

    def set_page(self, title: str, subtitle: str, actions: Iterable[QWidget]) -> None:
        """Shows a page's title and actions.

        Args:
            title: Page title.
            subtitle: One-line description.
            actions: Widgets (usually buttons) owned by the page.
        """
        self.title_label.setText(title)
        self.subtitle_label.setText(subtitle)
        self.subtitle_label.setVisible(bool(subtitle))
        for widget in self._current:
            self._actions.removeWidget(widget)
            widget.setParent(None)
        self._current = list(actions)
        for widget in self._current:
            self._actions.addWidget(widget)
            widget.show()

    def actions(self) -> Tuple[QWidget, ...]:
        """Returns the action widgets currently shown."""
        return tuple(self._current)
