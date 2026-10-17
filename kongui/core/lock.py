"""KonGUI side of the cross-process lock.

The mechanism itself lives in :mod:`konsave.lock` (standard library only, so the
original CLI can use it without KonGUI). This module binds it to one
:class:`~kongui.core.engine.KonsaveEngine`: the lock file is
``<konsave folder>/.kongui.lock`` of that engine's home, and the waiting policy
(timeout, cancel event, "waiting" callback) is stored in :class:`LockPolicy` so
that the interface can change it without touching the services.

Rules the services follow (see ``docs/CONCURRENCY.md``):

* ``exclusive`` for anything that writes profiles, live files, ``conf.yaml`` or
  the safety copies; ``shared`` for reads that must see a consistent state.
* The lock is taken by the *public* service methods and, as a safety net, by
  ``KonsaveEngine.call``. Both are re-entrant per thread.
* The lock is never held while the user decides something: dialogs run before
  the service call.
"""

# pylint: disable=duplicate-code

from __future__ import annotations

import functools
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, Optional

from konsave.lock import (
    DEFAULT_TIMEOUT,
    EXCLUSIVE,
    LOCK_NAME,
    SHARED,
    LockBusyError,
    LockCancelledError,
    LockError,
    LockTimeoutError,
    LockUnavailableError,
    LockUsageError,
    OperationLock,
    default_lock_path,
    describe_holder,
)

__all__ = [
    "DEFAULT_TIMEOUT",
    "EXCLUSIVE",
    "LOCK_NAME",
    "SHARED",
    "EngineLock",
    "LockBusyError",
    "LockCancelledError",
    "LockError",
    "LockPolicy",
    "LockTimeoutError",
    "LockUnavailableError",
    "LockUsageError",
    "describe_holder",
    "guarded",
]


@dataclass
class LockPolicy:
    """How long and how an operation waits for the lock.

    Attributes:
        timeout: Seconds to wait; ``0`` fails at once if busy; ``None`` waits
            for ever.
        cancel: Event that, when set, ends the wait with
            :class:`~konsave.lock.LockCancelledError`.
        on_wait: Called (from the waiting thread) once when the lock is busy and
            the call is going to wait, with unverified holder information.
    """

    timeout: Optional[float] = DEFAULT_TIMEOUT
    cancel: Optional[threading.Event] = None
    on_wait: Optional[Callable[[Optional[Dict[str, Any]]], None]] = None


class EngineLock:
    """The lock of one engine's Konsave folder plus its waiting policy."""

    def __init__(self, konsave_dir: Any) -> None:
        """Creates the handle (no file is touched yet).

        Args:
            konsave_dir: The engine's Konsave folder.
        """
        self._lock = OperationLock(default_lock_path(str(konsave_dir)))
        self.policy = LockPolicy()

    @property
    def path(self) -> str:
        """Absolute path of the lock file."""
        return self._lock.path

    @contextmanager
    def hold(self, mode: str, operation: str = "") -> Iterator[None]:
        """Holds the lock under the current :attr:`policy`.

        Args:
            mode: :data:`SHARED` or :data:`EXCLUSIVE`.
            operation: Short name for diagnostics.
        """
        policy = self.policy
        with self._lock.hold(
            mode,
            operation=operation,
            timeout=policy.timeout,
            cancel=policy.cancel,
            on_wait=policy.on_wait,
        ):
            yield


def guarded(mode: str, operation: Optional[str] = None):
    """Decorator for a service method: runs it under the engine's lock.

    The decorated object must have an ``_engine`` attribute.

    Args:
        mode: :data:`SHARED` or :data:`EXCLUSIVE`.
        operation: Name for diagnostics; the method name by default.
    """

    def decorator(method):
        label = operation or method.__name__

        @functools.wraps(method)
        def wrapper(self, *args, **kwargs):
            engine = self._engine  # pylint: disable=protected-access
            with engine.lock.hold(mode, label):
                return method(self, *args, **kwargs)

        return wrapper

    return decorator
