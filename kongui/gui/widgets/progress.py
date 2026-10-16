"""Fake long-running task used by the prototype."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal


class SimulatedTask(QObject):
    """Counts from 0 to 100 on a timer, then emits ``finished``.

    Signals:
        progress: Emitted with the percentage after each step.
        finished: Emitted once, after 100 %.
    """

    progress = Signal(int)
    finished = Signal()

    def __init__(
        self, steps: int = 16, interval_ms: int = 30, parent: Optional[QObject] = None
    ):
        """Creates the task.

        Args:
            steps: Number of timer ticks until completion.
            interval_ms: Milliseconds between ticks.
            parent: Optional Qt parent.
        """
        super().__init__(parent)
        self._steps = max(1, steps)
        self._done = 0
        self._timer = QTimer(self)
        self._timer.setInterval(max(0, interval_ms))
        self._timer.timeout.connect(self._tick)

    @property
    def running(self) -> bool:
        """Whether the task is in progress."""
        return self._timer.isActive()

    def start(self) -> None:
        """Starts (or restarts) the task."""
        self._done = 0
        self.progress.emit(0)
        self._timer.start()

    def cancel(self) -> None:
        """Stops the task without emitting ``finished``."""
        self._timer.stop()

    def _tick(self) -> None:
        """Advances one step."""
        self._done += 1
        self.progress.emit(round(100 * self._done / self._steps))
        if self._done >= self._steps:
            self._timer.stop()
            self.finished.emit()
