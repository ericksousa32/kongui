"""Profiles page: search, sort and a grid/list of profile cards."""

from __future__ import annotations

from typing import List

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QWidget

from kongui.gui.actions import ProfileActions
from kongui.gui.context import AppContext
from kongui.gui.formatting import plural
from kongui.gui.pages.base import Page
from kongui.gui.state import Profile
from kongui.gui.widgets.cards import ProfileCard
from kongui.gui.widgets.common import Button, Label, SegmentedControl
from kongui.gui.widgets.grid import ResponsiveGrid
from kongui.gui.widgets.search import SearchField
from kongui.gui.widgets.states import EmptyState

SORT_OPTIONS = (
    ("name", "Nome"),
    ("recent", "Mais recentes"),
    ("size", "Maior tamanho"),
)


def filter_and_sort(profiles: List[Profile], query: str, sort: str) -> List[Profile]:
    """Filters profiles by text and sorts them.

    Args:
        profiles: All profiles.
        query: Text searched in name, description and sections (case-insensitive).
        sort: ``"name"``, ``"recent"`` or ``"size"``.

    Returns:
        List[Profile]: The matching profiles, ordered.
    """
    needle = query.strip().casefold()

    def matches(profile: Profile) -> bool:
        haystack = " ".join(
            (profile.name, profile.description, *profile.sections)
        ).casefold()
        return needle in haystack

    found = [profile for profile in profiles if matches(profile)]
    if sort == "recent":
        found.sort(key=lambda profile: profile.modified, reverse=True)
    elif sort == "size":
        found.sort(key=lambda profile: profile.size_mb, reverse=True)
    else:
        found.sort(key=lambda profile: profile.name.casefold())
    return found


class ProfilesPage(Page):
    """Browse, search and act on profiles."""

    key = "profiles"
    title = "Perfis"
    subtitle = "Aplique, exporte e organize suas configurações salvas"
    icon_name = "profiles"

    def __init__(self, ctx: AppContext) -> None:
        """Builds the page.

        Args:
            ctx: Shared services.
        """
        super().__init__(ctx)
        self.actions = ProfileActions(ctx)
        self.new_button = Button("Novo perfil", variant="primary", icon_name="plus")
        self.new_button.setShortcut("Ctrl+N")
        self.new_button.clicked.connect(
            lambda: self.actions.save_current(self.window())
        )

        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)
        self.search = SearchField("Buscar perfis")
        self.search.setMinimumWidth(220)
        self.sort_combo = QComboBox()
        self.sort_combo.setAccessibleName("Ordenar por")
        self.sort_combo.setMinimumWidth(150)
        for value, label in SORT_OPTIONS:
            self.sort_combo.addItem(label, value)
        self.view_control = SegmentedControl(
            [("grid", "Grade", "grid"), ("list", "Lista", "list")]
        )
        self.view_control.set_value(str(ctx.settings.get("profiles_view")))
        self.count_label = Label("", "muted")
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(self.sort_combo)
        toolbar.addWidget(self.view_control)
        self.body.addLayout(toolbar)
        self.body.addWidget(self.count_label)

        self.grid = ResponsiveGrid(min_item_width=330, max_columns=4)
        self.body.addWidget(self.grid)
        self.empty_state = EmptyState(
            "profiles",
            "Nenhum perfil salvo",
            "Salve sua configuração atual do Plasma para poder voltar a ela quando quiser.",
            "Salvar perfil atual",
            "save",
        )
        self.empty_state.action_triggered.connect(self.new_button.click)
        self.no_results = EmptyState(
            "search",
            "Nenhum resultado",
            "Nenhum perfil corresponde à busca. Tente outro termo.",
            "Limpar busca",
            "x",
        )
        self.no_results.action_triggered.connect(self.search.clear)
        self.body.addWidget(self.empty_state)
        self.body.addWidget(self.no_results)
        self.body.addStretch(1)

        self.search.textChanged.connect(self.refresh)
        self.sort_combo.currentIndexChanged.connect(self.refresh)
        self.view_control.selected.connect(self._on_view_selected)
        ctx.store.changed.connect(self.refresh)
        self.refresh()

    def header_actions(self) -> List[QWidget]:
        """Returns the top-bar buttons."""
        return [self.new_button]

    def on_shown(self) -> None:
        """Rebuilds the list when the page appears."""
        self.refresh()

    def focus_search(self) -> None:
        """Moves the keyboard focus to the search box."""
        self.search.setFocus()
        self.search.selectAll()

    def cards(self) -> List[ProfileCard]:
        """Returns the profile cards currently shown."""
        return [item for item in self.grid.items() if isinstance(item, ProfileCard)]

    def _on_view_selected(self, value: str) -> None:
        """Stores the layout choice and redraws."""
        self.ctx.settings.set("profiles_view", value)
        self.refresh()

    def refresh(self) -> None:
        """Rebuilds the cards for the current search, sort and layout."""
        all_profiles = self.ctx.store.profiles()
        sort = str(self.sort_combo.currentData())
        shown = filter_and_sort(all_profiles, self.search.text(), sort)
        list_mode = self.ctx.settings.get("profiles_view") == "list"
        self.view_control.set_value("list" if list_mode else "grid")
        self.grid.set_forced_columns(1 if list_mode else None)
        cards = []
        for profile in shown:
            card = ProfileCard(profile, list_mode=list_mode)
            card.apply_requested.connect(
                lambda name: self.actions.apply(self.window(), name)
            )
            card.export_requested.connect(self.ctx.export_profile)
            card.duplicate_requested.connect(self.actions.duplicate)
            card.remove_requested.connect(
                lambda name: self.actions.remove(self.window(), name)
            )
            cards.append(card)
        self.grid.set_items(cards)
        has_any = bool(all_profiles)
        self.grid.setVisible(bool(shown))
        self.empty_state.setVisible(not has_any)
        self.no_results.setVisible(has_any and not shown)
        self.sort_combo.setEnabled(has_any)
        self.search.setEnabled(has_any)
        self.view_control.setEnabled(has_any)
        if not has_any:
            self.count_label.setText("")
        elif self.search.text().strip():
            self.count_label.setText(
                f"{plural(len(shown), 'resultado', 'resultados')} de {len(all_profiles)}"
            )
        else:
            self.count_label.setText(plural(len(all_profiles), "perfil", "perfis"))
