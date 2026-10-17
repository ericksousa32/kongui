"""Running blocking work without freezing the window.

An :class:`Executor` runs a callable somewhere and calls ``on_done(value, error)``
**in the GUI thread**. Two implementations exist:

* :class:`ThreadExecutor`: a single worker thread, so operations never overlap.
* :class:`InlineExecutor`: runs at once in the caller's thread (tests, scripts).
"""

from __future__ import annotations

import itertools
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

DoneCallback = Callable[[Any, Optional[BaseException]], None]


class Executor(ABC):
    """Runs a callable and reports back in the GUI thread."""

    @abstractmethod
    def submit(self, work: Callable[[], Any], on_done: DoneCallback) -> None:
        """Schedules ``work``.

        Args:
            work: Blocking callable without arguments.
            on_done: Called once with ``(value, None)`` or ``(None, error)``.
        """

    def shutdown(self, timeout_ms: int = 5000) -> bool:
        """Waits for running work to finish.

        Args:
            timeout_ms: Longest wait in milliseconds.

        Returns:
            bool: ``True`` if nothing is running any more.
        """
        del timeout_ms
        return True


class InlineExecutor(Executor):
    """Runs the work immediately in the calling thread."""

    def submit(self, work: Callable[[], Any], on_done: DoneCallback) -> None:
        """Runs ``work`` and calls ``on_done`` before returning."""
        try:
            value = work()
        except Exception as error:  # pylint: disable=broad-exception-caught
            on_done(None, error)
        else:
            on_done(value, None)


class _Signals(QObject):
    """Carries a worker's result to the GUI thread (queued connection)."""

    finished = Signal(int, object, object)


class _Job(QRunnable):
    """Runs one callable in a pool thread."""

    def __init__(self, token: int, work: Callable[[], Any], signals: _Signals) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self._token = token
        self._work = work
        self._signals = signals

    def run(self) -> None:  # pylint: disable=invalid-name
        """Executes the work; never lets an exception escape the thread."""
        value: Any = None
        error: Optional[BaseException] = None
        try:
            value = self._work()
        except Exception as caught:  # pylint: disable=broad-exception-caught
            error = caught
        try:
            self._signals.finished.emit(self._token, value, error)
        except RuntimeError:
            # The interface was destroyed while the work ran: nobody is left
            # to receive the result (it used to print a traceback at exit).
            return


class ThreadExecutor(Executor):
    """One worker thread; jobs run one after the other.

    Must be created in the GUI thread, which is where ``on_done`` runs.
    """

    def __init__(self) -> None:
        """Creates the pool."""
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(1)
        self._signals = _Signals()
        self._signals.finished.connect(self._deliver)
        self._pending: Dict[int, tuple] = {}
        self._tokens = itertools.count(1)

    def submit(self, work: Callable[[], Any], on_done: DoneCallback) -> None:
        """Queues ``work`` on the worker thread."""
        token = next(self._tokens)
        job = _Job(token, work, self._signals)
        self._pending[token] = (job, on_done)
        self._pool.start(job)

    def _deliver(self, token: int, value: Any, error: Optional[BaseException]) -> None:
        """Hands a finished job's result to its callback (GUI thread)."""
        _job, on_done = self._pending.pop(token)
        on_done(value, error)

    def shutdown(self, timeout_ms: int = 5000) -> bool:
        """Waits for the running job (an operation cannot be interrupted)."""
        return self._pool.waitForDone(timeout_ms)
