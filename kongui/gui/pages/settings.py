"""Settings page."""

from __future__ import annotations

from typing import List

from PySide6.QtWidgets import QLineEdit, QSpinBox, QVBoxLayout

from kongui.gui.context import AppContext
from kongui.gui.pages.base import Page
from kongui.gui.theme import ThemeMode
from kongui.gui.widgets.common import Button, Card, SegmentedControl, Separator
from kongui.gui.actions import ProfileActions
from kongui.gui.widgets.rows import SettingRow

#: Where the original Konsave keeps profiles (documented in docs/INTEGRATION.md).
PROFILES_FOLDER = "~/.config/konsave/profiles"


class SettingsPage(Page):  # pylint: disable=too-many-instance-attributes
    """Appearance, behaviour, notifications and demo data."""

    key = "settings"
    title = "Configurações"
    subtitle = "Aparência e comportamento do aplicativo"
    icon_name = "settings"

    def __init__(self, ctx: AppContext) -> None:
        """Builds the page.

        Args:
            ctx: Shared services.
        """
        super().__init__(ctx)
        settings = ctx.settings

        appearance = self._group("Aparência")
        self.theme_control = SegmentedControl(
            [
                (ThemeMode.SYSTEM.value, "Sistema", "monitor"),
                (ThemeMode.LIGHT.value, "Claro", "sun"),
                (ThemeMode.DARK.value, "Escuro", "moon"),
            ]
        )
        self.theme_control.set_value(str(settings.get("theme")))
        self.theme_control.selected.connect(lambda value: settings.set("theme", value))
        appearance.addWidget(
            SettingRow(
                "Tema",
                "“Sistema” segue o esquema de cores e a cor de destaque do Plasma.",
                self.theme_control,
            )
        )

        profiles = self._group("Perfis")
        self.view_control = SegmentedControl(
            [("grid", "Grade", "grid"), ("list", "Lista", "list")]
        )
        self.view_control.set_value(str(settings.get("profiles_view")))
        self.view_control.selected.connect(
            lambda value: settings.set("profiles_view", value)
        )
        profiles.addWidget(
            SettingRow(
                "Exibição padrão", "Como a página Perfis é mostrada.", self.view_control
            )
        )
        self.folder_edit = QLineEdit(PROFILES_FOLDER)
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setMinimumWidth(260)
        self.folder_edit.setAccessibleName("Pasta de perfis")
        profiles.addWidget(
            SettingRow(
                "Pasta de perfis", "Somente leitura nesta versão.", self.folder_edit
            )
        )

        notifications = self._group("Notificações")
        self.seconds_spin = QSpinBox()
        self.seconds_spin.setRange(1, 60)
        self.seconds_spin.setSuffix(" s")
        self.seconds_spin.setValue(int(settings.get("toast_seconds")))  # type: ignore[call-overload]
        self.seconds_spin.setAccessibleName("Duração das notificações")
        self.seconds_spin.valueChanged.connect(
            lambda value: settings.set("toast_seconds", value)
        )
        notifications.addWidget(
            SettingRow(
                "Duração", "Tempo que cada aviso fica na tela.", self.seconds_spin
            )
        )
        self.test_button = Button("Testar", icon_name="info")
        self.test_button.clicked.connect(
            lambda: ctx.toasts.show_message(
                "info", "Notificação de teste", "É assim que os avisos aparecem."
            )
        )
        notifications.addWidget(
            SettingRow("Visualizar", "Mostra um aviso de exemplo.", self.test_button)
        )

        self.clear_button = None
        self.reset_button = None
        if ctx.backend.capabilities.demo:
            self._build_demo()
        self.body.addStretch(1)

        settings.changed.connect(self._on_setting_changed)

    def _group(self, title: str) -> QVBoxLayout:
        """Adds a titled card to the page and returns its layout."""
        card = Card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 14)
        layout.setSpacing(4)
        layout.addWidget(self.section_title(title))
        layout.addWidget(Separator())
        self.body.addWidget(card)
        return layout

    def _on_setting_changed(self, key: str) -> None:
        """Keeps the controls in sync when a setting changes elsewhere."""
        value = self.ctx.settings.get(key)
        if key == "theme":
            self.theme_control.set_value(str(value))
        elif key == "profiles_view":
            self.view_control.set_value(str(value))
        elif key == "toast_seconds":
            self.seconds_spin.setValue(int(value))  # type: ignore[call-overload]

    def _build_demo(self) -> None:
        """Adds the demonstration-data group (demo backend only)."""
        demo = self._group("Dados de demonstração")
        self.clear_button = Button(
            "Esvaziar perfis", variant="danger", icon_name="trash"
        )
        self.clear_button.clicked.connect(self._clear_profiles)
        self.reset_button = Button("Restaurar fictícios", icon_name="refresh")
        self.reset_button.clicked.connect(self._reset_profiles)
        demo.addWidget(
            SettingRow(
                "Lista vazia",
                "Remove todos os perfis fictícios para mostrar os estados vazios.",
                self.clear_button,
            )
        )
        demo.addWidget(
            SettingRow(
                "Dados originais",
                "Volta aos sete perfis de exemplo.",
                self.reset_button,
            )
        )

    def _clear_profiles(self) -> None:
        """Empties the fictitious list after explicit confirmation."""
        ProfileActions(self.ctx).wipe_all(self.window())

    def _reset_profiles(self) -> None:
        """Restores the fictitious profiles."""
        self.ctx.controller.demo_reset()

    def header_actions(self) -> List:
        """Settings has no top-bar actions."""
        return []
