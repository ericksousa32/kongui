"""Small building blocks used all over the interface."""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Tuple

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
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


#: Horizontal padding (``theme.py``'s ``padding: 2px 9px``, both sides) to
#: leave out of a Badge's elision width, so the shown text does not crowd the
#: rounded background.
_BADGE_HPADDING = 18

#: Extra slack added on top of a text's exact measured advance when asking
#: for room for it (``sizeHint``/``minimumSizeHint``). ``QFontMetrics``'s
#: ``elidedText`` can still elide a string given *exactly* its own advance as
#: the available width (a sub-pixel rounding guard inside Qt), so without
#: this, a badge resized to precisely its own ``sizeHint`` could still show
#: "…" instead of its full text.
_BADGE_SLACK = 2


class Badge(QLabel):
    """A small rounded status label.

    When there is not enough room for the full text (a narrow card, a small
    window), it is elided with "…" instead of being cut off raw mid-word —
    the full text is still available as a tooltip. ``minimumSizeHint`` only
    asks for room for the ellipsis, so a row of several badges shrinks each
    one gracefully instead of overlapping its neighbors.
    """

    def __init__(self, text: Text = "", tone: str = "neutral") -> None:
        """Creates the badge.

        Args:
            text: Badge text, or a function returning it in the current language.
            tone: ``neutral``, ``accent``, ``success``, ``warning`` or ``danger``.
        """
        super().__init__()
        self._full_text = ""
        self._elided_for_width = -1
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setProperty("role", "badge")
        self.setProperty("tone", tone)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if callable(text):
            i18n.bind(self, lambda: self._set_full_text(text()), now=False)
        self._set_full_text(resolve_text(text))

    def _set_full_text(self, text: str) -> None:
        """Stores the untruncated text and re-elides it for the current width."""
        self._full_text = text
        self.setToolTip(text)
        self._apply_elision()

    def _apply_elision(self) -> None:
        """Shows as much of the full text as the current width allows.

        Never ends up fully blank: in a crowded row (several badges sharing
        too little space), Qt's layout can give one less room than even its
        own ``minimumSizeHint`` asked for, which would otherwise elide an
        already-short text (such as "+7") down to nothing at all. The full
        text is always in the tooltip regardless.
        """
        available = self.width() - _BADGE_HPADDING
        metrics = self.fontMetrics()
        if available <= 0:
            shown = self._full_text
        else:
            shown = metrics.elidedText(
                self._full_text, Qt.TextElideMode.ElideRight, available
            )
            if not shown and self._full_text:
                shown = "…"
        super().setText(shown)
        self._elided_for_width = self.width()

    def setText(self, text: str) -> None:  # pylint: disable=invalid-name
        """Like ``QLabel.setText``, but keeps the new text elidable too."""
        self._set_full_text(text)

    def resizeEvent(self, event) -> None:  # pylint: disable=invalid-name
        """Re-elides the text for the new width."""
        super().resizeEvent(event)
        self._apply_elision()

    def paintEvent(self, event: QPaintEvent) -> None:  # pylint: disable=invalid-name
        """Re-elides first if the width has moved since the last computation.

        During a live, interactive window drag, Qt can deliver several resizes
        between two paints (or paint before ``resizeEvent`` has caught up), so
        the text cached by ``resizeEvent`` may no longer match the box actually
        being painted. Re-checking here, right before painting, guarantees the
        shown text is always elided for the real, final width -- never a raw
        mid-word slice with no "…" from an earlier, now-stale width.
        """
        if self.width() != self._elided_for_width:
            self._apply_elision()
        super().paintEvent(event)

    def sizeHint(self) -> QSize:  # pylint: disable=invalid-name
        """Room for the *full* text, from ``self._full_text`` rather than
        whatever is currently displayed — so a badge that is elided today
        still asks for its real width, and grows back once a resize gives a
        crowded row enough room again."""
        height = super().sizeHint().height()
        width = (
            self.fontMetrics().horizontalAdvance(self._full_text)
            + _BADGE_HPADDING
            + _BADGE_SLACK
        )
        return QSize(width, height)

    def minimumSizeHint(self) -> QSize:  # pylint: disable=invalid-name
        """Room for just the ellipsis, so a crowded row can shrink this badge
        instead of overlapping it with its neighbors."""
        height = super().sizeHint().height()
        ellipsis = (
            self.fontMetrics().horizontalAdvance("…") + _BADGE_HPADDING + _BADGE_SLACK
        )
        return QSize(ellipsis, height)

    def set_tone(self, tone: str) -> None:
        """Changes the tone.

        Args:
            tone: New tone.
        """
        self.setProperty("tone", tone)
        repolish(self)


class BadgeRow(QWidget):
    """A row of section badges: at most ``max_shown`` of them, then "+N".

    A plain ``QHBoxLayout`` of badges shrinks every item together once they
    no longer all fit, eliding even the ones that had room to spare. This
    instead lays the badges out in order, each at its full width while there
    is room for it. Badges that do not fit are not squeezed or cut: they are
    left out and counted in a trailing "+N" badge, whose room is reserved
    first so it is never hidden, and whose tooltip lists every label. Only
    when not even the first badge fits next to "+N" is that one elided, so
    the row is never just a counter.
    """

    #: Horizontal gap between badges, matching the old ``QHBoxLayout`` spacing.
    SPACING = 6

    def __init__(self, labels: Sequence[str], max_shown: int = 3) -> None:
        """Creates the row.

        Args:
            labels: Every label, in priority order.
            max_shown: The most badges shown before "+N", whatever the width.
        """
        super().__init__()
        self._labels: List[str] = list(labels)
        self._badges: List[Badge] = []
        for label in self._labels[: max(1, max_shown)]:
            badge = Badge(label)
            badge.setParent(self)
            self._badges.append(badge)
        self._overflow: Optional[Badge] = None
        if len(self._labels) > 1:
            self._overflow = Badge("")
            self._overflow.setParent(self)
            self._overflow.hide()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._laid_out_for_width = -1

    @property
    def overflow(self) -> Optional[Badge]:
        """The "+N" badge, or ``None`` when there is a single label."""
        return self._overflow

    def shown_texts(self) -> List[str]:
        """Texts of the badges currently laid out, "+N" included."""
        if self.width() != self._laid_out_for_width:
            self._relayout()
        texts = [badge.text() for badge in self._badges if not badge.isHidden()]
        if self._overflow is not None and not self._overflow.isHidden():
            texts.append(self._overflow.text())
        return texts

    def _overflow_width(self) -> int:
        """Room for the widest "+N" this row can show."""
        if self._overflow is None:
            return 0
        metrics = self._overflow.fontMetrics()
        return (
            metrics.horizontalAdvance(f"+{len(self._labels)}")
            + _BADGE_HPADDING
            + _BADGE_SLACK
        )

    def _needs_overflow(self, width: int) -> bool:
        """Whether some label must be counted in "+N" at this width."""
        if len(self._badges) < len(self._labels):
            return True
        needed = sum(badge.sizeHint().width() for badge in self._badges)
        needed += self.SPACING * (len(self._badges) - 1)
        return needed > width

    def sizeHint(self) -> QSize:  # pylint: disable=invalid-name
        """Room for the shown badges at full width, plus "+N" if needed."""
        height = max((badge.sizeHint().height() for badge in self._badges), default=0)
        width = sum(badge.sizeHint().width() for badge in self._badges)
        width += self.SPACING * max(0, len(self._badges) - 1)
        if len(self._badges) < len(self._labels):
            width += self.SPACING + self._overflow_width()
        return QSize(width, height)

    def minimumSizeHint(self) -> QSize:  # pylint: disable=invalid-name
        """Room for the first badge elided down to "…", plus "+N"."""
        if not self._badges:
            return QSize(0, 0)
        first = self._badges[0].minimumSizeHint()
        if self._overflow is None:
            return first
        return QSize(
            first.width() + self.SPACING + self._overflow_width(), first.height()
        )

    def resizeEvent(self, event) -> None:  # pylint: disable=invalid-name
        """Re-lays out the badges for the new width."""
        super().resizeEvent(event)
        self._relayout()

    def paintEvent(self, event: QPaintEvent) -> None:  # pylint: disable=invalid-name
        """Re-lays out first if the width has moved since the last pass.

        Closes the same resize/paint race ``Badge.paintEvent`` closes for a
        single badge's text: a live, interactive window drag can deliver a
        paint for a width this row has not relaid out for yet.
        """
        if self.width() != self._laid_out_for_width:
            self._relayout()
        super().paintEvent(event)

    def _relayout(self) -> None:
        """Places full badges in order, then "+N" for whatever is left out."""
        available = self.width()
        height = self.height()
        self._laid_out_for_width = available
        if not self._needs_overflow(available):
            x = 0
            for badge in self._badges:
                width = badge.sizeHint().width()
                badge.setGeometry(x, 0, width, height)
                badge.show()
                x += width + self.SPACING
            if self._overflow is not None:
                self._overflow.hide()
            return
        budget = available - self._overflow_width() - self.SPACING
        x = 0
        shown = 0
        for badge in self._badges:
            width = badge.sizeHint().width()
            if x + width > budget:
                break
            badge.setGeometry(x, 0, width, height)
            badge.show()
            x += width + self.SPACING
            shown += 1
        if shown == 0 and self._badges:
            first = self._badges[0]
            room = max(budget, first.minimumSizeHint().width())
            first.setGeometry(0, 0, room, height)
            first.show()
            x = room + self.SPACING
            shown = 1
        for badge in self._badges[shown:]:
            badge.hide()
        if self._overflow is None:
            return
        self._overflow.setText(f"+{len(self._labels) - shown}")
        # setText resets the tooltip to the text; keep the full list instead.
        self._overflow.setToolTip("\n".join(self._labels))
        width = max(self._overflow.minimumSizeHint().width(), available - x)
        width = min(self._overflow.sizeHint().width(), width)
        self._overflow.setGeometry(x, 0, width, height)
        self._overflow.show()


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


class AppLogo(QWidget):
    """The application icon at a fixed size (side bar, About page).

    It is painted from the packaged icon files, so Qt picks the best one for the
    size and the screen's pixel ratio (sharp at 125 % or 200 %).
    """

    def __init__(self, size: int) -> None:
        """Creates the logo.

        Args:
            size: Side of the logo in pixels.
        """
        super().__init__()
        self.setObjectName("AppLogo")
        self.setFixedSize(size, size)
        self.setAccessibleName("KonGUI")
        self._icon = icons.app_icon()

    def is_empty(self) -> bool:
        """Whether there is no icon to paint (files missing from the package)."""
        return self._icon.isNull()

    def paintEvent(self, event: QPaintEvent) -> None:  # pylint: disable=invalid-name
        """Paints the icon over the whole widget."""
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self._icon.paint(painter, self.rect())
        painter.end()


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
