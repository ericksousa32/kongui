"""Editing ``conf.yaml`` without losing what the user wrote in it.

The editor works on the *text*. A form (:class:`ConfigModel`) is turned into a
list of small replacements, insertions and deletions at positions PyYAML
reports, so comments, blank lines, unknown keys and placeholders that the form
does not touch stay byte for byte the same. Every result is re-read with
``yaml.safe_load`` and compared with what was intended; if that fails, the text
is regenerated from the data (unknown keys kept, comments lost) and the result
says so (``preserved=False``).

What a ``location`` *means* (placeholders and so on) is never decided here: the
original ``read_konsave_config`` does that when the text is validated.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional, Sequence, Tuple

import yaml

from kongui.core.config import (
    _check_duplicates,
    _error,
    _yaml_problem,
    entries_not_list,
    group_not_mapping,
)
from kongui.core.errors import ValidationError
from kongui.core.results import Problem
from kongui.core.yamlmap import compose, content_end, find_pair, locate, mapping_pairs

KINDS = ("save", "export")
_STEP = 2


class ConfigParseError(ValidationError):
    """Raised when a text cannot be shown as a form.

    Attributes:
        problems: What prevents it, located in the text.
    """

    def __init__(self, message: str, problems: Sequence[Problem] = ()) -> None:
        """Creates the error.

        Args:
            message: Summary.
            problems: Located findings.
        """
        super().__init__(message)
        self.problems = tuple(problems)


@dataclass(frozen=True)
class Group:
    """One group of a section (``save.<name>`` or ``export.<name>``).

    Attributes:
        name: Group name (also the folder name inside the profile).
        location: Directory, with placeholders exactly as written.
        entries: File and folder names inside ``location``.
        origin: Name the group has in the text being edited; ``None`` for a
            group created in the form. Renaming keeps the origin.
    """

    name: str
    location: str = ""
    entries: Tuple[str, ...] = ()
    origin: Optional[str] = None


@dataclass(frozen=True)
class ConfigModel:
    """What the form edits: the ``save`` and ``export`` groups.

    Attributes:
        save: Groups of the ``save`` section.
        export: Groups of the ``export`` section.
    """

    save: Tuple[Group, ...] = ()
    export: Tuple[Group, ...] = ()

    def groups(self, kind: str) -> Tuple[Group, ...]:
        """Returns the groups of a section."""
        return self.save if kind == "save" else self.export

    def with_groups(self, kind: str, groups: Sequence[Group]) -> "ConfigModel":
        """Returns a copy with the groups of a section replaced."""
        if kind == "save":
            return replace(self, save=tuple(groups))
        return replace(self, export=tuple(groups))


@dataclass(frozen=True)
class EditResult:
    """Outcome of :func:`apply_model`.

    Attributes:
        text: The new ``conf.yaml`` text.
        preserved: ``False`` if the text had to be regenerated and comments
            were lost.
    """

    text: str
    preserved: bool = True


class _Unsupported(Exception):
    """The text uses a layout the surgical editor does not handle."""


def quote(value: str, *, always: bool = False) -> str:
    """Writes a string as a YAML scalar that loads back identical.

    Args:
        value: The string.
        always: Force double quotes (used for ``location``).

    Returns:
        str: YAML text of the scalar.
    """
    if not always:
        dumped = yaml.safe_dump(
            [value], default_flow_style=True, allow_unicode=True, width=10**9
        ).strip()
        candidate = dumped[1:-1]
        try:
            if yaml.safe_load("- " + candidate) == [value]:
                return candidate
        except yaml.YAMLError:
            pass
    return json.dumps(value, ensure_ascii=False)


def parse_model(text: str) -> ConfigModel:
    """Reads a ``conf.yaml`` text as a form model.

    Missing ``location``/``entries``/sections are accepted (an incomplete file
    can be completed in the form); anything that cannot be shown without
    changing its meaning raises :class:`ConfigParseError`.

    Args:
        text: ``conf.yaml`` contents.

    Returns:
        ConfigModel: The groups of ``save`` and ``export``.

    Raises:
        ConfigParseError: If the text is not YAML or not shaped like a Konsave
            configuration.
    """
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ConfigParseError(
            "invalid YAML", [_located(text, _yaml_problem(error))]
        ) from error
    root = compose(text)
    problems: List[Problem] = [_located(text, p) for p in _check_duplicates(root)]
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigParseError(
            "the root is not a mapping",
            [
                _located(
                    text, _error("root-not-mapping", (), "the root must be a mapping")
                )
            ],
        )
    sections: Dict[str, Tuple[Group, ...]] = {}
    for kind in KINDS:
        sections[kind] = _read_section(text, kind, data.get(kind), problems)
    if problems:
        raise ConfigParseError("cannot be shown as a form", problems)
    return ConfigModel(sections["save"], sections["export"])


def _located(text: str, problem: Problem) -> Problem:
    """Adds line and column to a problem that has none."""
    if problem.line is not None:
        return problem
    line, column = locate(compose(text), problem.path)
    return replace(problem, line=line, column=column)


def _read_section(
    text: str, kind: str, section: Any, problems: List[Problem]
) -> Tuple[Group, ...]:
    """Reads one section, collecting what cannot be represented."""
    if section is None:
        return ()
    if not isinstance(section, dict):
        problems.append(
            _located(
                text,
                _error(
                    "section-not-mapping",
                    (kind,),
                    f"'{kind}' must be a mapping of groups",
                    key=kind,
                ),
            )
        )
        return ()
    groups = []
    for name, body in section.items():
        name = str(name)
        where = (kind, name)
        label = f"{kind}.{name}"
        if not isinstance(body, dict):
            problems.append(_located(text, group_not_mapping(kind, name)))
            continue
        location = body.get("location", "")
        if not isinstance(location, str):
            problems.append(
                _located(
                    text,
                    _error(
                        "location-invalid",
                        where + ("location",),
                        "'location' must be a string",
                        label,
                    ),
                )
            )
            continue
        entries = body.get("entries")
        if entries is None:
            entries = []
        if not isinstance(entries, list):
            problems.append(_located(text, entries_not_list(kind, name)))
            continue
        bad = [i for i, entry in enumerate(entries) if not isinstance(entry, str)]
        for index in bad:
            problems.append(
                _located(
                    text,
                    _error(
                        "entry-invalid",
                        where + ("entries", index),
                        f"entry {entries[index]!r} must be text",
                        label,
                        value=entries[index],
                    ),
                )
            )
        if bad:
            continue
        groups.append(Group(name, location, tuple(entries), origin=name))
    return tuple(groups)


def expected_data(text: str, model: ConfigModel) -> Dict[str, Any]:
    """Computes the data a text must load to after applying a model.

    Unknown keys of the document and of each group are carried over.

    Args:
        text: Current text.
        model: Wanted groups.

    Returns:
        Dict[str, Any]: The expected result of ``yaml.safe_load``.
    """
    data = yaml.safe_load(text) or {}
    result: Dict[str, Any] = copy.deepcopy(data)
    for kind in KINDS:
        old = data.get(kind) if isinstance(data.get(kind), dict) else {}
        old = {str(k): v for k, v in old.items()}
        built: Dict[str, Any] = {}
        for group in model.groups(kind):
            base = copy.deepcopy(old.get(group.origin or "", {}))
            if not isinstance(base, dict):
                base = {}
            if group.location or "location" in base:
                base["location"] = group.location
            if group.entries or "entries" in base or not group.origin:
                base["entries"] = list(group.entries)
            built[group.name] = base
        if built or kind in data:
            result[kind] = built
    return result


def _normalized(data: Any) -> Any:
    """Treats null, missing and empty ``entries`` alike when comparing."""
    if data is None:
        return {}
    if not isinstance(data, dict):
        return data
    out = copy.deepcopy(data)
    for kind in KINDS:
        section = out.get(kind)
        if isinstance(section, dict):
            for body in section.values():
                if isinstance(body, dict) and not body.get("entries"):
                    body["entries"] = []
    return out


def apply_model(text: str, model: ConfigModel) -> EditResult:
    """Applies the form to the text, keeping everything it does not change.

    Args:
        text: Current ``conf.yaml`` text.
        model: Wanted groups (use ``origin`` to tell renames from new groups).

    Returns:
        EditResult: New text and whether comments were preserved.

    Raises:
        ConfigParseError: If ``text`` itself cannot be edited (invalid YAML).
    """
    try:
        wanted = expected_data(text, model)
    except yaml.YAMLError as error:
        raise ConfigParseError(
            "invalid YAML", [_located(text, _yaml_problem(error))]
        ) from error
    try:
        new_text = _Editor(text, model).run()
        if _normalized(yaml.safe_load(new_text)) == _normalized(wanted):
            return EditResult(new_text, True)
    except (_Unsupported, yaml.YAMLError):
        pass
    regenerated = yaml.safe_dump(
        wanted, sort_keys=False, allow_unicode=True, default_flow_style=False
    )
    return EditResult(regenerated, False)


def render_group(group: Group, indent: int, step: int = _STEP) -> str:
    """Writes a group as a block of YAML lines (without trailing newline).

    Args:
        group: The group.
        indent: Number of spaces of the group's name.
        step: Spaces per nesting level.

    Returns:
        str: The lines.
    """
    pad = " " * indent
    inner = " " * (indent + step)
    lines = [f"{pad}{quote(group.name)}:"]
    if group.location:
        lines.append(f"{inner}location: {quote(group.location, always=True)}")
    if group.entries:
        lines.append(f"{inner}entries:")
        lines += [f"{inner}{' ' * step}- {quote(e)}" for e in group.entries]
    else:
        lines.append(f"{inner}entries: []")
    return "\n".join(lines)


class _Editor:  # pylint: disable=too-few-public-methods
    """Collects and applies the textual edits for one model."""

    def __init__(self, text: str, model: ConfigModel) -> None:
        self.text = text
        self.model = model
        self.root = compose(text)
        self.step = self.guess_step()
        self.edits: List[Tuple[int, int, str]] = []
        self.inserts: Dict[int, List[str]] = {}

    def guess_step(self) -> int:
        """Indentation step used by the file (spaces per level)."""
        for key_node, value in mapping_pairs(self.root) if self.root else ():
            if isinstance(value, yaml.MappingNode) and not value.flow_style:
                if value.value:
                    step = (
                        value.value[0][0].start_mark.column - key_node.start_mark.column
                    )
                    if step > 0:
                        return step
        return _STEP

    # -- text helpers ----------------------------------------------------
    def line_start(self, index: int) -> int:
        """Index of the start of the line containing ``index``."""
        return self.text.rfind("\n", 0, index) + 1

    def line_end(self, index: int) -> int:
        """Index of the newline ending the line containing ``index``."""
        found = self.text.find("\n", index)
        return len(self.text) if found < 0 else found

    def insert_after(self, index: int, block: str) -> None:
        """Queues lines to go after the line containing ``index``."""
        self.inserts.setdefault(self.line_end(index), []).append("\n" + block)

    def delete_lines(self, first: int, last: int) -> None:
        """Queues the removal of the lines from ``first`` to ``last``."""
        start = self.line_start(first)
        end = self.line_end(last)
        end = min(end + 1, len(self.text))
        self.edits.append((start, end, ""))

    # -- driver ----------------------------------------------------------
    def run(self) -> str:
        """Builds the edited text."""
        if self.root is not None and not isinstance(self.root, yaml.MappingNode):
            raise _Unsupported("root is not a mapping")
        for kind in KINDS:
            self.edit_section(kind)
        edits = list(self.edits)
        for index, parts in self.inserts.items():
            edits.append((index, index, "".join(parts)))
        out = self.text
        for start, end, replacement in sorted(
            edits, key=lambda e: (e[0], e[1]), reverse=True
        ):
            out = out[:start] + replacement + out[end:]
        return out

    # -- sections --------------------------------------------------------
    def edit_section(self, kind: str) -> None:
        """Queues the edits of one section."""
        groups = self.model.groups(kind)
        pair = find_pair(self.root, kind) if self.root is not None else None
        if pair is None:
            if groups:
                self.add_section(kind, groups)
            return
        key_node, value = pair
        if isinstance(value, yaml.MappingNode) and not value.flow_style:
            self.edit_groups(key_node, value, groups)
            return
        empty_flow = isinstance(value, yaml.MappingNode) and not value.value
        null = isinstance(value, yaml.ScalarNode) and value.value in ("", "~", "null")
        if null and not groups:
            # ``save:`` alone makes Konsave crash; ``save: {}`` is what was meant.
            if value.end_mark.index > value.start_mark.index:
                self.edits.append((value.start_mark.index, value.end_mark.index, "{}"))
            else:
                self.inserts.setdefault(value.start_mark.index, []).append(" {}")
            return
        if empty_flow and not groups:
            return
        if empty_flow or null:
            self.fill(
                key_node, value, [render_group(g, self.step, self.step) for g in groups]
            )
            return
        raise _Unsupported("section layout")

    def add_section(self, kind: str, groups: Sequence[Group]) -> None:
        """Appends a missing top-level section."""
        body = "\n".join(render_group(g, self.step, self.step) for g in groups)
        block = f"{kind}:\n{body}"
        if self.root is None or not self.root.value:
            prefix = "" if not self.text or self.text.endswith("\n") else "\n"
            self.inserts.setdefault(len(self.text), []).append(prefix + block + "\n")
            return
        self.insert_after(content_end(self.root), block)

    def fill(self, key_node: yaml.Node, value: yaml.Node, blocks: List[str]) -> None:
        """Turns an empty value (``key:``, ``key: {}``) into a block."""
        indent = key_node.start_mark.column
        shifted = []
        for block in blocks:
            shifted.append("\n".join(" " * indent + line for line in block.split("\n")))
        if value.end_mark.index > value.start_mark.index:
            self.edits.append((value.start_mark.index, value.end_mark.index, ""))
        self.insert_after(
            max(value.end_mark.index, key_node.end_mark.index), "\n".join(shifted)
        )

    # -- groups ----------------------------------------------------------
    def edit_groups(
        self,
        key_node: yaml.Node,
        mapping: yaml.MappingNode,
        groups: Sequence[Group],
    ) -> None:
        """Queues renames, changes, removals and additions of groups."""
        old: Dict[str, Tuple[yaml.Node, yaml.Node]] = {}
        for name_node, value_node in mapping.value:
            old[str(name_node.value)] = (name_node, value_node)
        kept = {g.origin for g in groups if g.origin is not None}
        if not groups and old:
            # every group goes away: leave ``key: {}`` instead of a null value
            colon = self.text.find(":", key_node.end_mark.index)
            self.inserts.setdefault(colon + 1, []).append(" {}")
        anchor = key_node.end_mark.index
        for name, (name_node, value_node) in old.items():
            if name in kept:
                anchor = content_end(value_node)
            else:
                self.delete_lines(name_node.start_mark.index, content_end(value_node))
        indent = mapping.value[0][0].start_mark.column if mapping.value else _STEP
        step = _STEP
        if mapping.value:
            first = mapping.value[0][1]
            if isinstance(first, yaml.MappingNode) and first.value:
                step = first.value[0][0].start_mark.column - indent or _STEP
        for group in groups:
            if group.origin is None or group.origin not in old:
                continue
            name_node, value_node = old[group.origin]
            if group.name != group.origin:
                self.edits.append(
                    (
                        name_node.start_mark.index,
                        name_node.end_mark.index,
                        quote(group.name),
                    )
                )
            self.edit_group(name_node, value_node, group, step)
        added = [g for g in groups if g.origin is None or g.origin not in old]
        if added:
            block = "\n".join(render_group(g, indent, step) for g in added)
            self.insert_after(anchor, block)

    def edit_group(
        self, key_node: yaml.Node, value: yaml.Node, group: Group, step: int
    ) -> None:
        """Queues the edits inside one existing group."""
        if not isinstance(value, yaml.MappingNode):
            raise _Unsupported("group is not a mapping")
        if value.flow_style:
            if value.value:
                raise _Unsupported("flow group")
            if group.location or group.entries:
                self.fill(key_node, value, self.group_body(group, step))
            return
        key_column = value.value[0][0].start_mark.column if value.value else step
        self.edit_location(value, group, key_column)
        self.edit_entries(value, group, key_column, step)

    @staticmethod
    def group_body(group: Group, step: int) -> List[str]:
        """Lines for a group that had no body (relative to its name)."""
        return [
            "\n".join(render_group(replace(group, name="x"), 0, step).split("\n")[1:])
        ]

    def edit_location(
        self, mapping: yaml.MappingNode, group: Group, column: int
    ) -> None:
        """Changes, adds or leaves the ``location`` of a group."""
        pair = find_pair(mapping, "location")
        pad = " " * column
        if pair is None:
            if group.location:
                line = f"{pad}location: {quote(group.location, always=True)}\n"
                start = self.line_start(mapping.value[0][0].start_mark.index)
                self.inserts.setdefault(start, []).append(line)
            return
        node = pair[1]
        if isinstance(node, yaml.ScalarNode) and node.value == group.location:
            return
        self.edits.append(
            (
                node.start_mark.index,
                max(node.end_mark.index, node.start_mark.index),
                quote(group.location, always=True),
            )
        )

    def edit_entries(
        self, mapping: yaml.MappingNode, group: Group, column: int, step: int
    ) -> None:
        """Changes the ``entries`` of a group, item by item."""
        pair = find_pair(mapping, "entries")
        pad = " " * column
        if pair is None:
            if group.entries:
                lines = [f"{pad}entries:"] + [
                    f"{pad}{' ' * step}- {quote(e)}" for e in group.entries
                ]
                self.insert_after(content_end(mapping), "\n".join(lines))
            return
        key_node, node = pair
        if isinstance(node, yaml.ScalarNode):
            if not group.entries:
                return
            lines = [f"{pad}{' ' * step}- {quote(e)}" for e in group.entries]
            if node.end_mark.index > node.start_mark.index:
                self.edits.append((node.start_mark.index, node.end_mark.index, ""))
            self.insert_after(
                max(node.end_mark.index, key_node.end_mark.index), "\n".join(lines)
            )
            return
        if not isinstance(node, yaml.SequenceNode):
            raise _Unsupported("entries layout")
        old = [str(item.value) for item in node.value]
        if tuple(old) == group.entries:
            return
        if node.flow_style:
            flow = "[" + ", ".join(quote(e) for e in group.entries) + "]"
            self.edits.append((node.start_mark.index, node.end_mark.index, flow))
            return
        self.edit_block_items(node, group.entries)

    def edit_block_items(
        self, node: yaml.SequenceNode, wanted: Tuple[str, ...]
    ) -> None:
        """Keeps matching items in place, removes the rest, inserts new ones."""
        pool: List[Optional[yaml.Node]] = list(node.value)
        first = node.value[0]
        pad = self.text[
            self.line_start(first.start_mark.index) : first.start_mark.index
        ]
        dash = pad[: len(pad) - len(pad.lstrip(" -"))] if pad.strip(" -") == "" else pad
        indent = " " * (len(pad) - len(pad.lstrip()))
        del dash
        anchor: Optional[int] = None
        used = set()
        for value in wanted:
            match = next(
                (
                    i
                    for i, item in enumerate(pool)
                    if item is not None and item.value == value
                ),
                None,
            )
            if match is not None:
                item = pool[match]
                pool[match] = None
                used.add(id(item))
                anchor = content_end(item)
                continue
            line = f"{indent}- {quote(value)}"
            if anchor is None:
                self.inserts.setdefault(
                    self.line_start(first.start_mark.index), []
                ).append(line + "\n")
            else:
                self.insert_after(anchor, line)
        for item in node.value:
            if id(item) not in used:
                self.delete_lines(item.start_mark.index, content_end(item))
