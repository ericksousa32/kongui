"""Integration layer between a future GUI and the original Konsave engine."""

from kongui.core.cli import READ_ONLY_FLAGS, CliRunner
from kongui.core.config import ConfigService
from kongui.core.engine import EngineCall, KonsaveEngine
from kongui.core.errors import (
    ArchiveExistsError,
    CliExecutionError,
    ConfigMissingError,
    ConfigValidationError,
    ConfirmationRequiredError,
    EngineLoadError,
    KonGuiError,
    NotImplementedOperationError,
    OperationFailedError,
    ProfileExistsError,
    ProfileInvalidError,
    ProfileNotFoundError,
    RunningAsRootError,
    ValidationError,
)
from kongui.core.profiles import NOT_IMPLEMENTED_OPERATIONS, ProfileService
from kongui.core.results import (
    ArchiveInspection,
    CliResult,
    OperationResult,
    ProfileInfo,
    ValidationReport,
)

__all__ = [
    "ArchiveExistsError",
    "ArchiveInspection",
    "CliExecutionError",
    "CliResult",
    "CliRunner",
    "ConfigMissingError",
    "ConfigService",
    "ConfigValidationError",
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
    "ValidationReport",
]
