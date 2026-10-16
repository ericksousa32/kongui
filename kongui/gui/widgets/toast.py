"""Transient notifications shown over the window."""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from kongui.gui import icons
from kongui.gui.theme import get_theme
from kongui.gui.widgets.common import Button, Label, repolish

_KIND_ICON = {"success": "check", "info": "info", "warning": "warning", "error": "x"}


class Toast(QFrame):
    """One notification card."""

    def __init__(self, kind: str, title: str, text: str = "") -> None:
        """Creates the toast.

        Args:
            kind: ``success``, ``info``, ``warning`` or ``error``.
            title: Bold first line.
            text: Optional second line.

        Raises:
            ValueError: If ``kind`` is unknown.
        """
        super().__init__()
        if kind not in _KIND_ICON:
            raise ValueError(f"unknown toast kind: {kind!r}")
        self.kind = kind
        self.title = title
        self.setObjectName("Toast")
        self.setProperty("kind", kind)
        self.setAccessibleName(f"{title}. {text}".strip())
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 12, 8, 12)
        row.setSpacing(10)
        self._icon = QLabel()
        row.addWidget(self._icon, 0)
        column = QVBoxLayout()
        column.setSpacing(2)
        column.addWidget(Label(title, "h2"))
        if text:
            column.addWidget(Label(text, "muted", wrap=True))
        row.addLayout(column, 1)
        self.close_button = Button(
            variant="icon", icon_name="x", tooltip="Fechar", icon_size=14
        )
        row.addWidget(self.close_button, 0)
        get_theme().changed.connect(self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        """Repaints the kind icon."""
        tokens = get_theme().tokens
        color = {
            "success": tokens.success,
            "warning": tokens.warning,
            "error": tokens.danger,
            "info": tokens.accent,
        }[self.kind]
        self._icon.setPixmap(icons.pixmap(_KIND_ICON[self.kind], color, 22))
        repolish(self)


class ToastHost(QWidget):
    """Stacks toasts in the bottom-right corner of its parent widget."""

    WIDTH = 360
    MARGIN = 20
    MAX_VISIBLE = 4

    def __init__(self, parent: QWidget, default_seconds: int = 5) -> None:
        """Creates the host.

        Args:
            parent: Widget the toasts float over.
            default_seconds: How long a toast stays when not specified.
        """
        super().__init__(parent)
        self.default_seconds = default_seconds
        self._toasts: List[Toast] = []
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(10)
        parent.installEventFilter(self)
        self.hide()

    def show_message(
        self, kind: str, title: str, text: str = "", seconds: Optional[float] = None
    ) -> Toast:
        """Shows a notification.

        Args:
            kind: ``success``, ``info``, ``warning`` or ``error``.
            title: Bold first line.
            text: Optional second line.
            seconds: Time on screen; ``0`` keeps it until closed. Defaults to
                :attr:`default_seconds`.

        Returns:
            Toast: The created toast.
        """
        toast = Toast(kind, title, text)
        toast.close_button.clicked.connect(lambda: self.dismiss(toast))
        while len(self._toasts) >= self.MAX_VISIBLE:
            self.dismiss(self._toasts[0])
        self._toasts.append(toast)
        self._layout.addWidget(toast)
        duration = self.default_seconds if seconds is None else seconds
        if duration > 0:
            # Owned by the toast, so it dies with it and never fires on a deleted host.
            timer = QTimer(toast)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda: self.dismiss(toast))
            timer.start(int(duration * 1000))
        self.show()
        self.raise_()
        self._reposition()
        return toast

    def dismiss(self, toast: Toast) -> None:
        """Closes one toast (no effect if already closed).

        Args:
            toast: The toast to close.
        """
        if toast not in self._toasts:
            return
        self._toasts.remove(toast)
        self._layout.removeWidget(toast)
        toast.hide()
        toast.setParent(None)
        toast.deleteLater()
        if not self._toasts:
            self.hide()
        self._reposition()

    def dismiss_all(self) -> None:
        """Closes every toast."""
        for toast in list(self._toasts):
            self.dismiss(toast)

    def titles(self) -> List[str]:
        """Returns the titles of the visible toasts, oldest first."""
        return [toast.title for toast in self._toasts]

    def kinds(self) -> List[str]:
        """Returns the kinds of the visible toasts, oldest first."""
        return [toast.kind for toast in self._toasts]

    def eventFilter(
        self, watched: QObject, event: QEvent
    ) -> bool:  # pylint: disable=invalid-name
        """Keeps the stack anchored when the parent is resized."""
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self._reposition()
        return False

    def _reposition(self) -> None:
        """Anchors the stack to the bottom-right corner."""
        parent = self.parentWidget()
        if parent is None or not self._toasts:
            return
        width = min(self.WIDTH, max(200, parent.width() - 2 * self.MARGIN))
        self.setFixedWidth(width)
        # Measured by hand: the layout's cached hint is stale right after a change,
        # and wrapped labels need the width to know their height.
        height = self._layout.spacing() * (len(self._toasts) - 1)
        for toast in self._toasts:
            toast.ensurePolished()
            hinted = toast.heightForWidth(width)
            height += max(toast.sizeHint().height(), hinted if hinted > 0 else 0)
        self.setFixedHeight(height)
        self.move(
            parent.width() - width - self.MARGIN, parent.height() - height - self.MARGIN
        )
