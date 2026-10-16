"""In-memory models shared by the pages.

Nothing here touches Konsave or the disk. When the real services replace the
fictitious data, only these models need an adapter; the widgets keep using
the same signals.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

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
    """Editable list of profiles. Emits ``changed`` after every mutation."""

    changed = Signal()

    def __init__(
        self, factory: Callable[[], List[Profile]], parent: Optional[QObject] = None
    ):
        """Creates the store.

        Args:
            factory: Returns the initial (fictitious) profiles; also used by
                :meth:`reset_demo`.
            parent: Optional Qt parent.
        """
        super().__init__(parent)
        self._factory = factory
        self._items: Dict[str, Profile] = {}
        self._load(factory())

    def _load(self, items: List[Profile]) -> None:
        """Replaces the content without emitting."""
        self._items = {item.name: item for item in items}

    def profiles(self) -> List[Profile]:
        """Returns the profiles in insertion order."""
        return list(self._items.values())

    def names(self) -> List[str]:
        """Returns the profile names in insertion order."""
        return list(self._items)

    def get(self, name: str) -> Optional[Profile]:
        """Returns one profile or ``None``."""
        return self._items.get(name)

    def active(self) -> Optional[Profile]:
        """Returns the active profile, if any."""
        return next((item for item in self._items.values() if item.active), None)

    def total_size_mb(self) -> float:
        """Returns the summed size of all profiles."""
        return sum(item.size_mb for item in self._items.values())

    def latest_modified(self) -> Optional[datetime]:
        """Returns the most recent modification time, if any profile exists."""
        return max((item.modified for item in self._items.values()), default=None)

    def add(self, profile: Profile) -> None:
        """Adds a profile.

        Args:
            profile: The new profile.

        Raises:
            ValueError: If the name is already used.
        """
        if profile.name in self._items:
            raise ValueError(f"profile already exists: {profile.name}")
        self._items[profile.name] = profile
        self.changed.emit()

    def remove(self, name: str) -> None:
        """Removes a profile.

        Args:
            name: Profile name.

        Raises:
            KeyError: If the profile does not exist.
        """
        del self._items[name]
        self.changed.emit()

    def activate(self, name: str) -> None:
        """Marks one profile as active and clears the flag on the others.

        Args:
            name: Profile name.

        Raises:
            KeyError: If the profile does not exist.
        """
        if name not in self._items:
            raise KeyError(name)
        now = datetime.now()
        self._items = {
            key: replace(
                item, active=key == name, modified=now if key == name else item.modified
            )
            for key, item in self._items.items()
        }
        self.changed.emit()

    def unique_copy_name(self, name: str) -> str:
        """Returns a free name for a copy of ``name``.

        Args:
            name: Original name.

        Returns:
            str: ``"<name> (cópia)"``, numbered when taken.
        """
        candidate = f"{name} (cópia)"
        counter = 2
        while candidate in self._items:
            candidate = f"{name} (cópia {counter})"
            counter += 1
        return candidate

    def duplicate(self, name: str) -> Profile:
        """Duplicates a profile.

        Args:
            name: Profile to copy.

        Returns:
            Profile: The new (inactive) copy.

        Raises:
            KeyError: If the profile does not exist.
        """
        original = self._items[name]
        copy = replace(
            original,
            name=self.unique_copy_name(name),
            active=False,
            modified=datetime.now(),
        )
        self.add(copy)
        return copy

    def clear(self) -> None:
        """Removes every profile (to demonstrate the empty state)."""
        self._items = {}
        self.changed.emit()

    def reset_demo(self) -> None:
        """Restores the fictitious profiles."""
        self._load(self._factory())
        self.changed.emit()


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
        "confirm_apply": True,
        "toast_seconds": 5,
        "profiles_view": "grid",
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
