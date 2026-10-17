"""Objects every page receives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from kongui.gui.backend import ProfileBackend
from kongui.gui.controller import ProfileController
from kongui.gui.state import ActivityLog, AppSettings, ProfileStore
from kongui.gui.theme import ThemeManager
from kongui.gui.widgets.toast import ToastHost


@dataclass
class AppContext:
    """Shared services of the running window.

    Attributes:
        store: Profile list as the pages see it (filled by the controller).
        backend: The profile services in use (real or demo).
        controller: Runs operations and updates the store.
        activity: Activity feed.
        settings: Interface preferences.
        theme: Theme manager.
        toasts: Notification host.
        navigate: Switches to a page by key.
        export_profile: Opens the export form with a profile selected.
    """

    store: ProfileStore
    backend: ProfileBackend
    controller: ProfileController
    activity: ActivityLog
    settings: AppSettings
    theme: ThemeManager
    toasts: ToastHost
    navigate: Callable[[str], None]
    export_profile: Callable[[str], None]
