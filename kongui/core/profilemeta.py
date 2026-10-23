"""Profile details that Konsave does not store: a description and the sections.

Konsave keeps no description, so KonGUI keeps a small file next to the profile's
own files: ``<profile>/.kongui-profile.json``. Living inside the profile folder
means it is removed with the profile, survives applying and re-saving, and can
never be attached to another profile that happens to reuse a name. Konsave does
not export it, and it is not part of the ``.knsv`` format.

The *sections* are not stored at all: they are read from the profile's own
``conf.yaml`` (the ``save`` groups that really hold files).

Everything read from disk is untrusted (a folder can come from an imported
archive), so reading is strict about size and type and never raises.
"""

from __future__ import annotations

import json
import os
import stat
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

import yaml

from kongui.core.errors import ValidationError

#: Name of the file inside the profile folder.
META_FILENAME = ".kongui-profile.json"

#: Layout version of the file; a file with another version is ignored.
META_VERSION = 1

#: Longest accepted description, in characters.
MAX_DESCRIPTION_CHARS = 500

#: Largest metadata file that is read, in bytes.
MAX_META_BYTES = 16 * 1024

#: Largest ``conf.yaml`` read to find the sections, in bytes (as in ConfigService).
_MAX_CONF_BYTES = 1024 * 1024

#: Start of the warning that says a description could not be written.
DESCRIPTION_NOT_SAVED = "description not saved: "

#: Start of the warning that says a description that came inside an imported
#: archive could not be removed.
DESCRIPTION_NOT_REMOVED = (
    "could not remove the description that came with the archive: "
)

#: Unicode characters that reorder text (used to disguise it); dropped.
_BIDI_CONTROLS = frozenset(
    chr(code) for code in (*range(0x202A, 0x202F), *range(0x2066, 0x206A))
)


@dataclass(frozen=True)
class ProfileDetails:
    """What KonGUI knows about a profile besides what Konsave stores.

    Attributes:
        description: Free text (empty if none).
        sections: Names of the ``save`` groups that hold files, in the order of
            the profile's ``conf.yaml``.
    """

    description: str = ""
    sections: Tuple[str, ...] = ()


def clean_description(text: object, *, truncate: bool = False) -> str:
    """Normalizes a description.

    Line breaks become ``\\n``; control characters (except newline and tab),
    unpaired surrogates and text-direction overrides are dropped; surrounding
    blanks are removed.

    Args:
        text: The candidate text.
        truncate: Cut a too long text instead of refusing it (used when reading).

    Returns:
        str: The cleaned text, possibly empty.

    Raises:
        ValidationError: If ``text`` is not a string, or is longer than
            :data:`MAX_DESCRIPTION_CHARS` characters (unless ``truncate``).
    """
    if not isinstance(text, str):
        raise ValidationError("the description must be text")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    kept = []
    for char in text:
        if char in "\n\t":
            kept.append(char)
        elif char in _BIDI_CONTROLS or unicodedata.category(char) in ("Cc", "Cs"):
            continue
        else:
            kept.append(char)
    cleaned = "".join(kept).strip()
    if len(cleaned) > MAX_DESCRIPTION_CHARS:
        if not truncate:
            raise ValidationError(
                f"description too long: {len(cleaned)} characters, "
                f"the limit is {MAX_DESCRIPTION_CHARS}"
            )
        cleaned = cleaned[:MAX_DESCRIPTION_CHARS].rstrip()
    return cleaned


def read_description(folder: Path) -> str:
    """Reads the description of a profile folder.

    Never raises: a missing, unreadable, oversized, not regular, malformed or
    foreign-version file simply means "no description".

    Args:
        folder: The profile folder.

    Returns:
        str: The description, or ``""``.
    """
    path = Path(folder) / META_FILENAME
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_META_BYTES:
                return ""
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                raw = handle.read(MAX_META_BYTES + 1)
        finally:
            os.close(descriptor)
        data = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, RecursionError):
        return ""
    if not isinstance(data, dict) or data.get("version") != META_VERSION:
        return ""
    value = data.get("description")
    if not isinstance(value, str):
        return ""
    return clean_description(value, truncate=True)


def write_description(folder: Path, text: str) -> None:
    """Writes (or, if empty, removes) the description of a profile folder.

    The file is written to a temporary name and renamed into place, so a
    failure never leaves a half-written file, and the folder's modification
    time is put back (editing a text must not make the profile look "updated").

    Args:
        folder: The profile folder.
        text: The new description; empty removes the file.

    Raises:
        ValidationError: If the text is not acceptable (see
            :func:`clean_description`); nothing is written.
        OSError: If the file could not be written.
    """
    folder = Path(folder)
    cleaned = clean_description(text)
    if not cleaned:
        remove_description(folder)
        return
    payload = json.dumps(
        {"version": META_VERSION, "description": cleaned},
        ensure_ascii=False,
        indent=2,
    )
    before = folder.stat()
    temporary = folder / f"{META_FILENAME}.tmp-{os.getpid()}-{time.time_ns()}"
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, folder / META_FILENAME)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    finally:
        _restore_times(folder, before)


def remove_description(folder: Path) -> None:
    """Removes the description file of a profile folder, if there is one.

    Args:
        folder: The profile folder.

    Raises:
        OSError: If the file exists and could not be removed.
    """
    folder = Path(folder)
    try:
        before = folder.stat()
        os.unlink(folder / META_FILENAME)
    except FileNotFoundError:
        return
    _restore_times(folder, before)


def copy_description(source: Path, target: Path) -> None:
    """Carries the description of one profile folder over to another.

    Used by ``replace``, which swaps the whole folder. A folder without a
    (valid) description leaves the target without one.

    Args:
        source: Folder to read from.
        target: Folder to write to.

    Raises:
        OSError: If the target could not be written.
    """
    text = read_description(source)
    if text:
        write_description(target, text)


def profile_sections(folder: Path) -> Tuple[str, ...]:
    """Lists the ``save`` groups of a profile that really hold files.

    The groups come from the profile's own ``conf.yaml``. A group whose folder
    is missing or has no file in it (``autostart`` in the default configuration)
    is left out, and so are group names that could point outside the profile.
    Never raises.

    Args:
        folder: The profile folder.

    Returns:
        Tuple[str, ...]: Group names, in the order of the file.
    """
    folder = Path(folder)
    try:
        conf = folder / "conf.yaml"
        info = os.lstat(conf)
        if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_CONF_BYTES:
            return ()
        with open(conf, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle.read())
    except (OSError, ValueError, yaml.YAMLError, RecursionError):
        return ()
    groups = data.get("save") if isinstance(data, dict) else None
    if not isinstance(groups, dict):
        return ()
    found = []
    for name in groups:
        if _usable_group(name) and _holds_files(folder / name):
            found.append(name)
    return tuple(found)


def _usable_group(name: object) -> bool:
    """Whether a group name is plain text that stays inside the profile folder."""
    return (
        isinstance(name, str)
        and bool(name)
        and name not in (".", "..", META_FILENAME)
        and not any(char in name for char in "/\\\0")
    )


def _holds_files(folder: Path) -> bool:
    """Whether a folder (not a link) contains at least one file, at any depth."""
    try:
        if not stat.S_ISDIR(os.lstat(folder).st_mode):
            return False
        pending = [str(folder)]
        while pending:
            with os.scandir(pending.pop()) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(entry.path)
                    else:
                        return True
    except OSError:
        return False
    return False


def _restore_times(folder: Path, before: os.stat_result) -> None:
    """Puts a folder's access and modification times back (best effort)."""
    try:
        os.utime(folder, ns=(before.st_atime_ns, before.st_mtime_ns))
    except OSError:
        pass
