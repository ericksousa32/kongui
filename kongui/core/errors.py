"""Exception hierarchy of the KonGUI integration layer.

Preconditions that fail *before* anything touches the disk raise one of these
exceptions. Outcomes of the original Konsave engine are reported through
:class:`kongui.core.results.OperationResult` instead, because the engine can
fail halfway and the caller needs stdout, stderr and the error list.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, Optional, Tuple

if TYPE_CHECKING:  # pragma: no cover
    from kongui.core.results import OperationResult


class KonGuiError(Exception):
    """Base class for every error raised by the integration layer."""


class RunningAsRootError(KonGuiError):
    """Raised when the process runs as root (euid 0)."""


class EngineLoadError(KonGuiError):
    """Raised when the original Konsave modules cannot be loaded."""


class ValidationError(KonGuiError):
    """Raised when an argument or a file is invalid."""


class ArchiveLimitError(ValidationError):
    """Raised when a ``.knsv`` is larger than the import limits allow.

    Attributes:
        kind: ``"size"`` (the file), ``"extracted"`` (bytes after decompressing)
            or ``"entries"`` (number of members).
        limit: The limit that was exceeded (bytes, or a count for ``"entries"``).
        actual: The measured value, or ``None`` when counting stopped at the
            limit (``"extracted"``).
    """

    def __init__(
        self, message: str, kind: str, limit: int, actual: Optional[int] = None
    ) -> None:
        """Creates the error.

        Args:
            message: Human readable summary.
            kind: Which limit was exceeded.
            limit: The limit.
            actual: The measured value, if known.
        """
        super().__init__(message)
        self.kind = kind
        self.limit = limit
        self.actual = actual


class InsufficientSpaceError(KonGuiError):
    """Raised before an import or export when the disk clearly lacks room.

    Attributes:
        folder: Folder whose file system was checked.
        needed: Estimated bytes needed (including the safety margin).
        available: Free bytes found.
    """

    def __init__(self, message: str, folder: str, needed: int, available: int) -> None:
        """Creates the error.

        Args:
            message: Human readable summary.
            folder: Folder whose file system was checked.
            needed: Estimated bytes needed.
            available: Free bytes found.
        """
        super().__init__(message)
        self.folder = folder
        self.needed = needed
        self.available = available


class ConfigError(ValidationError):
    """Raised when Konsave cannot read a ``conf.yaml``, or what it says is unsafe.

    KonGUI does not validate ``conf.yaml`` files itself: it reads them through
    the original ``read_konsave_config`` and refuses an operation only when that
    fails or when the result would write outside the home folder.

    Attributes:
        details: One line per reason (may be empty).
    """

    def __init__(self, message: str, details: Iterable[str] = ()) -> None:
        """Creates the error.

        Args:
            message: Human readable summary.
            details: The reasons, one per line.
        """
        super().__init__(message)
        self.details: Tuple[str, ...] = tuple(str(line) for line in details)


class ConfigMissingError(KonGuiError):
    """Raised when the active ``conf.yaml`` does not exist."""


class ProfileNotFoundError(KonGuiError):
    """Raised when the requested profile does not exist."""


class ProfileInvalidError(KonGuiError):
    """Raised when a profile exists but is incomplete (for example no conf)."""


class ProfileExistsError(KonGuiError):
    """Raised when a profile with the requested name already exists."""


class ArchiveExistsError(KonGuiError):
    """Raised when an export would collide with an existing path."""


class ConfirmationRequiredError(KonGuiError):
    """Raised when a destructive operation is called without confirmation."""


class SnapshotError(KonGuiError):
    """Raised when a safety copy cannot be made, read or restored.

    When it is raised while *making* the copy, the operation that needed it
    (apply, import) was not started.
    """


class SnapshotNotFoundError(SnapshotError):
    """Raised when a safety copy does not exist."""


class NotImplementedOperationError(KonGuiError):
    """Raised by operations that are documented but not implemented yet."""


class CliExecutionError(KonGuiError):
    """Raised when the Konsave CLI subprocess cannot be started."""


class OperationFailedError(KonGuiError):
    """Raised by ``OperationResult.raise_for_status`` on a failed operation.

    Attributes:
        result: The failed result.
    """

    def __init__(self, result: "OperationResult") -> None:
        """Creates the error.

        Args:
            result: The failed operation result.
        """
        super().__init__(result.message)
        self.result = result
