"""Application start-up."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Sequence

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication

from kongui.core.errors import RunningAsRootError
from kongui.core.safety import ensure_not_root
from kongui.gui.main_window import MainWindow
from kongui.gui.state import AppSettings


def settings_path() -> Optional[str]:
    """Returns the preferences file, creating its folder.

    Returns:
        Optional[str]: The INI path, or ``None`` if the folder cannot be created
        (the app then keeps preferences in memory).
    """
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppConfigLocation
    )
    if not base:
        return None
    folder = Path(base)
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    return str(folder / "kongui-gui.ini")


def create_app(argv: Optional[Sequence[str]] = None) -> QApplication:
    """Returns the running ``QApplication``, creating it if needed.

    Args:
        argv: Command-line arguments; defaults to ``sys.argv``.

    Returns:
        QApplication: The application.
    """
    app = QApplication.instance()
    if app is None:
        app = QApplication(list(argv if argv is not None else sys.argv))
    app.setApplicationName("kongui")
    app.setApplicationDisplayName("KonGUI")
    app.setDesktopFileName("kongui")
    return app  # type: ignore[return-value]


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Runs the prototype.

    Args:
        argv: Command-line arguments; defaults to ``sys.argv``.

    Returns:
        int: Process exit status. ``1`` if started as root.
    """
    try:
        ensure_not_root()
    except RunningAsRootError as error:
        print(f"kongui: {error}", file=sys.stderr)
        return 1
    app = create_app(argv)
    window = MainWindow(AppSettings(settings_path()))
    window.show()
    return app.exec()
