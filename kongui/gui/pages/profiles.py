"""Profiles page: search, sort and a grid/list of profile cards."""

from __future__ import annotations

from typing import List

from PySide6.QtCore import QCoreApplication, QT_TRANSLATE_NOOP
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QWidget

from kongui.gui import i18n
from kongui.gui.actions import ProfileActions
from kongui.gui.context import AppContext
from kongui.gui.controller import LoadState
from kongui.gui.pages.base import Page
from kongui.gui.state import Profile
from kongui.gui.widgets.cards import ProfileCard
from kongui.gui.widgets.common import Button, Label, SegmentedControl
from kongui.gui.widgets.feedback import ErrorBanner
from kongui.gui.widgets.grid import ResponsiveGrid
from kongui.gui.widgets.search import SearchField
from kongui.gui.widgets.states import EmptyState

#: ``(value, English label)``; the label is translated with the context "ProfilesPage".
SORT_OPTIONS = (
    ("name", QT_TRANSLATE_NOOP("ProfilesPage", "Name")),
    ("recent", QT_TRANSLATE_NOOP("ProfilesPage", "Most recent")),
    ("size", QT_TRANSLATE_NOOP("ProfilesPage", "Largest size")),
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
    TITLE = QT_TRANSLATE_NOOP("ProfilesPage", "Profiles")
    SUBTITLE = QT_TRANSLATE_NOOP(
        "ProfilesPage", "Apply, export and organize your saved configurations"
    )
    icon_name = "profiles"

    def __init__(self, ctx: AppContext) -> None:
        """Builds the page.

        Args:
            ctx: Shared services.
        """
        super().__init__(ctx)
        self.actions = ProfileActions(ctx)
        self.new_button = Button(
            lambda: self.tr("New profile"), variant="primary", icon_name="plus"
        )
        self.new_button.setShortcut("Ctrl+N")
        self.new_button.clicked.connect(
            lambda: self.actions.save_current(self.window())
        )

        self.wipe_button = Button(
            lambda: self.tr("Clear all"), variant="danger", icon_name="trash"
        )
        self.wipe_button.clicked.connect(lambda: self.actions.wipe_all(self.window()))

        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)
        self.search = SearchField(lambda: self.tr("Search profiles"))
        self.search.setMinimumWidth(220)
        self.sort_combo = QComboBox()
        self.sort_combo.setMinimumWidth(150)
        for value, label in SORT_OPTIONS:
            self.sort_combo.addItem(self._translate_sort(label), value)
        i18n.bind(self.sort_combo, self._retranslate_sort)
        self.view_control = SegmentedControl(
            [
                ("grid", lambda: self.tr("Grid"), "grid"),
                ("list", lambda: self.tr("List"), "list"),
            ]
        )
        self.view_control.set_value(str(ctx.settings.get("profiles_view")))
        self.count_label = Label("", "muted")
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(self.sort_combo)
        toolbar.addWidget(self.view_control)
        self.body.addLayout(toolbar)
        self.body.addWidget(self.count_label)

        self.error_banner = ErrorBanner(self.tr("Could not list the profiles"))
        self.error_banner.retry_requested.connect(self._retry)
        self.body.addWidget(self.error_banner)
        self.loading_state = EmptyState(
            "refresh",
            lambda: self.tr("Loading profiles…"),
            lambda: self.tr("Reading Konsave's profiles folder."),
        )
        self.body.addWidget(self.loading_state)

        self.grid = ResponsiveGrid(min_item_width=330, max_columns=4)
        self.body.addWidget(self.grid)
        self.empty_state = EmptyState(
            "profiles",
            lambda: self.tr("No saved profiles"),
            lambda: self.tr(
                "Save your current Plasma configuration so you can go back to "
                "it whenever you want."
            ),
            lambda: self.tr("Save current profile"),
            "save",
        )
        self.empty_state.action_triggered.connect(self.new_button.click)
        self.no_results = EmptyState(
            "search",
            lambda: self.tr("No results"),
            lambda: self.tr("No profile matches the search. Try another term."),
            lambda: self.tr("Clear search"),
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

    def _translate_sort(self, label: str) -> str:
        """Translates the source label of a sort option."""
        return QCoreApplication.translate("ProfilesPage", label)

    def _retranslate_sort(self) -> None:
        """Sets the sort labels again; the selection is kept."""
        self.sort_combo.setAccessibleName(self.tr("Sort by"))
        for index, (_value, label) in enumerate(SORT_OPTIONS):
            self.sort_combo.setItemText(index, self._translate_sort(label))

    def retranslate(self) -> None:
        """Rebuilds the cards, counts and messages in the new language."""
        self.error_banner.set_title(self.tr("Could not list the profiles"))
        self.refresh()

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
            "apply": self.tr("Applying…"),
            "overwrite": self.tr("Overwriting…"),
            "remove": self.tr("Removing…"),
        }
        cards = []
        for profile in shown:
            text = ""
            if running and running[1] == profile.name:
                text = busy_texts.get(running[0], self.tr("Processing…"))
                if controller.waiting:
                    text = self.tr("Waiting for another operation…")
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
                self.tr("Could not list the profiles"), controller.error
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
                self.tr("%n result(s) of {total}", "", len(shown)).format(
                    total=len(all_profiles)
                )
            )
        else:
            self.count_label.setText(self.tr("%n profile(s)", "", len(all_profiles)))
