"""Loads and runs the original Konsave engine in-process, safely.

Why this module exists (all confirmed while auditing ``konsave/funcs.py`` and
``konsave/consts.py``):

* ``konsave.consts`` reads ``$HOME`` at import time, creates the profiles folder
  and takes a snapshot of the profile list that is never refreshed.
* Every public function of ``konsave.funcs`` is wrapped by
  ``exception_handler``: it swallows exceptions, prints to stdout, appends the
  traceback to ``~/.cache/konsave_log.txt`` and always returns ``None``.

:class:`KonsaveEngine` therefore imports a *private copy* of ``konsave.consts``,
``konsave.parse`` and ``konsave.funcs`` bound to a chosen home directory (so a
test never sees the real one and several engines can coexist), serialises
calls, captures stdout/stderr and detects failures by reading the part of the
log that the original code appended during the call.
"""

from __future__ import annotations

import importlib
import io
import os
import re
import sys
import threading
from contextlib import contextmanager, nullcontext, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Tuple

from kongui.core.errors import EngineLoadError, ValidationError
from kongui.core.lock import EXCLUSIVE, SHARED, EngineLock
from kongui.core.safety import EuidProvider, current_euid, ensure_not_root

#: Serialises imports, ``HOME`` patching and stdout redirection (all global).
ENGINE_LOCK = threading.RLock()

#: Used when Konsave runs from a source checkout without package metadata.
FALLBACK_VERSION = "0+unknown"

_MODULE_NAMES = ("consts", "parse", "funcs")

#: Lock each original function needs (see ``docs/CONCURRENCY.md``). Functions
#: that are not listed take no lock. ``export`` only reads profiles (it writes the
#: archive outside Konsave's folder), so a shared lock is enough.
CALL_LOCK_MODES = {
    "save_profile": EXCLUSIVE,
    "apply_profile": EXCLUSIVE,
    "remove_profile": EXCLUSIVE,
    "import_profile": EXCLUSIVE,
    "wipe": EXCLUSIVE,
    "export": SHARED,
}

#: The only functions of ``konsave.funcs`` this layer is allowed to call.
ALLOWED_CALLS = frozenset(
    {
        "save_profile",
        "apply_profile",
        "remove_profile",
        "export",
        "import_profile",
        "wipe",
        "read_konsave_config",
    }
)

_LOG_HEADER = re.compile(r"^\[\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}\]$")


@contextmanager
def _empty_stdin() -> Iterator[None]:
    """Temporarily replaces ``sys.stdin`` with an empty stream.

    ``contextlib`` has no ``redirect_stdin``. With an empty stdin an unexpected
    ``input()`` raises ``EOFError`` immediately instead of waiting for a
    terminal.
    """
    previous = sys.stdin
    sys.stdin = io.StringIO("")
    try:
        yield
    finally:
        sys.stdin = previous


def extract_log_errors(text: str) -> Tuple[str, ...]:
    """Summarises the entries of ``konsave_log.txt``.

    The original handler writes a ``[dd/mm/YYYY HH:MM:SS]`` header followed by a
    traceback. The last non-empty line of each traceback is ``Type: message``.

    Args:
        text: Log text written during one call.

    Returns:
        Tuple[str, ...]: One summary per logged exception, in order.
    """
    entries: List[List[str]] = []
    current: Optional[List[str]] = None
    for line in text.splitlines():
        if _LOG_HEADER.match(line):
            if current is not None:
                entries.append(current)
            current = []
        elif current is not None:
            current.append(line)
    if current is not None:
        entries.append(current)
    summaries = []
    for entry in entries:
        lines = [line.strip() for line in entry if line.strip()]
        summaries.append(lines[-1] if lines else "unknown error")
    return tuple(summaries)


@dataclass(frozen=True)
class EngineCall:
    """Everything observed while one engine function ran.

    Attributes:
        name: Name of the called function.
        returned: Return value. ``None`` for every decorated function except
            ``read_konsave_config`` on success.
        stdout: Captured standard output.
        stderr: Captured standard error.
        errors: Summaries of exceptions the original handler logged.
        raised: Exception that escaped the original handler, if any.
    """

    name: str
    returned: Any
    stdout: str
    stderr: str
    errors: Tuple[str, ...]
    raised: Optional[BaseException] = None

    @property
    def failed(self) -> bool:
        """Whether anything went wrong, even if the engine swallowed it."""
        return bool(self.errors) or self.raised is not None

    @property
    def error_messages(self) -> Tuple[str, ...]:
        """Logged errors plus the escaped exception, if any."""
        messages = list(self.errors)
        if self.raised is not None:
            messages.append(f"{type(self.raised).__name__}: {self.raised}")
        return tuple(messages)


def _load_modules(home: Path) -> Dict[str, ModuleType]:
    """Imports private copies of the Konsave modules bound to ``home``.

    ``sys.modules``, ``os.environ["HOME"]`` and the attributes of the
    ``konsave`` package are restored afterwards, so the rest of the process is
    unaffected. The functions keep working because they hold references to the
    globals of their own module objects.

    Args:
        home: Home directory the modules must use.

    Returns:
        Dict[str, ModuleType]: Modules keyed by short name.

    Raises:
        EngineLoadError: If importing fails.
    """
    with ENGINE_LOCK:
        try:
            import konsave  # pylint: disable=import-outside-toplevel
        except ImportError as error:
            raise EngineLoadError(f"cannot import konsave: {error}") from error

        full_names = {short: f"konsave.{short}" for short in _MODULE_NAMES}
        saved_modules = {
            name: sys.modules.pop(name)
            for name in full_names.values()
            if name in sys.modules
        }
        missing = object()
        saved_attrs = {short: getattr(konsave, short, missing) for short in full_names}
        previous_home = os.environ.get("HOME")
        injected_version = not hasattr(konsave, "__version__")
        os.environ["HOME"] = str(home)
        if injected_version:
            # konsave/__init__.py only defines __version__ for an installed
            # package, and konsave.consts imports it unconditionally.
            konsave.__version__ = FALLBACK_VERSION
        try:
            return {
                short: importlib.import_module(name)
                for short, name in full_names.items()
            }
        except Exception as error:  # pylint: disable=broad-except
            raise EngineLoadError(f"cannot load the Konsave engine: {error}") from error
        finally:
            if previous_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = previous_home
            if injected_version:
                del konsave.__version__
            for name in full_names.values():
                sys.modules.pop(name, None)
            sys.modules.update(saved_modules)
            for short, value in saved_attrs.items():
                if value is missing:
                    if hasattr(konsave, short):
                        delattr(konsave, short)
                else:
                    setattr(konsave, short, value)


class KonsaveEngine:
    """Gateway to the original Konsave functions for one home directory."""

    def __init__(
        self,
        home: Optional[Path] = None,
        *,
        euid_provider: EuidProvider = current_euid,
    ) -> None:
        """Loads the engine.

        Args:
            home: Home directory to operate on. Defaults to the real one.
            euid_provider: Callable returning the euid; injectable for tests.

        Raises:
            RunningAsRootError: If the process runs as root.
            ValidationError: If ``home`` is not an existing absolute folder.
            EngineLoadError: If the Konsave modules cannot be loaded or lack an
                expected function.
        """
        ensure_not_root(euid_provider)
        base = Path(home) if home is not None else Path.home()
        if not base.is_absolute() or not base.is_dir():
            raise ValidationError(f"home must be an existing absolute folder: {base}")
        self._home = Path(os.path.abspath(base))
        modules = _load_modules(self._home)
        self._consts = modules["consts"]
        self._parse = modules["parse"]
        self._funcs = modules["funcs"]
        missing = sorted(
            name
            for name in ALLOWED_CALLS
            if not callable(getattr(self._funcs, name, None))
        )
        if missing:
            raise EngineLoadError(f"Konsave lacks expected functions: {missing}")
        if self._consts.HOME != str(self._home):
            raise EngineLoadError("the Konsave engine did not honour the home folder")
        self._lock = EngineLock(self.konsave_dir)

    @property
    def lock(self) -> EngineLock:
        """Cross-process lock of this home's Konsave folder."""
        return self._lock

    @property
    def home(self) -> Path:
        """Home directory this engine operates on."""
        return self._home

    @property
    def funcs(self) -> ModuleType:
        """The private copy of ``konsave.funcs``."""
        return self._funcs

    @property
    def parse(self) -> ModuleType:
        """The private copy of ``konsave.parse``."""
        return self._parse

    @property
    def version(self) -> str:
        """Konsave version (``0+unknown`` for an uninstalled checkout)."""
        return str(self._consts.VERSION)

    @property
    def konsave_dir(self) -> Path:
        """``~/.config/konsave``."""
        return Path(self._consts.KONSAVE_DIR)

    @property
    def profiles_dir(self) -> Path:
        """Folder that holds the saved profiles."""
        return Path(self._consts.PROFILES_DIR)

    @property
    def config_file(self) -> Path:
        """The active ``conf.yaml``."""
        return Path(self._consts.CONFIG_FILE)

    @property
    def temp_dir(self) -> Path:
        """Staging folder used by ``import_profile``."""
        return self.konsave_dir / "temp"

    @property
    def log_file(self) -> Path:
        """Log file used by the original exception handler."""
        return Path(self._consts.HOME) / ".cache" / "konsave_log.txt"

    @property
    def export_extension(self) -> str:
        """Extension of exported archives (``.knsv``)."""
        return str(self._consts.EXPORT_EXTENSION)

    def ensure_runtime_dirs(self) -> None:
        """Creates the folders the original code assumes to exist.

        The original handler fails with ``FileNotFoundError`` if ``~/.cache`` is
        missing, and ``consts`` only creates the profiles folder at import time.
        """
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def profile_names(self) -> List[str]:
        """Lists the entries of the profiles folder, fresh from disk.

        The original ``consts.list_of_profiles`` is a stale import-time snapshot.

        Returns:
            List[str]: Sorted entry names.
        """
        try:
            return sorted(os.listdir(self.profiles_dir))
        except FileNotFoundError:
            return []

    def _log_size(self) -> int:
        """Returns the current size of the engine log in bytes."""
        try:
            return self.log_file.stat().st_size
        except FileNotFoundError:
            return 0

    def _log_since(self, offset: int) -> str:
        """Reads the engine log from a byte offset.

        Args:
            offset: Position to start reading from.

        Returns:
            str: Text appended since ``offset``.
        """
        try:
            with open(self.log_file, "rb") as handle:
                handle.seek(offset)
                return handle.read().decode("utf-8", errors="replace")
        except FileNotFoundError:
            return ""

    def call(
        self,
        name: str,
        *args: Any,
        overrides: Optional[Mapping[str, Callable[..., Any]]] = None,
        **kwargs: Any,
    ) -> EngineCall:
        """Calls one original function under the cross-process lock.

        Safety net: the services already hold the lock around whole operations
        (the lock is re-entrant per thread), but any other caller of the engine
        is covered too. See :data:`CALL_LOCK_MODES`.

        Args:
            name: Function name; must be in :data:`ALLOWED_CALLS`.
            *args: Positional arguments for the function.
            overrides: See :meth:`_call_unlocked`.
            **kwargs: Keyword arguments for the function.

        Returns:
            EngineCall: Return value, stdout, stderr and logged errors.

        Raises:
            ValueError: If ``name`` is not an allowed function.
            LockError: If the lock could not be obtained (see ``konsave.lock``).
        """
        mode = CALL_LOCK_MODES.get(name)
        with self._lock.hold(mode, name) if mode else nullcontext():
            return self._call_unlocked(name, *args, overrides=overrides, **kwargs)

    def _call_unlocked(
        self,
        name: str,
        *args: Any,
        overrides: Optional[Mapping[str, Callable[..., Any]]] = None,
        **kwargs: Any,
    ) -> EngineCall:
        """Calls one original function and observes it.

        Args:
            name: Function name; must be in :data:`ALLOWED_CALLS`.
            *args: Positional arguments for the function.
            overrides: Temporary attributes set on the private ``funcs``
                module during the call (used to replace ``input`` for ``wipe``).
            **kwargs: Keyword arguments for the function.

        Returns:
            EngineCall: Return value, stdout, stderr and logged errors.

        Raises:
            ValueError: If ``name`` is not an allowed function.
        """
        if name not in ALLOWED_CALLS:
            raise ValueError(f"{name!r} is not an allowed engine call")
        func = getattr(self._funcs, name)
        returned: Any = None
        raised: Optional[BaseException] = None
        out, err = io.StringIO(), io.StringIO()
        with ENGINE_LOCK:
            self.ensure_runtime_dirs()
            offset = self._log_size()
            installed = []
            try:
                for attr, value in (overrides or {}).items():
                    setattr(self._funcs, attr, value)
                    installed.append(attr)
                # stdin is empty: an unexpected prompt (the original ``wipe``
                # calls ``input()``) fails with EOFError instead of blocking
                # the whole process, which would freeze a GUI.
                with _empty_stdin(), redirect_stdout(out), redirect_stderr(err):
                    try:
                        returned = func(*args, **kwargs)
                    except Exception as error:  # pylint: disable=broad-except
                        raised = error
            finally:
                for attr in installed:
                    delattr(self._funcs, attr)
            log_text = self._log_since(offset)
        return EngineCall(
            name=name,
            returned=returned,
            stdout=out.getvalue(),
            stderr=err.getvalue(),
            errors=extract_log_errors(log_text),
            raised=raised,
        )
