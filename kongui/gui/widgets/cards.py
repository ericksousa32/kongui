"""Cards used by the dashboard and the profile list."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QBoxLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QVBoxLayout,
    QWidget,
)

from kongui.gui import icons
from kongui.gui.formatting import format_date, format_relative, format_size, plural
from kongui.gui.state import ActivityEntry, Profile
from kongui.gui.theme import get_theme
from kongui.gui.widgets.common import Badge, Button, Card, IconTile, Label
from kongui.gui.widgets.feedback import BusyBar

MAX_CHIPS = 3


class StatCard(Card):
    """A summary figure with an icon, a caption and a hint."""

    def __init__(
        self, icon_name: str, caption: str, value: str, hint: str = ""
    ) -> None:
        """Creates the card.

        Args:
            icon_name: Icon shown in the tile.
            caption: What the figure measures.
            value: The figure.
            hint: Optional small text under the figure.
        """
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(IconTile(icon_name, 36))
        self.caption_label = Label(caption, "muted")
        top.addWidget(self.caption_label, 1)
        outer.addLayout(top)
        self.value_label = Label(value, "stat")
        self.hint_label = Label(hint, "caption", wrap=True)
        outer.addWidget(self.value_label)
        outer.addWidget(self.hint_label)
        self.hint_label.setVisible(bool(hint))
        self.setAccessibleName(f"{caption}: {value}")

    def set_content(self, value: str, hint: str = "") -> None:
        """Updates the figure and the hint.

        Args:
            value: The new figure.
            hint: The new hint; empty hides it.
        """
        self.value_label.setText(value)
        self.hint_label.setText(hint)
        self.hint_label.setVisible(bool(hint))
        self.setAccessibleName(f"{self.caption_label.text()}: {value}")


class ProfileCard(Card):
    """Summary and actions of one profile; works as a grid card or a list row.

    Signals carry the profile name.
    """

    apply_requested = Signal(str)
    export_requested = Signal(str)
    duplicate_requested = Signal(str)
    overwrite_requested = Signal(str)
    remove_requested = Signal(str)

    def __init__(  # pylint: disable=too-many-arguments
        self,
        profile: Profile,
        *,
        list_mode: bool = False,
        can_export: bool = True,
        can_duplicate: bool = True,
        locked: bool = False,
        busy_text: str = "",
    ) -> None:
        """Creates the card.

        Args:
            profile: The profile to show.
            list_mode: Lay out as a wide row instead of a tall card.
            can_export: Show the export button.
            can_duplicate: Offer "Duplicar" in the menu.
            locked: Disable every action (another operation is running).
            busy_text: If given, this card is the one being processed: the text
                (for example ``"Aplicando…"``) and a progress bar are shown.
        """
        super().__init__(hoverable=True)
        self.profile_name = profile.name
        self.setProperty("profile", profile.name)
        self.set_active(profile.active)
        self.setAccessibleName(f"Perfil {profile.name}")
        self._outer = QBoxLayout(QBoxLayout.Direction.TopToBottom, self)
        self._outer.setContentsMargins(18, 16, 18, 16)
        self._outer.setSpacing(14)

        info = QVBoxLayout()
        info.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(IconTile("profiles", 36), 0, Qt.AlignmentFlag.AlignTop)
        names = QVBoxLayout()
        names.setSpacing(0)
        self.name_label = Label(profile.name, "h2")
        names.addWidget(self.name_label)
        names.addWidget(
            Label(f"Atualizado {format_relative(profile.modified)}", "caption")
        )
        head.addLayout(names, 1)
        self.badge: Optional[Badge] = None
        if profile.active:
            self.badge = Badge("Ativo", "accent")
            head.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignTop)
        info.addLayout(head)
        self.description_label: Optional[Label] = None
        if profile.description:
            self.description_label = Label(profile.description, "muted", wrap=True)
            info.addWidget(self.description_label)
        if profile.sections:
            chips = QHBoxLayout()
            chips.setSpacing(6)
            for section in profile.sections[:MAX_CHIPS]:
                chips.addWidget(Badge(section.split(" (", maxsplit=1)[0]))
            extra = len(profile.sections) - MAX_CHIPS
            if extra > 0:
                chips.addWidget(Badge(f"+{extra}"))
            chips.addStretch(1)
            info.addLayout(chips)
        parts = [format_size(profile.size_mb)]
        if profile.sections:
            parts.append(plural(len(profile.sections), "seção", "seções"))
        parts.append(format_date(profile.modified))
        info.addWidget(Label(" · ".join(parts), "caption"))
        self.busy_label: Optional[Label] = None
        self.busy_bar: Optional[BusyBar] = None
        if busy_text:
            self.busy_label = Label(busy_text, "caption")
            self.busy_bar = BusyBar()
            self.busy_bar.show()
            info.addWidget(self.busy_label)
            info.addWidget(self.busy_bar)
        info.addStretch(1)
        self._outer.addLayout(info, 1)

        self.actions = QWidget()
        self.actions_layout = QHBoxLayout(self.actions)
        self.actions_layout.setContentsMargins(0, 0, 0, 0)
        self.actions_layout.setSpacing(8)
        if profile.active:
            self.apply_button = Button("Em uso", icon_name="check")
            self.apply_button.setEnabled(False)
        else:
            self.apply_button = Button("Aplicar", variant="primary", icon_name="play")
        self.apply_button.setToolTip(f"Aplicar o perfil {profile.name}")
        self.apply_button.clicked.connect(
            lambda: self.apply_requested.emit(self.profile_name)
        )
        self.export_button: Optional[Button] = None
        if can_export:
            self.export_button = Button("Exportar", icon_name="export")
            self.export_button.setToolTip(f"Exportar o perfil {profile.name}")
            self.export_button.clicked.connect(
                lambda: self.export_requested.emit(self.profile_name)
            )
        self.more_button = Button(
            variant="icon", icon_name="more", tooltip="Mais ações"
        )
        self.more_button.setAccessibleName(f"Mais ações para {profile.name}")
        self.menu = QMenu(self.more_button)
        self.overwrite_action = self.menu.addAction(
            "Sobrescrever com a configuração atual…"
        )
        self.overwrite_action.triggered.connect(
            lambda: self.overwrite_requested.emit(self.profile_name)
        )
        self.duplicate_action = None
        if can_duplicate:
            self.duplicate_action = self.menu.addAction("Duplicar")
            self.duplicate_action.triggered.connect(
                lambda: self.duplicate_requested.emit(self.profile_name)
            )
        self.menu.addSeparator()
        self.remove_action = self.menu.addAction("Remover…")
        self.remove_action.triggered.connect(
            lambda: self.remove_requested.emit(self.profile_name)
        )
        self.more_button.setMenu(self.menu)
        self.actions_layout.addWidget(self.apply_button)
        if self.export_button is not None:
            self.actions_layout.addWidget(self.export_button)
        self.actions_layout.addStretch(1)
        self.actions_layout.addWidget(self.more_button)
        self._outer.addWidget(self.actions, 0)
        self.set_list_mode(list_mode)
        self.locked = locked or bool(busy_text)
        if self.locked:
            self.actions.setEnabled(False)
        if busy_text:
            self.setAccessibleDescription(busy_text)

    def set_list_mode(self, list_mode: bool) -> None:
        """Switches between the tall card and the wide row.

        Args:
            list_mode: ``True`` for the row layout.
        """
        self.list_mode = list_mode
        self._outer.setDirection(
            QBoxLayout.Direction.LeftToRight
            if list_mode
            else QBoxLayout.Direction.TopToBottom
        )
        self._outer.setAlignment(
            self.actions,
            Qt.AlignmentFlag.AlignVCenter if list_mode else Qt.AlignmentFlag(0),
        )
        self.actions_layout.setDirection(QBoxLayout.Direction.LeftToRight)


class ActivityRow(QWidget):
    """One line of the activity feed."""

    _ICONS = {
        "save": "save",
        "apply": "play",
        "export": "export",
        "import": "import",
        "remove": "trash",
        "info": "info",
    }

    def __init__(self, entry: ActivityEntry) -> None:
        """Creates the row.

        Args:
            entry: The event to show.
        """
        super().__init__()
        self._icon_name = self._ICONS.get(entry.kind, "info")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 6, 0, 6)
        row.setSpacing(12)
        self._icon = QLabel()
        row.addWidget(self._icon)
        self.text_label = Label(entry.text, wrap=True)
        row.addWidget(self.text_label, 1)
        row.addWidget(Label(format_relative(entry.when), "caption"))
        get_theme().changed.connect(self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        """Repaints the kind icon."""
        self._icon.setPixmap(
            icons.pixmap(self._icon_name, get_theme().tokens.muted, 18)
        )
