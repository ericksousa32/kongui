"""A grid whose column count follows the available width."""

from __future__ import annotations

from typing import List, Optional, Sequence

from PySide6.QtCore import QSize
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QGridLayout, QWidget


class ResponsiveGrid(QWidget):
    """Lays widgets out in as many equal columns as fit.

    The column count is ``width // (min_item_width + spacing)``, never less
    than 1 and never more than ``max_columns``. Calling
    :meth:`set_forced_columns` pins it (for example 1 for a list view).
    """

    def __init__(
        self,
        min_item_width: int = 260,
        spacing: int = 16,
        max_columns: int = 6,
        allowed_columns: Optional[Sequence[int]] = None,
    ) -> None:
        """Creates the grid.

        Args:
            min_item_width: Narrowest width an item may get.
            spacing: Gap between items, in pixels.
            max_columns: Upper bound for the column count.
            allowed_columns: If given, only these column counts are used (the
                largest one that fits), which avoids a lonely last item, for
                example ``(1, 2, 4)`` for four cards.
        """
        super().__init__()
        self._min_item_width = min_item_width
        self._spacing = spacing
        self._max_columns = max_columns
        self._allowed = tuple(sorted(allowed_columns)) if allowed_columns else None
        self._forced: Optional[int] = None
        self._items: List[QWidget] = []
        self._columns = 1
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(spacing)

    @property
    def columns(self) -> int:
        """Current number of columns."""
        return self._columns

    def columns_for_width(self, width: int) -> int:
        """Computes the column count for a width.

        Args:
            width: Available width in pixels.

        Returns:
            int: The number of columns.
        """
        if self._forced is not None:
            return self._forced
        fit = (width + self._spacing) // (self._min_item_width + self._spacing)
        columns = max(1, min(self._max_columns, fit))
        if self._allowed:
            fitting = [value for value in self._allowed if value <= columns]
            columns = fitting[-1] if fitting else self._allowed[0]
        return columns

    def set_forced_columns(self, columns: Optional[int]) -> None:
        """Pins the column count, or releases it with ``None``.

        Args:
            columns: Fixed number of columns, or ``None`` for automatic.
        """
        self._forced = columns
        self._relayout(force=True)

    def items(self) -> List[QWidget]:
        """Returns the managed widgets in order."""
        return list(self._items)

    def set_items(self, items: List[QWidget]) -> None:
        """Replaces the content. Old widgets are scheduled for deletion.

        Args:
            items: The new widgets, in display order.
        """
        for old in self._items:
            self._layout.removeWidget(old)
            old.hide()
            old.setParent(None)
            old.deleteLater()
        self._items = list(items)
        for item in self._items:
            item.setParent(self)
            item.show()
        self._relayout(force=True)

    def _relayout(self, force: bool = False) -> None:
        """Places the items for the current width."""
        columns = self.columns_for_width(self.width())
        if columns == self._columns and not force:
            return
        self._columns = columns
        for item in self._items:
            self._layout.removeWidget(item)
        for column in range(self._max_columns + 1):
            self._layout.setColumnStretch(column, 0)
        for index, item in enumerate(self._items):
            self._layout.addWidget(item, index // columns, index % columns)
        for column in range(columns):
            self._layout.setColumnStretch(column, 1)
        self._layout.invalidate()

    def minimumSizeHint(self) -> QSize:  # pylint: disable=invalid-name
        """Reports room for one column only, so the parent may shrink freely."""
        return QSize(self._min_item_width, super().minimumSizeHint().height())

    def resizeEvent(self, event: QResizeEvent) -> None:  # pylint: disable=invalid-name
        """Recomputes the columns when the width changes."""
        super().resizeEvent(event)
        self._relayout()
