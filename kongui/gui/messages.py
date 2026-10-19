"""Texts for operation results and errors, in the interface language.

The sources are English and live in the ``messages`` translation context. The
tables hold the English sources, marked with ``QT_TRANSLATE_NOOP`` so that
``pyside6-lupdate`` finds them, and the functions translate them when a text is
needed (so a language switch is picked up at once). Messages that come from the
core and Konsave in English are mapped to full translatable sentences here.
"""

from __future__ import annotations

import errno
import re
from typing import Optional, Tuple

from PySide6.QtCore import QCoreApplication as Q
from PySide6.QtCore import QT_TRANSLATE_NOOP

from kongui.core import (
    DESCRIPTION_NOT_REMOVED,
    DESCRIPTION_NOT_SAVED,
    MAX_DESCRIPTION_CHARS,
    CONF_DIFFERS_PREFIX,
    KEPT_PREFIX,
    UNDO_PREFIX,
    ArchiveExistsError,
    ArchiveLimitError,
    BackupNotFoundError,
    ConfigConflictError,
    ConfigMissingError,
    ConfigValidationError,
    ConfirmationRequiredError,
    InsufficientSpaceError,
    KonGuiError,
    LockBusyError,
    LockCancelledError,
    LockTimeoutError,
    LockUnavailableError,
    OperationFailedError,
    OperationResult,
    Problem,
    ProfileExistsError,
    ProfileInvalidError,
    ProfileNotFoundError,
    RunningAsRootError,
    SnapshotError,
    SnapshotNotFoundError,
    ValidationError,
)
from kongui.gui.formatting import format_size

#: Failure headline of each operation when a profile name is known
#: (``{name}`` is the profile name).
FAILURE_TITLES_WITH_NAME = {
    "save": QT_TRANSLATE_NOOP("messages", "Could not save profile “{name}”"),
    "overwrite": QT_TRANSLATE_NOOP("messages", "Could not overwrite profile “{name}”"),
    "apply": QT_TRANSLATE_NOOP("messages", "Could not apply profile “{name}”"),
    "remove": QT_TRANSLATE_NOOP("messages", "Could not remove profile “{name}”"),
    "duplicate": QT_TRANSLATE_NOOP("messages", "Could not duplicate profile “{name}”"),
    "import": QT_TRANSLATE_NOOP("messages", "Could not import profile “{name}”"),
    "export": QT_TRANSLATE_NOOP("messages", "Could not export profile “{name}”"),
    "set_description": QT_TRANSLATE_NOOP(
        "messages", "Could not update the details of “{name}”"
    ),
}

#: Failure headline of each operation (no profile name).
FAILURE_TITLES = {
    "list": QT_TRANSLATE_NOOP("messages", "Could not list the profiles"),
    "save": QT_TRANSLATE_NOOP("messages", "Could not save the profile"),
    "overwrite": QT_TRANSLATE_NOOP("messages", "Could not overwrite the profile"),
    "apply": QT_TRANSLATE_NOOP("messages", "Could not apply the profile"),
    "remove": QT_TRANSLATE_NOOP("messages", "Could not remove the profile"),
    "wipe_all": QT_TRANSLATE_NOOP("messages", "Could not clear the profiles"),
    "duplicate": QT_TRANSLATE_NOOP("messages", "Could not duplicate the profile"),
    "import": QT_TRANSLATE_NOOP("messages", "Could not import the profile"),
    "export": QT_TRANSLATE_NOOP("messages", "Could not export the profile"),
    "set_description": QT_TRANSLATE_NOOP(
        "messages", "Could not update the profile details"
    ),
    "reset": QT_TRANSLATE_NOOP("messages", "Could not restore the data"),
    "save_config": QT_TRANSLATE_NOOP("messages", "Could not save conf.yaml"),
    "restore_config": QT_TRANSLATE_NOOP(
        "messages", "Could not restore the conf.yaml backup"
    ),
    "restore_backup": QT_TRANSLATE_NOOP(
        "messages", "Could not restore the safety copy"
    ),
    "delete_backup": QT_TRANSLATE_NOOP("messages", "Could not delete the safety copy"),
}

#: Text of the success notification, ``{name}`` is the profile name.
SUCCESS = {
    "save": QT_TRANSLATE_NOOP("messages", "Profile “{name}” saved"),
    "overwrite": QT_TRANSLATE_NOOP("messages", "Profile “{name}” overwritten"),
    "apply": QT_TRANSLATE_NOOP("messages", "Profile “{name}” applied"),
    "remove": QT_TRANSLATE_NOOP("messages", "Profile “{name}” removed"),
    "wipe_all": QT_TRANSLATE_NOOP("messages", "All profiles were removed"),
    "duplicate": QT_TRANSLATE_NOOP("messages", "Profile “{name}” duplicated"),
    "import": QT_TRANSLATE_NOOP("messages", "Profile “{name}” imported"),
    "export": QT_TRANSLATE_NOOP("messages", "Profile “{name}” exported"),
    "set_description": QT_TRANSLATE_NOOP("messages", "Details of “{name}” updated"),
    "reset": QT_TRANSLATE_NOOP("messages", "Fictitious profiles restored"),
    "save_config": QT_TRANSLATE_NOOP("messages", "conf.yaml saved"),
    "restore_config": QT_TRANSLATE_NOOP("messages", "conf.yaml backup restored"),
    "restore_backup": QT_TRANSLATE_NOOP("messages", "Safety copy restored"),
    "delete_backup": QT_TRANSLATE_NOOP("messages", "Safety copy deleted"),
}

#: Extra advice appended to the success of some operations.
SUCCESS_HINT = {
    "apply": QT_TRANSLATE_NOOP(
        "messages", "Log out and back in to see all the changes."
    ),
    "restore_backup": QT_TRANSLATE_NOOP(
        "messages", "Log out and back in to see all the changes."
    ),
    "import": QT_TRANSLATE_NOOP(
        "messages",
        "The profile files were written to the system. Log out and back in to "
        "see everything.",
    ),
}


def success_title(operation: str, name: str) -> str:
    """Returns the success headline.

    Args:
        operation: Operation key.
        name: Profile name (may be empty).

    Returns:
        str: Text for a notification.
    """
    source = SUCCESS.get(operation) or QT_TRANSLATE_NOOP(
        "messages", "Operation completed"
    )
    return Q.translate("messages", source).format(name=name)


def partial_title(operation: str, name: str) -> str:
    """Returns the headline of an operation that worked only in part.

    Args:
        operation: Operation key.
        name: Profile name.

    Returns:
        str: For example ``Profile “Work” saved, but not its description``.
    """
    del operation  # only saving can end this way for now
    return Q.translate(
        "messages", "Profile “{name}” saved, but not its description"
    ).format(name=name)


def is_partial(result: Optional[OperationResult]) -> bool:
    """Tells whether a successful result carries a "description not saved" note."""
    return result is not None and any(
        line.startswith(DESCRIPTION_NOT_SAVED) for line in result.warnings
    )


#: Friendly names of the ``save`` groups of the default Konsave configuration.
#: Any other group keeps its own name (it is whatever the user wrote).
SECTION_LABELS = {
    "configs": QT_TRANSLATE_NOOP("messages", "Desktop settings"),
    "app_layouts": QT_TRANSLATE_NOOP("messages", "App layouts"),
    "autostart": QT_TRANSLATE_NOOP("messages", "Startup apps"),
}


def section_label(name: str) -> str:
    """Returns the name shown for a profile section (a ``save`` group).

    Args:
        name: Group name as written in ``conf.yaml``.

    Returns:
        str: The friendly name in the interface language for the groups of the
        default configuration, otherwise ``name`` unchanged.
    """
    source = SECTION_LABELS.get(name)
    return Q.translate("messages", source) if source else name


def _limit(lines, count: int = 4) -> Tuple[str, ...]:
    """Keeps the first lines and says how many were dropped."""
    lines = tuple(str(line) for line in lines if str(line).strip())
    if len(lines) <= count:
        return lines
    return lines[:count] + (
        Q.translate("messages", "… and %n more.", "", len(lines) - count),
    )


def holder_hint(holder: Optional[dict]) -> str:
    """Describes who seems to hold the lock, or ``""``.

    The information comes from a file any process may have written, so it is
    presented as a hint, never as a fact.

    Args:
        holder: ``{"pid", "operation"}`` or ``None``.
    """
    if not holder:
        return ""
    operation = holder.get("operation") or Q.translate("messages", "operation")
    return Q.translate(
        "messages", "Hint (unverified): “{operation}”, process {pid}."
    ).format(operation=operation, pid=holder.get("pid"))


def describe_wait(holder: Optional[dict]) -> Tuple[str, Tuple[str, ...]]:
    """Texts for the "waiting for another operation" banner.

    Args:
        holder: Unverified information about the holder, or ``None``.

    Returns:
        tuple: ``(headline, detail lines)``.
    """
    lines = [
        Q.translate(
            "messages",
            "It is running in the terminal or in another KonGUI window. "
            "Nothing has been changed so far; the operation starts by itself "
            "when it finishes.",
        )
    ]
    hint = holder_hint(holder)
    if hint:
        lines.append(hint)
    return Q.translate("messages", "Waiting for another Konsave operation…"), tuple(
        lines
    )


def failure_title(operation: str, name: str) -> str:
    """Returns the failure headline.

    Args:
        operation: Operation key.
        name: Profile name (may be empty).

    Returns:
        str: For example ``Could not apply profile “Gaming”``.
    """
    if name and operation in FAILURE_TITLES_WITH_NAME:
        return Q.translate("messages", FAILURE_TITLES_WITH_NAME[operation]).format(
            name=name
        )
    source = FAILURE_TITLES.get(operation)
    if source is None:
        if name:
            return Q.translate(
                "messages", "Could not complete the operation “{name}”"
            ).format(name=name)
        return Q.translate("messages", "Could not complete the operation")
    return Q.translate("messages", source)


_NO_DATA_FOLDER = re.compile(r"^the archive has no data folder in save/ for: (.+?) \(")
_UNLISTED_FOLDER = re.compile(
    r"^save/ has folders that its conf.yaml does not list: (.+?) \("
)


_KEPT = re.compile(r"^" + re.escape(KEPT_PREFIX) + r"(\S+)$")
_UNDO = re.compile(r"^" + re.escape(UNDO_PREFIX) + r"(\S+)$")


def describe_note(line: str) -> str:
    """Formats one line of ``OperationResult.warnings`` for a notification.

    Real warnings get the "Warning:" prefix; the notes naming a safety copy are
    information, not a problem.

    Args:
        line: English text from the services.

    Returns:
        str: Text in the interface language.
    """
    if _KEPT.match(line) or _UNDO.match(line):
        return describe_warning(line)
    return Q.translate("messages", "Warning: {text}").format(
        text=describe_warning(line)
    )


def _describe_description_warning(line: str) -> Optional[str]:
    """Translates the warnings about the description file, or returns ``None``."""
    if line.startswith(DESCRIPTION_NOT_SAVED):
        return Q.translate(
            "messages",
            "The profile was saved, but its description could not be written: "
            "{reason}",
        ).format(reason=line[len(DESCRIPTION_NOT_SAVED) :])
    if line.startswith(DESCRIPTION_NOT_REMOVED):
        return Q.translate(
            "messages",
            "The description that came inside the archive could not be removed: "
            "{reason}",
        ).format(reason=line[len(DESCRIPTION_NOT_REMOVED) :])
    return None


def describe_warning(line: str) -> str:
    """Translates a non-blocking warning of the services.

    Args:
        line: English warning text.

    Returns:
        str: Text in the interface language; warnings it does not know are
        returned unchanged.
    """
    if line.startswith(CONF_DIFFERS_PREFIX):
        found = line.rsplit("): ", 1)[-1]
        return Q.translate(
            "messages",
            "The .knsv carries Konsave's current conf.yaml, which differs from "
            "the conf.yaml stored in this profile. Groups: {found} (+ only in "
            "the current one, − only in the profile, ~ changed). On another "
            "computer, a new group prevents applying the profile and a group "
            "that disappeared is ignored without warning.",
        ).format(found=found)
    match = _KEPT.match(line)
    if match:
        return Q.translate(
            "messages",
            "Safety copy stored ({id}). To undo, use Settings → Safety copies.",
        ).format(id=match.group(1))
    match = _UNDO.match(line)
    if match:
        return Q.translate(
            "messages", "The state before the restore was stored in {id}."
        ).format(id=match.group(1))
    described = _describe_description_warning(line)
    if described:
        return described
    match = _NO_DATA_FOLDER.match(line)
    if match:
        return Q.translate(
            "messages",
            "The archive has no data for the groups: {groups}. The imported "
            "profile cannot be applied.",
        ).format(groups=match.group(1))
    match = _UNLISTED_FOLDER.match(line)
    if match:
        return Q.translate(
            "messages",
            "The archive has folders that its conf.yaml does not list: "
            "{groups}. They will be ignored when applying the profile.",
        ).format(groups=match.group(1))
    return line


def describe_result(result: OperationResult) -> Tuple[str, ...]:
    """Explains a failed :class:`OperationResult`.

    Args:
        result: A result with ``ok`` false.

    Returns:
        Tuple[str, ...]: Detail lines (engine errors, warnings, message).
    """
    lines = [result.message] if result.message else []
    lines += [line for line in result.errors if line not in lines]
    lines += [describe_note(line) for line in result.warnings]
    reason = _failure_reason(" ".join(lines))
    return _limit(([reason] if reason else []) + lines)


def _no_space_text() -> str:
    """The explanation of a full disk."""
    return Q.translate(
        "messages",
        "The disk ran out of free space during the operation. Free some space "
        "and try again.",
    )


def _failure_reason(text: str) -> Optional[str]:
    """Explains, in plain words, the engine failures that users can fix.

    Args:
        text: The English failure text of an operation (message and errors).

    Returns:
        Optional[str]: The explanation, or ``None`` when the failure is unknown.
    """
    if "[Errno 28]" in text or "No space left on device" in text:
        return _no_space_text()
    if "description could not be carried over" in text:
        return Q.translate(
            "messages",
            "The profile was not replaced because its description could not be "
            "copied to the new version. The previous profile is intact.",
        )
    if "BadZipFile" in text or "Bad CRC-32" in text:
        return Q.translate(
            "messages",
            "The file is corrupted: its contents could not be read to the end. "
            "Download or export it again.",
        )
    return None


#: Fragments of ``ValidationError`` messages (English, from the services) and
#: the English source of their text. The first match wins; unknown messages are
#: shown as they are.
_VALIDATION_TEXTS = (
    ("archive not found", QT_TRANSLATE_NOOP("messages", "The file was not found.")),
    (
        "must be a '*",
        QT_TRANSLATE_NOOP("messages", "Choose a file with the .knsv extension."),
    ),
    (
        "corrupted archive",
        QT_TRANSLATE_NOOP(
            "messages",
            "The file is corrupted: its contents could not be read to the end. "
            "Download or export it again.",
        ),
    ),
    (
        "not a readable archive",
        QT_TRANSLATE_NOOP(
            "messages", "The file is not a valid .knsv (not a readable zip)."
        ),
    ),
    (
        "archive has no conf.yaml",
        QT_TRANSLATE_NOOP(
            "messages",
            "The file does not contain conf.yaml and is not a Konsave profile.",
        ),
    ),
    (
        "no 'save/' folder",
        QT_TRANSLATE_NOOP(
            "messages",
            "The file does not contain the save/ folder and is not a Konsave "
            "profile.",
        ),
    ),
    (
        "unsafe path inside archive",
        QT_TRANSLATE_NOOP(
            "messages", "The file contains unsafe paths and was refused."
        ),
    ),
    (
        "conf.yaml is too large",
        QT_TRANSLATE_NOOP("messages", "The conf.yaml in the file is too large."),
    ),
    (
        "output folder does not exist",
        QT_TRANSLATE_NOOP("messages", "The destination folder does not exist."),
    ),
    (
        "output folder is not writable",
        QT_TRANSLATE_NOOP("messages", "No write permission in the destination folder."),
    ),
    (
        "description too long",
        QT_TRANSLATE_NOOP(
            "messages", "The description is too long (at most {limit} characters)."
        ),
    ),
    (
        "stale import folder",
        QT_TRANSLATE_NOOP(
            "messages",
            "There is an old, abandoned import folder; remove it first.",
        ),
    ),
)


#: English source of the explanation of each kind of ``conf.yaml`` finding
#: (``Problem.code``). ``{…}`` fields are taken from ``Problem.args``.
PROBLEM_TEXTS = {
    "file-missing": QT_TRANSLATE_NOOP("messages", "The conf.yaml file does not exist."),
    "file-too-large": QT_TRANSLATE_NOOP(
        "messages", "The file is too large to be a Konsave configuration."
    ),
    "file-unreadable": QT_TRANSLATE_NOOP(
        "messages", "The file could not be read: {detail}"
    ),
    "yaml-syntax": QT_TRANSLATE_NOOP(
        "messages",
        "The YAML is malformed: {problem}. Fix the syntax (indentation, quotes, "
        "colons or brackets) at this point.",
    ),
    "root-not-mapping": QT_TRANSLATE_NOOP(
        "messages",
        "The file must be a map with the “save” and “export” sections at the root.",
    ),
    "missing-top-key": QT_TRANSLATE_NOOP(
        "messages",
        "The “{key}” section is missing. Konsave requires both sections, “save” "
        "and “export”; use “{key}: {{}}” if it should stay empty.",
    ),
    "section-not-mapping": QT_TRANSLATE_NOOP(
        "messages",
        "“{key}” must be a map of groups. Leaving it empty (“{key}:”) makes "
        "Konsave fail; write “{key}: {{}}”.",
    ),
    "unknown-top-mapping": QT_TRANSLATE_NOOP(
        "messages",
        "The key “{key}” is unknown and is ignored when saving and exporting. "
        "It was kept in the file.",
    ),
    "unknown-top-scalar": QT_TRANSLATE_NOOP(
        "messages",
        "The unknown key “{key}” must be a map of groups; Konsave goes through "
        "every key at the root and would fail here.",
    ),
    "duplicate-key": QT_TRANSLATE_NOOP(
        "messages",
        "The key “{key}” appears more than once. YAML keeps only the last one "
        "and the other would be silently lost.",
    ),
    "group-name-invalid": QT_TRANSLATE_NOOP(
        "messages",
        "The group name “{name}” must be a plain folder name: no “/”, not "
        "empty, “.” or “..”.",
    ),
    "group-not-mapping": QT_TRANSLATE_NOOP(
        "messages", "The group must have “location” and “entries”."
    ),
    "group-unknown-keys": QT_TRANSLATE_NOOP(
        "messages",
        "Unknown keys in this group are ignored by Konsave: {keys_text}. They "
        "were kept in the file.",
    ),
    "location-invalid": QT_TRANSLATE_NOOP(
        "messages", "“location” must be a non-empty text (the source folder)."
    ),
    "placeholder-unsupported": QT_TRANSLATE_NOOP(
        "messages",
        "The placeholder ${name} does not exist in Konsave. The recognized ones "
        "are: {supported}.",
    ),
    "function-unsupported": QT_TRANSLATE_NOOP(
        "messages",
        "The function ${{{name}=...}} does not exist in Konsave. Recognized: "
        "{supported}.",
    ),
    "function-multiple": QT_TRANSLATE_NOOP(
        "messages",
        "Only the last placeholder function has an effect in the original Konsave.",
    ),
    "entries-missing": QT_TRANSLATE_NOOP(
        "messages",
        "“entries” is missing. Use an empty list (“entries: []”) if the group "
        "has no items.",
    ),
    "entries-not-list": QT_TRANSLATE_NOOP(
        "messages", "“entries” must be a list of names."
    ),
    "entry-invalid": QT_TRANSLATE_NOOP(
        "messages",
        "The item {value_text} must be a single file or folder name, without "
        "“/”. Nested paths make Konsave abort the whole save.",
    ),
    "entry-duplicate": QT_TRANSLATE_NOOP(
        "messages", "The item {value_text} is repeated."
    ),
    "location-unresolved": QT_TRANSLATE_NOOP(
        "messages",
        "The placeholder was not resolved ({resolved}). Without a matching "
        "folder, Konsave would use this text as a relative path.",
    ),
    "location-relative": QT_TRANSLATE_NOOP(
        "messages", "The resolved folder is not an absolute path: {resolved}."
    ),
    "location-missing-dir": QT_TRANSLATE_NOOP(
        "messages",
        "The folder {resolved} does not exist on this computer; the items of "
        "this group will be silently ignored.",
    ),
    "comments-lost": QT_TRANSLATE_NOOP(
        "messages",
        "The file's comments could not be kept in this edit; when saving, they "
        "will be lost (the previous file is kept as a backup).",
    ),
    "konsave-failed": QT_TRANSLATE_NOOP(
        "messages", "Konsave could not interpret the file: {detail}"
    ),
}


def describe_problem(problem: Problem) -> str:
    """Explains one ``conf.yaml`` finding, with its position.

    Args:
        problem: A finding from the validation report.

    Returns:
        str: For example
        ``line 12, column 9 · save.configs.entries[3]: The item … must …``.
    """
    return f"{problem_place(problem)}: {problem_text(problem)}"


def problem_text(problem: Problem) -> str:
    """Explains one ``conf.yaml`` finding, without its position."""
    args = dict(problem.args)
    args["keys_text"] = ", ".join(str(key) for key in args.get("keys", ()))
    args["value_text"] = repr(args.get("value", ""))
    source = PROBLEM_TEXTS.get(problem.code)
    try:
        return (
            Q.translate("messages", source).format(**args)
            if source
            else problem.message
        )
    except (KeyError, IndexError):
        return problem.message


def problem_place(problem: Problem) -> str:
    """Writes where a finding is, as ``line 3, column 5 · save.a.location``."""
    parts = []
    if problem.line is not None:
        if problem.column is not None:
            parts.append(
                Q.translate("messages", "line {line}, column {column}").format(
                    line=problem.line, column=problem.column
                )
            )
        else:
            parts.append(
                Q.translate("messages", "line {line}").format(line=problem.line)
            )
    if problem.dotted_path:
        parts.append(problem.dotted_path)
    return " · ".join(parts) or Q.translate("messages", "file")


def _translate_validation(text: str) -> str:
    """Returns the text, in the interface language, for a validation message."""
    for fragment, source in _VALIDATION_TEXTS:
        if fragment in text:
            translation = Q.translate("messages", source)
            if fragment == "stale import folder":
                # The user has to delete it by hand, so say where it is.
                return Q.translate("messages", "{text} Folder: {path}").format(
                    text=translation, path=text.rsplit(": ", 1)[-1]
                )
            if fragment == "description too long":
                return translation.format(limit=MAX_DESCRIPTION_CHARS)
            return translation
    return Q.translate("messages", "Invalid input: {text}").format(text=text)


def _describe_os_error(error: OSError) -> Tuple[str, ...]:
    """Explains a file-system error (permissions, missing file…)."""
    where = f" ({error.filename})" if error.filename else ""
    if error.errno == errno.ENOSPC:
        return (_no_space_text(),)
    if isinstance(error, PermissionError):
        return (
            Q.translate(
                "messages", "No permission to access the file or folder{where}."
            ).format(where=where),
        )
    if isinstance(error, FileNotFoundError):
        return (
            Q.translate("messages", "File or folder not found{where}.").format(
                where=where
            ),
        )
    if isinstance(error, IsADirectoryError):
        return (
            Q.translate(
                "messages", "A file was expected, but it is a folder{where}."
            ).format(where=where),
        )
    if isinstance(error, NotADirectoryError):
        return (
            Q.translate(
                "messages", "A folder was expected, but it is a file{where}."
            ).format(where=where),
        )
    return (
        Q.translate("messages", "File error{where}: {reason}").format(
            where=where, reason=error.strerror or error
        ),
    )


def _describe_limit(error: ArchiveLimitError) -> str:
    """Explains which import limit a file went over."""
    if error.kind == "size":
        return Q.translate(
            "messages",
            "The file is too large to import ({size}; the limit is {limit}). "
            "Check that it is a profile exported by KonGUI or Konsave.",
        ).format(
            size=format_size((error.actual or 0) / 1048576),
            limit=format_size(error.limit / 1048576),
        )
    if error.kind == "entries":
        return Q.translate(
            "messages",
            "The file has too many items ({count}; the limit is {limit}). "
            "Check that it is a profile exported by KonGUI or Konsave.",
        ).format(count=error.actual, limit=error.limit)
    return Q.translate(
        "messages",
        "Decompressed, the file would use more than {limit}, which is above the "
        "safety limit, so it was not imported. It may not be a profile.",
    ).format(limit=format_size(error.limit / 1048576))


def describe_error(  # pylint: disable=too-many-return-statements
    error: BaseException,
) -> Tuple[str, ...]:
    """Explains an exception raised by a service, in the interface language.

    Args:
        error: The exception.

    Returns:
        Tuple[str, ...]: Detail lines. Unknown exceptions are reported with
        their type so that a bug is not hidden behind a generic text.
    """
    if isinstance(error, RunningAsRootError):
        return (
            Q.translate(
                "messages", "KonGUI must not be run as root. Open it as your own user."
            ),
        )
    if isinstance(error, ProfileExistsError):
        return (
            Q.translate(
                "messages",
                "A profile with that name already exists. Use “Overwrite” to "
                "replace it.",
            ),
        )
    if isinstance(error, ProfileNotFoundError):
        return (
            Q.translate(
                "messages", "The profile no longer exists. The list was refreshed."
            ),
        )
    if isinstance(error, ArchiveExistsError):
        return (
            Q.translate(
                "messages",
                "A file, folder or .zip with that name already exists at the "
                "destination. Choose another name or another conflict policy.",
            ),
        )
    if isinstance(error, ProfileInvalidError):
        return (
            Q.translate(
                "messages",
                "The profile is incomplete (no conf.yaml) and cannot be applied.",
            ),
        )
    if isinstance(error, ConfigMissingError):
        return (Q.translate("messages", "There is no active Konsave conf.yaml."),)
    if isinstance(error, ConfirmationRequiredError):
        return (
            Q.translate(
                "messages",
                "The operation requires explicit confirmation and was not "
                "confirmed.",
            ),
        )
    if isinstance(error, ConfigValidationError):
        report = error.report
        if report is not None and report.problems:
            located = [problem for problem in report.problems if problem.is_error]
            known = {problem.text for problem in located}
            # Errors added by the service after validating (a destination outside
            # the home, a folder that does not exist) have no located problem;
            # without them a refusal could be shown with no reason at all.
            extra = [line for line in report.errors if line not in known]
            lines = [describe_problem(problem) for problem in located] + extra
            if lines:
                return _limit(lines)
        lines = [str(error)]
        if report is not None:
            lines += list(report.errors)
        return _limit(lines)
    if isinstance(error, ConfigConflictError):
        return (
            Q.translate(
                "messages",
                "conf.yaml was changed by another program after being opened "
                "here. Nothing was written.",
            ),
        )
    if isinstance(error, LockBusyError):
        if isinstance(error, LockTimeoutError):
            first = Q.translate(
                "messages",
                "The other Konsave operation (in the terminal or in another "
                "KonGUI window) did not finish in time. Nothing was changed; "
                "try again when it finishes.",
            )
        else:
            first = Q.translate(
                "messages",
                "Another Konsave operation is in progress (in the terminal or "
                "in another KonGUI window). Nothing was changed; try again when "
                "it finishes.",
            )
        lines = [first]
        hint = holder_hint(error.holder)
        if hint:
            lines.append(hint)
        return tuple(lines)
    if isinstance(error, LockCancelledError):
        return (
            Q.translate("messages", "The wait was cancelled. Nothing was changed."),
        )
    if isinstance(error, LockUnavailableError):
        return (
            Q.translate(
                "messages",
                "The Konsave lock file could not be used "
                "(~/.config/konsave/.kongui.lock). Nothing was changed.",
            ),
            Q.translate("messages", "Detail: {error}").format(error=error),
        )
    if isinstance(error, SnapshotNotFoundError):
        return (
            Q.translate(
                "messages", "That safety copy no longer exists. The list was refreshed."
            ),
        )
    if isinstance(error, SnapshotError):
        return (
            Q.translate(
                "messages",
                "The safety copy could not be made or read, so the operation "
                "was not done (or not completed).",
            ),
            Q.translate("messages", "Detail: {error}").format(error=error),
        )
    if isinstance(error, BackupNotFoundError):
        return (
            Q.translate(
                "messages", "That backup no longer exists. The list was refreshed."
            ),
        )
    if isinstance(error, InsufficientSpaceError):
        return (
            Q.translate(
                "messages",
                "Not enough free disk space in {folder}: about {needed} are "
                "needed and {available} are free. Free some space and try "
                "again. Nothing was changed.",
            ).format(
                folder=error.folder,
                needed=format_size(error.needed / 1048576),
                available=format_size(error.available / 1048576),
            ),
        )
    if isinstance(error, ArchiveLimitError):
        return (_describe_limit(error),)
    if isinstance(error, OperationFailedError):
        return describe_result(error.result)
    if isinstance(error, ValidationError):
        return (_translate_validation(str(error)),)
    if isinstance(error, KonGuiError):
        return (str(error),)
    if isinstance(error, OSError):
        return _describe_os_error(error)
    return (
        Q.translate("messages", "Unexpected error ({type}): {error}").format(
            type=type(error).__name__, error=error
        ),
    )


def outcome_hint(operation: str, ok: bool) -> Optional[str]:
    """Returns advice to show under a success notification.

    Args:
        operation: Operation key.
        ok: Whether the operation succeeded.

    Returns:
        Optional[str]: The hint, or ``None``.
    """
    source = SUCCESS_HINT.get(operation) if ok else None
    return Q.translate("messages", source) if source else None
