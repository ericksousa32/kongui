"""What the interface needs from the profile services, and two implementations.

This is the **only** GUI module that touches ``kongui.core``'s engine and
services. Everything else talks to a :class:`ProfileBackend`:

* :class:`ServiceBackend` calls the real :class:`~kongui.core.ProfileService`
  (and through it the original Konsave code) on one home directory.
* :class:`FakeBackend` keeps fictitious profiles in memory (demo mode, tests).

Backend methods are **blocking** and are meant to run in a worker thread (see
``kongui.gui.tasks``). They must not touch any Qt object.
"""

from __future__ import annotations

import os
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from kongui.core import (
    ConfirmationRequiredError,
    KonsaveEngine,
    NotImplementedOperationError,
    OperationResult,
    ProfileExistsError,
    ProfileNotFoundError,
    ProfileService,
)
from kongui.gui.mock_data import SECTIONS, demo_profiles
from kongui.gui.state import Profile


@dataclass(frozen=True)
class Capabilities:
    """What a backend can do, so the interface hides what it cannot.

    Attributes:
        duplicate: Duplicating a profile exists.
        transfer: Import and export work (simulated in demo mode only).
        descriptions: Profiles carry a free-text description.
        sections: The user may choose which sections a profile saves.
        demo: Fictitious data; extra demo-only controls make sense.
    """

    duplicate: bool
    transfer: bool
    descriptions: bool
    sections: bool
    demo: bool


def _require(confirmed: bool, operation: str) -> None:
    """Refuses a destructive call that was not explicitly confirmed.

    Args:
        confirmed: Value received.
        operation: Operation name for the message.

    Raises:
        ConfirmationRequiredError: If ``confirmed`` is not exactly ``True``.
    """
    if confirmed is not True:
        raise ConfirmationRequiredError(f"'{operation}' needs confirmed=True")


class ProfileBackend(ABC):
    """Blocking profile operations. Every method may raise ``KonGuiError``."""

    capabilities: Capabilities

    @property
    def initial_active(self) -> Optional[str]:
        """Name to show as active before the user applies anything."""
        return None

    @abstractmethod
    def list_profiles(self) -> List[Profile]:
        """Returns the saved profiles, sorted by name."""

    @abstractmethod
    def save(
        self, name: str, description: str = "", sections: Tuple[str, ...] = ()
    ) -> OperationResult:
        """Saves the current configuration as a new profile."""

    @abstractmethod
    def overwrite(self, name: str, *, confirmed: bool = False) -> OperationResult:
        """Replaces an existing profile with the current configuration."""

    @abstractmethod
    def apply(self, name: str, *, confirmed: bool = False) -> OperationResult:
        """Applies a profile to the live session."""

    @abstractmethod
    def remove(self, name: str, *, confirmed: bool = False) -> OperationResult:
        """Deletes one profile."""

    @abstractmethod
    def wipe_all(self, *, confirmed: bool = False) -> OperationResult:
        """Deletes every profile."""

    def duplicate(self, name: str) -> OperationResult:
        """Duplicates a profile (only when ``capabilities.duplicate``).

        Raises:
            NotImplementedOperationError: If the backend cannot duplicate.
        """
        raise NotImplementedOperationError("duplicate is not available")

    def add_profile(self, profile: Profile) -> OperationResult:
        """Adds a ready-made profile (demo import only).

        Raises:
            NotImplementedOperationError: If the backend is not a demo one.
        """
        raise NotImplementedOperationError("add_profile is demo only")

    def reset(self) -> OperationResult:
        """Restores the demo data (demo only).

        Raises:
            NotImplementedOperationError: If the backend is not a demo one.
        """
        raise NotImplementedOperationError("reset is demo only")


def folder_size_mb(path: Path) -> float:
    """Sums the size of the regular files below a folder.

    Symlinks are counted as links, never followed. Unreadable entries are
    skipped.

    Args:
        path: Folder to measure.

    Returns:
        float: Size in megabytes.
    """
    total = 0
    for base, _dirs, files in os.walk(path, followlinks=False):
        for name in files:
            try:
                total += os.lstat(os.path.join(base, name)).st_size
            except OSError:
                continue
    return total / 1048576


class ServiceBackend(ProfileBackend):
    """Real operations, through :class:`~kongui.core.ProfileService`."""

    capabilities = Capabilities(
        duplicate=False, transfer=False, descriptions=False, sections=False, demo=False
    )

    def __init__(self, service: ProfileService) -> None:
        """Creates the backend.

        Args:
            service: A service bound to the home directory in use.
        """
        self._service = service

    @classmethod
    def create(cls, home: Optional[Path] = None) -> "ServiceBackend":
        """Builds the engine and the service for a home directory.

        Args:
            home: Home directory; defaults to the real one.

        Returns:
            ServiceBackend: The backend.

        Raises:
            RunningAsRootError: If the process runs as root.
            EngineLoadError: If the original Konsave cannot be loaded.
        """
        return cls(ProfileService(KonsaveEngine(home)))

    @property
    def service(self) -> ProfileService:
        """The wrapped service."""
        return self._service

    def list_profiles(self) -> List[Profile]:
        """Lists profiles. Konsave stores no description or section list."""
        result = []
        for info in self._service.list_profiles():
            modified = (
                datetime.fromtimestamp(info.modified)
                if info.modified is not None
                else datetime.fromtimestamp(0)
            )
            result.append(
                Profile(
                    info.name, "", (), round(folder_size_mb(info.path), 1), modified
                )
            )
        return result

    def save(
        self, name: str, description: str = "", sections: Tuple[str, ...] = ()
    ) -> OperationResult:
        """Saves the current configuration; creates the default ``conf.yaml`` first.

        ``description`` and ``sections`` are ignored: Konsave cannot store them.
        """
        del description, sections
        self._service.config.ensure_default_config()
        return self._service.save(name)

    def overwrite(self, name: str, *, confirmed: bool = False) -> OperationResult:
        """Replaces the profile (a real replacement, see ``ProfileService.replace``)."""
        return self._service.replace(name, confirmed=confirmed)

    def apply(self, name: str, *, confirmed: bool = False) -> OperationResult:
        """Applies the profile to the live home directory."""
        return self._service.apply(name, confirmed=confirmed)

    def remove(self, name: str, *, confirmed: bool = False) -> OperationResult:
        """Deletes the profile."""
        return self._service.remove(name, confirmed=confirmed)

    def wipe_all(self, *, confirmed: bool = False) -> OperationResult:
        """Deletes every profile."""
        return self._service.wipe_all(confirmed=confirmed)


class FakeBackend(ProfileBackend):
    """In-memory profiles for demo mode and tests.

    It mirrors the real rules (exists / not found / confirmation) so the
    interface behaves the same way with either backend.

    Attributes:
        calls: Log of ``(operation, name)`` in call order.
    """

    capabilities = Capabilities(
        duplicate=True, transfer=True, descriptions=True, sections=True, demo=True
    )

    def __init__(
        self,
        profiles: Optional[List[Profile]] = None,
        *,
        latency: float = 0.0,
        active: Optional[str] = "Trabalho",
    ) -> None:
        """Creates the backend.

        Args:
            profiles: Initial profiles; the fictitious ones by default.
            latency: Seconds every call sleeps, to make loading states visible.
            active: Name reported by :attr:`initial_active`.
        """
        self._lock = threading.Lock()
        self._initial = [
            replace(item, active=False)
            for item in (demo_profiles() if profiles is None else profiles)
        ]
        self._items: Dict[str, Profile] = {item.name: item for item in self._initial}
        self._latency = latency
        self._active = active
        self._failures: Dict[str, BaseException] = {}
        self.calls: List[Tuple[str, str]] = []

    @property
    def initial_active(self) -> Optional[str]:
        """The profile shown as active at start."""
        return self._active

    def fail_next(self, operation: str, error: BaseException) -> None:
        """Makes the next call of ``operation`` raise ``error`` (tests).

        Args:
            operation: ``list``, ``save``, ``overwrite``, ``apply``, ``remove``,
                ``wipe_all``, ``duplicate`` or ``add_profile``.
            error: Exception to raise once.
        """
        self._failures[operation] = error

    def _enter(self, operation: str, name: str = "") -> None:
        """Records a call, sleeps for the latency and raises a planned failure."""
        with self._lock:
            self.calls.append((operation, name))
            failure = self._failures.pop(operation, None)
        if self._latency:
            time.sleep(self._latency)
        if failure is not None:
            raise failure

    @staticmethod
    def _ok(operation: str, message: str) -> OperationResult:
        """Builds a successful result."""
        return OperationResult(operation, True, message)

    def list_profiles(self) -> List[Profile]:
        """Returns the profiles sorted by name (never marked active)."""
        self._enter("list")
        with self._lock:
            return sorted(self._items.values(), key=lambda item: item.name.casefold())

    def save(
        self, name: str, description: str = "", sections: Tuple[str, ...] = ()
    ) -> OperationResult:
        """Adds a new profile with an invented size."""
        self._enter("save", name)
        with self._lock:
            if name in self._items:
                raise ProfileExistsError(f"profile already exists: {name}")
            chosen = tuple(sections) or SECTIONS[:5]
            self._items[name] = Profile(
                name,
                description or "Sem descrição.",
                chosen,
                round(4.0 + 7.3 * len(chosen), 1),
                datetime.now(),
            )
        return self._ok("save", f"profile '{name}' saved")

    def overwrite(self, name: str, *, confirmed: bool = False) -> OperationResult:
        """Refreshes the modification time and size of an existing profile."""
        _require(confirmed, "overwrite")
        self._enter("overwrite", name)
        with self._lock:
            old = self._items.get(name)
            if old is None:
                raise ProfileNotFoundError(f"profile not found: {name}")
            self._items[name] = replace(
                old, modified=datetime.now(), size_mb=old.size_mb + 0.1
            )
        return self._ok("overwrite", f"profile '{name}' replaced")

    def apply(self, name: str, *, confirmed: bool = False) -> OperationResult:
        """Pretends to apply a profile."""
        _require(confirmed, "apply")
        self._enter("apply", name)
        with self._lock:
            if name not in self._items:
                raise ProfileNotFoundError(f"profile not found: {name}")
        return self._ok("apply", f"profile '{name}' applied")

    def remove(self, name: str, *, confirmed: bool = False) -> OperationResult:
        """Removes one profile."""
        _require(confirmed, "remove")
        self._enter("remove", name)
        with self._lock:
            if name not in self._items:
                raise ProfileNotFoundError(f"profile not found: {name}")
            del self._items[name]
        return self._ok("remove", f"profile '{name}' removed")

    def wipe_all(self, *, confirmed: bool = False) -> OperationResult:
        """Removes every profile."""
        _require(confirmed, "wipe_all")
        self._enter("wipe_all")
        with self._lock:
            self._items.clear()
        return self._ok("wipe_all", "all profiles removed")

    def duplicate(self, name: str) -> OperationResult:
        """Copies a profile under a free name."""
        self._enter("duplicate", name)
        with self._lock:
            original = self._items.get(name)
            if original is None:
                raise ProfileNotFoundError(f"profile not found: {name}")
            candidate, counter = f"{name} (cópia)", 2
            while candidate in self._items:
                candidate, counter = f"{name} (cópia {counter})", counter + 1
            self._items[candidate] = replace(
                original, name=candidate, modified=datetime.now()
            )
        return self._ok("duplicate", candidate)

    def add_profile(self, profile: Profile) -> OperationResult:
        """Adds a ready-made profile (simulated import)."""
        self._enter("add_profile", profile.name)
        with self._lock:
            if profile.name in self._items:
                raise ProfileExistsError(f"profile already exists: {profile.name}")
            self._items[profile.name] = replace(profile, active=False)
        return self._ok("add_profile", profile.name)

    def reset(self) -> OperationResult:
        """Restores the initial profiles."""
        self._enter("reset")
        with self._lock:
            self._items = {item.name: item for item in self._initial}
        return self._ok("reset", "demo data restored")
