"""Plain data objects returned by the integration services."""

from __future__ import annotations

import re
from datetime import datetime
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple, Union

from kongui.core.errors import OperationFailedError

_VERSION_LINE = re.compile(r"^Konsave:\s*(\S+)\s*$", re.MULTILINE)

#: Printed by the original exception handler (``funcs.exception_handler``)
#: right before the process exits with status 0.
ERROR_MARKER = "Please check the log at"


PathStep = Union[str, int]


@dataclass(frozen=True)
class Problem:
    """One finding about a ``conf.yaml``, with where it is.

    Attributes:
        severity: ``"error"`` (blocks saving) or ``"warning"``.
        code: Stable identifier of the kind of finding, used by the GUI to
            pick a translated explanation.
        path: Where in the document, e.g. ``("save", "configs", "entries", 3)``.
        message: English explanation (the same text kept in
            :attr:`ValidationReport.errors`/``warnings``, without the label).
        label: Dotted ``kind.group`` prefix of the legacy text, if any.
        line: 1-based line in the text, if known.
        column: 1-based column in the text, if known.
        args: Values the explanation refers to (name, value, supported…).
    """

    severity: str
    code: str
    path: Tuple[PathStep, ...]
    message: str
    label: str = ""
    line: Optional[int] = None
    column: Optional[int] = None
    args: Dict[str, Any] = field(default_factory=dict, hash=False, compare=False)

    @property
    def is_error(self) -> bool:
        """Whether this finding blocks saving."""
        return self.severity == "error"

    @property
    def text(self) -> str:
        """The legacy one-line text (``label: message``)."""
        return f"{self.label}: {self.message}" if self.label else self.message

    @property
    def dotted_path(self) -> str:
        """The path written as ``save.configs.entries[3]``."""
        out = ""
        for step in self.path:
            out += (
                f"[{step}]" if isinstance(step, int) else f"{'.' if out else ''}{step}"
            )
        return out


@dataclass(frozen=True)
class ValidationReport:
    """Outcome of validating a ``conf.yaml``.

    Attributes:
        errors: Problems that make the configuration unusable.
        warnings: Problems that deserve attention but do not block.
        resolved: The configuration after placeholder resolution, produced by
            the original ``read_konsave_config``. ``None`` if not reached.
        problems: The same findings, structured and located in the text.
    """

    errors: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()
    resolved: Optional[Dict[str, Any]] = None
    problems: Tuple[Problem, ...] = ()

    @property
    def ok(self) -> bool:
        """Whether the report has no errors."""
        return not self.errors

    def with_errors(self, extra: Iterable[str]) -> "ValidationReport":
        """Returns a copy of the report with extra errors appended.

        Args:
            extra: Additional error messages.

        Returns:
            ValidationReport: The new report.
        """
        return replace(self, errors=self.errors + tuple(extra))


@dataclass(frozen=True)
class BackupInfo:
    """A saved copy of a previous ``conf.yaml``.

    Attributes:
        name: File name, ``conf.yaml.bak-<date>-<time>-<microseconds>``.
        path: Full path of the backup.
        created: When the backup was made (from its name; else its mtime).
        size_bytes: Size of the backup.
    """

    name: str
    path: Path
    created: datetime
    size_bytes: int


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
        warnings: Non-blocking observations about the configuration.
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
    """

    operation: str
    ok: bool
    message: str
    stdout: str = ""
    stderr: str = ""
    errors: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()
    path: Optional[Path] = None

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
