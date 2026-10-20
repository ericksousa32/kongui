"""Plain data objects returned by the integration services."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from kongui.core.errors import OperationFailedError

_VERSION_LINE = re.compile(r"^Konsave:\s*(\S+)\s*$", re.MULTILINE)

#: Printed by the original exception handler (``funcs.exception_handler``)
#: right before the process exits with status 0.
ERROR_MARKER = "Please check the log at"


@dataclass(frozen=True)
class ArchiveInspection:
    """What a ``.knsv`` file holds, read without extracting anything.

    Attributes:
        path: The archive.
        name: Profile name it would create (the file name without ``.knsv``).
        size_bytes: Size of the file.
        member_count: Number of entries in the zip.
        save_sections: Sections of the profile (``save`` in its ``conf.yaml``).
        export_sections: Sections written to the live system on import
            (``export`` in its ``conf.yaml``).
        warnings: Non-blocking observations (for example destination folders
            that do not exist yet).
        name_taken: A profile with that name already exists.
    """

    path: Path
    name: str
    size_bytes: int
    member_count: int
    save_sections: Tuple[str, ...] = ()
    export_sections: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()
    name_taken: bool = False


@dataclass(frozen=True)
class OperationResult:  # pylint: disable=too-many-instance-attributes
    """Outcome of an operation executed by the original engine.

    Attributes:
        operation: Short operation name, such as ``"save"``.
        ok: ``True`` only if the engine logged no error and every
            post-condition holds.
        message: One-line summary suitable for a status bar.
        stdout: Everything the engine printed to stdout.
        stderr: Everything the engine printed to stderr.
        errors: Error summaries taken from the engine log.
        warnings: Non-blocking observations.
        path: Main file or folder produced by the operation, if any.
        backup: Copy kept of a file the operation replaced, if any.
    """

    operation: str
    ok: bool
    message: str
    stdout: str = ""
    stderr: str = ""
    errors: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()
    path: Optional[Path] = None
    backup: Optional[Path] = None

    def raise_for_status(self) -> "OperationResult":
        """Raises if the operation failed.

        Returns:
            OperationResult: The same result, for chaining.

        Raises:
            OperationFailedError: If ``ok`` is false.
        """
        if not self.ok:
            raise OperationFailedError(self)
        return self


@dataclass(frozen=True)
class CliResult:
    """Outcome of one Konsave CLI subprocess.

    ``returncode`` is reported as it is, but it cannot be trusted alone: the
    original CLI exits with 0 even when an operation failed. Use :attr:`ok`.

    Attributes:
        args: Arguments that were passed after ``python -m konsave``.
        returncode: Exit code, or ``None`` if the process timed out.
        stdout: Captured standard output.
        stderr: Captured standard error.
        timed_out: Whether the timeout killed the process.
    """

    args: Tuple[str, ...]
    returncode: Optional[int]
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False

    @property
    def reported_error(self) -> bool:
        """Whether stdout carries the original error report."""
        return ERROR_MARKER in self.stdout

    @property
    def ok(self) -> bool:
        """Whether the process exited with 0 *and* reported no error."""
        return self.returncode == 0 and not self.timed_out and not self.reported_error

    def parsed_version(self) -> Optional[str]:
        """Extracts the version from a ``--version`` output.

        Returns:
            Optional[str]: The version, or ``None`` if it cannot be parsed.
        """
        if not self.ok:
            return None
        match = _VERSION_LINE.search(self.stdout)
        return match.group(1) if match else None


@dataclass(frozen=True)
class ProfileInfo:
    """Summary of one saved profile.

    Attributes:
        name: Profile name (its folder name).
        path: Folder of the profile.
        has_config: Whether the profile contains its own ``conf.yaml``.
        modified: Modification time of the folder, if readable.
    """

    name: str
    path: Path
    has_config: bool
    modified: Optional[float] = None
