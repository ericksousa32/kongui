"""Safety copies of the live files that apply and import overwrite (RN-01).

Before ``apply`` or ``import`` writes anything, :class:`SnapshotService` copies
exactly the files the operation is going to replace, and notes the files and
folders it is going to create. The copy lives in
``~/.config/konsave/kongui-backups/<id>/`` (private, mode 0700) and can be
restored, listed and deleted. Nothing is ever deleted automatically.

Failing closed: if the copy cannot be completed (no space, no permission), a
:class:`~kongui.core.errors.SnapshotError` is raised and the operation does not
start.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from kongui.core.errors import (
    ConfirmationRequiredError,
    SnapshotError,
    SnapshotNotFoundError,
    ValidationError,
)
from kongui.core.results import OperationResult

SNAPSHOT_DIR_NAME = "kongui-backups"
MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1
OPERATIONS = ("apply", "import", "restore")

#: Start of the note added to an apply/import result naming its safety copy.
KEPT_PREFIX = "safety copy kept: "
#: Start of the note added to a restore result naming the undo copy.
UNDO_PREFIX = "the state before the restore was kept as "

_ID_RE = re.compile(r"^\d{8}-\d{6}-\d{6}-(apply|import|restore)$")
_STORED_RE = re.compile(r"^files/\d{1,9}$")


@dataclass(frozen=True)
class SnapshotInfo:
    """One safety copy.

    Attributes:
        id: Folder name, ``<date>-<time>-<microseconds>-<operation>``.
        path: Full path of the folder.
        operation: ``"apply"``, ``"import"`` or ``"restore"``.
        profile: Profile (or source) the operation was about.
        created: When the copy was made.
        replaced: Number of files that were copied.
        created_files: Number of files the operation was going to create.
        size_bytes: Bytes of file data kept.
        succeeded: Outcome of the operation, ``None`` if unknown.
        problem: Why the copy cannot be used, empty if it is fine.
    """

    id: str
    path: Path
    operation: str
    profile: str
    created: datetime
    replaced: int
    created_files: int
    size_bytes: int
    succeeded: Optional[bool] = None
    problem: str = ""


def _stamp_to_datetime(snapshot_id: str) -> datetime:
    """Reads the creation time from an id."""
    return datetime.strptime(snapshot_id[:22], "%Y%m%d-%H%M%S-%f")


def _within(path: str, home: Path) -> bool:
    """Tells whether an absolute path is inside ``home``."""
    try:
        return os.path.commonpath([os.path.normpath(path), str(home)]) == str(home)
    except ValueError:
        return False


class SnapshotService:
    """Makes, lists, restores and deletes safety copies."""

    def __init__(self, konsave_dir: Path, home: Path) -> None:
        """Creates the service.

        Args:
            konsave_dir: Konsave's configuration folder.
            home: Home folder of the user (restores stay inside it).
        """
        self._root = Path(konsave_dir) / SNAPSHOT_DIR_NAME
        self._home = Path(os.path.abspath(home))

    @property
    def root(self) -> Path:
        """Folder holding every safety copy."""
        return self._root

    # ------------------------------------------------------------------ planning

    @staticmethod
    def destinations_of_apply(
        resolved_save: Dict[str, Any], profile_dir: Path
    ) -> List[Path]:
        """Lists the files ``apply_profile`` would write.

        Args:
            resolved_save: The ``save`` part of the resolved profile config.
            profile_dir: Folder of the profile.

        Returns:
            List[Path]: Destination files, in a stable order.
        """
        found: List[Path] = []
        for name, data in resolved_save.items():
            source = profile_dir / name
            location = Path(os.path.normpath(data["location"]))
            for relative in _walk_files(source):
                found.append(location / relative)
        return found

    @staticmethod
    def destinations_of_import(
        members: Iterable[str], resolved_export: Dict[str, Any]
    ) -> List[Path]:
        """Lists the files ``import_profile`` would write outside the profile.

        Args:
            members: Names inside the ``.knsv``.
            resolved_export: The ``export`` part of the resolved archive config.

        Returns:
            List[Path]: Destination files, in a stable order.
        """
        found: List[Path] = []
        names = [m for m in members if not m.endswith("/")]
        for section, data in resolved_export.items():
            prefix = f"export/{section}/"
            location = Path(os.path.normpath(data["location"]))
            entries = set(data.get("entries") or ())
            for member in names:
                if not member.startswith(prefix):
                    continue
                relative = member[len(prefix) :]
                if relative.split("/", 1)[0] in entries:
                    found.append(location / relative)
        return found

    # ------------------------------------------------------------------ creating

    def create(
        self, operation: str, profile: str, destinations: Iterable[Path]
    ) -> Optional[SnapshotInfo]:
        """Copies what the operation is about to overwrite.

        Args:
            operation: One of :data:`OPERATIONS`.
            profile: Profile name, kept for display.
            destinations: Files the operation will write.

        Returns:
            Optional[SnapshotInfo]: The copy, or ``None`` if there were no
            destinations at all.

        Raises:
            SnapshotError: If the copy could not be completed. Nothing is left
                behind and the caller must not start the operation.
        """
        if operation not in OPERATIONS:
            raise ValueError(f"unknown operation: {operation!r}")
        targets = _unique(destinations)
        if not targets:
            return None
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        snapshot_id = f"{stamp}-{operation}"
        folder = self._root / snapshot_id
        try:
            self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self._root, 0o700)
            folder.mkdir(mode=0o700)
            (folder / "files").mkdir(mode=0o700)
        except OSError as error:
            raise SnapshotError(
                f"could not create the safety copy folder {folder}: {error}"
            ) from error
        try:
            entries, created_dirs, size = self._copy_all(folder, targets)
            manifest = {
                "version": MANIFEST_VERSION,
                "operation": operation,
                "profile": profile,
                "created": stamp,
                "succeeded": None,
                "entries": entries,
                "created_dirs": created_dirs,
                "size_bytes": size,
            }
            _write_json(folder / MANIFEST_NAME, manifest)
        except (OSError, ValueError) as error:
            shutil.rmtree(folder, ignore_errors=True)
            raise SnapshotError(
                f"could not make the safety copy, nothing was changed: {error}"
            ) from error
        return self._info(folder)

    def _copy_all(self, folder: Path, targets: Sequence[Path]):
        """Copies every target; returns manifest entries, new dirs and size."""
        entries: List[Dict[str, Any]] = []
        missing_dirs: Set[str] = set()
        size = 0
        counter = 0
        for target in targets:
            path = str(target)
            if not os.path.isabs(path):
                raise ValueError(f"destination is not absolute: {path}")
            info = _lstat(target)
            if info is None:
                entries.append({"path": path, "kind": "created"})
                parent = target.parent
                while _lstat(parent) is None and parent != parent.parent:
                    missing_dirs.add(str(parent))
                    parent = parent.parent
            elif os.path.islink(target):
                entry: Dict[str, Any] = {
                    "path": path,
                    "kind": "symlink",
                    "link": os.readlink(target),
                }
                real = os.path.realpath(target)
                if os.path.isfile(real):
                    counter += 1
                    entry["target"] = real
                    entry["stored"] = f"files/{counter:04d}"
                    size += _store(Path(real), folder / entry["stored"])
                entries.append(entry)
            elif os.path.isfile(target):
                counter += 1
                stored = f"files/{counter:04d}"
                size += _store(target, folder / stored)
                entries.append({"path": path, "kind": "file", "stored": stored})
            # anything else (a folder in the way): the operation itself fails
        return entries, sorted(missing_dirs, key=len, reverse=True), size

    def finish(self, snapshot: SnapshotInfo, succeeded: bool) -> Optional[str]:
        """Records how the operation ended (informational).

        Args:
            snapshot: The copy made for the operation.
            succeeded: Whether the operation succeeded.

        Returns:
            Optional[str]: A warning if the note could not be written.
        """
        try:
            manifest = self._load(snapshot.path)
            manifest["succeeded"] = bool(succeeded)
            _write_json(snapshot.path / MANIFEST_NAME, manifest)
        except (OSError, SnapshotError) as error:
            return f"could not update the safety copy record: {error}"
        return None

    # ------------------------------------------------------------------ queries

    def list(self) -> List[SnapshotInfo]:
        """Lists the safety copies, newest first.

        Returns:
            List[SnapshotInfo]: Copies found; unreadable ones carry ``problem``.
        """
        try:
            names = [n for n in os.listdir(self._root) if _ID_RE.match(n)]
        except FileNotFoundError:
            return []
        except OSError as error:
            raise SnapshotError(f"could not read {self._root}: {error}") from error
        found = [self._info(self._root / name) for name in sorted(names)]
        return list(reversed(found))

    def get(self, snapshot_id: str) -> SnapshotInfo:
        """Returns one safety copy.

        Args:
            snapshot_id: Id, as listed.

        Raises:
            ValidationError: If the id is malformed.
            SnapshotNotFoundError: If there is no such copy.
        """
        return self._info(self._folder(snapshot_id))

    # ------------------------------------------------------------------ restoring

    def restore(
        self,
        snapshot_id: str,
        *,
        confirmed: bool = False,
        allow_outside_home: bool = False,
    ) -> OperationResult:
        """Puts the files back as they were before the operation.

        Replaced files return to their old content; symlinks are recreated;
        files the operation created are removed (only files, then folders it
        created if they are empty). Before touching anything, the current state
        of those paths is kept as a new copy, so a restore can be undone.

        Args:
            snapshot_id: Id of the copy.
            confirmed: Must be ``True``; the caller asks the user first.
            allow_outside_home: Allow paths outside the home folder.

        Returns:
            OperationResult: ``ok`` is false if any path could not be restored.

        Raises:
            ConfirmationRequiredError: If ``confirmed`` is not true.
            ValidationError: If the id is malformed or a path is unsafe.
            SnapshotNotFoundError: If there is no such copy.
            SnapshotError: If the copy is damaged, or the undo copy of the
                current state cannot be made (nothing is changed then).
        """
        if confirmed is not True:
            raise ConfirmationRequiredError(
                "restoring a safety copy needs confirmation"
            )
        folder = self._folder(snapshot_id)
        manifest = self._load(folder)
        entries = self._checked_entries(folder, manifest, allow_outside_home)
        paths = [Path(e["path"]) for e in entries]
        paths += [Path(e["target"]) for e in entries if "target" in e]
        undo = self.create("restore", snapshot_id, paths)
        errors: List[str] = []
        for entry in entries:
            try:
                _restore_entry(folder, entry)
            except OSError as error:
                errors.append(f"{entry['path']}: {error}")
        for directory in manifest.get("created_dirs", []):
            try:
                os.rmdir(directory)
            except OSError:
                pass  # not empty or already gone: leave it
        ok = not errors
        message = (
            f"restored {len(entries)} path(s) from {snapshot_id}"
            if ok
            else f"restore incomplete: {len(errors)} of {len(entries)} path(s) failed"
        )
        return OperationResult(
            operation="restore_backup",
            ok=ok,
            message=message,
            errors=tuple(errors),
            warnings=((f"{UNDO_PREFIX}{undo.id}",) if undo is not None else ()),
            path=folder,
            backup=undo.path if undo is not None else None,
        )

    def delete(self, snapshot_id: str, *, confirmed: bool = False) -> OperationResult:
        """Deletes one safety copy.

        Args:
            snapshot_id: Id of the copy.
            confirmed: Must be ``True``; the caller asks the user first.

        Raises:
            ConfirmationRequiredError: If ``confirmed`` is not true.
            ValidationError: If the id is malformed.
            SnapshotNotFoundError: If there is no such copy.
            SnapshotError: If the folder cannot be removed.
        """
        if confirmed is not True:
            raise ConfirmationRequiredError("deleting a safety copy needs confirmation")
        folder = self._folder(snapshot_id)
        try:
            shutil.rmtree(folder)
        except OSError as error:
            raise SnapshotError(f"could not delete {folder}: {error}") from error
        return OperationResult(
            "delete_backup", True, f"safety copy {snapshot_id} deleted", path=folder
        )

    # ------------------------------------------------------------------ helpers

    def _folder(self, snapshot_id: object) -> Path:
        """Maps an id to its folder, refusing anything but a plain id."""
        if not isinstance(snapshot_id, str) or not _ID_RE.match(snapshot_id):
            raise ValidationError(f"not a safety copy id: {snapshot_id!r}")
        folder = self._root / snapshot_id
        if not folder.is_dir() or folder.is_symlink():
            raise SnapshotNotFoundError(f"no such safety copy: {snapshot_id}")
        return folder

    @staticmethod
    def _load(folder: Path) -> Dict[str, Any]:
        """Reads and checks a manifest."""
        try:
            data = json.loads((folder / MANIFEST_NAME).read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise SnapshotError(
                f"damaged safety copy ({folder.name}): {error}"
            ) from error
        if (
            not isinstance(data, dict)
            or data.get("version") != MANIFEST_VERSION
            or not isinstance(data.get("entries"), list)
        ):
            raise SnapshotError(f"unsupported safety copy: {folder.name}")
        return data

    def _checked_entries(
        self, folder: Path, manifest: Dict[str, Any], allow_outside_home: bool
    ) -> List[Dict[str, Any]]:
        """Validates every entry before anything is touched."""
        checked = []
        for entry in manifest["entries"]:
            if not isinstance(entry, dict):
                raise SnapshotError("damaged safety copy: bad entry")
            path = entry.get("path")
            kind = entry.get("kind")
            if not isinstance(path, str) or not os.path.isabs(path):
                raise SnapshotError("damaged safety copy: bad path")
            if kind not in ("file", "symlink", "created"):
                raise SnapshotError("damaged safety copy: bad kind")
            places = [path]
            if "target" in entry:
                places.append(str(entry["target"]))
            for place in places:
                if not allow_outside_home and not _within(place, self._home):
                    raise ValidationError(f"path outside the home folder: {place}")
            stored = entry.get("stored")
            if kind == "file" or "stored" in entry:
                if not isinstance(stored, str) or not _STORED_RE.match(stored):
                    raise SnapshotError("damaged safety copy: bad stored name")
                if not (folder / stored).is_file():
                    raise SnapshotError(f"damaged safety copy: {stored} is missing")
            if kind == "symlink" and not isinstance(entry.get("link"), str):
                raise SnapshotError("damaged safety copy: bad link")
            checked.append(entry)
        return checked

    def _info(self, folder: Path) -> SnapshotInfo:
        """Summarises one folder; never raises for a damaged one."""
        snapshot_id = folder.name
        created = _stamp_to_datetime(snapshot_id)
        try:
            manifest = self._load(folder)
        except SnapshotError as error:
            return SnapshotInfo(
                snapshot_id, folder, snapshot_id.rsplit("-", 1)[-1], "",
                created, 0, 0, 0, None, str(error),
            )  # fmt: skip
        entries = manifest["entries"]
        kinds = [e.get("kind") for e in entries if isinstance(e, dict)]
        return SnapshotInfo(
            id=snapshot_id,
            path=folder,
            operation=str(manifest.get("operation", "")),
            profile=str(manifest.get("profile", "")),
            created=created,
            replaced=sum(1 for k in kinds if k in ("file", "symlink")),
            created_files=sum(1 for k in kinds if k == "created"),
            size_bytes=int(manifest.get("size_bytes", 0) or 0),
            succeeded=manifest.get("succeeded"),
        )


# ---------------------------------------------------------------------- functions


def _unique(paths: Iterable[Path]) -> List[Path]:
    """Removes repeated paths, keeping the order."""
    seen: Set[str] = set()
    result = []
    for path in paths:
        key = os.path.normpath(str(path))
        if key not in seen:
            seen.add(key)
            result.append(Path(key))
    return result


def _lstat(path: Path):
    """``os.lstat`` that returns ``None`` when nothing is there."""
    try:
        return os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None


def _walk_files(source: Path) -> List[str]:
    """Relative paths of the files below ``source`` (follows folder links)."""
    found: List[str] = []
    seen: Set[str] = set()
    for root, dirs, files in os.walk(source, followlinks=True):
        real = os.path.realpath(root)
        if real in seen:
            dirs[:] = []
            continue
        seen.add(real)
        dirs.sort()
        for name in sorted(files):
            found.append(os.path.relpath(os.path.join(root, name), source))
    return found


def _store(source: Path, target: Path) -> int:
    """Copies a file (content, mode, times) into the safety folder."""
    shutil.copy2(source, target)  # keeps the mode; the folder is private
    return os.path.getsize(target)


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    """Writes JSON atomically, private to the user."""
    temp = path.with_name(path.name + ".tmp")
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=1, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def _put_back(stored: Path, destination: Path, mode_from: Path) -> None:
    """Replaces ``destination`` with a copy of ``stored`` without a gap."""
    os.makedirs(destination.parent, exist_ok=True)
    temp = destination.with_name(f".{destination.name}.kongui-restore")
    try:
        shutil.copyfile(stored, temp)
        shutil.copystat(mode_from, temp)
        os.replace(temp, destination)
    finally:
        if os.path.lexists(temp):
            os.unlink(temp)


def _restore_entry(folder: Path, entry: Dict[str, Any]) -> None:
    """Restores one manifest entry."""
    destination = Path(entry["path"])
    kind = entry["kind"]
    if kind == "created":
        if os.path.islink(destination) or os.path.isfile(destination):
            os.unlink(destination)
        return
    if kind == "file":
        stored = folder / entry["stored"]
        if os.path.isdir(destination) and not os.path.islink(destination):
            raise IsADirectoryError("a folder is in the way")
        _put_back(stored, destination, stored)
        return
    # symlink: bring back the link, and the content it pointed at if the
    # operation wrote through it (import) or not (apply replaced the link)
    link = entry["link"]
    if not (os.path.islink(destination) and os.readlink(destination) == link):
        if os.path.isdir(destination) and not os.path.islink(destination):
            raise IsADirectoryError("a folder is in the way")
        if os.path.lexists(destination):
            os.unlink(destination)
        os.makedirs(destination.parent, exist_ok=True)
        os.symlink(link, destination)
    if "stored" in entry:
        stored = folder / entry["stored"]
        _put_back(stored, Path(entry["target"]), stored)
