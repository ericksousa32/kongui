"""Safety checks shared by the services: root guard and name validation."""

from __future__ import annotations

import os
from typing import Callable, Optional

from kongui.core.errors import RunningAsRootError, ValidationError

KNSV_SUFFIX = ".knsv"
MAX_NAME_LENGTH = 200

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
    if len(value) > MAX_NAME_LENGTH:
        raise ValidationError(f"{label} is longer than {MAX_NAME_LENGTH} characters")
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
    two different names from it and could merge into an existing profile.

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
