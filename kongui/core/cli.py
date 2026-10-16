"""Optional runner for the real Konsave command line.

None of the services needs it: the original functions are called in-process.
It exists for diagnostics and compatibility checks (for example comparing the
installed CLI version with the engine, or checking exit codes), where running
the genuine executable is the point.

Safety rules, all enforced here:

* the command is a ``list`` (``shell=False``), never a concatenated string;
* arguments must be a list/tuple of strings without NUL bytes;
* by default only the exact read-only flags in :data:`READ_ONLY_FLAGS` are
  accepted, so abbreviations such as ``--sav`` cannot slip through;
* the environment is rebuilt from a small allow-list (no inherited secrets);
* stdin is closed, a timeout always applies, and root is refused.

Even read-only invocations are not free of side effects: the original ``main``
creates ``~/.config/konsave/conf.yaml`` and the profiles folder on first run.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Optional, Sequence, Tuple

from kongui.core.errors import CliExecutionError, ValidationError
from kongui.core.results import CliResult
from kongui.core.safety import EuidProvider, current_euid, ensure_not_root

#: Exact tokens accepted unless ``allow_mutating=True``.
READ_ONLY_FLAGS = frozenset({"-h", "--help", "-v", "--version", "-l", "--list"})

_PASSTHROUGH_ENV = ("PATH", "LANG", "LANGUAGE", "XDG_CURRENT_DESKTOP")


def _to_text(value: Any) -> str:
    """Converts captured output (``str``, ``bytes`` or ``None``) to ``str``.

    Args:
        value: Captured output from ``subprocess``.

    Returns:
        str: Decoded text.
    """
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


class CliRunner:
    """Runs ``python -m konsave <args>`` in a controlled environment."""

    DEFAULT_TIMEOUT = 60.0
    MAX_ARGS = 64
    MAX_ARG_LENGTH = 4096

    def __init__(  # pylint: disable=too-many-arguments
        self,
        home: Path,
        *,
        python: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        extra_pythonpath: Sequence[Path] = (),
        allow_mutating: bool = False,
        euid_provider: EuidProvider = current_euid,
        run_func: Callable[..., Any] = subprocess.run,
    ) -> None:
        """Creates the runner.

        Args:
            home: Home directory the CLI must use (becomes ``$HOME``).
            python: Interpreter to use; defaults to the current one.
            timeout: Seconds before the process is killed.
            extra_pythonpath: Extra ``PYTHONPATH`` folders, for example the one
                with package metadata when Konsave is not installed.
            allow_mutating: Accept any argument, including the ones that save,
                apply, remove, export, import or wipe. Off by default.
            euid_provider: Callable returning the euid; injectable for tests.
            run_func: ``subprocess.run`` replacement; injectable for tests.

        Raises:
            RunningAsRootError: If the process runs as root.
            ValidationError: If ``home`` is not an absolute existing folder or
                the timeout is not positive.
        """
        ensure_not_root(euid_provider)
        base = Path(home)
        if not base.is_absolute() or not base.is_dir():
            raise ValidationError(f"home must be an existing absolute folder: {base}")
        # "not timeout > 0" (and not "timeout <= 0") so that NaN is refused too.
        if not timeout > 0:  # pylint: disable=unnecessary-negation
            raise ValidationError("timeout must be positive")
        self._home = base
        self._python = python or sys.executable
        self._timeout = timeout
        self._extra_pythonpath = tuple(Path(item) for item in extra_pythonpath)
        self._allow_mutating = allow_mutating
        self._run = run_func

    def _validate_args(self, args: Sequence[str]) -> Tuple[str, ...]:
        """Validates the CLI arguments.

        Args:
            args: Candidate arguments.

        Returns:
            Tuple[str, ...]: The arguments as a tuple of ``str``.

        Raises:
            ValidationError: If ``args`` is not a safe sequence of strings, or
                contains a token outside :data:`READ_ONLY_FLAGS` while
                ``allow_mutating`` is off.
        """
        if isinstance(args, (str, bytes)) or not isinstance(args, (list, tuple)):
            raise ValidationError("args must be a list or tuple of strings")
        if len(args) > self.MAX_ARGS:
            raise ValidationError(f"at most {self.MAX_ARGS} arguments are allowed")
        for arg in args:
            if not isinstance(arg, str):
                raise ValidationError("every argument must be a string")
            if "\0" in arg or len(arg) > self.MAX_ARG_LENGTH:
                raise ValidationError("argument contains NUL or is too long")
            if not self._allow_mutating and arg not in READ_ONLY_FLAGS:
                raise ValidationError(
                    f"argument {arg!r} is not allowed in read-only mode "
                    f"(allowed: {', '.join(sorted(READ_ONLY_FLAGS))})"
                )
        return tuple(args)

    def _build_env(self) -> dict:
        """Builds the minimal environment of the subprocess.

        Returns:
            dict: Environment variables.
        """
        import konsave  # pylint: disable=import-outside-toplevel

        package_parent = Path(konsave.__file__).resolve().parent.parent
        paths = [str(package_parent)] + [str(item) for item in self._extra_pythonpath]
        env = {key: os.environ[key] for key in _PASSTHROUGH_ENV if key in os.environ}
        env.update(
            HOME=str(self._home),
            PYTHONPATH=os.pathsep.join(paths),
            PYTHONIOENCODING="utf-8",
            PYTHONUTF8="1",
        )
        return env

    def run(self, args: Sequence[str]) -> CliResult:
        """Runs the Konsave CLI.

        Args:
            args: Arguments after ``python -m konsave``, as a list of strings.

        Returns:
            CliResult: Exit code, stdout, stderr and timeout flag. A non-zero
            exit code is a normal result, not an exception.

        Raises:
            ValidationError: If ``args`` is not acceptable.
            CliExecutionError: If the interpreter cannot be started.
        """
        arguments = self._validate_args(args)
        command = [self._python, "-m", "konsave", *arguments]
        try:
            completed = self._run(
                command,
                shell=False,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout,
                env=self._build_env(),
                cwd=str(self._home),
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as error:
            return CliResult(
                args=arguments,
                returncode=None,
                stdout=_to_text(error.stdout),
                stderr=_to_text(error.stderr),
                timed_out=True,
            )
        except OSError as error:
            raise CliExecutionError(f"cannot start {self._python}: {error}") from error
        return CliResult(
            args=arguments,
            returncode=completed.returncode,
            stdout=_to_text(completed.stdout),
            stderr=_to_text(completed.stderr),
        )

    def version(self) -> Optional[str]:
        """Asks the CLI for its version (``--version``).

        Returns:
            Optional[str]: The version, or ``None`` if the CLI failed.
        """
        return self.run(["--version"]).parsed_version()
