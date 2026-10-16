"""Connects the pages to a :class:`~kongui.gui.backend.ProfileBackend`.

One operation runs at a time. Each one goes through the same life cycle:

``operation_started`` → work in a worker thread → store updated →
``operation_finished(Outcome)``.

After every operation the profile list is read again (in the same worker
call), so the interface always shows what is on disk, even when the operation
failed halfway. Destructive operations refuse to start without
``confirmed=True``; the pages obtain it from a dialog.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Callable, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal

from kongui.core import ConfirmationRequiredError, OperationResult
from kongui.gui import messages
from kongui.gui.backend import ProfileBackend
from kongui.gui.state import AppSettings, Profile, ProfileStore
from kongui.gui.tasks import Executor

LOG = logging.getLogger(__name__)


class LoadState(str, Enum):
    """State of the profile list."""

    IDLE = "idle"
    LOADING = "loading"
    READY = "ready"
    ERROR = "error"


@dataclass(frozen=True)
class Outcome:
    """What happened in one operation.

    Attributes:
        operation: ``list``, ``save``, ``overwrite``, ``apply``, ``remove``,
            ``wipe_all``, ``duplicate``, ``import`` or ``reset``.
        name: Profile concerned, or ``""``.
        ok: Whether the operation succeeded.
        title: Headline for a notification.
        details: Extra lines (engine errors, hints).
        result: The service result, when there was one.
        error: The exception, when the service raised one.
    """

    operation: str
    name: str
    ok: bool
    title: str
    details: Tuple[str, ...] = ()
    result: Optional[OperationResult] = None
    error: Optional[BaseException] = None


@dataclass(frozen=True)
class _JobValue:
    """What the worker thread returns."""

    result: Optional[OperationResult]
    profiles: Optional[List[Profile]]
    list_error: Optional[BaseException]
    work_error: Optional[BaseException] = None


class ProfileController(QObject):  # pylint: disable=too-many-public-methods
    """Runs profile operations and keeps the :class:`ProfileStore` current.

    Signals:
        state_changed: Busy flag, current operation or list state changed.
        operation_started: ``(operation, name)``.
        operation_finished: An :class:`Outcome`.
    """

    state_changed = Signal()
    operation_started = Signal(str, str)
    operation_finished = Signal(object)

    def __init__(
        self,
        backend: ProfileBackend,
        executor: Executor,
        store: ProfileStore,
        settings: AppSettings,
        parent: Optional[QObject] = None,
    ) -> None:
        """Creates the controller.

        Args:
            backend: Where the operations go.
            executor: Where blocking work runs.
            store: View model to keep up to date.
            settings: Preferences; ``last_applied`` is kept there.
            parent: Optional Qt parent.
        """
        super().__init__(parent)
        self._backend = backend
        self._executor = executor
        self._store = store
        self._settings = settings
        self._state = LoadState.IDLE
        self._error: Tuple[str, ...] = ()
        self._current: Optional[Tuple[str, str]] = None
        stored = str(settings.get("last_applied"))
        self._active = stored or backend.initial_active or ""

    # ---------------------------------------------------------------- properties

    @property
    def backend(self) -> ProfileBackend:
        """The backend in use."""
        return self._backend

    @property
    def executor(self) -> Executor:
        """The executor in use."""
        return self._executor

    @property
    def state(self) -> LoadState:
        """State of the profile list."""
        return self._state

    @property
    def error(self) -> Tuple[str, ...]:
        """Why the last listing failed (empty unless ``state`` is ``ERROR``)."""
        return self._error

    @property
    def busy(self) -> bool:
        """Whether an operation is running."""
        return self._current is not None

    @property
    def current(self) -> Optional[Tuple[str, str]]:
        """``(operation, name)`` of the running operation, if any."""
        return self._current

    @property
    def active_name(self) -> str:
        """Profile applied most recently from this interface, or ``""``."""
        return self._active

    # ---------------------------------------------------------------- operations

    def refresh(self) -> bool:
        """Reads the profile list again.

        Returns:
            bool: ``False`` if another operation is running.
        """
        return self._run("list", "", None)

    def save(
        self, name: str, description: str = "", sections: Tuple[str, ...] = ()
    ) -> bool:
        """Saves the current configuration as a new profile.

        Args:
            name: New profile name.
            description: Free text (kept only by backends that support it).
            sections: Chosen sections (same).

        Returns:
            bool: ``False`` if another operation is running.
        """
        return self._run(
            "save", name, lambda: self._backend.save(name, description, sections)
        )

    def overwrite(self, name: str, *, confirmed: bool = False) -> bool:
        """Replaces a profile with the current configuration.

        Args:
            name: Existing profile.
            confirmed: Must be ``True``.

        Returns:
            bool: ``False`` if another operation is running.

        Raises:
            ConfirmationRequiredError: If ``confirmed`` is not exactly ``True``.
        """
        self._need(confirmed, "overwrite")
        return self._run(
            "overwrite", name, lambda: self._backend.overwrite(name, confirmed=True)
        )

    def apply(self, name: str, *, confirmed: bool = False) -> bool:
        """Applies a profile to the live session.

        Args:
            name: Existing profile.
            confirmed: Must be ``True``.

        Returns:
            bool: ``False`` if another operation is running.

        Raises:
            ConfirmationRequiredError: If ``confirmed`` is not exactly ``True``.
        """
        self._need(confirmed, "apply")
        return self._run(
            "apply", name, lambda: self._backend.apply(name, confirmed=True)
        )

    def remove(self, name: str, *, confirmed: bool = False) -> bool:
        """Deletes one profile.

        Args:
            name: Existing profile.
            confirmed: Must be ``True``.

        Returns:
            bool: ``False`` if another operation is running.

        Raises:
            ConfirmationRequiredError: If ``confirmed`` is not exactly ``True``.
        """
        self._need(confirmed, "remove")
        return self._run(
            "remove", name, lambda: self._backend.remove(name, confirmed=True)
        )

    def wipe_all(self, *, confirmed: bool = False) -> bool:
        """Deletes every profile.

        Args:
            confirmed: Must be ``True``.

        Returns:
            bool: ``False`` if another operation is running.

        Raises:
            ConfirmationRequiredError: If ``confirmed`` is not exactly ``True``.
        """
        self._need(confirmed, "wipe_all")
        return self._run("wipe_all", "", lambda: self._backend.wipe_all(confirmed=True))

    def duplicate(self, name: str) -> bool:
        """Duplicates a profile (backends with ``capabilities.duplicate`` only).

        Args:
            name: Existing profile.

        Returns:
            bool: ``False`` if another operation is running.
        """
        return self._run("duplicate", name, lambda: self._backend.duplicate(name))

    def demo_import(self, profile: Profile, apply_after: bool = False) -> bool:
        """Adds a simulated imported profile (demo backends only).

        Args:
            profile: The profile to add.
            apply_after: Also mark it as applied.

        Returns:
            bool: ``False`` if another operation is running.
        """

        def work() -> OperationResult:
            result = self._backend.add_profile(profile)
            if apply_after:
                self._backend.apply(profile.name, confirmed=True)
            return result

        if self.busy:
            return False
        self._pending_active = profile.name if apply_after else ""
        return self._run("import", profile.name, work)

    def demo_reset(self) -> bool:
        """Restores the demo data (demo backends only).

        Returns:
            bool: ``False`` if another operation is running.
        """
        return self._run("reset", "", self._backend.reset)

    # ------------------------------------------------------------------ internals

    @staticmethod
    def _need(confirmed: bool, operation: str) -> None:
        """Refuses a destructive call without explicit confirmation."""
        if confirmed is not True:
            raise ConfirmationRequiredError(f"'{operation}' needs confirmed=True")

    _pending_active: str = ""

    def _run(
        self, operation: str, name: str, work: Optional[Callable[[], OperationResult]]
    ) -> bool:
        """Starts an operation unless another one is running."""
        if self.busy:
            return False
        self._current = (operation, name)
        if operation == "list" or self._state is LoadState.IDLE:
            self._state = LoadState.LOADING
        self.operation_started.emit(operation, name)
        self.state_changed.emit()

        def job() -> _JobValue:
            # The list is read again even if the operation failed: the interface
            # must show what is really on disk.
            result: Optional[OperationResult] = None
            work_error: Optional[BaseException] = None
            if work is not None:
                try:
                    result = work()
                except Exception as caught:  # pylint: disable=broad-exception-caught
                    work_error = caught
            try:
                profiles: Optional[List[Profile]] = self._backend.list_profiles()
                list_error = None
            except Exception as caught:  # pylint: disable=broad-exception-caught
                profiles, list_error = None, caught
                if work is None:
                    raise
            return _JobValue(result, profiles, list_error, work_error)

        self._executor.submit(
            job, lambda value, error: self._finish(operation, name, value, error)
        )
        return True

    def _finish(
        self,
        operation: str,
        name: str,
        value: Optional[_JobValue],
        error: Optional[BaseException],
    ) -> None:
        """Handles a finished job in the GUI thread."""
        self._current = None
        profiles = value.profiles if value is not None else None
        result = value.result if value is not None else None
        list_error = value.list_error if value is not None else None
        if error is None and value is not None:
            error = value.work_error
        if error is not None and not _is_expected(error):
            LOG.error("unexpected error in %s", operation, exc_info=error)
        if profiles is not None:
            self._after_listing(operation, name, result, profiles)
            self._state = LoadState.READY
            self._error = ()
        elif operation == "list" and error is not None:
            self._state = LoadState.ERROR
            self._error = messages.describe_error(error)
        elif self._state is LoadState.LOADING:
            self._state = LoadState.READY if self._store.profiles() else LoadState.ERROR
            if self._state is LoadState.ERROR:
                self._error = messages.describe_error(error) if error else ()
        outcome = self._outcome(operation, name, result, error, list_error)
        self._pending_active = ""
        self.state_changed.emit()
        self.operation_finished.emit(outcome)

    def _after_listing(
        self,
        operation: str,
        name: str,
        result: Optional[OperationResult],
        profiles: List[Profile],
    ) -> None:
        """Updates the active marker and publishes the new list."""
        names = {profile.name for profile in profiles}
        if operation == "apply" and result is not None and result.ok:
            self._active = name
        elif operation == "reset":
            self._active = self._backend.initial_active or ""
        elif (
            operation == "import"
            and self._pending_active
            and self._pending_active in names
        ):
            self._active = self._pending_active
        if self._active and self._active not in names:
            self._active = ""
        if not self._backend.capabilities.demo:
            self._settings.set("last_applied", self._active)
        self._store.replace(
            [replace(item, active=item.name == self._active) for item in profiles]
        )

    @staticmethod
    def _outcome(
        operation: str,
        name: str,
        result: Optional[OperationResult],
        error: Optional[BaseException],
        list_error: Optional[BaseException],
    ) -> Outcome:
        """Builds the :class:`Outcome` of a finished operation."""
        if error is not None:
            return Outcome(
                operation,
                name,
                False,
                messages.failure_title(operation, name),
                messages.describe_error(error),
                error=error,
            )
        if result is not None and not result.ok:
            return Outcome(
                operation,
                name,
                False,
                messages.failure_title(operation, name),
                messages.describe_result(result),
                result=result,
            )
        details: List[str] = []
        hint = messages.outcome_hint(operation, True)
        if hint:
            details.append(hint)
        if result is not None:
            details += [f"Aviso: {line}" for line in result.warnings]
        if list_error is not None:
            details.append(
                "A lista de perfis não pôde ser atualizada: "
                + " ".join(messages.describe_error(list_error))
            )
        return Outcome(
            operation,
            name,
            True,
            messages.success_title(operation, name),
            tuple(details),
            result=result,
        )


def _is_expected(error: BaseException) -> bool:
    """Tells whether an exception is a normal ``KonGuiError`` outcome."""
    from kongui.core import KonGuiError  # pylint: disable=import-outside-toplevel

    return isinstance(error, KonGuiError)


__all__: List[Any] = ["LoadState", "Outcome", "ProfileController"]
