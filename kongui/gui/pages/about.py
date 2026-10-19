"""About page."""

from __future__ import annotations

import platform
from typing import Dict, List, Tuple

import PySide6
from PySide6.QtCore import QT_TRANSLATE_NOOP, Qt, QUrl, qVersion
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout

import kongui
from kongui.gui.context import AppContext
from kongui.gui.i18n import Text, resolve_text
from kongui.gui.pages.base import Page
from kongui.gui.widgets.common import Badge, Button, Card, IconTile, Label, Separator
from kongui.gui.widgets.rows import SettingRow

REPOSITORY_URL = "https://github.com/ericksousa32/kongui"
KONSAVE_URL = "https://github.com/prayag2/konsave"


class AboutPage(Page):
    """Version, credits and environment."""

    key = "about"
    TITLE = QT_TRANSLATE_NOOP("AboutPage", "About")
    SUBTITLE = QT_TRANSLATE_NOOP("AboutPage", "Information about the application")
    icon_name = "info"

    def __init__(self, ctx: AppContext) -> None:
        """Builds the page.

        Args:
            ctx: Shared services.
        """
        super().__init__(ctx)
        hero = Card()
        row = QHBoxLayout(hero)
        row.setContentsMargins(24, 22, 24, 22)
        row.setSpacing(18)
        row.addWidget(IconTile("profiles", 64))
        texts = QVBoxLayout()
        texts.setSpacing(2)
        heading = QHBoxLayout()
        heading.addWidget(Label("KonGUI", "title"))
        heading.addWidget(Badge(kongui.version_label(), "accent"))
        heading.addStretch(1)
        texts.addLayout(heading)
        texts.addWidget(
            Label(
                lambda: self.tr(
                    "Graphical interface to save, apply and share your KDE Plasma "
                    "customization, built on top of Konsave."
                ),
                "muted",
                wrap=True,
            )
        )
        buttons = QHBoxLayout()
        self.repository_button = Button(
            lambda: self.tr("Repository"), icon_name="folder"
        )
        self.repository_button.clicked.connect(lambda: self.open_url(REPOSITORY_URL))
        self.konsave_button = Button(
            lambda: self.tr("Konsave project"), icon_name="folder"
        )
        self.konsave_button.clicked.connect(lambda: self.open_url(KONSAVE_URL))
        buttons.addWidget(self.repository_button)
        buttons.addWidget(self.konsave_button)
        buttons.addStretch(1)
        texts.addSpacing(8)
        texts.addLayout(buttons)
        row.addLayout(texts, 1)
        self.body.addWidget(hero)

        notice = Card()
        notice_layout = QVBoxLayout(notice)
        notice_layout.setContentsMargins(20, 16, 20, 16)
        badge, text = self._notice_texts(ctx.backend.capabilities.demo)
        notice_layout.addWidget(Badge(badge, "warning"), 0, Qt.AlignmentFlag.AlignLeft)
        notice_layout.addWidget(Label(text, wrap=True))
        self.body.addWidget(notice)

        info = Card()
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(20, 16, 20, 14)
        info_layout.setSpacing(2)
        info_layout.addWidget(self.section_title(lambda: self.tr("Environment")))
        info_layout.addWidget(Separator())
        for name, value in self._info_rows():
            info_layout.addWidget(SettingRow(name, "", Label(value, "muted")))
        self.body.addWidget(info)
        self.body.addStretch(1)

    def _notice_texts(self, demo: bool) -> Tuple[Text, Text]:
        """The badge and the notice of the page, as texts that follow the language."""
        if demo:
            return (
                lambda: self.tr("Visual prototype"),
                lambda: self.tr(
                    "This version uses fictitious data. No Konsave operation is run "
                    "and no system file is read or changed."
                ),
            )
        return (
            lambda: self.tr("In development"),
            lambda: self.tr(
                "Listing, saving, overwriting, applying, removing, clearing, "
                "importing and exporting profiles use the real Konsave, and "
                "conf.yaml can be edited (with validation and backup). Before "
                "applying or importing, the files that would be overwritten are "
                "copied and can be restored in Settings."
            ),
        )

    def _info_rows(self) -> List[Tuple[Text, Text]]:
        """The environment rows as ``(name, value)``; each may follow the language."""
        engine_version = self.ctx.backend.engine_version
        # The whole version (with the commit of a build between two tags), or
        # "dev" when running from a checkout that was never installed.
        own_version = kongui.__version__ if kongui.short_version() else "dev"
        rows: List[Tuple[Text, Text]] = [
            (lambda: self.tr("KonGUI version"), own_version),
        ]
        if engine_version:
            rows.append((lambda: self.tr("Konsave version"), engine_version))
        rows += [
            ("Qt", qVersion()),
            ("PySide6", PySide6.__version__),
            ("Python", platform.python_version()),
            (lambda: self.tr("System"), f"{platform.system()} {platform.release()}"),
            (lambda: self.tr("License"), lambda: self.tr("GPL-3.0, same as Konsave")),
        ]
        return rows

    @property
    def info_values(self) -> Dict[str, str]:
        """The environment rows as shown now: name -> value."""
        return {
            resolve_text(name): resolve_text(value) for name, value in self._info_rows()
        }

    def open_url(self, url: str) -> bool:
        """Opens a link in the default browser.

        Args:
            url: Address to open.

        Returns:
            bool: Whether the desktop accepted the request.
        """
        return QDesktopServices.openUrl(QUrl(url))


__all__ = ["AboutPage", "REPOSITORY_URL", "KONSAVE_URL"]
