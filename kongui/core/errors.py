"""Exception hierarchy of the KonGUI integration layer.

Preconditions that fail *before* anything touches the disk raise one of these
exceptions. Outcomes of the original Konsave engine are reported through
:class:`kongui.core.results.OperationResult` instead, because the engine can
fail halfway and the caller needs stdout, stderr and the error list.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover
    from kongui.core.results import OperationResult, ValidationReport


class KonGuiError(Exception):
    """Base class for every error raised by the integration layer."""


class RunningAsRootError(KonGuiError):
    """Raised when the process runs as root (euid 0)."""


class EngineLoadError(KonGuiError):
    """Raised when the original Konsave modules cannot be loaded."""


class ValidationError(KonGuiError):
    """Raised when an argument or a file is invalid."""


class ConfigValidationError(ValidationError):
    """Raised when a ``conf.yaml`` (or an operation derived from it) is unsafe.

    Attributes:
        report: The validation report that explains the problem, if any.
    """

    def __init__(
        self, message: str, report: Optional["ValidationReport"] = None
    ) -> None:
        """Creates the error.

        Args:
            message: Human readable summary.
            report: Detailed report with every error and warning found.
        """
        super().__init__(message)
        self.report = report


class ConfigConflictError(KonGuiError):
    """Raised when ``conf.yaml`` changed on disk after it was loaded for editing."""


class BackupNotFoundError(KonGuiError):
    """Raised when a requested ``conf.yaml`` backup does not exist."""


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
