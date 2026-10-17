"""Profiles page: search, sort and a grid/list of profile cards."""

from __future__ import annotations

from typing import List

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QWidget

from kongui.gui.actions import ProfileActions
from kongui.gui.context import AppContext
from kongui.gui.controller import LoadState
from kongui.gui.formatting import plural
from kongui.gui.pages.base import Page
from kongui.gui.state import Profile
from kongui.gui.widgets.cards import ProfileCard
from kongui.gui.widgets.common import Button, Label, SegmentedControl
from kongui.gui.widgets.feedback import ErrorBanner
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

        self.wipe_button = Button("Limpar todos", variant="danger", icon_name="trash")
        self.wipe_button.clicked.connect(lambda: self.actions.wipe_all(self.window()))

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

        self.error_banner = ErrorBanner("Não foi possível listar os perfis")
        self.error_banner.retry_requested.connect(self._retry)
        self.body.addWidget(self.error_banner)
        self.loading_state = EmptyState(
            "refresh", "Carregando perfis…", "Lendo a pasta de perfis do Konsave."
        )
        self.body.addWidget(self.loading_state)

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
        ctx.controller.state_changed.connect(self.refresh)
        self.refresh()

    def header_actions(self) -> List[QWidget]:
        """Returns the top-bar buttons."""
        return [self.wipe_button, self.new_button]

    def _retry(self) -> None:
        """Tries to list the profiles again."""
        self.ctx.controller.refresh()

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
        """Rebuilds the page for the list, the search and the running operation."""
        controller = self.ctx.controller
        caps = self.ctx.backend.capabilities
        all_profiles = self.ctx.store.profiles()
        loaded = controller.state in (LoadState.READY,) or bool(all_profiles)
        loading = controller.state is LoadState.LOADING and not all_profiles
        failed = controller.state is LoadState.ERROR and not all_profiles
        busy = controller.busy
        running = controller.current
        sort = str(self.sort_combo.currentData())
        shown = filter_and_sort(all_profiles, self.search.text(), sort)
        list_mode = self.ctx.settings.get("profiles_view") == "list"
        self.view_control.set_value("list" if list_mode else "grid")
        self.grid.set_forced_columns(1 if list_mode else None)
        busy_texts = {
            "apply": "Aplicando…",
            "overwrite": "Sobrescrevendo…",
            "remove": "Removendo…",
        }
        cards = []
        for profile in shown:
            text = ""
            if running and running[1] == profile.name:
                text = busy_texts.get(running[0], "Processando…")
                if controller.waiting:
                    text = "Aguardando outra operação…"
            card = ProfileCard(
                profile,
                list_mode=list_mode,
                can_export=caps.transfer,
                can_duplicate=caps.duplicate,
                locked=busy,
                busy_text=text,
            )
            card.apply_requested.connect(
                lambda name: self.actions.apply(self.window(), name)
            )
            card.export_requested.connect(self.ctx.export_profile)
            card.duplicate_requested.connect(self.actions.duplicate)
            card.overwrite_requested.connect(
                lambda name: self.actions.overwrite(self.window(), name)
            )
            card.remove_requested.connect(
                lambda name: self.actions.remove(self.window(), name)
            )
            cards.append(card)
        self.grid.set_items(cards)
        has_any = bool(all_profiles)
        self.loading_state.setVisible(loading)
        self.error_banner.setVisible(failed)
        if failed:
            self.error_banner.set_content(
                "Não foi possível listar os perfis", controller.error
            )
        self.grid.setVisible(bool(shown))
        self.empty_state.setVisible(
            loaded and not has_any and not loading and not failed
        )
        self.no_results.setVisible(has_any and not shown)
        for widget in (self.sort_combo, self.search, self.view_control):
            widget.setEnabled(has_any)
        self.new_button.setEnabled(not busy and not failed)
        self.wipe_button.setEnabled(not busy and has_any)
        self.error_banner.retry_button.setEnabled(not busy)
        if not has_any:
            self.count_label.setText("")
        elif self.search.text().strip():
            self.count_label.setText(
                f"{plural(len(shown), 'resultado', 'resultados')} de {len(all_profiles)}"
            )
        else:
            self.count_label.setText(plural(len(all_profiles), "perfil", "perfis"))
