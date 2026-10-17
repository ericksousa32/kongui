"""What the interface needs from the profile services, and two implementations.

This is the **only** GUI module that touches ``kongui.core``'s engine and
services. Everything else talks to a :class:`ProfileBackend`:

* :class:`ServiceBackend` calls the real :class:`~kongui.core.ProfileService`
  (and through it the original Konsave code) on one home directory.
* :class:`FakeBackend` keeps fictitious profiles in memory (demo mode, tests).

Backend methods are **blocking** and are meant to run in a worker thread (see
``kongui.gui.tasks``). They must not touch any Qt object.
"""

# pylint: disable=duplicate-code
from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
import weakref
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from kongui.core import (
    ArchiveExistsError,
    BackupInfo,
    ConfigService,
    ConfirmationRequiredError,
    KonsaveEngine,
    NotImplementedOperationError,
    OperationResult,
    Problem,
    ProfileExistsError,
    ProfileNotFoundError,
    ProfileService,
    SnapshotInfo,
    SnapshotNotFoundError,
    ValidationError,
)
from kongui.core import KEPT_PREFIX
from kongui.core.safety import validate_archive_name, validate_profile_name
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


#: Export conflict policies (see ``ProfileService.export``): refuse, pick a free
#: name, or replace an existing ``.knsv`` file.
ON_CONFLICT = ("error", "unique", "overwrite")


@dataclass(frozen=True)
class ArchiveInfo:  # pylint: disable=too-many-instance-attributes
    """What a ``.knsv`` file holds, for the import form.

    Attributes:
        path: Archive path as given.
        name: Profile name the file would create.
        size_mb: File size in megabytes.
        save_sections: Sections kept in the profile.
        export_sections: Sections written to the live system on import.
        warnings: Non-blocking observations.
        name_taken: A profile with that name already exists.
    """

    path: str
    name: str
    size_mb: float
    save_sections: Tuple[str, ...] = ()
    export_sections: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()
    name_taken: bool = False


@dataclass(frozen=True)
class ExportProbe:
    """What the export form needs to know about its target, read without writing.

    Attributes:
        path: Archive that would be written with the plain (``error``) policy.
        folder_problem: ``""`` if the folder is usable, else ``missing``,
            ``not_dir`` or ``not_writable``.
        conflict: ``""`` if the target is free, ``archive`` if a regular
            ``.knsv`` file is there (it can be replaced or the name made
            unique) or ``blocked`` if a folder, ``.zip`` or special file with
            that name exists (the original export would delete or replace it,
            so only a unique name is possible).
        unique_path: Archive that the ``unique`` policy would write.
    """

    path: str
    folder_problem: str = ""
    conflict: str = ""
    unique_path: str = ""


@dataclass(frozen=True)
class ConfigSnapshot:  # pylint: disable=too-many-instance-attributes
    """The ``conf.yaml`` as read for editing.

    Attributes:
        path: Where the file is (or would be created).
        exists: Whether the file exists. If not, ``text`` is the default
            template and saving creates the file.
        text: The contents.
        digest: Fingerprint to pass back when saving, to detect outside edits.
        backups: Saved previous versions, newest first.
        keywords: Placeholders of the form ``$NAME`` known to Konsave.
        functions: Function placeholders (``ENDS_WITH``…) known to Konsave.
        sandbox: The file is a temporary copy (demo mode), not the real one.
    """

    path: str
    exists: bool
    text: str
    digest: Optional[str]
    backups: Tuple[BackupInfo, ...] = ()
    keywords: Tuple[str, ...] = ()
    functions: Tuple[str, ...] = ()
    sandbox: bool = False


@dataclass(frozen=True)
class ConfigCheck:
    """Result of validating a candidate ``conf.yaml`` text.

    Attributes:
        problems: Errors and warnings, each with its position.
        resolved: ``(kind, group)`` → location after Konsave's own placeholder
            resolution (only when the text could be resolved).
    """

    problems: Tuple[Problem, ...] = ()
    resolved: Dict[Tuple[str, str], str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """Whether nothing blocks saving."""
        return not any(problem.is_error for problem in self.problems)


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


class ProfileBackend(ABC):  # pylint: disable=too-many-public-methods
    """Blocking profile operations. Every method may raise ``KonGuiError``."""

    capabilities: Capabilities

    @property
    def initial_active(self) -> Optional[str]:
        """Name to show as active before the user applies anything."""
        return None

    @property
    def engine_version(self) -> str:
        """Version of the Konsave engine in use (``konsave --version``), or ``""``."""
        return ""

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

    def list_backups(self) -> Tuple[SnapshotInfo, ...]:
        """Lists the safety copies made before apply/import, newest first.

        Raises:
            NotImplementedOperationError: If the backend keeps none.
        """
        raise NotImplementedOperationError("list_backups is not available")

    def restore_backup(
        self, backup_id: str, *, confirmed: bool = False
    ) -> OperationResult:
        """Puts the files of a safety copy back (destructive).

        Raises:
            NotImplementedOperationError: If the backend keeps none.
        """
        del backup_id, confirmed
        raise NotImplementedOperationError("restore_backup is not available")

    def delete_backup(
        self, backup_id: str, *, confirmed: bool = False
    ) -> OperationResult:
        """Deletes a safety copy (destructive).

        Raises:
            NotImplementedOperationError: If the backend keeps none.
        """
        del backup_id, confirmed
        raise NotImplementedOperationError("delete_backup is not available")

    @abstractmethod
    def wipe_all(self, *, confirmed: bool = False) -> OperationResult:
        """Deletes every profile."""

    def duplicate(self, name: str) -> OperationResult:
        """Duplicates a profile (only when ``capabilities.duplicate``).

        Raises:
            NotImplementedOperationError: If the backend cannot duplicate.
        """
        raise NotImplementedOperationError("duplicate is not available")

    def inspect_archive(self, path: str) -> ArchiveInfo:
        """Checks a ``.knsv`` file and describes it, writing nothing.

        Raises:
            NotImplementedOperationError: If the backend cannot transfer.
        """
        raise NotImplementedOperationError("inspect_archive is not available")

    def probe_export(self, directory: str, base: str) -> ExportProbe:
        """Looks at the export target (folder and name) without writing.

        Raises:
            NotImplementedOperationError: If the backend cannot transfer.
        """
        raise NotImplementedOperationError("probe_export is not available")

    def export_profile(
        self,
        name: str,
        directory: str,
        archive_name: Optional[str] = None,
        on_conflict: str = "error",
    ) -> OperationResult:
        """Exports a profile to ``<directory>/<archive_name>.knsv``.

        ``on_conflict`` is ``error`` (refuse), ``unique`` (free name) or
        ``overwrite`` (replace an existing ``.knsv`` file).

        Raises:
            NotImplementedOperationError: If the backend cannot transfer.
        """
        raise NotImplementedOperationError("export_profile is not available")

    def import_profile(
        self, path: str, name: Optional[str] = None, *, confirmed: bool = False
    ) -> OperationResult:
        """Imports a ``.knsv`` file as profile ``name`` (default: file name).

        Raises:
            NotImplementedOperationError: If the backend cannot transfer.
        """
        raise NotImplementedOperationError("import_profile is not available")

    def reset(self) -> OperationResult:
        """Restores the demo data (demo only).

        Raises:
            NotImplementedOperationError: If the backend is not a demo one.
        """
        raise NotImplementedOperationError("reset is demo only")

    # ------------------------------------------------------------- conf.yaml

    def _config_service(self, operation: str) -> ConfigService:
        """Returns the configuration service to use for ``operation``.

        Raises:
            NotImplementedOperationError: If the backend has none.
        """
        raise NotImplementedOperationError(f"{operation} is not available")

    def load_config(self) -> ConfigSnapshot:
        """Reads the ``conf.yaml`` (or the default template if there is none)."""
        config = self._config_service("load_config")
        exists = config.exists()
        if exists:
            try:
                text = config.read_text()
            except UnicodeDecodeError as error:
                raise ValidationError("conf.yaml is not valid UTF-8 text") from error
        else:
            text = config.default_text()
        placeholders = config.placeholders()
        return ConfigSnapshot(
            str(config.config_path),
            exists,
            text,
            config.digest(),
            config.list_backups(),
            placeholders["keywords"],
            placeholders["functions"],
            self.capabilities.demo,
        )

    def check_config(self, text: str) -> ConfigCheck:
        """Validates a candidate text with Konsave's own reader; writes nothing."""
        report = self._config_service("check_config").validate_text(text)
        resolved: Dict[Tuple[str, str], str] = {}
        for kind, groups in (report.resolved or {}).items():
            if isinstance(groups, dict):
                for name, body in groups.items():
                    if isinstance(body, dict) and "location" in body:
                        resolved[(str(kind), str(name))] = str(body["location"])
        return ConfigCheck(report.problems, resolved)

    def save_config(
        self, text: str, expected_digest: Optional[str], *, force: bool = False
    ) -> OperationResult:
        """Validates and writes the ``conf.yaml``, keeping the previous file.

        ``expected_digest`` is the digest the text was loaded with; the write is
        refused if the file changed since, unless ``force`` is set.

        Raises:
            ConfigValidationError: If the text is invalid (nothing is written).
            ConfigConflictError: If the file changed since it was loaded.
        """
        config = self._config_service("save_config")
        if force:
            return config.write_text(text)
        return config.write_text(text, expected_digest=expected_digest)

    def list_config_backups(self) -> Tuple[BackupInfo, ...]:
        """Lists the saved previous versions of the ``conf.yaml``."""
        return self._config_service("list_config_backups").list_backups()

    def read_config_backup(self, name: str) -> str:
        """Reads one backup."""
        return self._config_service("read_config_backup").read_backup(name)

    def restore_config(
        self, name: str, expected_digest: Optional[str], *, force: bool = False
    ) -> OperationResult:
        """Puts a backup back (after validating it); the current file is kept
        as a new backup.

        Raises:
            BackupNotFoundError: If there is no such backup.
            ConfigValidationError: If the backup is not a valid configuration.
            ConfigConflictError: If the file changed since it was loaded.
        """
        config = self._config_service("restore_config")
        if force:
            return config.restore_backup(name)
        return config.restore_backup(name, expected_digest=expected_digest)


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
        duplicate=False, transfer=True, descriptions=False, sections=False, demo=False
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

    @property
    def engine_version(self) -> str:
        """Version of the original Konsave loaded by the engine."""
        return self._service.engine.version

    def _config_service(self, operation: str) -> ConfigService:
        """The real configuration service."""
        del operation
        return self._service.config

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

    def list_backups(self) -> Tuple[SnapshotInfo, ...]:
        """Lists the safety copies of ``~/.config/konsave/kongui-backups``."""
        return tuple(self._service.list_backups())

    def restore_backup(
        self, backup_id: str, *, confirmed: bool = False
    ) -> OperationResult:
        """Restores the files of a safety copy."""
        return self._service.restore_backup(backup_id, confirmed=confirmed)

    def delete_backup(
        self, backup_id: str, *, confirmed: bool = False
    ) -> OperationResult:
        """Deletes a safety copy."""
        return self._service.delete_backup(backup_id, confirmed=confirmed)

    def _expand(self, path: str) -> Path:
        """Expands a leading ``~`` against the engine's home directory."""
        text = str(path).strip()
        home = self._service.engine.home
        if text == "~":
            return Path(home)
        if text.startswith("~/"):
            return Path(home) / text[2:]
        return Path(text)

    def inspect_archive(self, path: str) -> ArchiveInfo:
        """Reads a ``.knsv`` without extracting it."""
        info = self._service.inspect_archive(self._expand(path))
        return ArchiveInfo(
            str(info.path),
            info.name,
            round(info.size_bytes / 1048576, 1),
            info.save_sections,
            info.export_sections,
            info.warnings,
            info.name_taken,
        )

    def probe_export(self, directory: str, base: str) -> ExportProbe:
        """Checks the output folder and whether the archive name is taken."""
        folder = self._expand(directory)
        suffix = self._service.engine.export_extension
        path = str(folder / f"{base}{suffix}")
        if not folder.exists():
            return ExportProbe(path, "missing")
        if not folder.is_dir():
            return ExportProbe(path, "not_dir")
        if not os.access(folder, os.W_OK | os.X_OK):
            return ExportProbe(path, "not_writable")

        def taken(name: str) -> list:
            return [
                item
                for item in (
                    folder / name,
                    folder / f"{name}{suffix}",
                    folder / f"{name}.zip",
                )
                if os.path.lexists(item)
            ]

        conflict = ""
        if taken(base):
            archive = folder / f"{base}{suffix}"
            only_archive = (
                taken(base) == [archive]
                and archive.is_file()
                and not archive.is_symlink()
            )
            conflict = "archive" if only_archive else "blocked"
        unique, counter = base, 1
        while taken(unique) and counter < 1000:
            counter += 1
            unique = f"{base}-{counter}"
        return ExportProbe(path, "", conflict, str(folder / f"{unique}{suffix}"))

    def export_profile(
        self,
        name: str,
        directory: str,
        archive_name: Optional[str] = None,
        on_conflict: str = "error",
    ) -> OperationResult:
        """Exports with the original ``export`` (``-e``, ``-d``, ``-n``, ``-f``).

        The original CLI creates the default ``conf.yaml`` at start-up, on every
        command, and ``export`` copies that file into the archive. A fresh
        account that only imported a profile has none, so it is created here
        too (an existing file is never touched).
        """
        self._service.config.ensure_default_config()
        return self._service.export(
            name,
            directory=self._expand(directory),
            archive_name=archive_name or None,
            on_conflict=on_conflict,
        )

    def import_profile(
        self, path: str, name: Optional[str] = None, *, confirmed: bool = False
    ) -> OperationResult:
        """Imports with the original ``import_profile`` (``-i``).

        The original names the profile after the file. To use another name, the
        very same file is copied to a private temporary folder under that name
        and imported from there; the archive format is untouched.
        """
        _require(confirmed, "import")
        source = self._expand(path)
        info = self._service.inspect_archive(source)
        target = validate_profile_name(name) if name else info.name
        if target == info.name:
            return self._service.import_profile(source, confirmed=True)
        suffix = self._service.engine.export_extension
        staging = Path(tempfile.mkdtemp(prefix="kongui-import-"))
        try:
            copy = staging / f"{target}{suffix}"
            shutil.copyfile(source, copy)
            return self._service.import_profile(copy, confirmed=True)
        finally:
            shutil.rmtree(staging, ignore_errors=True)


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
        archives: Optional[List[str]] = None,
    ) -> None:
        """Creates the backend.

        Args:
            profiles: Initial profiles; the fictitious ones by default.
            latency: Seconds every call sleeps, to make loading states visible.
            active: Name reported by :attr:`initial_active`.
            archives: Paths of archives that "already exist" in the fictitious
                file system (``~/Downloads/Minimalista.knsv`` by default).
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
        self.blocked: set = set()
        self._copies: List[SnapshotInfo] = []
        self.archives = set(
            ["~/Downloads/Minimalista.knsv"] if archives is None else archives
        )
        self._sandbox: Optional[ConfigService] = None

    @property
    def initial_active(self) -> Optional[str]:
        """The profile shown as active at start."""
        return self._active

    def _config_service(self, operation: str) -> ConfigService:
        """A real configuration service on a private temporary home.

        Demo mode edits a throw-away copy of the default KDE ``conf.yaml``
        with the genuine validation, so the editor behaves as it would for
        real, and the user's own file is never read or written.
        """
        self._enter(operation)
        with self._lock:
            if self._sandbox is None:
                folder = tempfile.mkdtemp(prefix="kongui-demo-")
                weakref.finalize(self, shutil.rmtree, folder, True)
                config = ConfigService(KonsaveEngine(Path(folder)))
                config.ensure_default_config(kind="kde")
                self._sandbox = config
            return self._sandbox

    def fail_next(self, operation: str, error: BaseException) -> None:
        """Makes the next call of ``operation`` raise ``error`` (tests).

        Args:
            operation: ``list``, ``save``, ``overwrite``, ``apply``, ``remove``,
                ``wipe_all``, ``duplicate``, ``add_profile`` or one of the
                ``conf.yaml`` operations (``load_config``, ``check_config``,
                ``save_config``, ``list_config_backups``,
                ``read_config_backup``, ``restore_config``).
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
        copy = self._keep_copy("apply", name)
        return replace(
            self._ok("apply", f"profile '{name}' applied"),
            backup=copy.path,
            warnings=(f"{KEPT_PREFIX}{copy.id}",),
        )

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

    def probe_export(self, directory: str, base: str) -> ExportProbe:
        """Looks at the fictitious file system."""
        path = self._archive_path(directory, base)
        if not directory.strip():
            return ExportProbe(path, "missing")

        def taken(candidate: str) -> bool:
            return candidate in self.archives or candidate in self.blocked

        conflict = ""
        if taken(path):
            conflict = "blocked" if path in self.blocked else "archive"
        unique, counter = path, 1
        while taken(unique):
            counter += 1
            unique = self._archive_path(directory, f"{base}-{counter}")
        return ExportProbe(path, "", conflict, unique)

    @staticmethod
    def _archive_path(directory: str, base: str) -> str:
        """Joins a folder and an archive base name the way the real one does."""
        return f"{directory.strip().rstrip('/')}/{base}.knsv"

    def inspect_archive(self, path: str) -> ArchiveInfo:
        """Describes a fictitious archive; only the file name (and size, if the
        file happens to exist) is looked at, the file is never opened."""
        self._enter("inspect_archive", path)
        if not path.endswith(".knsv") or path.endswith("/.knsv"):
            raise ValidationError("archive must be a '*.knsv' file")
        name = validate_profile_name(os.path.basename(path)[: -len(".knsv")])
        try:
            size = round(os.stat(os.path.expanduser(path)).st_size / 1048576, 1)
        except OSError:
            size = 8.0 + 6.1 * 5
        with self._lock:
            taken = name in self._items
        return ArchiveInfo(
            path, name, size, tuple(SECTIONS[:4]), (SECTIONS[4],), (), taken
        )

    def export_profile(
        self,
        name: str,
        directory: str,
        archive_name: Optional[str] = None,
        on_conflict: str = "error",
    ) -> OperationResult:
        """Pretends to export, following the real conflict rules."""
        self._enter("export", name)
        if on_conflict not in ON_CONFLICT:
            raise ValidationError(f"on_conflict must be one of {ON_CONFLICT}")
        base = validate_archive_name(archive_name) if archive_name else name
        if not directory.strip():
            raise ValidationError("output folder is required")
        with self._lock:
            if name not in self._items:
                raise ProfileNotFoundError(f"profile not found: {name}")
            target = self._archive_path(directory, base)
            if target in self.blocked and on_conflict != "unique":
                raise ArchiveExistsError(f"refusing to overwrite: {target}")
            if target in self.archives or target in self.blocked:
                if on_conflict == "error":
                    raise ArchiveExistsError(f"already exists: {target}")
                if on_conflict == "unique":
                    counter = 2
                    while self._archive_path(directory, f"{base}-{counter}") in (
                        self.archives | self.blocked
                    ):
                        counter += 1
                    target = self._archive_path(directory, f"{base}-{counter}")
            self.archives.add(target)
        return OperationResult(
            "export", True, f"profile '{name}' exported to {target}", path=Path(target)
        )

    def import_profile(
        self, path: str, name: Optional[str] = None, *, confirmed: bool = False
    ) -> OperationResult:
        """Pretends to import: adds a fictitious profile."""
        _require(confirmed, "import")
        info = self.inspect_archive(path)
        target = validate_profile_name(name) if name else info.name
        self._enter("import", target)
        with self._lock:
            if target in self._items:
                raise ProfileExistsError(f"profile already exists: {target}")
            sections = tuple(info.save_sections) + tuple(info.export_sections)
            self._items[target] = Profile(
                target,
                f"Importado de {os.path.basename(path)}.",
                sections,
                max(info.size_mb, 0.1),
                datetime.now(),
            )
        copy = self._keep_copy("import", target)
        return OperationResult(
            "import",
            True,
            f"profile '{target}' imported",
            path=Path(target),
            backup=copy.path,
            warnings=(f"{KEPT_PREFIX}{copy.id}",),
        )

    def _keep_copy(self, operation: str, profile: str) -> SnapshotInfo:
        """Records a fictitious safety copy."""
        with self._lock:
            moment = datetime.now()
            number = len(self._copies) + 1
            copy_id = f"{moment:%Y%m%d-%H%M%S}-{number:06d}-{operation}"
            copy = SnapshotInfo(
                copy_id,
                Path("/demo/kongui-backups") / copy_id,
                operation,
                profile,
                moment,
                3,
                1,
                2048,
                True,
            )
            self._copies.insert(0, copy)
            return copy

    def list_backups(self) -> Tuple[SnapshotInfo, ...]:
        """Lists the fictitious safety copies."""
        self._enter("list_backups")
        with self._lock:
            return tuple(self._copies)

    def _find_copy(self, backup_id: str) -> SnapshotInfo:
        """Returns a fictitious copy or raises like the real service."""
        with self._lock:
            for copy in self._copies:
                if copy.id == backup_id:
                    return copy
        raise SnapshotNotFoundError(f"no such safety copy: {backup_id}")

    def restore_backup(
        self, backup_id: str, *, confirmed: bool = False
    ) -> OperationResult:
        """Pretends to restore a safety copy."""
        _require(confirmed, "restore_backup")
        self._enter("restore_backup", backup_id)
        copy = self._find_copy(backup_id)
        return self._ok("restore_backup", f"restored from {copy.id}")

    def delete_backup(
        self, backup_id: str, *, confirmed: bool = False
    ) -> OperationResult:
        """Pretends to delete a safety copy."""
        _require(confirmed, "delete_backup")
        self._enter("delete_backup", backup_id)
        copy = self._find_copy(backup_id)
        with self._lock:
            self._copies.remove(copy)
        return self._ok("delete_backup", f"safety copy {copy.id} deleted")

    def reset(self) -> OperationResult:
        """Restores the initial profiles."""
        self._enter("reset")
        with self._lock:
            self._items = {item.name: item for item in self._initial}
            self._copies = []
        return self._ok("reset", "demo data restored")
