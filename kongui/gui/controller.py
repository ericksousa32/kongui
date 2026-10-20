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
import threading
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QCoreApplication, QObject, Signal, Slot

from kongui.core import (
    ConfirmationRequiredError,
    KonGuiError,
    LockError,
    OperationResult,
)
from kongui.gui import messages
from kongui.gui.backend import ArchiveInfo, ProfileBackend
from kongui.gui.state import AppSettings, Profile, ProfileStore
from kongui.gui.tasks import Executor

LOG = logging.getLogger(__name__)

#: Operations that cannot change the profile list: it is not reloaded after them.
_LIST_UNCHANGED = (
    "restore_backup",
    "delete_backup",
)


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
            ``wipe_all``, ``duplicate``, ``set_description``, ``import`` or ``reset``.
        name: Profile concerned, or ``""``.
        ok: Whether the operation succeeded.
        title: Headline for a notification.
        details: Extra lines (engine errors, hints).
        result: The service result, when there was one.
        error: The exception, when the service raised one.
        warning: The operation worked, but only in part (for example the
            profile was saved and its description was not); it is shown as a
            warning, not as a plain success.
    """

    operation: str
    name: str
    ok: bool
    title: str
    details: Tuple[str, ...] = ()
    result: Optional[OperationResult] = None
    error: Optional[BaseException] = None
    warning: bool = False


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
    #: Emitted by the worker thread when the lock is busy (queued to the GUI).
    _wait_reported = Signal(object)

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
        self._error_cause: Optional[BaseException] = None
        self._current: Optional[Tuple[str, str]] = None
        self._waiting: Optional[Dict[str, Any]] = None
        self._cancelling = False
        self._cancel = threading.Event()
        self._wait_reported.connect(self._on_wait_reported)
        backend.configure_lock_wait(self._wait_reported.emit, self._cancel)
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
        """Why the last listing failed (empty unless ``state`` is ``ERROR``).

        The lines are written when read, in the interface language of that
        moment, so a language switch shows an open error in the new language.
        """
        if self._error_cause is None:
            return ()
        return messages.describe_error(self._error_cause)

    @property
    def busy(self) -> bool:
        """Whether an operation is running."""
        return self._current is not None

    @property
    def current(self) -> Optional[Tuple[str, str]]:
        """``(operation, name)`` of the running operation, if any."""
        return self._current

    @property
    def waiting(self) -> bool:
        """Whether the running operation is waiting for another process's lock."""
        return self._waiting is not None

    @property
    def waiting_holder(self) -> Dict[str, Any]:
        """Unverified information about who holds the lock (may be empty)."""
        return dict(self._waiting or {})

    @property
    def cancelling(self) -> bool:
        """Whether the user asked to stop waiting and the wait is ending."""
        return self._cancelling

    @property
    def active_name(self) -> str:
        """Profile applied most recently from this interface, or ``""``."""
        return self._active

    # ---------------------------------------------------------------- operations

    def cancel_wait(self) -> bool:
        """Stops waiting for another process's lock (nothing is changed).

        Only the wait is cancelled: an operation that already started is never
        interrupted. The operation then ends with a "wait cancelled" outcome.

        Returns:
            bool: ``False`` if nothing is waiting.
        """
        if self._waiting is None or self._cancelling:
            return False
        self._cancelling = True
        self._cancel.set()
        self.state_changed.emit()
        return True

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

    def set_description(self, name: str, description: str) -> bool:
        """Sets, changes or clears the description of a profile.

        Args:
            name: Existing profile.
            description: New text; empty clears it.

        Returns:
            bool: ``False`` if another operation is running.
        """
        return self._run(
            "set_description",
            name,
            lambda: self._backend.set_description(name, description),
        )

    def duplicate(self, name: str) -> bool:
        """Duplicates a profile (backends with ``capabilities.duplicate`` only).

        Args:
            name: Existing profile.

        Returns:
            bool: ``False`` if another operation is running.
        """
        return self._run("duplicate", name, lambda: self._backend.duplicate(name))

    def export_profile(
        self,
        name: str,
        directory: str,
        archive_name: Optional[str] = None,
        on_conflict: str = "error",
        *,
        confirmed: bool = False,
    ) -> bool:
        """Exports a profile to a ``.knsv`` file.

        Args:
            name: Existing profile.
            directory: Output folder.
            archive_name: File name without extension (default: the profile name).
            on_conflict: ``error``, ``unique`` or ``overwrite``.
            confirmed: Must be ``True`` when ``on_conflict`` is ``overwrite``.

        Returns:
            bool: ``False`` if another operation is running.

        Raises:
            ConfirmationRequiredError: If replacing is asked without confirmation.
        """
        if on_conflict == "overwrite":
            self._need(confirmed, "export")
        return self._run(
            "export",
            name,
            lambda: self._backend.export_profile(
                name, directory, archive_name, on_conflict
            ),
        )

    def import_profile(
        self,
        path: str,
        name: Optional[str] = None,
        apply_after: bool = False,
        *,
        confirmed: bool = False,
    ) -> bool:
        """Imports a ``.knsv`` file, optionally applying the new profile.

        Importing writes the archive's export section into the live system, so
        it always needs confirmation. Applying afterwards is a second, separate
        step; if it fails the import still stands and a warning says so.

        Args:
            path: The archive.
            name: Name of the new profile (default: the file name).
            apply_after: Apply the profile once imported.
            confirmed: Must be ``True``.

        Returns:
            bool: ``False`` if another operation is running.

        Raises:
            ConfirmationRequiredError: If ``confirmed`` is not exactly ``True``.
        """
        self._need(confirmed, "import")
        label = name or ""

        def work() -> OperationResult:
            result = self._backend.import_profile(path, name, confirmed=True)
            if not (apply_after and result.ok):
                return result
            target = label or _profile_name_of(result)
            try:
                applied = self._backend.apply(target, confirmed=True)
            except Exception as error:  # pylint: disable=broad-exception-caught
                applied = None
                reason = " ".join(messages.describe_error(error))
            else:
                reason = (
                    " ".join(messages.describe_result(applied))
                    if not applied.ok
                    else ""
                )
            if applied is not None and applied.ok:
                self._pending_active = target
                return result
            return replace(
                result,
                warnings=result.warnings
                + (
                    self.tr(
                        "The profile was imported but not applied: {reason}"
                    ).format(reason=reason),
                ),
            )

        if self.busy:
            return False
        self._pending_active = ""
        return self._run("import", label, work)

    def inspect_archive(
        self,
        path: str,
        on_done: Callable[[Optional[ArchiveInfo], Optional[BaseException]], None],
    ) -> None:
        """Reads a ``.knsv`` without extracting it, off the interface thread.

        It does not count as an operation (the list is not reloaded and other
        operations are not blocked).

        Args:
            path: The archive.
            on_done: Called in the interface thread with ``(info, None)`` or
                ``(None, error)``.
        """
        self._executor.submit(lambda: self._backend.inspect_archive(path), on_done)

    def background(
        self,
        work: Callable[[], Any],
        on_done: Callable[[Any, Optional[BaseException]], None],
    ) -> None:
        """Runs a read-only backend call off the interface thread.

        Like :meth:`inspect_archive`, it is not an operation: the list is not
        reloaded and other operations are not blocked.

        Args:
            work: Blocking callable (for example a backend method).
            on_done: Called in the interface thread with ``(value, None)`` or
                ``(None, error)``.
        """
        self._executor.submit(work, on_done)

    def restore_backup(self, backup_id: str, *, confirmed: bool = False) -> bool:
        """Puts the files of a safety copy back (destructive).

        Args:
            backup_id: Id of the copy.
            confirmed: Must be ``True``.

        Returns:
            bool: ``False`` if another operation is running.

        Raises:
            ConfirmationRequiredError: If ``confirmed`` is not ``True``.
        """
        self._need(confirmed, "restore_backup")
        return self._run(
            "restore_backup",
            backup_id,
            lambda: self._backend.restore_backup(backup_id, confirmed=True),
            reload_profiles=False,
        )

    def delete_backup(self, backup_id: str, *, confirmed: bool = False) -> bool:
        """Deletes a safety copy.

        Args:
            backup_id: Id of the copy.
            confirmed: Must be ``True``.

        Returns:
            bool: ``False`` if another operation is running.

        Raises:
            ConfirmationRequiredError: If ``confirmed`` is not ``True``.
        """
        self._need(confirmed, "delete_backup")
        return self._run(
            "delete_backup",
            backup_id,
            lambda: self._backend.delete_backup(backup_id, confirmed=True),
            reload_profiles=False,
        )

    def demo_reset(self) -> bool:
        """Restores the demo data (demo backends only).

        Returns:
            bool: ``False`` if another operation is running.
        """
        return self._run("reset", "", self._backend.reset)

    # ------------------------------------------------------------------ internals

    @Slot(object)
    def _on_wait_reported(self, holder: Optional[Dict[str, Any]]) -> None:
        """The running operation found the lock busy and is waiting (GUI thread)."""
        if self._current is None:
            return  # a background read, not an operation of ours
        self._waiting = dict(holder or {})
        self.state_changed.emit()

    @staticmethod
    def _need(confirmed: bool, operation: str) -> None:
        """Refuses a destructive call without explicit confirmation."""
        if confirmed is not True:
            raise ConfirmationRequiredError(f"'{operation}' needs confirmed=True")

    _pending_active: str = ""

    def _run(
        self,
        operation: str,
        name: str,
        work: Optional[Callable[[], OperationResult]],
        *,
        reload_profiles: bool = True,
    ) -> bool:
        """Starts an operation unless another one is running.

        ``reload_profiles=False`` is for operations that cannot change the
        profile list (the safety copy ones).
        """
        if self.busy:
            return False
        self._current = (operation, name)
        self._waiting = None
        self._cancelling = False
        self._cancel.clear()
        if operation == "list" or (
            self._state is LoadState.IDLE and operation not in _LIST_UNCHANGED
        ):
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
            if isinstance(work_error, LockError):
                # Nothing ran, so the list cannot have changed; reading it again
                # would only wait for the same lock.
                return _JobValue(result, None, None, work_error)
            if not reload_profiles:
                return _JobValue(result, None, None, work_error)
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
        self._waiting = None
        self._cancelling = False
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
            self._error_cause = None
        elif operation == "list" and error is not None:
            self._state = LoadState.ERROR
            self._error_cause = error
        elif self._state is LoadState.LOADING and operation not in _LIST_UNCHANGED:
            self._state = LoadState.READY if self._store.profiles() else LoadState.ERROR
            if self._state is LoadState.ERROR:
                self._error_cause = error
        if (
            not name
            and result is not None
            and result.path is not None
            and operation not in _LIST_UNCHANGED
        ):
            name = result.path.name
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
        if operation == "export" and result is not None and result.path is not None:
            details.append(str(result.path))
        hint = messages.outcome_hint(operation, True)
        if hint:
            details.append(hint)
        if result is not None:
            details += [messages.describe_note(line) for line in result.warnings]
        if list_error is not None:
            details.append(
                QCoreApplication.translate(
                    "ProfileController",
                    "The profile list could not be refreshed: {reason}",
                ).format(reason=" ".join(messages.describe_error(list_error)))
            )
        partial = messages.is_partial(result)
        return Outcome(
            operation,
            name,
            True,
            (
                messages.partial_title(operation, name)
                if partial
                else messages.success_title(operation, name)
            ),
            tuple(details),
            result=result,
            warning=partial,
        )


def _profile_name_of(result: OperationResult) -> str:
    """Returns the profile folder name an import result points to."""
    return result.path.name if result.path is not None else ""


def _is_expected(error: BaseException) -> bool:
    """Tells whether an exception is a normal ``KonGuiError`` outcome."""
    return isinstance(error, (KonGuiError, LockError, OSError))


__all__: List[Any] = ["LoadState", "Outcome", "ProfileController"]
