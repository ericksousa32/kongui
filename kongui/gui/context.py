"""Objects every page receives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from kongui.gui.state import ActivityLog, AppSettings, ProfileStore
from kongui.gui.theme import ThemeManager
from kongui.gui.widgets.toast import ToastHost


@dataclass
class AppContext:
    """Shared services of the running window.

    Attributes:
        store: Fictitious profile list.
        activity: Activity feed.
        settings: Interface preferences.
        theme: Theme manager.
        toasts: Notification host.
        navigate: Switches to a page by key.
        export_profile: Opens the export form with a profile selected.
    """

    store: ProfileStore
    activity: ActivityLog
    settings: AppSettings
    theme: ThemeManager
    toasts: ToastHost
    navigate: Callable[[str], None]
    export_profile: Callable[[str], None]
