"""Safety checks shared by the services: root guard and name validation."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Callable, Optional

from kongui.core.errors import (
    InsufficientSpaceError,
    RunningAsRootError,
    ValidationError,
)

KNSV_SUFFIX = ".knsv"
#: Longest name accepted, in UTF-8 *bytes*. Linux limits a file name to 255
#: bytes (not characters), and the service adds a prefix and a timestamp to it
#: when it builds the temporary folders of ``ProfileService.replace``.
MAX_NAME_BYTES = 200
#: Names starting with this are reserved for the temporary folders created by
#: ``ProfileService.replace``. ``list_profiles`` hides them, so a profile with
#: such a name would be saved but never shown (and could not be removed).
RESERVED_PREFIX = ".kongui-"

#: Import limits for a ``.knsv`` (protection against huge or "zip bomb" files).
#: They are initial values, not a guarantee that every legitimate profile fits:
#: change them here if a real profile needs more.
MAX_ARCHIVE_BYTES = 512 * 1024**2
#: Bytes actually produced by decompressing every member (counted, not read from
#: the zip headers, which a hostile file can falsify).
MAX_EXTRACTED_BYTES = 2 * 1024**3
MAX_ARCHIVE_ENTRIES = 10_000
#: Free space that must remain on top of the estimate (the estimate is rough).
DISK_MARGIN_BYTES = 64 * 1024**2

EuidProvider = Callable[[], Optional[int]]


def current_euid() -> Optional[int]:
    """Returns the effective user id of the process.

    Returns:
        Optional[int]: The euid, or ``None`` on platforms without one.
    """
    getter = getattr(os, "geteuid", None)
    return getter() if getter is not None else None


def ensure_not_root(euid_provider: EuidProvider = current_euid) -> None:
    """Refuses to continue when running as root.

    Konsave only manages per-user files; running it as root would write into
    the wrong home directory and create root-owned files.

    Args:
        euid_provider: Callable returning the euid; injectable for tests.

    Raises:
        RunningAsRootError: If the effective user id is 0.
    """
    if euid_provider() == 0:
        raise RunningAsRootError(
            "KonGUI must not run as root: Konsave only manages per-user files."
        )


def is_plain_name(value: object) -> bool:
    """Tells whether a value is a single, relative path component.

    This is the rule for group names and entries of a ``conf.yaml``: they are
    joined to a folder, so they must not climb out of it or nest.

    Args:
        value: Candidate name.

    Returns:
        bool: ``True`` if safe to join to a folder.
    """
    return (
        isinstance(value, str)
        and bool(value)
        and value not in {".", ".."}
        and "/" not in value
        and "\0" not in value
    )


def _validate_component(value: object, label: str) -> str:
    """Validates a single file-name component.

    Args:
        value: Candidate value.
        label: Name used in error messages.

    Returns:
        str: The validated value.

    Raises:
        ValidationError: If the value is not a safe single path component.
    """
    if not isinstance(value, str):
        raise ValidationError(f"{label} must be a string")
    if not value or value != value.strip():
        raise ValidationError(f"{label} must not be empty or start/end with whitespace")
    if len(value.encode("utf-8", "surrogatepass")) > MAX_NAME_BYTES:
        raise ValidationError(
            f"{label} is longer than {MAX_NAME_BYTES} bytes in UTF-8 "
            "(accented letters and emoji take more than one byte)"
        )
    if value in {".", ".."}:
        raise ValidationError(f"{label} must not be '.' or '..'")
    if value.startswith("-"):
        raise ValidationError(f"{label} must not start with '-'")
    if "/" in value or "\\" in value:
        raise ValidationError(f"{label} must not contain path separators")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValidationError(f"{label} must not contain control characters")
    return value


def validate_profile_name(name: object) -> str:
    """Validates a profile name.

    The original ``save_profile`` joins the name to the profiles folder without
    any check, so ``../x`` would escape that folder and ``.`` would pollute it.
    A name containing ``.knsv`` is refused because ``import_profile`` derives
    two different names from it and could merge into an existing profile. A
    name starting with :data:`RESERVED_PREFIX` is refused because the service
    hides such folders (they are its own temporary folders).

    Args:
        name: Candidate profile name.

    Returns:
        str: The validated name.

    Raises:
        ValidationError: If the name is not acceptable.
    """
    value = _validate_component(name, "profile name")
    if KNSV_SUFFIX in value:
        raise ValidationError(f"profile name must not contain '{KNSV_SUFFIX}'")
    if value.startswith(RESERVED_PREFIX):
        raise ValidationError(
            f"profile name must not start with '{RESERVED_PREFIX}' (reserved)"
        )
    return value


def validate_archive_name(name: object) -> str:
    """Validates the base name of an exported archive (without extension).

    Args:
        name: Candidate archive name.

    Returns:
        str: The validated name.

    Raises:
        ValidationError: If the name is not acceptable.
    """
    value = _validate_component(name, "archive name")
    if value.lower().endswith((KNSV_SUFFIX, ".zip")):
        raise ValidationError(
            f"archive name must not include the '{KNSV_SUFFIX}' or '.zip' extension"
        )
    return value


def tree_size(path: Path) -> int:
    """Adds up the sizes of the files under a path, without following links.

    Unreadable entries count as zero: the result is only an estimate.

    Args:
        path: File or folder.

    Returns:
        int: Bytes.
    """
    total = 0
    pending = [str(path)]
    while pending:
        current = pending.pop()
        try:
            info = os.lstat(current)
            if not os.path.isdir(current) or os.path.islink(current):
                total += info.st_size
                continue
            with os.scandir(current) as entries:
                pending.extend(entry.path for entry in entries)
        except OSError:
            continue
    return total


def require_free_space(folder: Path, needed: int, what: str) -> None:
    """Refuses to start when the file system of ``folder`` clearly lacks room.

    This is an estimate before the work, not a guarantee: a real "no space"
    error during the operation is still handled by the caller. When the free
    space cannot be read, the operation is allowed to go on.

    Args:
        folder: An existing folder on the file system that will receive data.
        needed: Estimated bytes the operation will write.
        what: Short English name of the operation, for the message.

    Raises:
        InsufficientSpaceError: If less than ``needed`` plus the safety margin
            is free.
    """
    try:
        available = shutil.disk_usage(folder).free
    except OSError:
        return
    required = needed + DISK_MARGIN_BYTES
    if available < required:
        raise InsufficientSpaceError(
            f"not enough free space for {what} in {folder}: "
            f"about {required} bytes needed, {available} free",
            str(folder),
            required,
            available,
        )
