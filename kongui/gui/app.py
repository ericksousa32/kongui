"""Application start-up."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Sequence

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication

from kongui.core.errors import EngineLoadError, RunningAsRootError
from kongui.gui import i18n
from kongui.core.safety import ensure_not_root
from kongui.gui.backend import FakeBackend, ProfileBackend, ServiceBackend
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


def build_backend(demo: bool) -> ProfileBackend:
    """Creates the profile backend.

    Args:
        demo: Use the in-memory fictitious backend instead of the real services.

    Returns:
        ProfileBackend: The backend.

    Raises:
        KonGuiError: If the real services cannot start (running as root, or
            Konsave cannot be loaded).
    """
    if demo:
        return FakeBackend(latency=0.35)
    return ServiceBackend.create()


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Runs the application.

    Args:
        argv: Command-line arguments; ``--demo`` uses fictitious data and never
            touches the real profiles. Defaults to ``sys.argv``.

    Returns:
        int: Process exit status. ``1`` if started as root or Konsave is missing.
    """
    args = list(argv if argv is not None else sys.argv)
    demo = "--demo" in args
    args = [arg for arg in args if arg != "--demo"]
    try:
        ensure_not_root()
    except RunningAsRootError as error:
        print(f"kongui: {error}", file=sys.stderr)
        return 1
    backend: Optional[ProfileBackend] = None
    if not demo:
        # Nothing graphical exists yet if Konsave cannot be loaded.
        try:
            backend = build_backend(False)
        except EngineLoadError as error:
            print(f"kongui: {error}", file=sys.stderr)
            return 1
    app = create_app(args)
    settings = AppSettings(settings_path())
    # The language is chosen before anything that makes texts (the demo data).
    i18n.manager().follow(settings)
    if backend is None:
        backend = build_backend(True)
    window = MainWindow(settings, backend)
    window.show()
    return app.exec()
