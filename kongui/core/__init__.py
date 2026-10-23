"""Integration layer between the GUI and the original Konsave engine."""

# pylint: disable=duplicate-code

from kongui.core.cli import READ_ONLY_FLAGS, CliRunner
from kongui.core.config import ConfigService
from kongui.core.engine import EngineCall, KonsaveEngine
from kongui.core.errors import (
    ArchiveExistsError,
    ArchiveLimitError,
    CliExecutionError,
    ConfigError,
    ConfigMissingError,
    ConfirmationRequiredError,
    EngineLoadError,
    InsufficientSpaceError,
    KonGuiError,
    NotImplementedOperationError,
    OperationFailedError,
    ProfileExistsError,
    ProfileInvalidError,
    ProfileNotFoundError,
    RunningAsRootError,
    SnapshotError,
    SnapshotNotFoundError,
    ValidationError,
)
from kongui.core.profilemeta import (
    DESCRIPTION_NOT_REMOVED,
    DESCRIPTION_NOT_SAVED,
    MAX_DESCRIPTION_CHARS,
    ProfileDetails,
    clean_description,
)
from kongui.core.profiles import NOT_IMPLEMENTED_OPERATIONS, ProfileService
from kongui.core.lock import (
    EngineLock,
    LockBusyError,
    LockCancelledError,
    LockError,
    LockPolicy,
    LockTimeoutError,
    LockUnavailableError,
    LockUsageError,
    describe_holder,
)
from kongui.core.snapshot import (
    KEPT_PREFIX,
    UNDO_PREFIX,
    SnapshotInfo,
    SnapshotService,
)
from kongui.core.results import (
    ArchiveInspection,
    CliResult,
    OperationResult,
    ProfileInfo,
)

__all__ = [
    "DESCRIPTION_NOT_REMOVED",
    "DESCRIPTION_NOT_SAVED",
    "MAX_DESCRIPTION_CHARS",
    "clean_description",
    "ProfileDetails",
    "EngineLock",
    "LockBusyError",
    "LockCancelledError",
    "LockError",
    "LockPolicy",
    "LockTimeoutError",
    "LockUnavailableError",
    "LockUsageError",
    "describe_holder",
    "KEPT_PREFIX",
    "UNDO_PREFIX",
    "SnapshotError",
    "SnapshotInfo",
    "SnapshotNotFoundError",
    "SnapshotService",
    "ArchiveExistsError",
    "ArchiveLimitError",
    "InsufficientSpaceError",
    "ArchiveInspection",
    "CliExecutionError",
    "CliResult",
    "CliRunner",
    "ConfigError",
    "ConfigMissingError",
    "ConfigService",
    "ConfirmationRequiredError",
    "EngineCall",
    "EngineLoadError",
    "KonGuiError",
    "KonsaveEngine",
    "NOT_IMPLEMENTED_OPERATIONS",
    "NotImplementedOperationError",
    "OperationFailedError",
    "OperationResult",
    "ProfileExistsError",
    "ProfileInfo",
    "ProfileInvalidError",
    "ProfileNotFoundError",
    "ProfileService",
    "READ_ONLY_FLAGS",
    "RunningAsRootError",
    "ValidationError",
]
