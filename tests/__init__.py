"""Unit tests of the KonGUI integration layer.

Every test works inside a temporary folder and replaces ``$HOME`` for its whole
duration. The state of the *real* home is recorded here, when the package is
first imported (before any test patches the environment), and compared at the
end by ``test_zz_real_home_guard``.

Run from the repository root, as an ordinary user::

    python3 -m unittest discover -s tests -t . -v
"""

from pathlib import Path
from typing import Any, Dict


def _describe(path: Path) -> Any:
    """Describes a file or folder so that any change can be detected.

    Args:
        path: File or folder to describe.

    Returns:
        Any: ``None`` if absent, otherwise names and modification times.
    """
    if not path.exists():
        return None
    if path.is_dir():
        return sorted(
            f"{item.relative_to(path)}:{item.lstat().st_mtime_ns}"
            for item in path.rglob("*")
        )
    stat = path.stat()
    return (stat.st_size, stat.st_mtime_ns)


def real_home_state() -> Dict[str, Any]:
    """Records what Konsave would have written in the real home.

    Returns:
        Dict[str, Any]: Description of ``~/.config/konsave`` and the log file.
    """
    home = Path.home()
    return {
        "konsave_dir": _describe(home / ".config" / "konsave"),
        "log_file": _describe(home / ".cache" / "konsave_log.txt"),
    }


REAL_HOME = Path.home()
REAL_HOME_BEFORE = real_home_state()
