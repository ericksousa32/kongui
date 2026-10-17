"""Common structure of every page."""

from __future__ import annotations

from typing import List

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from kongui.gui import i18n
from kongui.gui.i18n import Text
from kongui.gui.context import AppContext
from kongui.gui.widgets.common import Label


class Page(QWidget):
    """A scrollable page with a content column.

    Subclasses set :attr:`key`, :attr:`icon_name` and the English source texts
    ``TITLE`` and ``SUBTITLE`` (marked with ``QT_TRANSLATE_NOOP`` and the class
    name as context), build their content into :attr:`body` and return their
    top-bar buttons from :meth:`header_actions`. :attr:`title` and
    :attr:`subtitle` give the texts in the current language. When the language
    changes the page calls :meth:`retranslate`, which subclasses override to set
    again any text they built from a function or an f-string.
    """

    key = ""
    TITLE = ""
    SUBTITLE = ""
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
        i18n.bind(self, self.retranslate, now=False)

    @property
    def title(self) -> str:
        """Page title in the current language."""
        return self._translated(self.TITLE)

    @property
    def subtitle(self) -> str:
        """One-line description in the current language (may be empty)."""
        return self._translated(self.SUBTITLE)

    def _translated(self, source: str) -> str:
        """Translates one of the page's own source texts."""
        if not source:
            return ""
        return QCoreApplication.translate(type(self).__name__, source)

    def retranslate(self) -> None:
        """Sets again every text that depends on the language.

        Called when the interface language changes, with the page kept alive:
        what the user typed and the page state are not touched. The default does
        nothing; static texts built with callables follow by themselves.
        """

    def header_actions(self) -> List[QWidget]:
        """Returns the buttons for the top bar.

        Returns:
            List[QWidget]: Widgets owned by the page.
        """
        return []

    def on_shown(self) -> None:
        """Called each time the page becomes the current one."""

    def confirm_leave(self, parent: QWidget) -> bool:
        """Asks whether the user may leave the page (unsaved work).

        Args:
            parent: Window used as dialog parent.

        Returns:
            bool: ``True`` if leaving (or closing the window) is fine.
        """
        del parent
        return True

    def section_title(self, text: Text) -> Label:
        """Creates a section heading.

        Args:
            text: Heading text (or a function returning it, so the heading
                follows language changes).

        Returns:
            Label: The heading.
        """
        return Label(text, "h2")
