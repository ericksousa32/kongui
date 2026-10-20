"""Profile service: save, apply, remove, export, import and wipe profiles.

Every operation reuses the original ``konsave.funcs`` through
:class:`~kongui.core.engine.KonsaveEngine`. This layer adds what the original
lacks: argument checks and safety refusals *before* anything is written (an
archive or a profile that would write outside the home), fresh profile lists,
outcome detection (the original always returns ``None``), and clean-up of
leftovers it can prove it created itself. ``conf.yaml`` files are read through
Konsave itself (:meth:`ConfigService.resolve`), never validated or rewritten.
"""

# pylint: disable=too-many-lines  # one service, one cohesive class

from __future__ import annotations

import os
import shutil
import tempfile
import time
import zipfile
import zlib
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from kongui.core.config import ConfigService, Groups
from kongui.core.engine import EngineCall, KonsaveEngine
from kongui.core.errors import (
    ArchiveExistsError,
    ArchiveLimitError,
    ConfigError,
    ConfigMissingError,
    ConfirmationRequiredError,
    ProfileExistsError,
    ProfileInvalidError,
    ProfileNotFoundError,
    ValidationError,
)
from kongui.core.lock import EXCLUSIVE, SHARED, guarded
from kongui.core.profilemeta import (
    DESCRIPTION_NOT_REMOVED,
    DESCRIPTION_NOT_SAVED,
    ProfileDetails,
    clean_description,
    copy_description,
    profile_sections,
    read_description,
    remove_description,
    write_description,
)
from kongui.core.results import ArchiveInspection, OperationResult, ProfileInfo
from kongui.core.snapshot import KEPT_PREFIX, SnapshotInfo, SnapshotService
from kongui.core.safety import (
    MAX_ARCHIVE_BYTES,
    MAX_ARCHIVE_ENTRIES,
    MAX_EXTRACTED_BYTES,
    RESERVED_PREFIX,
    is_plain_name,
    require_free_space,
    tree_size,
    validate_archive_name,
    validate_profile_name,
)

ON_CONFLICT_CHOICES = ("error", "unique", "overwrite")

#: Bytes read at a time while counting what an archive decompresses to.
_COUNT_CHUNK = 1 << 20

#: Prefix of the temporary folders ``replace`` creates inside the profiles
#: folder. They are never listed as profiles, so profile names may not start
#: with it (see :func:`kongui.core.safety.validate_profile_name`).
TEMP_PREFIX = RESERVED_PREFIX

#: Operations that are planned but deliberately not implemented yet. Empty
#: since the safety copies (RN-01) exist; kept so the API stays stable.
NOT_IMPLEMENTED_OPERATIONS: Mapping[str, str] = {}


class ProfileService:
    """High level operations on Konsave profiles."""

    def __init__(
        self, engine: KonsaveEngine, config: Optional[ConfigService] = None
    ) -> None:
        """Creates the service.

        Args:
            engine: Engine bound to the home directory in use.
            config: Configuration service; created from ``engine`` if omitted.
        """
        self._engine = engine
        self._config = config if config is not None else ConfigService(engine)
        self._snapshots = SnapshotService(engine.konsave_dir, engine.home)

    @property
    def engine(self) -> KonsaveEngine:
        """The engine used by this service."""
        return self._engine

    @property
    def config(self) -> ConfigService:
        """The configuration service used by this service."""
        return self._config

    # ------------------------------------------------------------------ queries

    @guarded(SHARED)
    def list_profiles(self) -> List[ProfileInfo]:
        """Lists the saved profiles, fresh from disk.

        Returns:
            List[ProfileInfo]: One entry per profile folder, sorted by name.
            Loose files in the profiles folder are ignored.
        """
        profiles = []
        for name in self._engine.profile_names():
            path = self._engine.profiles_dir / name
            if name.startswith(TEMP_PREFIX) or not path.is_dir():
                continue
            try:
                modified: Optional[float] = path.stat().st_mtime
            except OSError:
                modified = None
            profiles.append(
                ProfileInfo(name, path, (path / "conf.yaml").is_file(), modified)
            )
        return profiles

    @guarded(SHARED)
    def get_profile(self, name: str) -> ProfileInfo:
        """Returns one profile.

        Args:
            name: Profile name.

        Returns:
            ProfileInfo: The profile.

        Raises:
            ValidationError: If the name is not acceptable.
            ProfileNotFoundError: If there is no such profile.
        """
        validate_profile_name(name)
        for profile in self.list_profiles():
            if profile.name == name:
                return profile
        raise ProfileNotFoundError(f"profile not found: {name}")

    @guarded(SHARED)
    def profile_details(self, names: Iterable[str]) -> Dict[str, ProfileDetails]:
        """Reads the description and the sections of some profiles.

        This is separate from :meth:`list_profiles` so the operations, which
        list profiles often, do not parse every ``conf.yaml``. It never fails
        for one bad profile: a profile that disappeared is left out, and a
        damaged file just means no description and no sections.

        Args:
            names: Profile names (names that are not valid are ignored).

        Returns:
            Dict[str, ProfileDetails]: Details of each profile found.
        """
        found: Dict[str, ProfileDetails] = {}
        for name in names:
            try:
                validate_profile_name(name)
            except ValidationError:
                continue
            folder = self._engine.profiles_dir / name
            if folder.is_dir() and not os.path.islink(folder):
                found[name] = ProfileDetails(
                    read_description(folder), profile_sections(folder)
                )
        return found

    # --------------------------------------------------------------- operations

    @guarded(EXCLUSIVE)
    def set_description(self, name: str, description: str) -> OperationResult:
        """Sets, changes or clears the description of a profile.

        Only the small ``.kongui-profile.json`` file of the profile is written;
        the profile's own files, the ``conf.yaml`` and the ``.knsv`` format are
        not touched, and the folder keeps its modification time.

        Args:
            name: Profile name.
            description: New text; empty removes the description.

        Returns:
            OperationResult: Outcome, with the profile folder as ``path``.

        Raises:
            ValidationError: If the name or the text is not acceptable.
            ProfileNotFoundError: If there is no such profile.
            OSError: If the file could not be written (nothing is left behind).
        """
        validate_profile_name(name)
        text = clean_description(description)
        profile = self.get_profile(name)
        write_description(profile.path, text)
        return OperationResult(
            operation="set_description",
            ok=True,
            message=f"description of '{name}' updated",
            path=profile.path,
        )

    @guarded(EXCLUSIVE)
    def save(
        self,
        name: str,
        *,
        overwrite: bool = False,
        description: Optional[str] = None,
    ) -> OperationResult:
        """Saves the current configuration as a profile (``save_profile``).

        With ``overwrite`` the original ``force`` flag is used, which *merges*
        into the existing profile: files that no longer exist on the system
        stay in the profile (use :meth:`replace` to overwrite completely).

        Args:
            name: Profile name.
            overwrite: Allow saving over an existing profile.
            description: Text to keep with the profile (``None`` leaves an
                existing description alone). If the profile is saved but the
                description cannot be written, the result is still ``ok`` and
                carries a warning starting with
                :data:`~kongui.core.profilemeta.DESCRIPTION_NOT_SAVED`.

        Returns:
            OperationResult: Outcome, with the profile folder as ``path``.

        Raises:
            ValidationError: If the name or the description is not acceptable.
            ConfigMissingError: If there is no active ``conf.yaml``.
            ProfileExistsError: If the profile exists and ``overwrite`` is false.
        """
        validate_profile_name(name)
        text = None if description is None else clean_description(description)
        self._require_config()
        names = self._engine.profile_names()
        if name in names and not overwrite:
            raise ProfileExistsError(f"profile already exists: {name}")
        target = self._engine.profiles_dir / name
        existed = os.path.lexists(target)
        call = self._engine.call("save_profile", name, names, force=overwrite)
        ok = not call.failed and (target / "conf.yaml").is_file()
        notes: List[str] = []
        if not ok and not existed:
            notes.append(self._remove_created(target))
        if ok and text is not None:
            try:
                write_description(target, text)
            except OSError as error:
                notes.append(f"{DESCRIPTION_NOT_SAVED}{error.strerror or error}")
        return self._result(
            "save",
            ok,
            call,
            f"profile '{name}' saved",
            "save failed",
            target,
            (),
            notes,
        )

    @guarded(EXCLUSIVE)
    def replace(self, name: str, *, confirmed: bool = False) -> OperationResult:
        """Replaces a profile with the current configuration.

        The original ``save_profile(force=True)`` *merges* into the existing
        profile, so files that no longer exist on the system would survive. This
        method gives a real replacement without touching the original code:

        1. the current configuration is saved under a temporary name inside the
           profiles folder (``TEMP_PREFIX``);
        2. only if that worked, the old profile is renamed aside, the new one is
           renamed to ``name`` and the old one is deleted;
        3. if a rename fails, everything is put back.

        The old profile is therefore never removed before a complete new one
        exists. Both renames stay in the same folder, hence on one filesystem.

        Args:
            name: Name of an existing profile.
            confirmed: Must be ``True``; the caller asks the user first.

        Returns:
            OperationResult: Outcome, with the profile folder as ``path``. On
            failure the previous profile is still in place.

        Raises:
            ConfirmationRequiredError: If ``confirmed`` is not true.
            ValidationError: If the name is not acceptable.
            ProfileNotFoundError: If there is no such profile.
            ConfigMissingError: If there is no active ``conf.yaml``.
        """
        self._require_confirmation(confirmed, "replace")
        existing = self.get_profile(name)
        self._require_config()
        stamp = f"{os.getpid()}-{time.time_ns()}"
        fresh = self._engine.profiles_dir / f"{TEMP_PREFIX}new-{stamp}-{name}"
        aside = self._engine.profiles_dir / f"{TEMP_PREFIX}old-{stamp}-{name}"
        call = self._engine.call(
            "save_profile", fresh.name, self._engine.profile_names()
        )
        notes: List[str] = []
        if call.failed or not (fresh / "conf.yaml").is_file():
            if os.path.lexists(fresh):
                notes.append(self._remove_created(fresh))
            return self._result(
                "replace",
                False,
                call,
                "",
                f"replace failed; profile '{name}' was left as it was",
                existing.path,
                (),
                notes,
            )
        try:
            copy_description(existing.path, fresh)
        except OSError as error:
            notes.append(self._remove_created(fresh))
            return self._result(
                "replace",
                False,
                call,
                "",
                f"replace failed: the description could not be carried over "
                f"({error.strerror or error}); profile '{name}' was left as it was",
                existing.path,
                (),
                notes,
            )
        try:
            os.rename(existing.path, aside)
        except OSError as error:
            notes.append(self._remove_created(fresh))
            return self._failed_swap(name, existing.path, call, error, notes)
        try:
            os.rename(fresh, existing.path)
        except OSError as error:
            try:
                os.rename(aside, existing.path)
                notes.append("the previous profile was put back")
            except OSError as rollback_error:
                notes.append(
                    f"could not put the previous profile back from {aside}: {rollback_error}"
                )
            notes.append(self._remove_created(fresh))
            return self._failed_swap(name, existing.path, call, error, notes)
        notes_after = self._remove_created(aside)
        if not notes_after.startswith("removed"):
            notes.append(notes_after)
        return self._result(
            "replace",
            True,
            call,
            f"profile '{name}' replaced",
            "",
            existing.path,
            (),
            notes,
        )

    def _failed_swap(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        name: str,
        path: Path,
        call: EngineCall,
        error: OSError,
        notes: List[str],
    ) -> OperationResult:
        """Builds the failure result of a rename that did not work.

        Args:
            name: Profile name.
            path: Folder of the profile.
            call: The engine call that saved the new copy.
            error: The ``OSError`` raised by the rename.
            notes: Clean-up notes collected so far.

        Returns:
            OperationResult: A failed result mentioning the error.
        """
        return self._result(
            "replace",
            False,
            call,
            "",
            f"replace failed while swapping folders for '{name}': {error}",
            path,
            (),
            notes,
        )

    @guarded(EXCLUSIVE)
    def apply(
        self,
        name: str,
        *,
        confirmed: bool = False,
        allow_outside_home: bool = False,
    ) -> OperationResult:
        """Applies a profile to the live system (``apply_profile``).

        Destructive: files are replaced and folders are merged, not replaced.
        Before anything is written, the files that will be overwritten are
        copied to a safety copy (see :meth:`list_backups`); if that copy cannot
        be made, nothing is applied.

        Args:
            name: Profile name.
            confirmed: Must be ``True``; the caller asks the user first.
            allow_outside_home: Allow destinations outside the home folder.

        Returns:
            OperationResult: Outcome. ``ok`` is false if *any* section failed,
            even though the original prints a success message.

        Raises:
            ConfirmationRequiredError: If ``confirmed`` is not true.
            ValidationError: If the name is not acceptable.
            ProfileNotFoundError: If there is no such profile.
            ProfileInvalidError: If the profile has no ``conf.yaml``.
            ConfigError: If Konsave cannot read the profile's ``conf.yaml``,
                or the profile cannot be applied safely.
            SnapshotError: If the safety copy could not be made.
        """
        self._require_confirmation(confirmed, "apply")
        info = self._require_valid_profile(name)
        groups = self._config.resolve(info.path / "conf.yaml")
        problems = self._apply_problems(groups, info.path)
        if not allow_outside_home:
            problems += self._unsafe_destinations(groups, ("save",))
        if problems:
            raise ConfigError("the profile cannot be applied safely", problems)
        snapshot = self._snapshots.create(
            "apply",
            name,
            self._snapshots.destinations_of_apply(groups["save"], info.path),
        )
        names = self._engine.profile_names()
        call = self._engine.call("apply_profile", name, names, len(names))
        result = self._result(
            "apply",
            not call.failed,
            call,
            f"profile '{name}' applied; log out and in to see all changes",
            "apply failed (some files may already have been replaced)",
            info.path,
            (),
        )
        return self._with_snapshot(result, snapshot)

    @guarded(EXCLUSIVE)
    def remove(self, name: str, *, confirmed: bool = False) -> OperationResult:
        """Deletes a profile (``remove_profile``). Irreversible.

        Args:
            name: Profile name.
            confirmed: Must be ``True``; the caller asks the user first.

        Returns:
            OperationResult: Outcome.

        Raises:
            ConfirmationRequiredError: If ``confirmed`` is not true.
            ValidationError: If the name is not acceptable.
            ProfileNotFoundError: If there is no such profile.
        """
        self._require_confirmation(confirmed, "remove")
        info = self.get_profile(name)
        names = self._engine.profile_names()
        call = self._engine.call("remove_profile", name, names, len(names))
        ok = not call.failed and not os.path.lexists(info.path)
        return self._result(
            "remove", ok, call, f"profile '{name}' removed", "remove failed"
        )

    @guarded(SHARED)
    def export(
        self,
        name: str,
        *,
        directory: Path,
        archive_name: Optional[str] = None,
        on_conflict: str = "error",
    ) -> OperationResult:
        """Exports a profile to a ``.knsv`` file (``export``).

        The original ``force`` flag is *never* used to overwrite a folder: it
        deletes ``<directory>/<name>`` with ``rmtree``. Conflicts are resolved
        here instead.

        Args:
            name: Profile name.
            directory: Existing folder that receives the archive.
            archive_name: Archive base name without extension; defaults to
                ``name``.
            on_conflict: ``"error"`` refuses when something with that name
                exists; ``"unique"`` picks ``<name>-2``, ``<name>-3``...;
                ``"overwrite"`` replaces an existing ``.knsv`` file only.

        Returns:
            OperationResult: Outcome, with the archive as ``path``.

        Raises:
            ValidationError: For invalid names, folder or ``on_conflict``.
            ProfileNotFoundError: If there is no such profile.
            ProfileInvalidError: If the profile has no ``conf.yaml``.
            ConfigMissingError: If there is no active ``conf.yaml`` (the
                original copies it into the archive and fails without it).
            ConfigError: If Konsave cannot read the profile's ``conf.yaml``.
            ArchiveExistsError: If the conflict policy forbids the target.
        """
        validate_profile_name(name)
        if on_conflict not in ON_CONFLICT_CHOICES:
            raise ValidationError(f"on_conflict must be one of {ON_CONFLICT_CHOICES}")
        info = self._require_valid_profile(name)
        self._require_config()  # the original copies the active conf.yaml into the .knsv
        folder = Path(directory)
        if not folder.is_dir():
            raise ValidationError(f"output folder does not exist: {folder}")
        if not os.access(folder, os.W_OK | os.X_OK):
            raise ValidationError(f"output folder is not writable: {folder}")
        base = validate_archive_name(archive_name) if archive_name else name
        groups = self._config.resolve(info.path / "conf.yaml")
        base, force = self._resolve_export_target(folder, base, on_conflict)
        # The original copies the data next to the archive and zips the copy,
        # so about twice the data must fit in the destination.
        require_free_space(
            folder,
            2 * self._export_size(info.path, groups["export"]),
            "the export",
        )
        names = self._engine.profile_names()
        call = self._engine.call(
            "export", name, names, len(names), str(folder), base, force
        )
        archive = folder / f"{base}{self._engine.export_extension}"
        ok = not call.failed and archive.is_file() and self._archive_has_config(archive)
        notes: List[str] = []
        if not ok:
            # The policy above guarantees neither path existed before the call.
            for leftover in (folder / base, folder / f"{base}.zip"):
                if os.path.lexists(leftover):
                    notes.append(self._remove_created(leftover))
        return self._result(
            "export",
            ok,
            call,
            f"profile '{name}' exported to {archive}",
            "export failed",
            archive,
            (),
            notes,
        )

    @guarded(EXCLUSIVE)
    def import_profile(
        self,
        archive_path: Path,
        *,
        confirmed: bool = False,
        allow_outside_home: bool = False,
    ) -> OperationResult:
        """Imports a ``.knsv`` file (``import_profile``).

        Destructive: the original writes the archive's ``export`` section into
        the live system immediately, overwriting files. The archive's own
        ``conf.yaml`` decides the destinations, so they are checked first.

        Args:
            archive_path: Path of the ``.knsv`` file.
            confirmed: Must be ``True``; the caller asks the user first.
            allow_outside_home: Allow destinations outside the home folder.

        Returns:
            OperationResult: Outcome, with the new profile folder as ``path``.

        Raises:
            ConfirmationRequiredError: If ``confirmed`` is not true.
            ValidationError: If the file is not an acceptable archive.
            ConfigError: If Konsave cannot read the archive's ``conf.yaml``, or
                it would write outside the home folder.
            ProfileExistsError: If a profile with that name exists.
            SnapshotError: If the safety copy could not be made.
        """
        self._require_confirmation(confirmed, "import")
        path = Path(archive_path)
        name, groups = self._check_archive(path, allow_outside_home)
        if name in self._engine.profile_names():
            raise ProfileExistsError(f"profile already exists: {name}")
        staging = self._engine.temp_dir / name
        if os.path.lexists(staging):
            raise ValidationError(
                f"stale import folder found, remove it first: {staging}"
            )
        extracted = self._measure_extracted(path)
        # The original extracts into its temp folder, then copies the profile
        # and the export section: about twice the extracted size, in total.
        require_free_space(self._engine.konsave_dir, 2 * extracted, "the import")
        target = self._engine.profiles_dir / name
        snapshot = self._snapshots.create(
            "import",
            name,
            self._snapshots.destinations_of_import(
                self._archive_members(path), groups["export"]
            ),
        )
        call = self._engine.call("import_profile", str(path))
        ok = (
            not call.failed
            and (target / "conf.yaml").is_file()
            and not os.path.lexists(staging)
        )
        notes: List[str] = []
        if not ok:
            for leftover in (target, staging):
                if os.path.lexists(leftover):
                    notes.append(self._remove_created(leftover))
        else:
            # Konsave copies everything under ``save/`` into the profile, so an
            # archive could plant a description. An imported profile starts
            # without one: the file format carries none.
            try:
                remove_description(target)
            except OSError as error:
                notes.append(f"{DESCRIPTION_NOT_REMOVED}{error.strerror or error}")
        result = self._result(
            "import",
            ok,
            call,
            f"profile '{name}' imported",
            "import failed (files of the export section may already be written)",
            target,
            (),
            notes,
        )
        return self._with_snapshot(result, snapshot)

    def inspect_archive(
        self, archive_path: Path, *, allow_outside_home: bool = False
    ) -> ArchiveInspection:
        """Checks a ``.knsv`` file and describes it, writing nothing.

        It applies the same checks as :meth:`import_profile` (readable zip,
        safe member names, ``conf.yaml`` and ``save/`` present, a configuration
        Konsave can read that stays inside the home) so a problem is found
        before the user confirms.

        Args:
            archive_path: Path of the ``.knsv`` file.
            allow_outside_home: Accept destinations outside the home folder.

        Returns:
            ArchiveInspection: Name, size and sections of the archive.

        Raises:
            ValidationError: If the file is missing, not a ``.knsv``, not a
                readable archive or its name is not acceptable.
            ConfigError: If its configuration cannot be read or is unsafe.
        """
        path = Path(archive_path)
        name, groups = self._check_archive(path, allow_outside_home)
        with zipfile.ZipFile(path) as handle:
            names = handle.namelist()
        members = len(names)
        folders = self._archive_folder_warnings(groups, names)
        return ArchiveInspection(
            path=path,
            name=name,
            size_bytes=path.stat().st_size,
            member_count=members,
            save_sections=tuple(groups["save"]),
            export_sections=tuple(groups["export"]),
            warnings=tuple(folders),
            name_taken=name in self._engine.profile_names(),
        )

    def _check_archive(
        self, path: Path, allow_outside_home: bool
    ) -> Tuple[str, Groups]:
        """Runs the checks shared by inspection and import.

        Args:
            path: Archive path.
            allow_outside_home: Accept destinations outside the home folder.

        Returns:
            Tuple[str, Groups]: Profile name and the groups of its configuration.

        Raises:
            ValidationError: If the file or its name is not acceptable.
            ConfigError: If the configuration cannot be read or is unsafe.
        """
        suffix = self._engine.export_extension
        if not path.is_file():
            raise ValidationError(f"archive not found: {path}")
        if not path.name.endswith(suffix) or path.name == suffix:
            raise ValidationError(f"archive must be a '*{suffix}' file")
        name = validate_profile_name(path.name[: -len(suffix)])
        try:
            size = path.stat().st_size
        except OSError as error:
            raise ValidationError(f"not a readable archive: {error}") from error
        if size > MAX_ARCHIVE_BYTES:
            raise ArchiveLimitError(
                f"archive too large: {size} bytes (limit {MAX_ARCHIVE_BYTES})",
                "size",
                MAX_ARCHIVE_BYTES,
                size,
            )
        groups = self._read_archive_config(path)
        if not allow_outside_home:
            outside = self._unsafe_destinations(groups, ("export", "save"))
            if outside:
                raise ConfigError("the archive writes outside the home folder", outside)
        return name, groups

    @guarded(EXCLUSIVE)
    def wipe_all(self, *, confirmed: bool = False) -> OperationResult:
        """Deletes every profile (``wipe``). Irreversible.

        The original asks for the word ``WIPE`` through ``input()``; here the
        caller's confirmation replaces it by overriding ``input`` on the private
        engine module only for the duration of the call. ``conf.yaml`` is kept.

        Args:
            confirmed: Must be ``True``; the caller asks the user first.

        Returns:
            OperationResult: Outcome.

        Raises:
            ConfirmationRequiredError: If ``confirmed`` is not true.
        """
        self._require_confirmation(confirmed, "wipe_all")
        call = self._engine.call("wipe", overrides={"input": lambda _prompt="": "WIPE"})
        self._engine.ensure_runtime_dirs()
        ok = not call.failed and not self._engine.profile_names()
        return self._result("wipe_all", ok, call, "all profiles removed", "wipe failed")

    # ------------------------------------------------------------ safety copies

    @guarded(SHARED)
    def list_backups(self) -> List[SnapshotInfo]:
        """Lists the safety copies made before apply/import (RN-01).

        Returns:
            List[SnapshotInfo]: Newest first.

        Raises:
            SnapshotError: If the folder cannot be read.
        """
        return self._snapshots.list()

    @guarded(EXCLUSIVE)
    def restore_backup(
        self,
        backup_id: str,
        *,
        confirmed: bool = False,
        allow_outside_home: bool = False,
    ) -> OperationResult:
        """Restores the live files kept in a safety copy.

        Destructive: files changed since are overwritten. The state before the
        restore is itself kept as a new safety copy.

        Args:
            backup_id: Id from :meth:`list_backups`.
            confirmed: Must be ``True``; the caller asks the user first.
            allow_outside_home: Allow paths outside the home folder.

        Returns:
            OperationResult: ``ok`` is false if any path could not be restored.

        Raises:
            ConfirmationRequiredError: If ``confirmed`` is not true.
            ValidationError: If the id or a path is not acceptable.
            SnapshotNotFoundError: If there is no such copy.
            SnapshotError: If the copy is damaged.
        """
        return self._snapshots.restore(
            backup_id, confirmed=confirmed, allow_outside_home=allow_outside_home
        )

    @guarded(EXCLUSIVE)
    def delete_backup(
        self, backup_id: str, *, confirmed: bool = False
    ) -> OperationResult:
        """Deletes a safety copy. Safety copies are never deleted automatically.

        Args:
            backup_id: Id from :meth:`list_backups`.
            confirmed: Must be ``True``; the caller asks the user first.

        Returns:
            OperationResult: Outcome.

        Raises:
            ConfirmationRequiredError: If ``confirmed`` is not true.
            ValidationError: If the id is not acceptable.
            SnapshotNotFoundError: If there is no such copy.
            SnapshotError: If it cannot be removed.
        """
        return self._snapshots.delete(backup_id, confirmed=confirmed)

    # ------------------------------------------------------------------ helpers

    def _with_snapshot(
        self, result: OperationResult, snapshot: Optional[SnapshotInfo]
    ) -> OperationResult:
        """Attaches the safety copy to a result and records the outcome."""
        if snapshot is None:
            return result
        extra = [f"{KEPT_PREFIX}{snapshot.id}"]
        problem = self._snapshots.finish(snapshot, result.ok)
        if problem:
            extra.append(problem)
        return replace(
            result, backup=snapshot.path, warnings=result.warnings + tuple(extra)
        )

    @staticmethod
    def _archive_members(archive: Path) -> List[str]:
        """Names inside a ``.knsv`` (already validated by the caller)."""
        try:
            with zipfile.ZipFile(archive) as handle:
                return handle.namelist()
        except (zipfile.BadZipFile, OSError) as error:
            raise ValidationError(f"not a readable archive: {error}") from error

    @staticmethod
    def _require_confirmation(confirmed: bool, operation: str) -> None:
        """Refuses destructive operations that were not confirmed.

        Args:
            confirmed: Value passed by the caller.
            operation: Operation name for the message.

        Raises:
            ConfirmationRequiredError: If ``confirmed`` is not exactly ``True``.
        """
        if confirmed is not True:
            raise ConfirmationRequiredError(
                f"'{operation}' is destructive; call it with confirmed=True"
            )

    def _require_config(self) -> None:
        """Ensures the active configuration exists.

        Raises:
            ConfigMissingError: If there is no ``conf.yaml``.
        """
        if not self._config.exists():
            raise ConfigMissingError(
                "no conf.yaml; call ConfigService.ensure_default_config() first"
            )

    def _require_valid_profile(self, name: str) -> ProfileInfo:
        """Returns a profile that has its own ``conf.yaml``.

        Args:
            name: Profile name.

        Returns:
            ProfileInfo: The profile.

        Raises:
            ProfileInvalidError: If the profile has no ``conf.yaml``.
        """
        info = self.get_profile(name)
        if not info.has_config:
            raise ProfileInvalidError(f"profile '{name}' has no conf.yaml")
        return info

    def _unsafe_destinations(self, groups: Groups, kinds: Iterable[str]) -> List[str]:
        """Finds groups that would write outside the home folder.

        A ``location`` that resolves outside the home is refused, and so is an
        entry that is not a single file or folder name (``../x`` or ``a/b``),
        because the original joins it to the location and could leave it.

        Args:
            groups: Groups read by :meth:`ConfigService.resolve`.
            kinds: Top-level keys to check.

        Returns:
            List[str]: One message per offending group or entry.
        """
        home = os.path.realpath(self._engine.home)
        problems = []
        for kind in kinds:
            for section, data in groups.get(kind, {}).items():
                location = data["location"]
                real = os.path.realpath(location)
                if real != home and not real.startswith(home + os.sep):
                    problems.append(
                        f"{kind}.{section}: '{location}' is outside the home folder"
                    )
                for entry in data["entries"]:
                    if not is_plain_name(entry):
                        problems.append(
                            f"{kind}.{section}: entry {entry!r} is not a plain "
                            "file or folder name"
                        )
        return problems

    @staticmethod
    def _archive_folder_warnings(groups: Groups, names: List[str]) -> Tuple[str, ...]:
        """Compares the groups of an archive's ``conf.yaml`` with its ``save/``.

        Args:
            groups: Groups of the archive's configuration.
            names: Member names of the archive.

        Returns:
            Tuple[str, ...]: Warnings about groups without data (the profile
            could not be applied) and data without a group (ignored).
        """
        present = {
            parts[1]
            for parts in (PurePosixPath(name).parts for name in names)
            if len(parts) > 1 and parts[0] == "save"
        }
        wanted = set(groups["save"])
        warnings = []
        missing = sorted(wanted - present)
        if missing:
            warnings.append(
                "the archive has no data folder in save/ for: "
                + ", ".join(missing)
                + " (the imported profile could not be applied)"
            )
        extra = sorted(present - wanted)
        if extra:
            warnings.append(
                "save/ has folders that its conf.yaml does not list: "
                + ", ".join(extra)
                + " (they are ignored when the profile is applied)"
            )
        return tuple(warnings)

    @staticmethod
    def _apply_problems(groups: Groups, profile_dir: Path) -> List[str]:
        """Finds problems the original would hide behind a success message.

        Args:
            groups: Groups of the profile's configuration.
            profile_dir: Folder of the profile being applied.

        Returns:
            List[str]: One message per problem.
        """
        problems = []
        for section, data in groups["save"].items():
            if not (profile_dir / section).is_dir():
                problems.append(f"save.{section}: folder missing in the profile")
            location = data["location"]
            parent = os.path.dirname(os.path.normpath(location))
            if not os.path.isdir(location) and not os.path.isdir(parent):
                problems.append(
                    f"save.{section}: neither '{location}' nor its parent exists"
                )
        return problems

    def _resolve_export_target(
        self, folder: Path, base: str, policy: str
    ) -> Tuple[str, bool]:
        """Applies the conflict policy for an export.

        Args:
            folder: Output folder.
            base: Requested archive base name.
            policy: One of :data:`ON_CONFLICT_CHOICES`.

        Returns:
            Tuple[str, bool]: Base name to pass to the engine and whether the
            original ``force`` flag may be set (only to replace an existing
            ``.knsv`` file).

        Raises:
            ArchiveExistsError: If the policy forbids the target.
        """
        suffix = self._engine.export_extension

        def candidates(name: str) -> Tuple[Path, Path, Path]:
            return folder / name, folder / f"{name}{suffix}", folder / f"{name}.zip"

        def taken(name: str) -> List[Path]:
            return [path for path in candidates(name) if os.path.lexists(path)]

        if policy == "error":
            if taken(base):
                raise ArchiveExistsError(f"already exists: {taken(base)[0]}")
            return base, False
        if policy == "unique":
            name, counter = base, 1
            while taken(name):
                counter += 1
                if counter > 1000:
                    raise ArchiveExistsError("no free archive name found")
                name = f"{base}-{counter}"
            return name, False
        stage, archive, zipped = candidates(base)
        for blocker in (stage, zipped):
            if os.path.lexists(blocker):
                raise ArchiveExistsError(
                    f"refusing to overwrite: {blocker} exists and the original "
                    "export would delete or replace it"
                )
        if os.path.lexists(archive):
            if archive.is_symlink() or not archive.is_file():
                raise ArchiveExistsError(f"not a regular file: {archive}")
            return base, True
        return base, False

    @staticmethod
    def _archive_has_config(archive: Path) -> bool:
        """Tells whether a file is a ZIP containing ``conf.yaml``.

        Args:
            archive: File to test.

        Returns:
            bool: ``True`` if it looks like a valid ``.knsv``.
        """
        try:
            with zipfile.ZipFile(archive) as handle:
                return "conf.yaml" in handle.namelist()
        except (zipfile.BadZipFile, OSError):
            return False

    def _read_archive_config(self, archive: Path) -> Groups:
        """Checks the structure of a ``.knsv`` and reads its ``conf.yaml``.

        Nothing is extracted to the real folders: only ``conf.yaml`` is copied
        to a temporary folder so that the original code can read it.

        Args:
            archive: Path of the ``.knsv``.

        Returns:
            Groups: The groups of the archive's configuration.

        Raises:
            ValidationError: If the file is not a usable archive.
            ConfigError: If Konsave cannot read its ``conf.yaml``.
        """
        try:
            with zipfile.ZipFile(archive) as handle:
                members = handle.namelist()
                if len(members) > MAX_ARCHIVE_ENTRIES:
                    raise ArchiveLimitError(
                        f"archive has too many entries: {len(members)} "
                        f"(limit {MAX_ARCHIVE_ENTRIES})",
                        "entries",
                        MAX_ARCHIVE_ENTRIES,
                        len(members),
                    )
                for member in members:
                    parts = PurePosixPath(member).parts
                    if (
                        member.startswith("/")
                        or ".." in parts
                        or "\\" in member
                        or "\0" in member
                    ):
                        raise ValidationError(f"unsafe path inside archive: {member!r}")
                if "conf.yaml" not in members:
                    raise ValidationError("archive has no conf.yaml")
                if not any(member.startswith("save/") for member in members):
                    raise ValidationError("archive has no 'save/' folder")
                if (
                    handle.getinfo("conf.yaml").file_size
                    > ConfigService.MAX_CONFIG_BYTES
                ):
                    raise ValidationError("archive conf.yaml is too large")
                data = handle.read("conf.yaml")
        except (zipfile.BadZipFile, OSError, RuntimeError) as error:
            raise ValidationError(f"not a readable archive: {error}") from error
        with tempfile.TemporaryDirectory(prefix="kongui-import-") as folder:
            candidate = Path(folder) / "conf.yaml"
            candidate.write_bytes(data)
            return self._config.resolve(candidate)

    @staticmethod
    def _measure_extracted(archive: Path) -> int:
        """Counts the bytes an archive really decompresses to, writing nothing.

        Every member is read to its end, so the count does not depend on the
        sizes declared in the zip headers, reading stops at the first chunk that
        passes the limit, and a damaged member (bad checksum, broken data) is
        found before anything is imported.

        Args:
            archive: Path of the ``.knsv`` (already checked by the caller).

        Returns:
            int: Total decompressed bytes.

        Raises:
            ArchiveLimitError: If the total passes ``MAX_EXTRACTED_BYTES``.
            ValidationError: If the archive is unreadable or corrupted.
        """
        total = 0
        try:
            with zipfile.ZipFile(archive) as handle:
                for member in handle.infolist():
                    if member.is_dir():
                        continue
                    with handle.open(member) as stream:
                        while True:
                            chunk = stream.read(_COUNT_CHUNK)
                            if not chunk:
                                break
                            total += len(chunk)
                            if total > MAX_EXTRACTED_BYTES:
                                raise ArchiveLimitError(
                                    "archive expands to more than "
                                    f"{MAX_EXTRACTED_BYTES} bytes",
                                    "extracted",
                                    MAX_EXTRACTED_BYTES,
                                )
        except (zipfile.BadZipFile, zlib.error, EOFError) as error:
            raise ValidationError(f"corrupted archive: {error}") from error
        except (OSError, RuntimeError, NotImplementedError) as error:
            raise ValidationError(f"not a readable archive: {error}") from error
        return total

    @staticmethod
    def _export_size(profile: Path, resolved_export: Mapping[str, Any]) -> int:
        """Estimates the bytes an export copies: the profile and its export entries.

        Args:
            profile: Profile folder.
            resolved_export: The ``export`` part of the resolved configuration.

        Returns:
            int: Bytes (an estimate; unreadable files count as zero).
        """
        total = tree_size(profile)
        for data in resolved_export.values():
            location = Path(os.path.normpath(data["location"]))
            for entry in data.get("entries") or ():
                total += tree_size(location / entry)
        return total

    @staticmethod
    def _remove_created(path: Path) -> str:
        """Removes a leftover that the caller proved did not exist before.

        Args:
            path: File or folder to remove.

        Returns:
            str: Message describing what happened.
        """
        try:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
        except OSError as error:
            return f"could not remove leftover {path}: {error}"
        return f"removed leftover {path}"

    @staticmethod
    def _result(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        operation: str,
        ok: bool,
        call: EngineCall,
        success: str,
        failure: str,
        path: Optional[Path] = None,
        warnings: Iterable[str] = (),
        notes: Iterable[str] = (),
    ) -> OperationResult:
        """Builds an :class:`OperationResult`.

        Args:
            operation: Operation name.
            ok: Final verdict (log *and* post-conditions).
            call: What the engine did.
            success: Message for success.
            failure: Message prefix for failure.
            path: Main path produced.
            warnings: Non-blocking observations.
            notes: Clean-up notes, appended to the warnings.

        Returns:
            OperationResult: The result.
        """
        errors = call.error_messages
        if ok:
            message = success
        elif errors:
            message = f"{failure}: {errors[0]}"
        else:
            message = failure
        return OperationResult(
            operation=operation,
            ok=ok,
            message=message,
            stdout=call.stdout,
            stderr=call.stderr,
            errors=errors,
            warnings=tuple(warnings) + tuple(notes),
            path=path,
        )
