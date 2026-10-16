"""Shared pieces of the GUI tests (offscreen Qt, no real data)."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from typing import Callable, Optional
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication

    HAVE_QT = True
except ImportError:  # pragma: no cover - depends on the machine
    HAVE_QT = False


class ManualExecutor:
    """Executor that queues jobs until the test runs them.

    It lets a test look at the "loading" state: the job is accepted but nothing
    has happened yet; :meth:`run_next` runs the work and delivers the result.

    Attributes:
        queue: Pending ``(work, on_done)`` pairs.
    """

    def __init__(self) -> None:
        """Creates an empty queue."""
        self.queue: list = []

    def submit(self, work, on_done) -> None:
        """Queues a job."""
        self.queue.append((work, on_done))

    def run_next(self) -> bool:
        """Runs the oldest queued job and delivers its result.

        Returns:
            bool: ``False`` if the queue was empty.
        """
        if not self.queue:
            return False
        work, on_done = self.queue.pop(0)
        try:
            value, error = work(), None
        except Exception as exc:  # pylint: disable=broad-except
            value, error = None, exc
        on_done(value, error)
        return True

    def shutdown(self) -> None:
        """Drops pending jobs."""
        self.queue.clear()


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class GuiTestCase(unittest.TestCase):
    """Base class: one shared ``QApplication``, a private ``$HOME``, cleanup.

    Attributes:
        app: The running application.
        window: Main window created by :meth:`make_window`, if any.
    """

    app: "QApplication"
    window = None

    @classmethod
    def setUpClass(cls) -> None:
        """Creates (or reuses) the application."""
        super().setUpClass()
        from kongui.gui.app import create_app

        cls.app = create_app([])

    def setUp(self) -> None:
        """Isolates ``$HOME`` and restores the theme afterwards."""
        super().setUp()
        folder = tempfile.mkdtemp(prefix="kongui-gui-test-")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        self.home = folder
        patcher = mock.patch.dict(os.environ, {"HOME": folder})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(mock.patch.stopall)
        from kongui.gui.theme import ThemeMode, get_theme

        self.addCleanup(lambda: get_theme().set_mode(ThemeMode.SYSTEM))

    def make_window(self, **kwargs):
        """Creates and shows a main window with in-memory settings.

        Args:
            **kwargs: Passed to ``MainWindow``.

        Returns:
            MainWindow: The visible window (closed automatically at cleanup).
        """
        from kongui.gui.backend import FakeBackend
        from kongui.gui.main_window import MainWindow
        from kongui.gui.state import AppSettings
        from kongui.gui.tasks import InlineExecutor

        kwargs.setdefault("settings", AppSettings())
        kwargs.setdefault("backend", FakeBackend())
        kwargs.setdefault("executor", InlineExecutor())
        window = MainWindow(**kwargs)
        window.show()
        self.addCleanup(self.destroy_window, window)
        self.flush()
        self.window = window
        return window

    def destroy_window(self, window) -> None:
        """Closes and deletes a window so it stops costing time on theme changes.

        Args:
            window: The window to dispose of.
        """
        from PySide6.QtCore import QEvent

        window.close()
        window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def backend_do(self, window, operation: str, *args, **kwargs) -> None:
        """Changes the window's fake backend behind the interface's back, then
        reloads the list (as if another program had changed the profiles).

        Args:
            window: The main window.
            operation: Backend method name.
            *args: Positional arguments of the method.
            **kwargs: Keyword arguments of the method.
        """
        getattr(window.backend, operation)(*args, **kwargs)
        window.controller.refresh()
        self.flush()

    def flush(self) -> None:
        """Processes pending events."""
        for _ in range(3):
            self.app.processEvents()

    def wait_until(self, condition: Callable[[], bool], timeout: float = 3.0) -> bool:
        """Runs the event loop until a condition holds.

        Args:
            condition: Callable returning ``True`` when done.
            timeout: Maximum seconds to wait.

        Returns:
            bool: Whether the condition became true in time.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if condition():
                return True
            time.sleep(0.005)
        self.app.processEvents()
        return condition()

    @staticmethod
    def button_with_text(root, text: str):
        """Finds a visible push button by its label.

        Args:
            root: Widget to search in.
            text: Exact button text.

        Returns:
            Optional[QPushButton]: The button, or ``None``.
        """
        from PySide6.QtWidgets import QPushButton

        for button in root.findChildren(QPushButton):
            if button.text() == text and button.isVisibleTo(root.window()):
                return button
        return None

    @staticmethod
    def accept_dialogs(fill: Optional[Callable] = None):
        """Patches ``ProfileDialog.exec`` so it fills itself and is accepted.

        Args:
            fill: Called with the dialog before it is "accepted".

        Returns:
            mock._patch: Started patcher; stopped by ``mock.patch.stopall``.
        """
        from PySide6.QtWidgets import QDialog

        from kongui.gui.widgets.dialogs import ProfileDialog

        def fake_exec(dialog):
            if fill:
                fill(dialog)
            return QDialog.DialogCode.Accepted

        patcher = mock.patch.object(ProfileDialog, "exec", new=fake_exec)
        patcher.start()
        return patcher


class WindowCase(GuiTestCase):
    """A window with a fake backend whose work only runs when told to."""

    def open_window(self, backend=None, load=True, page="profiles"):
        """Opens the window and (optionally) finishes the first listing.

        Args:
            backend: Backend to use; a fresh ``FakeBackend`` by default.
            load: Run the initial listing.
            page: Page to show.

        Returns:
            MainWindow: The window.
        """
        from kongui.gui.backend import FakeBackend

        self.backend = backend or FakeBackend()
        self.executor = ManualExecutor()
        window = self.make_window(backend=self.backend, executor=self.executor)
        self.outcomes: List = []
        window.controller.operation_finished.connect(self.outcomes.append)
        window.show_page(page)
        self.flush()
        if load:
            self.run_all()
        return window

    def run_all(self) -> None:
        """Runs every queued job."""
        self.flush()
        while self.executor.run_next():
            self.flush()

    def run_one(self) -> None:
        """Runs exactly one queued job."""
        self.assertTrue(self.executor.run_next(), "nothing was queued")
        self.flush()

    @staticmethod
    def names(page):
        """Names of the cards shown by the profiles page."""
        return [card.profile_name for card in page.cards()]

    @staticmethod
    def card(page, name):
        """The card of one profile."""
        return next(c for c in page.cards() if c.profile_name == name)
