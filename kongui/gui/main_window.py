"""Main window: fixed sidebar, top bar and a stack of pages."""

from __future__ import annotations

from typing import Dict, List, Optional, Type

from PySide6.QtCore import QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from kongui.gui import i18n, messages
from kongui.gui.actions import OutcomeNotifier
from kongui.gui.backend import FakeBackend, ProfileBackend
from kongui.gui.context import AppContext
from kongui.gui.controller import ProfileController
from kongui.gui.mock_data import demo_activity
from kongui.gui.pages.about import AboutPage
from kongui.gui.pages.base import Page
from kongui.gui.pages.dashboard import DashboardPage
from kongui.gui.pages.profiles import ProfilesPage
from kongui.gui.pages.settings import SettingsPage
from kongui.gui.pages.transfer import TransferPage
from kongui.gui.state import ActivityLog, AppSettings, ProfileStore
from kongui.gui.tasks import Executor, ThreadExecutor
from kongui.gui.theme import ThemeMode, get_theme
from kongui.gui.widgets.feedback import BusyBar, WaitBanner
from kongui.gui.widgets.shell import Sidebar, TopBar
from kongui.gui.widgets.toast import ToastHost

PAGE_CLASSES: List[Type[Page]] = [
    DashboardPage,
    ProfilesPage,
    TransferPage,
    SettingsPage,
    AboutPage,
]


class MainWindow(QMainWindow):
    """The application window.

    Shortcuts: ``Ctrl+1`` … ``Ctrl+5`` switch pages, ``Ctrl+F`` focuses the
    profile search, ``Ctrl+N`` / ``Ctrl+S`` open the "save profile" dialog
    while the matching page is visible.
    """

    def __init__(
        self,
        settings: Optional[AppSettings] = None,
        backend: Optional[ProfileBackend] = None,
        activity: Optional[ActivityLog] = None,
        executor: Optional[Executor] = None,
    ) -> None:
        """Builds the window.

        Args:
            settings: Preferences; defaults to in-memory settings.
            backend: Profile services; defaults to the in-memory demo backend.
            activity: Activity feed; defaults to the fictitious feed in demo
                mode and to an empty one with a real backend.
            executor: Where blocking work runs; defaults to a worker thread.
        """
        super().__init__()
        self.setWindowTitle("KonGUI")
        self.setMinimumSize(900, 600)
        self.resize(1140, 740)
        self.settings = settings or AppSettings()
        self.language = i18n.manager()
        self.language.follow(self.settings)
        self.theme = get_theme()
        self.theme.set_mode(ThemeMode.parse(self.settings.get("theme")))

        self.backend = backend or FakeBackend()
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = Sidebar(demo=self.backend.capabilities.demo)
        self.top_bar = TopBar()
        self.stack = QStackedWidget()
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self.top_bar)
        self.busy_bar = BusyBar()
        column.addWidget(self.busy_bar)
        self.wait_banner = WaitBanner()
        column.addWidget(self.wait_banner)
        column.addWidget(self.stack, 1)
        layout.addWidget(self.sidebar)
        layout.addLayout(column, 1)

        self.toasts = ToastHost(root, int(self.settings.get("toast_seconds")))  # type: ignore[call-overload]
        self.executor = executor or ThreadExecutor()
        self.store = ProfileStore()
        self.controller = ProfileController(
            self.backend, self.executor, self.store, self.settings
        )
        if activity is None:
            activity = ActivityLog(
                demo_activity() if self.backend.capabilities.demo else []
            )
        self.context = AppContext(
            store=self.store,
            backend=self.backend,
            controller=self.controller,
            activity=activity,
            settings=self.settings,
            theme=self.theme,
            toasts=self.toasts,
            navigate=self.show_page,
            export_profile=self.open_export,
        )
        self.pages: Dict[str, Page] = {}
        for index, page_class in enumerate(PAGE_CLASSES, start=1):
            page = page_class(self.context)
            self.pages[page.key] = page
            self.stack.addWidget(page)
            self.sidebar.add_item(
                page.key,
                lambda page=page: page.title,  # type: ignore[misc]
                page.icon_name,
                f"Ctrl+{index}",
            )
            QShortcut(
                QKeySequence(f"Ctrl+{index}"),
                self,
                activated=self._page_shortcut(page.key),
            )
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.focus_search)

        self.sidebar.page_requested.connect(self.show_page)
        self.sidebar.theme_toggle_requested.connect(self.toggle_theme)
        self.settings.changed.connect(self._on_setting_changed)
        self.notifier = OutcomeNotifier(self.context)
        self.controller.state_changed.connect(self._sync_busy)
        self.wait_banner.cancel_requested.connect(self.controller.cancel_wait)
        i18n.bind(self, self._retranslate, now=False)
        self.show_page("dashboard")
        QTimer.singleShot(0, self.controller.refresh)

    def _retranslate(self) -> None:
        """Updates the window texts after a language change.

        The sidebar buttons, the pages and the toasts translate themselves; the
        top bar and the window title belong to the page being shown. The wait
        banner is rebuilt from the controller state.
        """
        page = self.stack.currentWidget()
        if page is None:
            return
        self.top_bar.set_page(page.title, page.subtitle, page.header_actions())  # type: ignore[attr-defined]
        self.setWindowTitle(f"{page.title} — KonGUI")  # type: ignore[attr-defined]
        self._sync_busy()

    def _sync_busy(self) -> None:
        """Shows the busy bar while an operation is running."""
        self.busy_bar.set_busy(self.controller.busy)
        controller = self.controller
        if controller.waiting:
            title, lines = messages.describe_wait(controller.waiting_holder)
        else:
            title, lines = "", ()
        self.wait_banner.set_waiting(
            controller.waiting, title, lines, cancelling=controller.cancelling
        )

    def closeEvent(self, event) -> None:  # pylint: disable=invalid-name
        """Refuses while an operation runs; asks about unsaved work; then closes.

        An operation of the original Konsave cannot be interrupted, and closing
        the window used to freeze it for five seconds, hide it and leave the
        operation running in a process nobody could see. Now the window stays
        until the operation is over.
        """
        if self.controller.busy:
            text = (
                self.tr(
                    "Cancel the wait or wait for the other operation to finish "
                    "before closing."
                )
                if self.controller.waiting
                else self.tr(
                    "Wait for it to finish before closing: closing now could "
                    "leave files half-written."
                )
            )
            self.toasts.show_message("warning", self.tr("Operation in progress"), text)
            event.ignore()
            return
        for page in self.pages.values():
            if not page.confirm_leave(self):
                event.ignore()
                return
        self.executor.shutdown()
        super().closeEvent(event)

    def _page_shortcut(self, key: str):
        """Returns a callback that opens one page."""
        return lambda: self.show_page(key)

    @property
    def current_key(self) -> str:
        """Key of the visible page."""
        return self.stack.currentWidget().key  # type: ignore[attr-defined]

    def show_page(self, key: str) -> Page:
        """Switches to a page.

        Args:
            key: Page key (``dashboard``, ``profiles``, ``transfer``,
                ``settings`` or ``about``).

        Returns:
            Page: The page now visible.

        Raises:
            KeyError: If the key is unknown.
        """
        page = self.pages[key]
        current = self.stack.currentWidget()
        if current is not None and current is not page:
            if not current.confirm_leave(self):  # type: ignore[attr-defined]
                self.sidebar.set_current(current.key)  # type: ignore[attr-defined]
                return current  # type: ignore[return-value]
        self.stack.setCurrentWidget(page)
        self.sidebar.set_current(key)
        self.top_bar.set_page(page.title, page.subtitle, page.header_actions())
        self.setWindowTitle(f"{page.title} — KonGUI")
        page.on_shown()
        return page

    def focus_search(self) -> None:
        """Opens the profiles page and focuses its search box."""
        page = self.show_page("profiles")
        if page.key == "profiles":
            page.focus_search()  # type: ignore[attr-defined]

    def open_export(self, name: str) -> None:
        """Opens the export form with a profile selected.

        Args:
            name: Profile name.
        """
        page = self.show_page("transfer")
        if page.key == "transfer":
            page.select_profile(name)  # type: ignore[attr-defined]

    def toggle_theme(self) -> None:
        """Switches between the light and dark themes."""
        self.settings.set(
            "theme", ThemeMode.LIGHT.value if self.theme.is_dark else "dark"
        )

    def _on_setting_changed(self, key: str) -> None:
        """Applies settings that affect the whole window."""
        if key == "theme":
            self.theme.set_mode(ThemeMode.parse(self.settings.get("theme")))
        elif key == "toast_seconds":
            self.toasts.default_seconds = int(self.settings.get(key))  # type: ignore[call-overload]
