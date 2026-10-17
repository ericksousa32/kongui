"""Cross-process lock for the data Konsave shares (KonGUI addition).

This module does not exist in upstream Konsave. It was added by the KonGUI fork
so that two Konsave processes (the CLI, the graphical interface, or one of each)
never run conflicting operations at the same time. See
``docs/KONSAVE_PATCHES.md`` for what it protects and how to adapt it to a new
Konsave release.

Design
------
* One **stable** lock file per Konsave folder: ``~/.config/konsave/.kongui.lock``.
  It is created on first use (mode 0600) and **never deleted or recreated**:
  deleting it while another process holds it would let two processes lock two
  different files. Removing the file by hand is the only unsafe thing a user can
  do to it.
* The kernel does the locking: ``fcntl.flock``. The lock is tied to the open file
  description, so it is released when the process exits, crashes or is killed.
* ``exclusive`` for operations that change data, ``shared`` for operations that
  only need a consistent view. Any number of shared holders may coexist.
* Re-entrant per thread: a thread that already holds the lock may ask for it
  again (needed by composite operations). Asking for ``exclusive`` while holding
  only ``shared`` raises :class:`LockUsageError` instead of deadlocking.
* Waiting is polled (``flock`` has no timeout of its own) so it can honour a
  timeout and a cooperative cancel event, and never needs a signal.
* The PID and operation written into the file while an exclusive lock is held are
  **information for messages only**. They are not proof of ownership: only the
  kernel lock is.

Only the standard library is used, so the original CLI does not depend on KonGUI.
"""

import errno
import fcntl
import json
import math
import os
import stat
import sys
import threading
import time
from contextlib import ExitStack, contextmanager
from typing import Any, Callable, Dict, Iterator, Optional

LOCK_NAME = ".kongui.lock"
SHARED = "shared"
EXCLUSIVE = "exclusive"
#: Seconds a command waits for the lock unless told otherwise.
DEFAULT_TIMEOUT = 30.0
#: Environment variable that overrides the CLI timeout (seconds; ``0`` = do not
#: wait, negative or ``inf`` = wait forever).
TIMEOUT_ENV = "KONSAVE_LOCK_TIMEOUT"
#: Exit status of the CLI when the lock could not be obtained (``EX_TEMPFAIL``).
EXIT_BUSY = 75
#: Exit status of the CLI when the lock file cannot be used at all.
EXIT_UNAVAILABLE = 1

_POLL_FIRST = 0.01
_POLL_MAX = 0.1


class LockError(Exception):
    """Base class of every error raised by this module."""


class LockBusyError(LockError):
    """Another process holds a conflicting lock (a normal contention).

    Attributes:
        holder: Best-effort, **unverified** description of the exclusive holder
            (``{"pid", "operation", "since"}``), or ``None``.
    """

    def __init__(self, message: str, holder: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.holder = holder


class LockTimeoutError(LockBusyError):
    """The lock stayed busy until the timeout expired."""


class LockCancelledError(LockError):
    """The wait was cancelled through the ``cancel`` event."""


class LockUnavailableError(LockError):
    """The lock file cannot be opened or locked (permissions, file system...).

    This is *not* a contention: waiting will not help.
    """


class LockUsageError(LockError):
    """The lock was asked for in a way that would deadlock (shared → exclusive)."""


def default_lock_path(konsave_dir: str) -> str:
    """Returns the lock file path for a Konsave folder."""
    return os.path.join(str(konsave_dir), LOCK_NAME)


def timeout_from_environment(
    environ: Optional[Dict[str, str]] = None, default: Optional[float] = DEFAULT_TIMEOUT
) -> Optional[float]:
    """Reads :data:`TIMEOUT_ENV`.

    Args:
        environ: Environment to read; ``os.environ`` by default.
        default: Value when the variable is missing or not a number.

    Returns:
        Optional[float]: Seconds to wait, ``0`` for no waiting, ``None`` for no
        limit.
    """
    raw = (environ if environ is not None else os.environ).get(TIMEOUT_ENV)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if math.isnan(value):
        return default
    return None if value < 0 or value == float("inf") else value


# One entry per lock path and thread: the lock this thread already holds.
_LOCAL = threading.local()


class _Hold:  # pylint: disable=too-few-public-methods
    """A lock held by the current thread."""

    def __init__(self, fd: int, mode: str) -> None:
        self.fd = fd
        self.mode = mode
        self.depth = 1


def _held() -> Dict[str, _Hold]:
    """The locks held by the current thread, by path."""
    if not hasattr(_LOCAL, "held"):
        _LOCAL.held = {}
    return _LOCAL.held


class OperationLock:
    """The lock of one Konsave folder."""

    def __init__(self, path: str) -> None:
        """Creates the handle (nothing is opened yet).

        Args:
            path: Lock file, normally :func:`default_lock_path`.
        """
        self._path = os.path.abspath(str(path))

    @property
    def path(self) -> str:
        """Absolute path of the lock file."""
        return self._path

    def exclusive(self, **kwargs: Any):
        """Context manager for an operation that changes data."""
        return self.hold(EXCLUSIVE, **kwargs)

    def shared(self, **kwargs: Any):
        """Context manager for an operation that needs a consistent view."""
        return self.hold(SHARED, **kwargs)

    @contextmanager
    def hold(  # pylint: disable=too-many-arguments
        self,
        mode: str,
        *,
        operation: str = "",
        timeout: Optional[float] = DEFAULT_TIMEOUT,
        cancel: Optional[threading.Event] = None,
        on_wait: Optional[Callable[[Optional[Dict[str, Any]]], None]] = None,
    ) -> Iterator[None]:
        """Holds the lock for the duration of the ``with`` block.

        Args:
            mode: :data:`SHARED` or :data:`EXCLUSIVE`.
            operation: Short name, written to the file for diagnostics.
            timeout: Seconds to wait; ``0`` tries once; ``None`` waits forever.
            cancel: Event that, once set, stops the wait.
            on_wait: Called once, with the holder information if known, when the
                lock turns out to be busy and the call is going to wait.

        Raises:
            LockBusyError: Busy and ``timeout`` is ``0``.
            LockTimeoutError: Still busy when ``timeout`` expired.
            LockCancelledError: ``cancel`` was set while waiting.
            LockUnavailableError: The lock file cannot be used.
            LockUsageError: ``exclusive`` requested while holding only ``shared``.
            ValueError: Unknown ``mode``.
        """
        if mode not in (SHARED, EXCLUSIVE):
            raise ValueError(f"unknown lock mode: {mode!r}")
        held = _held()
        current = held.get(self._path)
        if current is not None:
            if mode == EXCLUSIVE and current.mode == SHARED:
                raise LockUsageError(
                    "cannot upgrade a shared lock to exclusive (it would deadlock)"
                )
            current.depth += 1
            try:
                yield
            finally:
                current.depth -= 1
            return
        fd = self._open()
        try:
            self._acquire(fd, mode, operation, timeout, cancel, on_wait)
        except BaseException:
            os.close(fd)
            raise
        hold = _Hold(fd, mode)
        held[self._path] = hold
        try:
            yield
        finally:
            del held[self._path]
            self._release(hold)

    # ------------------------------------------------------------------ internals

    def _open(self) -> int:
        """Opens (creating if needed) the lock file and checks it is ours."""
        flags = (
            os.O_RDWR
            | os.O_CREAT
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            os.makedirs(os.path.dirname(self._path), mode=0o700, exist_ok=True)
            fd = os.open(self._path, flags, 0o600)
        except OSError as error:
            raise LockUnavailableError(
                f"cannot open the lock file {self._path}: {error.strerror or error}"
            ) from error
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
                raise LockUnavailableError(
                    f"the lock file {self._path} is not a regular file owned by you"
                )
        except BaseException:
            os.close(fd)
            raise
        return fd

    def _acquire(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        fd: int,
        mode: str,
        operation: str,
        timeout: Optional[float],
        cancel: Optional[threading.Event],
        on_wait: Optional[Callable[[Optional[Dict[str, Any]]], None]],
    ) -> None:
        """Takes the kernel lock, waiting as allowed."""
        flag = fcntl.LOCK_EX if mode == EXCLUSIVE else fcntl.LOCK_SH
        started = time.monotonic()
        pause = _POLL_FIRST
        announced = False
        while True:
            if cancel is not None and cancel.is_set():
                raise LockCancelledError("the wait for the lock was cancelled")
            try:
                fcntl.flock(fd, flag | fcntl.LOCK_NB)
                break
            except OSError as error:
                if error.errno not in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EINTR):
                    raise LockUnavailableError(
                        f"cannot lock {self._path}: {error.strerror or error}"
                    ) from error
            holder = _read_holder(fd)
            if timeout is not None and timeout <= 0:
                raise LockBusyError("another Konsave operation is running", holder)
            if not announced:
                announced = True
                if on_wait is not None:
                    on_wait(holder)
            if timeout is not None and time.monotonic() - started >= timeout:
                raise LockTimeoutError(
                    f"another Konsave operation is still running after {timeout:g} s",
                    holder,
                )
            time.sleep(pause)
            pause = min(pause * 2, _POLL_MAX)
        if mode == EXCLUSIVE:
            _write_holder(fd, operation)

    @staticmethod
    def _release(hold: _Hold) -> None:
        """Releases the kernel lock and closes the descriptor."""
        try:
            if hold.mode == EXCLUSIVE:
                try:
                    os.ftruncate(hold.fd, 0)
                except OSError:
                    pass
            fcntl.flock(hold.fd, fcntl.LOCK_UN)
        finally:
            os.close(hold.fd)


def _write_holder(fd: int, operation: str) -> None:
    """Records who holds the exclusive lock (information only)."""
    data = json.dumps(
        {"pid": os.getpid(), "operation": operation, "since": time.time()}
    ).encode("utf-8")
    try:
        os.ftruncate(fd, 0)
        os.pwrite(fd, data, 0)
    except OSError:
        pass


def _read_holder(fd: int) -> Optional[Dict[str, Any]]:
    """Reads the diagnostic record; ``None`` when absent, damaged or stale."""
    try:
        data = json.loads(os.pread(fd, 4096, 0).decode("utf-8"))
        pid = int(data["pid"])
        os.kill(pid, 0)  # a dead PID cannot be the holder
        return {
            "pid": pid,
            "operation": str(data.get("operation", "")),
            "since": float(data.get("since", 0)),
        }
    except (OSError, ValueError, KeyError, TypeError):
        return None


def describe_holder(holder: Optional[Dict[str, Any]]) -> str:
    """Formats the (unverified) holder information for a message."""
    if not holder:
        return ""
    what = holder.get("operation") or "an operation"
    return f" (possibly {what}, pid {holder.get('pid')}; this is only a hint)"


@contextmanager
def command_lock(
    konsave_dir: str,
    mode: Optional[str],
    operation: str,
    *,
    timeout: Optional[float] = None,
    stream: Any = None,
) -> Iterator[None]:
    """Lock for a command line run: waits with a message, exits with a status.

    ``mode=None`` takes no lock (``--help``, ``--version``). On failure it
    prints one line to ``stderr`` and raises ``SystemExit`` with
    :data:`EXIT_BUSY` (busy or timeout) or :data:`EXIT_UNAVAILABLE`; Ctrl+C
    while waiting exits with 130.

    Args:
        konsave_dir: Konsave configuration folder.
        mode: :data:`SHARED`, :data:`EXCLUSIVE` or ``None``.
        operation: Short name for diagnostics.
        timeout: Seconds to wait; ``None`` reads :data:`TIMEOUT_ENV`
            (default :data:`DEFAULT_TIMEOUT`).
        stream: Where messages go (``sys.stderr`` by default).
    """
    if mode is None:
        yield
        return
    out = stream if stream is not None else sys.stderr
    wait = timeout_from_environment() if timeout is None else timeout

    def waiting(holder: Optional[Dict[str, Any]]) -> None:
        limit = "indefinitely" if wait is None else f"up to {wait:g} s"
        print(
            f"Konsave: another Konsave operation is running"
            f"{describe_holder(holder)}; waiting {limit} (Ctrl+C to give up)...",
            file=out,
        )

    lock = OperationLock(default_lock_path(konsave_dir))
    with ExitStack() as stack:
        # Only the acquisition is translated: errors and Ctrl+C raised by the
        # command itself (inside the ``with``) keep their original behaviour.
        try:
            stack.enter_context(
                lock.hold(mode, operation=operation, timeout=wait, on_wait=waiting)
            )
        except LockBusyError as error:  # includes LockTimeoutError
            print(
                f"Konsave: {error}{describe_holder(error.holder)}. "
                "Nothing was changed.",
                file=out,
            )
            raise SystemExit(EXIT_BUSY) from None
        except LockUnavailableError as error:
            print(f"Konsave: {error}. Nothing was changed.", file=out)
            raise SystemExit(EXIT_UNAVAILABLE) from None
        except KeyboardInterrupt:
            print("Konsave: interrupted while waiting. Nothing was changed.", file=out)
            raise SystemExit(130) from None
        yield
