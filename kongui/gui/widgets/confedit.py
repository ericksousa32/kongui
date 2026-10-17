"""Widgets of the ``conf.yaml`` editor: a section editor and the problem list."""

from __future__ import annotations

from dataclasses import replace
from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QCoreApplication, Qt, Signal
from PySide6.QtGui import QBrush
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from kongui.core import Group, Problem
from kongui.core.safety import is_plain_name
from kongui.gui import i18n, messages
from kongui.gui.i18n import Text, resolve_text
from kongui.gui.theme import get_theme
from kongui.gui.validation import group_name_problem
from kongui.gui.widgets.common import (
    Badge,
    Button,
    Card,
    Label,
    Separator,
    clear_layout,
    repolish,
)
from kongui.gui.widgets.dialogs import GroupNameDialog


class SectionEditor(QWidget):  # pylint: disable=too-many-instance-attributes
    """Edits the groups of one section (``save`` or ``export``).

    The editor holds a tuple of :class:`~kongui.core.Group` and never changes
    it by itself: every edit emits :attr:`changed` with the new tuple, and the
    owner decides (and calls :meth:`set_groups` with what really resulted).

    Signals:
        changed: ``(groups)`` after the user edited something.
    """

    changed = Signal(object)

    def __init__(self, kind: str, intro: Text) -> None:
        """Creates the editor.

        Args:
            kind: ``"save"`` or ``"export"``.
            intro: One or two sentences about what the section does (text or
                function returning it).
        """
        super().__init__()
        self.kind = kind
        self.groups: Tuple[Group, ...] = ()
        self._updating = False
        self._resolved: Dict[str, str] = {}
        self._placeholders: Tuple[Sequence[str], Sequence[str]] = ((), ())
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)
        self.intro_label = Label(intro, "muted", wrap=True)
        outer.addWidget(self.intro_label)
        self.unavailable_label = Label(
            lambda: self.tr(
                "The file text could not be read as a form. Fix the problems in "
                "the “Text” tab to edit here again."
            ),
            "danger",
            wrap=True,
        )
        self.unavailable_label.hide()
        outer.addWidget(self.unavailable_label)

        row = QHBoxLayout()
        row.setSpacing(16)
        outer.addLayout(row, 1)

        left = Card()
        left_column = QVBoxLayout(left)
        left_column.setContentsMargins(14, 12, 14, 12)
        left_column.setSpacing(8)
        left_column.addWidget(Label(lambda: self.tr("Groups"), "h2"))
        self.group_list = QListWidget()
        i18n.bind(
            self.group_list,
            lambda: self.group_list.setAccessibleName(
                self.tr("{kind} groups").format(kind=kind)
            ),
        )
        self.group_list.setMinimumWidth(190)
        left_column.addWidget(self.group_list, 1)
        buttons = QHBoxLayout()
        self.add_button = Button(lambda: self.tr("Add"), icon_name="plus")
        self.remove_button = Button(
            lambda: self.tr("Remove"), variant="danger", icon_name="trash"
        )
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.remove_button)
        left_column.addLayout(buttons)
        row.addWidget(left, 0)

        right = Card()
        self.form = QVBoxLayout(right)
        self.form.setContentsMargins(18, 14, 18, 14)
        self.form.setSpacing(6)
        self.empty_label = Label(
            lambda: self.tr(
                "No group selected. Add a group or pick one from the list."
            ),
            "muted",
            wrap=True,
        )
        self.form.addWidget(self.empty_label)
        self.detail = QWidget()
        detail = QVBoxLayout(self.detail)
        detail.setContentsMargins(0, 0, 0, 0)
        detail.setSpacing(6)
        self.form.addWidget(self.detail, 1)
        row.addWidget(right, 1)

        detail.addWidget(Label(lambda: self.tr("Group name"), "muted"))
        self.name_edit = QLineEdit()
        i18n.bind(
            self.name_edit,
            lambda: self.name_edit.setAccessibleName(self.tr("Group name")),
        )
        detail.addWidget(self.name_edit)
        self.name_error = Label("", "danger", wrap=True)
        self.name_error.hide()
        detail.addWidget(self.name_error)

        detail.addWidget(Label(lambda: self.tr("Source folder (location)"), "muted"))
        self.location_edit = QLineEdit()
        i18n.bind(self.location_edit, self._retranslate_location)
        detail.addWidget(self.location_edit)
        self.placeholder_row = QHBoxLayout()
        self.placeholder_row.setSpacing(4)
        detail.addLayout(self.placeholder_row)
        self.function_row = QHBoxLayout()
        self.function_row.setSpacing(4)
        detail.addLayout(self.function_row)
        self.placeholder_buttons: Dict[str, Button] = {}
        self.resolved_label = Label("", "caption", wrap=True)
        detail.addWidget(self.resolved_label)

        detail.addWidget(Separator())
        detail.addWidget(Label(lambda: self.tr("Files and folders (entries)"), "muted"))
        self.entries_list = QListWidget()
        i18n.bind(
            self.entries_list,
            lambda: self.entries_list.setAccessibleName(self.tr("Group items")),
        )
        self.entries_list.setMinimumHeight(120)
        detail.addWidget(self.entries_list, 1)
        entry_buttons = QHBoxLayout()
        self.entry_add_button = Button(lambda: self.tr("Add item"), icon_name="plus")
        self.entry_remove_button = Button(
            lambda: self.tr("Remove item"), variant="danger", icon_name="trash"
        )
        entry_buttons.addWidget(self.entry_add_button)
        entry_buttons.addWidget(self.entry_remove_button)
        entry_buttons.addStretch(1)
        detail.addLayout(entry_buttons)
        detail.addWidget(
            Label(
                lambda: self.tr(
                    "Each item is the name of a file or folder inside the source "
                    "folder. Double-click to edit; do not use “/”."
                ),
                "caption",
                wrap=True,
            )
        )

        self.add_button.clicked.connect(self._ask_new_group)
        self.remove_button.clicked.connect(self.remove_current)
        self.group_list.currentRowChanged.connect(self._on_group_selected)
        self.name_edit.editingFinished.connect(self._commit_name)
        self.name_edit.textEdited.connect(self._preview_name)
        self.location_edit.editingFinished.connect(self._commit_location)
        self.entries_list.itemChanged.connect(self._on_entry_changed)
        self.entry_add_button.clicked.connect(self._start_new_entry)
        self.entry_remove_button.clicked.connect(self.remove_current_entry)
        self.entries_list.currentRowChanged.connect(self._sync_buttons)
        self._show_detail(False)
        i18n.bind(self, self._retranslate, now=False)

    # -------------------------------------------------------------- content

    def _retranslate_location(self) -> None:
        """Sets the texts of the location field in the current language."""
        self.location_edit.setAccessibleName(self.tr("Source folder"))
        self.location_edit.setPlaceholderText(self.tr("E.g.: $HOME/.config"))

    def _retranslate(self) -> None:
        """Rebuilds what was made from language-dependent text.

        The typed values, the selection and the groups are not touched.
        """
        keywords, functions = self._placeholders
        self.set_placeholders(keywords, functions)
        self._show_resolved()
        for row in range(self.entries_list.count()):
            self._paint_entry(self.entries_list.item(row))
        if self.name_error.isVisible():
            self._preview_name(self.name_edit.text())

    @staticmethod
    def function_sample() -> str:
        """Text put in a function placeholder when it is inserted, to be replaced."""
        return QCoreApplication.translate("SectionEditor", "text")

    def set_placeholders(
        self, keywords: Sequence[str], functions: Sequence[str]
    ) -> None:
        """Offers the placeholders the original Konsave understands.

        Args:
            keywords: Names with their ``$`` (``$HOME``…).
            functions: Function names (``ENDS_WITH``…).
        """
        self._placeholders = (tuple(keywords), tuple(functions))
        clear_layout(self.placeholder_row)
        clear_layout(self.function_row)
        self.placeholder_buttons = {}
        self.placeholder_row.addWidget(Label(self.tr("Insert:"), "caption"))
        self.function_row.addWidget(Label(self.tr("Functions:"), "caption"))
        sample = self.function_sample()
        for token in keywords:
            button = Button(
                token,
                variant="ghost",
                tooltip=self.tr("Insert {token}").format(token=token),
            )
            button.clicked.connect(lambda _c=False, t=token: self.insert_text(t))
            self.placeholder_row.addWidget(button)
            self.placeholder_buttons[token] = button
        for name in functions:
            template = f"${{{name}='{sample}'}}"
            button = Button(
                f"${{{name}}}",
                variant="ghost",
                tooltip=self.tr(
                    "Insert {template} (replace “{sample}” with your text)"
                ).format(template=template, sample=sample),
            )
            button.clicked.connect(lambda _c=False, t=template: self.insert_text(t))
            self.function_row.addWidget(button)
            self.placeholder_buttons[name] = button
        self.placeholder_row.addStretch(1)
        self.function_row.addStretch(1)

    def set_resolved(self, resolved: Dict[str, str]) -> None:
        """Shows how Konsave itself resolved each group's location.

        Args:
            resolved: Group name → resolved location.
        """
        self._resolved = dict(resolved)
        self._show_resolved()

    def set_available(self, available: bool) -> None:
        """Enables the form, or explains that the text must be fixed first."""
        self.unavailable_label.setVisible(not available)
        for widget in (self.add_button, self.remove_button):
            widget.setEnabled(available)
        self.group_list.setEnabled(available)
        self.detail.setEnabled(available)

    def set_groups(self, groups: Sequence[Group], select: Optional[str] = None) -> None:
        """Shows the groups, keeping the selection when possible.

        Args:
            groups: Groups of this section.
            select: Name to select; defaults to the one selected before.
        """
        wanted = select if select is not None else self.current_name()
        self._updating = True
        try:
            self.groups = tuple(groups)
            self.group_list.clear()
            for group in self.groups:
                self.group_list.addItem(group.name)
            names = [group.name for group in self.groups]
            if wanted in names:
                self.group_list.setCurrentRow(names.index(wanted))
            elif names:
                self.group_list.setCurrentRow(0)
        finally:
            self._updating = False
        self._load_form()

    def current_index(self) -> int:
        """Row of the selected group, or ``-1``."""
        row = self.group_list.currentRow()
        return row if 0 <= row < len(self.groups) else -1

    def current_name(self) -> Optional[str]:
        """Name of the selected group, if any."""
        index = self.current_index()
        return self.groups[index].name if index >= 0 else None

    def current_group(self) -> Optional[Group]:
        """The selected group, if any."""
        index = self.current_index()
        return self.groups[index] if index >= 0 else None

    def select_group(self, name: str) -> bool:
        """Selects a group by name.

        Returns:
            bool: Whether it exists.
        """
        for index, group in enumerate(self.groups):
            if group.name == name:
                self.group_list.setCurrentRow(index)
                return True
        return False

    def focus_field(self, field: str, index: Optional[int] = None) -> None:
        """Moves the focus to one field of the selected group.

        Args:
            field: ``name``, ``location`` or ``entries``.
            index: Entry row to select, for ``entries``.
        """
        if field == "location":
            self.location_edit.setFocus()
        elif field == "entries":
            if index is not None and 0 <= index < self.entries_list.count():
                self.entries_list.setCurrentRow(index)
            self.entries_list.setFocus()
        else:
            self.name_edit.setFocus()

    def insert_text(self, text: str) -> None:
        """Inserts text in the location field at the cursor and applies it."""
        if self.current_index() < 0:
            return
        self.location_edit.insert(text)
        self._commit_location()

    def commit(self) -> None:
        """Applies what is typed in the fields (call before saving)."""
        if self.current_index() < 0:
            return
        self._commit_name()
        self._commit_location()

    # ------------------------------------------------------------ internals

    def _show_detail(self, shown: bool) -> None:
        """Switches between the form and the "nothing selected" note."""
        self.detail.setVisible(shown)
        self.empty_label.setVisible(not shown)
        self.remove_button.setEnabled(shown)

    def _load_form(self) -> None:
        """Fills the form from the selected group."""
        group = self.current_group()
        self._show_detail(group is not None)
        self._updating = True
        try:
            self.name_edit.setText(group.name if group else "")
            self.location_edit.setText(group.location if group else "")
            self.entries_list.clear()
            for entry in group.entries if group else ():
                self._add_entry_item(entry)
        finally:
            self._updating = False
        self._set_name_error("")
        self._show_resolved()
        self._sync_buttons()

    def _add_entry_item(self, text: str) -> QListWidgetItem:
        """Adds an editable row, red if it cannot be a plain name."""
        item = QListWidgetItem(text)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self._paint_entry(item)
        self.entries_list.addItem(item)
        return item

    @staticmethod
    def _paint_entry(item: QListWidgetItem) -> None:
        """Colours an entry that Konsave would reject."""
        tokens = get_theme().tokens
        if is_plain_name(item.text()):
            item.setData(Qt.ItemDataRole.ForegroundRole, None)
            item.setToolTip("")
        else:
            item.setForeground(QBrush(tokens.danger))
            item.setToolTip(
                QCoreApplication.translate(
                    "SectionEditor",
                    "Use only the name of the file or folder, without “/”.",
                )
            )

    def _show_resolved(self) -> None:
        """Shows the resolved location of the selected group."""
        name = self.current_name()
        text = self._resolved.get(name or "")
        self.resolved_label.setText(
            self.tr("Konsave resolves this folder as: {path}").format(path=text)
            if text
            else ""
        )
        self.resolved_label.setVisible(bool(text))

    def _sync_buttons(self, *_args) -> None:
        """Enables the entry buttons that make sense."""
        has_group = self.current_index() >= 0
        self.entry_add_button.setEnabled(has_group)
        self.entry_remove_button.setEnabled(
            has_group and self.entries_list.currentRow() >= 0
        )

    def _set_name_error(self, text: str) -> None:
        """Shows or hides the name error and marks the field."""
        self.name_error.setText(text)
        self.name_error.setVisible(bool(text))
        self.name_edit.setProperty("invalid", bool(text))
        repolish(self.name_edit)

    def _others(self) -> List[str]:
        """Names of the other groups of this section."""
        index = self.current_index()
        return [g.name for i, g in enumerate(self.groups) if i != index]

    def _emit(self, groups: Sequence[Group]) -> None:
        """Announces an edit."""
        self.changed.emit(tuple(groups))

    def _replace_current(self, **fields) -> None:
        """Emits the groups with the selected one changed."""
        index = self.current_index()
        if index < 0:
            return
        groups = list(self.groups)
        groups[index] = replace(groups[index], **fields)
        if "name" in fields:
            self.pending_select = fields["name"]
        self._emit(groups)

    def _on_group_selected(self, _row: int) -> None:
        """Loads the form for the newly selected group."""
        if not self._updating:
            self._load_form()

    def _preview_name(self, text: str) -> None:
        """Shows the name error while typing."""
        self._set_name_error(
            group_name_problem(text, self._others()) if text != "" else ""
        )

    def _commit_name(self) -> None:
        """Renames the group if the typed name is valid and new."""
        group = self.current_group()
        if self._updating or group is None:
            return
        text = self.name_edit.text()
        if text == group.name:
            self._set_name_error("")
            return
        problem = group_name_problem(text, self._others())
        self._set_name_error(problem or "")
        if problem:
            return
        self._replace_current(name=text)

    def _commit_location(self) -> None:
        """Applies the typed location."""
        group = self.current_group()
        if self._updating or group is None:
            return
        if self.location_edit.text() != group.location:
            self._replace_current(location=self.location_edit.text())

    def _entries_from_list(self) -> Tuple[str, ...]:
        """Reads the entries as shown."""
        return tuple(
            self.entries_list.item(row).text()
            for row in range(self.entries_list.count())
            if self.entries_list.item(row).text() != ""
        )

    def _on_entry_changed(self, item: QListWidgetItem) -> None:
        """Applies an edited or new entry (an emptied one is dropped)."""
        if self._updating:
            return
        self._paint_entry(item)
        group = self.current_group()
        if group is None:
            return
        entries = self._entries_from_list()
        if entries != group.entries:
            self._replace_current(entries=entries)
        else:
            self._load_form()

    def _start_new_entry(self) -> None:
        """Adds an empty row and starts editing it."""
        self._updating = True
        try:
            item = self._add_entry_item("")
        finally:
            self._updating = False
        self.entries_list.setCurrentItem(item)
        self.entries_list.editItem(item)

    def add_entry(self, text: str) -> None:
        """Adds an entry to the selected group (same as typing it).

        Args:
            text: File or folder name.
        """
        group = self.current_group()
        if group is not None and text != "":
            self._replace_current(entries=group.entries + (text,))

    def remove_current_entry(self) -> None:
        """Removes the selected entry."""
        group = self.current_group()
        row = self.entries_list.currentRow()
        if group is None or not 0 <= row < len(group.entries):
            return
        entries = group.entries[:row] + group.entries[row + 1 :]
        self._replace_current(entries=entries)

    def _ask_new_group(self) -> None:
        """Asks for a name and adds the group."""
        name = GroupNameDialog.ask(self.window(), [g.name for g in self.groups])
        if name is not None:
            self.add_group(name)

    def add_group(self, name: str, location: str = "") -> None:
        """Adds an empty group at the end.

        Args:
            name: Group name (the caller has validated it).
            location: Initial location.
        """
        groups = list(self.groups) + [Group(name, location, ())]
        self.pending_select = name
        self._emit(groups)

    def remove_current(self) -> None:
        """Removes the selected group."""
        index = self.current_index()
        if index < 0:
            return
        groups = list(self.groups)
        del groups[index]
        self._emit(groups)

    #: Group the owner should select after applying the next edit.
    pending_select: Optional[str] = None


class ProblemRow(QFrame):
    """One finding with its position and a button to jump to it.

    Signals:
        goto: Emitted with the :class:`~kongui.core.Problem`.
    """

    goto = Signal(object)

    def __init__(self, problem: Problem) -> None:
        """Creates the row.

        Args:
            problem: The finding.
        """
        super().__init__()
        self.problem = problem
        self.setObjectName("ProblemRow")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 4, 0, 4)
        row.setSpacing(10)
        kind = self.tr("Error") if problem.is_error else self.tr("Warning")
        badge = Badge(kind, "danger" if problem.is_error else "warning")
        badge.setFixedWidth(52)
        row.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        column = QVBoxLayout()
        column.setSpacing(1)
        self.place_label = Label(messages.problem_place(problem), "caption")
        self.text_label = Label(messages.problem_text(problem), "body", wrap=True)
        column.addWidget(self.place_label)
        column.addWidget(self.text_label)
        row.addLayout(column, 1)
        self.goto_button = Button(self.tr("Go to"), variant="ghost", icon_name="edit")
        self.goto_button.clicked.connect(lambda: self.goto.emit(problem))
        row.addWidget(self.goto_button, 0, Qt.AlignmentFlag.AlignTop)
        self.setAccessibleName(
            self.tr("{kind}: {text}").format(kind=kind, text=self.text_label.text())
        )


class ProblemList(Card):
    """Errors and warnings of the text being edited.

    Signals:
        goto: A row asked to jump to its problem.
    """

    goto = Signal(object)

    def __init__(self) -> None:
        """Creates the list, empty."""
        super().__init__()
        column = QVBoxLayout(self)
        column.setContentsMargins(18, 14, 18, 14)
        column.setSpacing(6)
        self._summary: Text = lambda: self.tr("Not checked yet.")
        self.summary_label = Label(self._summary_text, "h2")
        column.addWidget(self.summary_label)
        self._rows = QVBoxLayout()
        self._rows.setSpacing(0)
        column.addLayout(self._rows)
        self.problems: Tuple[Problem, ...] = ()
        i18n.bind(self, self.retranslate, now=False)

    def _summary_text(self) -> str:
        """Current headline in the current language."""
        return resolve_text(self._summary)

    def _set_summary(self, summary: Text) -> None:
        """Sets the headline, kept as a function so it follows the language."""
        self._summary = summary
        self.summary_label.setText(resolve_text(summary))

    def retranslate(self) -> None:
        """Rebuilds the rows in the current language."""
        if self.problems:
            self.set_problems(self.problems)
        else:
            self.summary_label.setText(self._summary_text())

    def rows(self) -> List[ProblemRow]:
        """The rows currently shown."""
        return [
            self._rows.itemAt(i).widget()
            for i in range(self._rows.count())
            if isinstance(self._rows.itemAt(i).widget(), ProblemRow)
        ]

    def set_pending(self, text: Optional[str] = None) -> None:
        """Marks the list as out of date while a check runs.

        Args:
            text: Headline; defaults to "Checking…".
        """
        if text is None:
            self._set_summary(lambda: self.tr("Checking…"))
        else:
            self._set_summary(text)

    def set_failure(self, lines: Sequence[str]) -> None:
        """Shows that the check itself could not run."""
        self.problems = ()
        clear_layout(self._rows)
        self._set_summary(lambda: self.tr("The file could not be checked"))
        for line in lines:
            self._rows.addWidget(Label(line, "muted", wrap=True))

    def _count_summary(self, errors: int, warnings: int) -> str:
        """Headline such as "2 errors and 1 warning"."""
        parts = []
        if errors:
            parts.append(self.tr("%n error(s)", "", errors))
        if warnings:
            parts.append(self.tr("%n warning(s)", "", warnings))
        if len(parts) == 2:
            return self.tr("{errors} and {warnings}").format(
                errors=parts[0], warnings=parts[1]
            )
        return parts[0]

    def set_problems(self, problems: Sequence[Problem]) -> None:
        """Shows the findings, errors first and in file order.

        Args:
            problems: Findings from a validation.
        """
        ordered = sorted(
            problems, key=lambda p: (not p.is_error, p.line or 0, p.column or 0)
        )
        self.problems = tuple(ordered)
        clear_layout(self._rows)
        errors = sum(1 for p in ordered if p.is_error)
        warnings = len(ordered) - errors
        if not ordered:
            self._set_summary(lambda: self.tr("No problems found"))
        else:
            self._set_summary(lambda: self._count_summary(errors, warnings))
        for problem in ordered:
            row = ProblemRow(problem)
            row.goto.connect(self.goto)
            self._rows.addWidget(row)
