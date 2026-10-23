"""Small building blocks used all over the interface."""

from __future__ import annotations

from typing import Iterable, List, Optional, Tuple

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QWidget,
)

from kongui.gui import i18n, icons
from kongui.gui.i18n import Text, resolve_text
from kongui.gui.theme import get_theme

#: Font scale of each label role, relative to the application font.
_ROLE_SCALE = {
    "title": 1.55,
    "h2": 1.18,
    "stat": 1.9,
    "brand": 1.25,
    "caption": 0.9,
    "badge": 0.85,
}
_BOLD_ROLES = {"title", "h2", "stat", "brand"}


def repolish(widget: QWidget) -> None:
    """Re-applies the stylesheet after a dynamic property changed.

    Args:
        widget: The widget whose properties changed.
    """
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def clear_layout(layout: QLayout) -> None:
    """Removes and deletes everything inside a layout, nested layouts included.

    Args:
        layout: The layout to empty. The layout itself is kept.
    """
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child = item.layout()
        if widget is not None:
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        elif child is not None:
            clear_layout(child)
            child.deleteLater()


class Label(QLabel):
    """A label with a typographic role (``title``, ``h2``, ``muted`` ...)."""

    def __init__(
        self,
        text: Text = "",
        role: str = "body",
        *,
        wrap: bool = False,
        plain: bool = False,
    ) -> None:
        """Creates the label.

        Args:
            text: Label text, or a function returning it in the current
                language (re-evaluated when the language changes).
            role: One of ``body``, ``muted``, ``caption``, ``title``, ``h2``,
                ``stat``, ``brand``, ``danger``.
            wrap: Whether long text wraps.
            plain: Show the text exactly as given. Without it Qt may read
                ``<b>`` or ``<img>`` in the text as markup; use it for anything
                a user typed or an archive supplied.
        """
        super().__init__(resolve_text(text))
        if plain:
            self.setTextFormat(Qt.TextFormat.PlainText)
        if callable(text):
            i18n.bind(self, lambda: self.setText(text()), now=False)
        self.setProperty("role", role)
        self.setWordWrap(wrap)
        font = QFont(self.font())
        scale = _ROLE_SCALE.get(role)
        if scale and font.pointSizeF() > 0:
            font.setPointSizeF(font.pointSizeF() * scale)
        if role in _BOLD_ROLES:
            font.setWeight(QFont.Weight.DemiBold)
        self.setFont(font)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)


class Badge(QLabel):
    """A small rounded status label."""

    def __init__(self, text: Text = "", tone: str = "neutral") -> None:
        """Creates the badge.

        Args:
            text: Badge text, or a function returning it in the current language.
            tone: ``neutral``, ``accent``, ``success``, ``warning`` or ``danger``.
        """
        super().__init__(resolve_text(text))
        if callable(text):
            i18n.bind(self, lambda: self.setText(text()), now=False)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setProperty("role", "badge")
        self.setProperty("tone", tone)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_tone(self, tone: str) -> None:
        """Changes the tone.

        Args:
            tone: New tone.
        """
        self.setProperty("tone", tone)
        repolish(self)


class Button(QPushButton):
    """A push button with a visual variant and an optional themed icon."""

    VARIANTS = (
        "default",
        "primary",
        "ghost",
        "danger",
        "danger-solid",
        "icon",
        "segment",
    )

    def __init__(
        self,
        text: Text = "",
        *,
        variant: str = "default",
        icon_name: Optional[str] = None,
        tooltip: Text = "",
        icon_size: int = 18,
    ) -> None:
        """Creates the button.

        Args:
            text: Button label (or a function returning it in the current
                language); empty for icon-only buttons.
            variant: One of :attr:`VARIANTS`.
            icon_name: Name from :data:`kongui.gui.icons.ICON_NAMES`.
            tooltip: Tooltip (or a function returning it), also used as the
                accessible name when there is no text.
            icon_size: Icon size in pixels.

        Raises:
            ValueError: If ``variant`` is unknown.
        """
        super().__init__(resolve_text(text))
        if variant not in self.VARIANTS:
            raise ValueError(f"unknown button variant: {variant!r}")
        self._variant = variant
        self._icon_name = icon_name
        self.setProperty("variant", variant)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._icon_size = icon_size
        self.setIconSize(QSize(icon_size, icon_size))
        self._text = text
        self._tooltip = tooltip
        self._apply_texts()
        if callable(text) or callable(tooltip):
            i18n.bind(self, self._apply_texts, now=False)
        get_theme().changed.connect(self._refresh_icon)
        self._refresh_icon()

    def _apply_texts(self) -> None:
        """Sets the label, tooltip and accessible name in the current language."""
        if callable(self._text):
            self.setText(self._text())
        tip = resolve_text(self._tooltip)
        if tip:
            self.setToolTip(tip)
            if not resolve_text(self._text):
                self.setAccessibleName(tip)

    def set_icon_name(self, name: Optional[str]) -> None:
        """Changes the icon.

        Args:
            name: New icon name, or ``None`` to remove it.
        """
        self._icon_name = name
        self._refresh_icon()

    def _icon_color(self) -> QColor:
        """Chooses the icon colour for the variant."""
        tokens = get_theme().tokens
        if self._variant == "primary":
            return tokens.on_accent
        if self._variant == "danger":
            return tokens.danger
        if self._variant == "danger-solid":
            return QColor("#ffffff")
        return tokens.text

    def _refresh_icon(self) -> None:
        """Rebuilds the icon with the current theme colours."""
        if not self._icon_name:
            self.setIcon(QIcon())
            return
        tokens = get_theme().tokens
        checked = (
            tokens.accent
            if self._variant in ("segment", "ghost")
            else self._icon_color()
        )
        self.setIcon(
            icons.icon(self._icon_name, self._icon_color(), self._icon_size, checked)
        )


class Card(QFrame):
    """A rounded surface that groups related content."""

    def __init__(self, *, hoverable: bool = False) -> None:
        """Creates the card.

        Args:
            hoverable: Highlight the border on mouse over.
        """
        super().__init__()
        self.setObjectName("Card")
        self.setProperty("hoverable", hoverable)
        self.setProperty("active", False)
        self.setFrameShape(QFrame.Shape.NoFrame)

    def set_active(self, active: bool) -> None:
        """Marks the card as the highlighted one.

        Args:
            active: Whether to draw the accent border.
        """
        self.setProperty("active", active)
        repolish(self)


class IconTile(QFrame):
    """A rounded square with a centred, accent-coloured icon."""

    def __init__(self, icon_name: str, size: int = 40) -> None:
        """Creates the tile.

        Args:
            icon_name: Icon to show.
            size: Side of the tile in pixels.
        """
        super().__init__()
        self.setObjectName("IconTile")
        self.setFixedSize(size, size)
        self._icon_name = icon_name
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)
        get_theme().changed.connect(self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        """Repaints the icon with the current accent."""
        self._label.setPixmap(
            icons.pixmap(self._icon_name, get_theme().tokens.accent, 22)
        )

    def set_icon_name(self, name: str) -> None:
        """Changes the icon.

        Args:
            name: New icon name.
        """
        self._icon_name = name
        self._refresh()


class Separator(QFrame):
    """A one-pixel horizontal rule."""

    def __init__(self) -> None:
        """Creates the rule."""
        super().__init__()
        self.setObjectName("Separator")
        self.setFixedHeight(1)


class SegmentedControl(QWidget):
    """Mutually exclusive buttons side by side (for example grid / list).

    Signals:
        selected: Emitted with the value of the button the user picked.
    """

    selected = Signal(str)

    def __init__(self, options: Iterable[Tuple[str, Text, Optional[str]]]) -> None:
        """Creates the control.

        Args:
            options: ``(value, label, icon_name)`` tuples, in order; ``label`` is
                a string or a function returning it in the current language.
        """
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict = {}
        items: List[Tuple[str, Text, Optional[str]]] = list(options)
        for index, (value, label, icon_name) in enumerate(items):
            button = Button(
                label, variant="segment", icon_name=icon_name, tooltip=label
            )
            button.setCheckable(True)
            position = (
                "only"
                if len(items) == 1
                else (
                    "first"
                    if index == 0
                    else "last" if index == len(items) - 1 else "middle"
                )
            )
            button.setProperty("segpos", position)
            button.clicked.connect(
                lambda _checked=False, v=value: self.selected.emit(v)
            )
            self._group.addButton(button)
            layout.addWidget(button)
            self._buttons[value] = button

    def value(self) -> Optional[str]:
        """Returns the selected value, if any."""
        for value, button in self._buttons.items():
            if button.isChecked():
                return value
        return None

    def set_value(self, value: str) -> None:
        """Selects a value without emitting ``selected``.

        Args:
            value: One of the option values.

        Raises:
            KeyError: If the value is not an option.
        """
        self._buttons[value].setChecked(True)

    def button(self, value: str) -> Button:
        """Returns the button of one option.

        Args:
            value: Option value.

        Returns:
            Button: The button.
        """
        return self._buttons[value]
