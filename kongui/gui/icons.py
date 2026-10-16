"""Stroke icons drawn from inline SVG, tinted at runtime.

Drawing the icons ourselves keeps them identical on every desktop and lets
them follow the active theme colours. Only the shapes below exist; asking for
another name raises ``KeyError``.
"""

from __future__ import annotations

from typing import Dict, Tuple

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_SHAPES: Dict[str, str] = {
    "dashboard": (
        '<rect x="3" y="3" width="7" height="9" rx="1.5"/>'
        '<rect x="14" y="3" width="7" height="5" rx="1.5"/>'
        '<rect x="14" y="12" width="7" height="9" rx="1.5"/>'
        '<rect x="3" y="16" width="7" height="5" rx="1.5"/>'
    ),
    "profiles": '<path d="M12 3 3 8l9 5 9-5-9-5z"/><path d="m3 13 9 5 9-5"/>',
    "transfer": (
        '<path d="M8 4v14"/><path d="m4 14 4 4 4-4"/>'
        '<path d="M16 20V6"/><path d="m12 10 4-4 4 4"/>'
    ),
    "settings": (
        '<path d="M4 7h10"/><path d="M18 7h2"/><circle cx="16" cy="7" r="2"/>'
        '<path d="M4 17h2"/><path d="M10 17h10"/><circle cx="8" cy="17" r="2"/>'
    ),
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 8h.01"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "save": (
        '<path d="M5 4h11l3 3v13H5z"/><path d="M8 4v5h7V4"/>'
        '<rect x="8" y="14" width="8" height="6"/>'
    ),
    "check": '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    "play": '<path d="M7 5v14l11-7z"/>',
    "export": '<path d="M12 15V4"/><path d="m7.5 8.5 4.5-4.5 4.5 4.5"/><path d="M5 15v4h14v-4"/>',
    "import": '<path d="M12 4v11"/><path d="m7.5 10.5 4.5 4.5 4.5-4.5"/><path d="M5 15v4h14v-4"/>',
    "trash": (
        '<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7l1 13h10l1-13"/>'
        '<path d="M10 11v6M14 11v6"/>'
    ),
    "more": (
        '<circle cx="5" cy="12" r="1.3" fill="currentColor"/>'
        '<circle cx="12" cy="12" r="1.3" fill="currentColor"/>'
        '<circle cx="19" cy="12" r="1.3" fill="currentColor"/>'
    ),
    "grid": (
        '<rect x="4" y="4" width="6.5" height="6.5" rx="1.2"/>'
        '<rect x="13.5" y="4" width="6.5" height="6.5" rx="1.2"/>'
        '<rect x="4" y="13.5" width="6.5" height="6.5" rx="1.2"/>'
        '<rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.2"/>'
    ),
    "list": (
        '<path d="M9 6h11M9 12h11M9 18h11"/><path d="M4.5 6h.01M4.5 12h.01M4.5 18h.01"/>'
    ),
    "sun": (
        '<circle cx="12" cy="12" r="4"/>'
        '<path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4'
        'M18.7 5.3l-1.4 1.4M6.7 17.3l-1.4 1.4"/>'
    ),
    "moon": '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
    "monitor": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    "folder": (
        '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'
    ),
    "file": '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/>',
    "warning": '<path d="M12 4 3 20h18z"/><path d="M12 10v4M12 17h.01"/>',
    "x": '<path d="m6 6 12 12M18 6 6 18"/>',
    "copy": (
        '<rect x="8" y="8" width="12" height="12" rx="2"/>'
        '<path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>'
    ),
    "edit": '<path d="M4 20h4L19 9l-4-4L4 16z"/>',
    "refresh": (
        '<path d="M20 11a8 8 0 0 0-14-4L4 9"/><path d="M4 4v5h5"/>'
        '<path d="M4 13a8 8 0 0 0 14 4l2-2"/><path d="M20 20v-5h-5"/>'
    ),
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "disk": (
        '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6"/>'
        '<path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>'
    ),
}

#: Names accepted by :func:`pixmap` and :func:`icon`.
ICON_NAMES: Tuple[str, ...] = tuple(sorted(_SHAPES))

_CACHE: Dict[Tuple[str, str, int, float], QPixmap] = {}


def _svg(name: str, color: str, stroke: float) -> bytes:
    """Builds the SVG document for an icon.

    Args:
        name: Icon name from :data:`ICON_NAMES`.
        color: CSS colour used for strokes and fills.
        stroke: Stroke width in a 24x24 view box.

    Returns:
        bytes: UTF-8 SVG source.
    """
    body = _SHAPES[name].replace("currentColor", color)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" '
        f'stroke-linejoin="round">{body}</svg>'
    ).encode("utf-8")


def pixmap(name: str, color: QColor, size: int = 20) -> QPixmap:
    """Renders an icon.

    Args:
        name: Icon name from :data:`ICON_NAMES`.
        color: Tint colour.
        size: Logical size in pixels.

    Returns:
        QPixmap: A pixmap with the right device pixel ratio.

    Raises:
        KeyError: If ``name`` is not a known icon.
    """
    if name not in _SHAPES:
        raise KeyError(f"unknown icon: {name!r}")
    screen = QGuiApplication.primaryScreen()
    ratio = screen.devicePixelRatio() if screen else 1.0
    key = (name, color.name(QColor.NameFormat.HexArgb), size, ratio)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    side = max(1, round(size * ratio))
    image = QImage(side, side, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(_svg(name, color.name(), 1.8)))
    painter = QPainter(image)
    renderer.render(painter, QRectF(0, 0, side, side))
    painter.end()
    result = QPixmap.fromImage(image)
    result.setDevicePixelRatio(ratio)
    _CACHE[key] = result
    return result


def icon(
    name: str, color: QColor, size: int = 20, checked_color: QColor = None
) -> QIcon:
    """Builds a ``QIcon`` from a drawn icon.

    Args:
        name: Icon name from :data:`ICON_NAMES`.
        color: Tint colour.
        size: Logical size in pixels.
        checked_color: Optional colour for the checked ("on") state.

    Returns:
        QIcon: The icon.
    """
    result = QIcon()
    result.addPixmap(pixmap(name, color, size), QIcon.Mode.Normal, QIcon.State.Off)
    on_color = checked_color or color
    result.addPixmap(pixmap(name, on_color, size), QIcon.Mode.Normal, QIcon.State.On)
    return result
