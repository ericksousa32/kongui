"""Common structure of every page."""

from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from kongui.gui.context import AppContext
from kongui.gui.widgets.common import Label


class Page(QWidget):
    """A scrollable page with a content column.

    Subclasses set :attr:`key`, :attr:`title`, :attr:`subtitle` and
    :attr:`icon_name`, build their content into :attr:`body` and return their
    top-bar buttons from :meth:`header_actions`.
    """

    key = ""
    title = ""
    subtitle = ""
    icon_name = "info"
    MAX_WIDTH = 1180

    def __init__(self, ctx: AppContext) -> None:
        """Creates the page shell.

        Args:
            ctx: Shared services.
        """
        super().__init__()
        self.ctx = ctx
        self.setObjectName("Page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("Content")
        scroll.setWidget(content)
        outer.addWidget(scroll)
        self.scroll = scroll
        self.body = QVBoxLayout(content)
        self.body.setContentsMargins(28, 24, 28, 28)
        self.body.setSpacing(20)

    def header_actions(self) -> List[QWidget]:
        """Returns the buttons for the top bar.

        Returns:
            List[QWidget]: Widgets owned by the page.
        """
        return []

    def on_shown(self) -> None:
        """Called each time the page becomes the current one."""

    def section_title(self, text: str) -> Label:
        """Creates a section heading.

        Args:
            text: Heading text.

        Returns:
            Label: The heading.
        """
        return Label(text, "h2")
