"""Input checks for names typed in the interface, with translated messages."""

from __future__ import annotations

from typing import Collection, Optional

from PySide6.QtCore import QCoreApplication as Q

from kongui.core.errors import ValidationError
from kongui.core.safety import validate_archive_name, validate_profile_name


def profile_name_problem(name: str, existing: Collection[str] = ()) -> Optional[str]:
    """Explains why a profile name cannot be used.

    The rules come from the integration layer
    (:func:`kongui.core.safety.validate_profile_name`), so the interface
    refuses exactly what the services would refuse.

    Args:
        name: Name typed by the user.
        existing: Names already in use.

    Returns:
        Optional[str]: A message in the interface language, or ``None`` if the name is fine.
    """
    if not name.strip():
        return Q.translate("validation", "Enter a name for the profile.")
    try:
        validate_profile_name(name)
    except ValidationError:
        return Q.translate(
            "validation",
            "Invalid name. Do not use slashes, “.” or “..”, a leading hyphen, "
            "spaces at the ends, control characters, the .knsv extension or the "
            "reserved prefix “.kongui-”. Maximum 200 bytes (accented letters and "
            "emojis take more than one).",
        )
    if name in existing:
        return Q.translate("validation", "A profile with that name already exists.")
    return None


def archive_name_problem(name: str) -> Optional[str]:
    """Explains why an exported file name (without extension) cannot be used.

    Uses :func:`kongui.core.safety.validate_archive_name`, so the interface
    refuses exactly what the export service would refuse.

    Args:
        name: Name typed by the user.

    Returns:
        Optional[str]: A message in the interface language, or ``None`` if the name is fine.
    """
    if not name.strip():
        return Q.translate("validation", "Enter a name for the file.")
    try:
        validate_archive_name(name)
    except ValidationError:
        return Q.translate(
            "validation",
            "Invalid name. Do not use slashes, “.” or “..”, a leading hyphen, "
            "spaces at the ends, control characters, or the .knsv or .zip "
            "extensions. Maximum 200 bytes (accented letters and emojis take "
            "more than one).",
        )
    return None
