"""In-memory models shared by the pages.

Nothing here touches Konsave or the disk. When the real services replace the
fictitious data, only these models need an adapter; the widgets keep using
the same signals.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, QSettings, Signal

from kongui.gui.theme import ThemeMode


@dataclass(frozen=True)
class Profile:  # pylint: disable=too-many-instance-attributes
    """A saved profile as the interface shows it.

    Attributes:
        name: Unique profile name.
        description: Free text shown on the card.
        sections: Names of the configuration areas the profile covers.
        size_mb: Size on disk in megabytes.
        modified: Last modification time.
        active: Whether this is the profile applied most recently.
    """

    name: str
    description: str
    sections: Tuple[str, ...]
    size_mb: float
    modified: datetime
    active: bool = False


class ProfileStore(QObject):
    """Read-only view model of the profile list. Emits ``changed`` on updates.

    It is filled by the :class:`~kongui.gui.controller.ProfileController`; the
    pages only read from it.
    """

    changed = Signal()

    def __init__(
        self, profiles: Optional[List[Profile]] = None, parent: Optional[QObject] = None
    ) -> None:
        """Creates the store.

        Args:
            profiles: Initial profiles (empty by default).
            parent: Optional Qt parent.
        """
        super().__init__(parent)
        self._items: List[Profile] = list(profiles or [])

    def replace(self, profiles: List[Profile]) -> bool:
        """Replaces the whole list; emits ``changed`` only if something differs.

        Args:
            profiles: The new profiles, in display order.

        Returns:
            bool: Whether the content changed.
        """
        new_items = list(profiles)
        if new_items == self._items:
            return False
        self._items = new_items
        self.changed.emit()
        return True

    def profiles(self) -> List[Profile]:
        """Returns the profiles in order."""
        return list(self._items)

    def names(self) -> List[str]:
        """Returns the profile names in order."""
        return [item.name for item in self._items]

    def get(self, name: str) -> Optional[Profile]:
        """Returns one profile or ``None``."""
        return next((item for item in self._items if item.name == name), None)

    def active(self) -> Optional[Profile]:
        """Returns the active profile, if any."""
        return next((item for item in self._items if item.active), None)

    def total_size_mb(self) -> float:
        """Returns the summed size of all profiles."""
        return sum(item.size_mb for item in self._items)

    def latest_modified(self) -> Optional[datetime]:
        """Returns the most recent modification time, if any profile exists."""
        return max((item.modified for item in self._items), default=None)


@dataclass(frozen=True)
class ActivityEntry:
    """One line of the activity feed.

    Attributes:
        when: Time of the event.
        kind: ``"save"``, ``"apply"``, ``"export"``, ``"import"``, ``"remove"`` or ``"info"``.
        text: Description.
    """

    when: datetime
    kind: str
    text: str


class ActivityLog(QObject):
    """Newest-first activity feed. Emits ``changed`` when an entry is added."""

    changed = Signal()
    MAX_ENTRIES = 50

    def __init__(
        self, entries: Optional[List[ActivityEntry]] = None, parent=None
    ) -> None:
        """Creates the log.

        Args:
            entries: Initial entries, newest first.
            parent: Optional Qt parent.
        """
        super().__init__(parent)
        self._entries: List[ActivityEntry] = list(entries or [])

    def entries(self) -> List[ActivityEntry]:
        """Returns the entries, newest first."""
        return list(self._entries)

    def add(self, kind: str, text: str) -> ActivityEntry:
        """Records an event happening now.

        Args:
            kind: Event kind.
            text: Description.

        Returns:
            ActivityEntry: The new entry.
        """
        entry = ActivityEntry(datetime.now(), kind, text)
        self._entries = [entry] + self._entries[: self.MAX_ENTRIES - 1]
        self.changed.emit()
        return entry


class AppSettings(QObject):
    """Interface preferences. Persisted only when a file path is given.

    Without a path the values live in memory, which is what the tests use.
    """

    changed = Signal(str)

    DEFAULTS = {
        "theme": ThemeMode.SYSTEM.value,
        "toast_seconds": 5,
        "profiles_view": "grid",
        "last_applied": "",
    }

    def __init__(
        self, path: Optional[str] = None, parent: Optional[QObject] = None
    ) -> None:
        """Creates the settings.

        Args:
            path: INI file to read and write, or ``None`` for memory only.
            parent: Optional Qt parent.
        """
        super().__init__(parent)
        self._values: Dict[str, object] = dict(self.DEFAULTS)
        self._backend = QSettings(path, QSettings.Format.IniFormat) if path else None
        if self._backend is not None:
            for key, default in self.DEFAULTS.items():
                stored = self._backend.value(key, default)
                self._values[key] = self._coerce(key, stored)

    def _coerce(self, key: str, value: object) -> object:
        """Converts a stored value to the type of the default."""
        default = self.DEFAULTS[key]
        if isinstance(default, bool):
            return value in (True, "true", "1", 1)
        if isinstance(default, int):
            try:
                return max(1, min(60, int(value)))  # type: ignore[call-overload]
            except (TypeError, ValueError):
                return default
        text = str(value)
        if key == "theme":
            return ThemeMode.parse(text).value
        if key == "profiles_view":
            return text if text in ("grid", "list") else default
        return text

    def get(self, key: str) -> object:
        """Returns a setting.

        Args:
            key: One of :attr:`DEFAULTS`.

        Returns:
            object: The current value.

        Raises:
            KeyError: If the key is unknown.
        """
        if key not in self.DEFAULTS:
            raise KeyError(key)
        return self._values[key]

    def set(self, key: str, value: object) -> None:
        """Changes a setting, saving it when a file is configured.

        Args:
            key: One of :attr:`DEFAULTS`.
            value: The new value.

        Raises:
            KeyError: If the key is unknown.
        """
        coerced = self._coerce(key, value) if key in self.DEFAULTS else None
        if key not in self.DEFAULTS:
            raise KeyError(key)
        if coerced == self._values[key]:
            return
        self._values[key] = coerced
        if self._backend is not None:
            self._backend.setValue(key, coerced)
            self._backend.sync()
        self.changed.emit(key)
