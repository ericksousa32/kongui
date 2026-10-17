"""Positions inside a YAML document, read from PyYAML's own node graph.

Only *locates* things; what a configuration means is decided by the original
Konsave code (see :mod:`kongui.core.config`).
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple, Union

import yaml

PathStep = Union[str, int]


def compose(text: str) -> Optional[yaml.Node]:
    """Builds the node graph of a document.

    Args:
        text: YAML text.

    Returns:
        Optional[yaml.Node]: Root node, or ``None`` if the text is empty or not
        valid YAML.
    """
    try:
        return yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError:
        return None


def mapping_pairs(node: yaml.Node) -> Sequence[Tuple[yaml.Node, yaml.Node]]:
    """Returns the key/value node pairs of a mapping node (else empty)."""
    if isinstance(node, yaml.MappingNode):
        return node.value
    return ()


def find_pair(node: yaml.Node, key: str) -> Optional[Tuple[yaml.Node, yaml.Node]]:
    """Finds the pair of a key in a mapping node.

    As in ``yaml.safe_load``, the *last* occurrence of a repeated key wins.

    Args:
        node: A mapping node.
        key: Key text.

    Returns:
        Optional[Tuple[yaml.Node, yaml.Node]]: Key and value nodes.
    """
    found = None
    for key_node, value_node in mapping_pairs(node):
        if isinstance(key_node, yaml.ScalarNode) and key_node.value == key:
            found = (key_node, value_node)
    return found


def locate(root: Optional[yaml.Node], path: Sequence[PathStep]) -> Tuple[int, int]:
    """Finds the 1-based line and column of a path.

    The last step of a mapping path points at the *key*; a sequence step at the
    item. If part of the path does not exist, the deepest node found is used.

    Args:
        root: Root node from :func:`compose`.
        path: Steps (keys and list indexes) from the root.

    Returns:
        Tuple[int, int]: ``(line, column)``; ``(1, 1)`` without a document.
    """
    if root is None:
        return 1, 1
    node = root
    best = root
    for position, step in enumerate(path):
        if isinstance(node, yaml.MappingNode):
            pair = find_pair(node, str(step))
            if pair is None:
                break
            best = pair[0] if position == len(path) - 1 else pair[1]
            node = pair[1]
        elif isinstance(node, yaml.SequenceNode) and isinstance(step, int):
            if not 0 <= step < len(node.value):
                break
            node = node.value[step]
            best = node
        else:
            break
    mark = best.start_mark
    return mark.line + 1, mark.column + 1


def content_end(node: yaml.Node) -> int:
    """Index in the text right after the last character of a node's content.

    Unlike ``node.end_mark`` this does not swallow the blank lines and
    comments that follow a block collection.

    Args:
        node: Any node.

    Returns:
        int: Character index.
    """
    if isinstance(node, yaml.ScalarNode) or node.flow_style:
        return node.end_mark.index
    if isinstance(node, yaml.SequenceNode):
        return content_end(node.value[-1]) if node.value else node.end_mark.index
    if isinstance(node, yaml.MappingNode):
        if not node.value:
            return node.end_mark.index
        return content_end(node.value[-1][1])
    return node.end_mark.index
