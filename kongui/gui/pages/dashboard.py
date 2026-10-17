"""Dashboard: summary cards, active profile and recent activity."""

from __future__ import annotations

from typing import List

from PySide6.QtCore import QT_TRANSLATE_NOOP, Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from kongui.gui.actions import ProfileActions
from kongui.gui.context import AppContext
from kongui.gui.controller import LoadState
from kongui.gui.formatting import format_relative, format_size
from kongui.gui.pages.base import Page
from kongui.gui.widgets.cards import ActivityRow, StatCard
from kongui.gui.widgets.common import Badge, Button, Card, Label, clear_layout
from kongui.gui.widgets.grid import ResponsiveGrid
from kongui.gui.widgets.states import EmptyState

RECENT_LIMIT = 6


class DashboardPage(Page):
    """Overview of profiles and recent events."""

    key = "dashboard"
    TITLE = QT_TRANSLATE_NOOP("DashboardPage", "Dashboard")
    SUBTITLE = QT_TRANSLATE_NOOP(
        "DashboardPage", "Overview of your customization profiles"
    )
    icon_name = "dashboard"

    def __init__(self, ctx: AppContext) -> None:
        """Builds the page.

        Args:
            ctx: Shared services.
        """
        super().__init__(ctx)
        self.actions = ProfileActions(ctx)
        self.save_button = Button(
            lambda: self.tr("Save current profile"),
            variant="primary",
            icon_name="save",
        )
        self.save_button.setShortcut("Ctrl+S")
        self.save_button.clicked.connect(
            lambda: self.actions.save_current(self.window())
        )
        self.import_button = Button(lambda: self.tr("Import"), icon_name="import")
        self.import_button.clicked.connect(lambda: ctx.navigate("transfer"))

        self.stats = {
            "count": StatCard("profiles", lambda: self.tr("Saved profiles"), "0"),
            "active": StatCard("check", lambda: self.tr("Active profile"), "—"),
            "size": StatCard("disk", lambda: self.tr("Space used"), "0 MB"),
            "recent": StatCard("clock", lambda: self.tr("Last change"), "—"),
        }
        grid = ResponsiveGrid(
            min_item_width=180, max_columns=4, allowed_columns=(1, 2, 4)
        )
        grid.set_items(list(self.stats.values()))
        self.stats_grid = grid
        self.body.addWidget(grid)

        self.panels = ResponsiveGrid(min_item_width=380, max_columns=2)
        self.active_card = Card()
        self.active_layout = QVBoxLayout(self.active_card)
        self.active_layout.setContentsMargins(20, 18, 20, 18)
        self.active_layout.setSpacing(12)
        self.activity_card = Card()
        self.activity_layout = QVBoxLayout(self.activity_card)
        self.activity_layout.setContentsMargins(20, 18, 20, 18)
        self.activity_layout.setSpacing(2)
        self.panels.set_items([self.active_card, self.activity_card])
        self.body.addWidget(self.panels)
        self.body.addStretch(1)

        ctx.store.changed.connect(self.refresh)
        ctx.activity.changed.connect(self.refresh)
        ctx.controller.state_changed.connect(self.refresh)
        self.refresh()

    def header_actions(self) -> List[QWidget]:
        """Returns the top-bar buttons."""
        if self.ctx.backend.capabilities.transfer:
            return [self.import_button, self.save_button]
        return [self.save_button]

    def on_shown(self) -> None:
        """Refreshes the figures when the page appears."""
        self.refresh()

    def refresh(self) -> None:
        """Rebuilds the figures and panels from the models."""
        store = self.ctx.store
        controller = self.ctx.controller
        active = store.active()
        latest = store.latest_modified()
        count = len(store.names())
        waiting = controller.state in (LoadState.IDLE, LoadState.LOADING) and not count
        failed = controller.state is LoadState.ERROR and not count
        self.save_button.setEnabled(not controller.busy and not failed)
        if waiting or failed:
            placeholder = "…" if waiting else "—"
            hint = self.tr("Loading…") if waiting else self.tr("Could not be listed")
            for stat in self.stats.values():
                stat.set_content(placeholder, hint)
        else:
            self.stats["count"].set_content(
                str(count), self.tr("%n profile(s) in total", "", count)
            )
            self.stats["active"].set_content(
                active.name if active else self.tr("None"),
                self.tr("In use now") if active else self.tr("Apply a profile"),
            )
            self.stats["size"].set_content(
                format_size(store.total_size_mb()), self.tr("Sum of all profiles")
            )
            self.stats["recent"].set_content(
                format_relative(latest) if latest else "—",
                self.tr("Most recent profile") if latest else "",
            )
        self._build_active(active if not (waiting or failed) else None)
        self._build_activity()

    def retranslate(self) -> None:
        """Rebuilds the figures and panels in the new language."""
        self.refresh()

    def _build_active(self, active) -> None:
        """Fills the active-profile panel."""
        clear_layout(self.active_layout)
        self.active_layout.addWidget(self.section_title(self.tr("Active profile")))
        if active is None:
            state = EmptyState(
                "profiles",
                self.tr("No active profile"),
                self.tr(
                    "Save the current configuration or apply a profile to see it "
                    "here."
                ),
                self.tr("Save current profile"),
                "save",
            )
            state.action_triggered.connect(self.save_button.click)
            self.active_layout.addWidget(state)
            return
        head = QHBoxLayout()
        head.addWidget(Label(active.name, "h2"), 1)
        head.addWidget(Badge(self.tr("Active"), "accent"))
        self.active_layout.addLayout(head)
        self.active_layout.addWidget(Label(active.description, "muted", wrap=True))
        chips = QHBoxLayout()
        chips.setSpacing(6)
        for section in active.sections:
            chips.addWidget(Badge(section.split(" (", maxsplit=1)[0]))
        chips.addStretch(1)
        self.active_layout.addLayout(chips)
        buttons = QHBoxLayout()
        view = Button(self.tr("View profiles"), icon_name="profiles")
        view.clicked.connect(lambda: self.ctx.navigate("profiles"))
        buttons.addWidget(view)
        if self.ctx.backend.capabilities.transfer:
            export = Button(self.tr("Export"), icon_name="export")
            export.clicked.connect(lambda: self.ctx.navigate("transfer"))
            buttons.addWidget(export)
        buttons.addStretch(1)
        self.active_layout.addSpacing(6)
        self.active_layout.addLayout(buttons)
        self.active_layout.addStretch(1)

    def _build_activity(self) -> None:
        """Fills the recent-activity panel."""
        clear_layout(self.activity_layout)
        self.activity_layout.addWidget(self.section_title(self.tr("Recent activity")))
        entries = self.ctx.activity.entries()[:RECENT_LIMIT]
        if not entries:
            hint = Label(self.tr("Nothing has happened yet."), "muted")
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.activity_layout.addWidget(hint)
            return
        for entry in entries:
            self.activity_layout.addWidget(ActivityRow(entry))
        self.activity_layout.addStretch(1)
