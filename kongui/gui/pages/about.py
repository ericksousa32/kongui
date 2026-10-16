"""About page."""

from __future__ import annotations

import platform

import PySide6
from PySide6.QtCore import Qt, QUrl, qVersion
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout

from kongui import __version__
from kongui.gui.context import AppContext
from kongui.gui.pages.base import Page
from kongui.gui.widgets.common import Badge, Button, Card, IconTile, Label, Separator
from kongui.gui.widgets.rows import SettingRow

REPOSITORY_URL = "https://github.com/ericksousa32/kongui"
KONSAVE_URL = "https://github.com/prayag2/konsave"


class AboutPage(Page):
    """Version, credits and environment."""

    key = "about"
    title = "Sobre"
    subtitle = "Informações sobre o aplicativo"
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
        heading.addWidget(Badge(f"v{__version__}", "accent"))
        heading.addStretch(1)
        texts.addLayout(heading)
        texts.addWidget(
            Label(
                "Interface gráfica para salvar, aplicar e compartilhar a aparência do KDE Plasma, "
                "construída sobre o Konsave.",
                "muted",
                wrap=True,
            )
        )
        buttons = QHBoxLayout()
        self.repository_button = Button("Repositório", icon_name="folder")
        self.repository_button.clicked.connect(lambda: self.open_url(REPOSITORY_URL))
        self.konsave_button = Button("Projeto Konsave", icon_name="folder")
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
        if ctx.backend.capabilities.demo:
            badge, text = (
                "Protótipo visual",
                "Esta versão usa dados fictícios. Nenhuma operação do Konsave é "
                "executada e nenhum arquivo do sistema é lido ou alterado.",
            )
        else:
            badge, text = (
                "Em desenvolvimento",
                "Listar, salvar, sobrescrever, aplicar, remover, limpar, importar e "
                "exportar perfis usam o Konsave de verdade. Aplicar e importar "
                "substituem arquivos de configuração sem backup. Editar o "
                "conf.yaml ainda não está disponível.",
            )
        notice_layout.addWidget(Badge(badge, "warning"), 0, Qt.AlignmentFlag.AlignLeft)
        notice_layout.addWidget(Label(text, wrap=True))
        self.body.addWidget(notice)

        info = Card()
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(20, 16, 20, 14)
        info_layout.setSpacing(2)
        info_layout.addWidget(self.section_title("Ambiente"))
        info_layout.addWidget(Separator())
        self.info_values = {
            "Versão do KonGUI": __version__,
            "Qt": qVersion(),
            "PySide6": PySide6.__version__,
            "Python": platform.python_version(),
            "Sistema": f"{platform.system()} {platform.release()}",
            "Licença": "GPL-3.0, como o Konsave",
        }
        for name, value in self.info_values.items():
            info_layout.addWidget(SettingRow(name, "", Label(value, "muted")))
        self.body.addWidget(info)
        self.body.addStretch(1)

    def open_url(self, url: str) -> bool:
        """Opens a link in the default browser.

        Args:
            url: Address to open.

        Returns:
            bool: Whether the desktop accepted the request.
        """
        return QDesktopServices.openUrl(QUrl(url))


__all__ = ["AboutPage", "REPOSITORY_URL", "KONSAVE_URL"]
