"""Theme tokens, stylesheet and the light/dark/system switch.

Three modes exist:

* ``system``: follows the desktop. Backgrounds and text come from the Qt
  palette (which, under KDE, is the Plasma colour scheme) and the accent is the
  system highlight colour.
* ``light`` / ``dark``: fixed palettes. The Qt colour scheme is switched too,
  so native widgets that the stylesheet does not touch match.

Widgets never hard-code colours. They read :class:`Tokens` through
:func:`get_theme` and rebuild their icons when ``ThemeManager.changed`` fires.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication


class ThemeMode(str, Enum):
    """User choice for the colour theme."""

    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"

    @classmethod
    def parse(cls, value: object) -> "ThemeMode":
        """Converts stored text to a mode, falling back to ``SYSTEM``.

        Args:
            value: Stored value.

        Returns:
            ThemeMode: The matching mode.
        """
        try:
            return cls(str(value))
        except ValueError:
            return cls.SYSTEM


@dataclass(frozen=True)
class Tokens:  # pylint: disable=too-many-instance-attributes
    """Semantic colours of one theme. Every field is a ``QColor``."""

    dark: bool
    window: QColor
    sidebar: QColor
    surface: QColor
    surface_alt: QColor
    border: QColor
    text: QColor
    muted: QColor
    accent: QColor
    accent_hover: QColor
    on_accent: QColor
    success: QColor
    warning: QColor
    danger: QColor


def mix(first: QColor, second: QColor, amount: float) -> QColor:
    """Blends two colours.

    Args:
        first: Colour returned when ``amount`` is 0.
        second: Colour returned when ``amount`` is 1.
        amount: Share of ``second`` between 0 and 1.

    Returns:
        QColor: The blended opaque colour.
    """
    inverse = 1.0 - amount
    return QColor(
        round(first.red() * inverse + second.red() * amount),
        round(first.green() * inverse + second.green() * amount),
        round(first.blue() * inverse + second.blue() * amount),
    )


def _hex(color: QColor) -> str:
    """Returns ``#rrggbb`` for stylesheets."""
    return color.name()


def _luminance(color: QColor) -> float:
    """Returns the WCAG relative luminance of a colour."""

    def channel(value: int) -> float:
        scaled = value / 255
        return (
            scaled / 12.92 if scaled <= 0.03928 else ((scaled + 0.055) / 1.055) ** 2.4
        )

    return (
        0.2126 * channel(color.red())
        + 0.7152 * channel(color.green())
        + 0.0722 * channel(color.blue())
    )


def contrast_ratio(first: QColor, second: QColor) -> float:
    """Returns the WCAG contrast ratio between two colours (1 to 21).

    Args:
        first: One colour.
        second: The other colour.

    Returns:
        float: The ratio.
    """
    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def readable_on(background: QColor, preferred: QColor) -> QColor:
    """Returns ``preferred`` if it is readable on ``background``, else a better colour.

    Args:
        background: The colour text is drawn on.
        preferred: The colour the platform would use.

    Returns:
        QColor: ``preferred`` when the contrast is at least 4.5, otherwise the
        best of near-black and white.
    """
    if contrast_ratio(preferred, background) >= 4.5:
        return preferred
    candidates = (QColor("#0b1220"), QColor("#ffffff"))
    return max(candidates, key=lambda color: contrast_ratio(color, background))


def fixed_tokens(dark: bool) -> Tokens:
    """Returns the built-in palette.

    Args:
        dark: ``True`` for the dark palette.

    Returns:
        Tokens: The palette.
    """
    if dark:
        accent = QColor("#5aa2ff")
        return Tokens(
            True,
            QColor("#1b1e24"),
            QColor("#15171c"),
            QColor("#242830"),
            QColor("#2d323c"),
            QColor("#353b46"),
            QColor("#e8eaee"),
            QColor("#a3abb9"),
            accent,
            accent.lighter(112),
            QColor("#0b1220"),
            QColor("#4cc38a"),
            QColor("#e0a93b"),
            QColor("#ff6b64"),
        )
    accent = QColor("#1d6fd8")
    return Tokens(
        False,
        QColor("#f4f5f7"),
        QColor("#eceef1"),
        QColor("#ffffff"),
        QColor("#f0f2f5"),
        QColor("#dfe2e7"),
        QColor("#1d2330"),
        QColor("#5f6878"),
        accent,
        accent.darker(112),
        QColor("#ffffff"),
        QColor("#1a7f4b"),
        QColor("#8a5a00"),
        QColor("#c4302b"),
    )


def system_tokens(palette: QPalette) -> Tokens:
    """Derives tokens from the platform palette (Plasma colour scheme on KDE).

    Args:
        palette: The application palette.

    Returns:
        Tokens: The palette.
    """
    window = palette.color(QPalette.ColorRole.Window)
    text = palette.color(QPalette.ColorRole.WindowText)
    base = palette.color(QPalette.ColorRole.Base)
    dark = window.lightness() < 128
    fallback = fixed_tokens(dark)
    accent = palette.color(QPalette.ColorRole.Highlight)
    on_accent = readable_on(accent, palette.color(QPalette.ColorRole.HighlightedText))
    if dark:
        surface = window.lighter(118)
        sidebar = window.darker(118)
    else:
        surface = base
        sidebar = window.darker(104)
    return Tokens(
        dark,
        window,
        sidebar,
        surface,
        mix(surface, text, 0.07),
        mix(window, text, 0.16),
        text,
        mix(surface, text, 0.62),
        accent,
        accent.lighter(112) if dark else accent.darker(112),
        on_accent,
        fallback.success,
        fallback.warning,
        fallback.danger,
    )


def palette_from_tokens(tk: Tokens) -> QPalette:
    """Builds a Qt palette so native widgets match a fixed theme.

    Args:
        tk: The theme tokens.

    Returns:
        QPalette: A palette with active, inactive and disabled groups.
    """
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: tk.window,
        QPalette.ColorRole.WindowText: tk.text,
        QPalette.ColorRole.Base: tk.surface,
        QPalette.ColorRole.AlternateBase: tk.surface_alt,
        QPalette.ColorRole.Text: tk.text,
        QPalette.ColorRole.Button: tk.surface,
        QPalette.ColorRole.ButtonText: tk.text,
        QPalette.ColorRole.BrightText: tk.text,
        QPalette.ColorRole.ToolTipBase: tk.surface,
        QPalette.ColorRole.ToolTipText: tk.text,
        QPalette.ColorRole.PlaceholderText: tk.muted,
        QPalette.ColorRole.Highlight: tk.accent,
        QPalette.ColorRole.HighlightedText: tk.on_accent,
        QPalette.ColorRole.Link: tk.accent,
        QPalette.ColorRole.Light: tk.surface.lighter(120),
        QPalette.ColorRole.Midlight: tk.surface_alt,
        QPalette.ColorRole.Mid: tk.border,
        QPalette.ColorRole.Dark: tk.border.darker(130),
        QPalette.ColorRole.Shadow: QColor(0, 0, 0),
    }
    for role, color in roles.items():
        palette.setColor(role, color)
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, tk.muted)
    return palette


def build_stylesheet(tk: Tokens) -> str:  # pylint: disable=too-many-locals
    """Builds the application stylesheet.

    Only KonGUI widgets are styled, through object names and properties, plus
    form controls inside pages and dialogs. Everything else keeps the native
    look.

    Args:
        tk: The theme tokens.

    Returns:
        str: Qt style sheet source.
    """
    # pylint: disable=line-too-long
    accent_soft = _hex(mix(tk.window, tk.accent, 0.18))
    success_soft = _hex(mix(tk.surface, tk.success, 0.16))
    warning_soft = _hex(mix(tk.surface, tk.warning, 0.18))
    danger_soft = _hex(mix(tk.surface, tk.danger, 0.14))
    c = {
        name: _hex(getattr(tk, name))
        for name in (
            "window",
            "sidebar",
            "surface",
            "surface_alt",
            "border",
            "text",
            "muted",
            "accent",
            "accent_hover",
            "on_accent",
            "success",
            "warning",
            "danger",
        )
    }
    return f"""
#Root, #PageBody, #Content {{ background: {c['window']}; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {c['muted']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

#Sidebar {{ background: {c['sidebar']}; border-right: 1px solid {c['border']}; }}
#BrandMark {{ background: transparent; }}
QLabel[role="brand"] {{ color: {c['text']}; }}
QToolButton#NavButton {{
    text-align: left; padding: 9px 12px; border: 1px solid transparent;
    border-radius: 8px; color: {c['text']}; background: transparent; }}
QToolButton#NavButton:hover {{ background: {c['surface_alt']}; }}
QToolButton#NavButton:checked {{ background: {accent_soft}; color: {c['accent']}; font-weight: 600; }}
QToolButton#NavButton:focus {{ border-color: {c['accent']}; }}

#TopBar {{ background: {c['window']}; border-bottom: 1px solid {c['border']}; }}

QLabel[role="muted"], QLabel[role="caption"] {{ color: {c['muted']}; }}
QLabel[role="danger"] {{ color: {c['danger']}; }}
QLabel[role="badge"] {{ border-radius: 9px; padding: 2px 9px; background: {c['surface_alt']}; color: {c['muted']}; }}
QLabel[role="badge"][tone="accent"] {{ background: {accent_soft}; color: {c['accent']}; }}
QLabel[role="badge"][tone="success"] {{ background: {success_soft}; color: {c['success']}; }}
QLabel[role="badge"][tone="warning"] {{ background: {warning_soft}; color: {c['warning']}; }}
QLabel[role="badge"][tone="danger"] {{ background: {danger_soft}; color: {c['danger']}; }}

QFrame#Card {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 12px; }}
QFrame#Card[hoverable="true"]:hover {{ border-color: {c['accent']}; }}
QFrame#Card[active="true"] {{ border: 2px solid {c['accent']}; }}
QFrame#IconTile {{ background: {accent_soft}; border-radius: 10px; }}
QFrame#DropZone {{ background: {c['surface']}; border: 2px dashed {c['border']}; border-radius: 12px; }}
QFrame#DropZone[dragging="true"] {{ border-color: {c['accent']}; background: {accent_soft}; }}
QFrame#Separator {{ background: {c['border']}; max-height: 1px; min-height: 1px; border: none; }}

QPushButton {{
    padding: 7px 14px; border-radius: 8px; border: 1px solid {c['border']};
    background: {c['surface']}; color: {c['text']}; }}
QPushButton:hover {{ background: {c['surface_alt']}; }}
QPushButton:focus {{ border-color: {c['accent']}; }}
QPushButton:disabled {{ color: {c['muted']}; background: {c['window']}; }}
QPushButton[variant="primary"] {{ background: {c['accent']}; color: {c['on_accent']}; border-color: {c['accent']}; font-weight: 600; }}
QPushButton[variant="primary"]:hover {{ background: {c['accent_hover']}; }}
QPushButton[variant="primary"]:focus {{ border-color: {c['text']}; }}
QPushButton[variant="primary"]:disabled {{ background: {c['border']}; border-color: {c['border']}; color: {c['muted']}; }}
QPushButton[variant="ghost"] {{ background: transparent; border-color: transparent; }}
QPushButton[variant="ghost"]:hover {{ background: {c['surface_alt']}; }}
QPushButton[variant="ghost"]:checked {{ background: {accent_soft}; color: {c['accent']}; }}
QPushButton[variant="danger"] {{ color: {c['danger']}; }}
QPushButton[variant="danger"]:hover {{ background: {danger_soft}; }}
QPushButton[variant="danger-solid"] {{ background: {c['danger']}; color: #ffffff; border-color: {c['danger']}; font-weight: 600; }}
QPushButton[variant="danger-solid"]:hover {{ background: {_hex(tk.danger.darker(112))}; }}
QPushButton::menu-indicator {{ image: none; width: 0; }}
QPushButton[variant="icon"] {{ padding: 6px; background: transparent; border-color: transparent; }}
QPushButton[variant="icon"]:hover {{ background: {c['surface_alt']}; }}
QPushButton[variant="segment"] {{ border-radius: 0; margin: 0; border-color: {c['border']}; }}
QPushButton[variant="segment"][segpos="first"] {{ border-top-left-radius: 8px; border-bottom-left-radius: 8px; }}
QPushButton[variant="segment"][segpos="last"] {{ border-top-right-radius: 8px; border-bottom-right-radius: 8px; }}
QPushButton[variant="segment"][segpos="only"] {{ border-radius: 8px; }}
QPushButton[variant="segment"]:checked {{ background: {accent_soft}; color: {c['accent']}; border-color: {c['accent']}; font-weight: 600; }}

#Page QLineEdit, #Dialog QLineEdit, QLineEdit#SearchField {{
    background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 8px;
    padding: 7px 10px; color: {c['text']}; selection-background-color: {c['accent']};
    selection-color: {c['on_accent']}; }}
#Page QLineEdit:focus, #Dialog QLineEdit:focus, QLineEdit#SearchField:focus {{ border-color: {c['accent']}; }}
#Page QLineEdit:disabled, #Dialog QLineEdit:disabled {{ color: {c['muted']}; }}
#Page QLineEdit[invalid="true"], #Dialog QLineEdit[invalid="true"] {{ border-color: {c['danger']}; }}
#Page QListWidget, #Dialog QListWidget, #Page QPlainTextEdit, #Dialog QPlainTextEdit {{
    background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 8px;
    padding: 4px; color: {c['text']}; selection-background-color: {c['accent']};
    selection-color: {c['on_accent']}; }}
#Page QListWidget:focus, #Dialog QListWidget:focus, #Page QPlainTextEdit:focus,
#Dialog QPlainTextEdit:focus {{ border-color: {c['accent']}; }}
#Page QListWidget::item, #Dialog QListWidget::item {{ padding: 6px 8px; border-radius: 6px; }}
#Page QListWidget::item:selected, #Dialog QListWidget::item:selected {{
    background: {accent_soft}; color: {c['accent']}; }}
#Page QCheckBox, #Dialog QCheckBox, #Page QRadioButton {{ spacing: 8px; color: {c['text']}; }}
#Dialog, #Dialog QWidget#DialogBody {{ background: {c['window']}; }}
#Dialog QLabel, #Page QLabel {{ color: {c['text']}; }}
#Page QLabel[role="muted"], #Page QLabel[role="caption"], #Dialog QLabel[role="muted"] {{ color: {c['muted']}; }}
#Page QLabel[role="danger"], #Dialog QLabel[role="danger"] {{ color: {c['danger']}; }}
#Page QLabel[role="badge"], #Dialog QLabel[role="badge"] {{ color: {c['muted']}; }}
#Page QLabel[role="badge"][tone="accent"] {{ color: {c['accent']}; }}
#Page QLabel[role="badge"][tone="success"] {{ color: {c['success']}; }}
#Page QLabel[role="badge"][tone="warning"] {{ color: {c['warning']}; }}
#Page QLabel[role="badge"][tone="danger"] {{ color: {c['danger']}; }}

QProgressBar {{ background: {c['surface_alt']}; border: none; border-radius: 4px; max-height: 8px; min-height: 8px; text-align: center; }}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 4px; }}

QFrame#Toast {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 10px; }}
QFrame#Toast[kind="success"] {{ border-left: 4px solid {c['success']}; }}
QFrame#Toast[kind="warning"] {{ border-left: 4px solid {c['warning']}; }}
QFrame#Toast[kind="error"] {{ border-left: 4px solid {c['danger']}; }}
QFrame#Toast[kind="info"] {{ border-left: 4px solid {c['accent']}; }}
QFrame#Toast QLabel {{ color: {c['text']}; }}
QFrame#Toast QLabel[role="muted"] {{ color: {c['muted']}; }}
"""


class ThemeManager(QObject):
    """Owns the current theme and applies it to the application.

    Signals:
        changed: Emitted after the tokens or the stylesheet changed.
    """

    changed = Signal()

    def __init__(self, app: QApplication) -> None:
        """Creates the manager and applies the system theme.

        Args:
            app: The running application.
        """
        super().__init__(app)
        self._app = app
        self._mode = ThemeMode.SYSTEM
        self._system_palette = QPalette(app.palette())
        self._tokens = system_tokens(self._system_palette)
        self._sheet = ""
        self._applying = False
        hints = app.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(self._on_system_changed)
        app.paletteChanged.connect(self._on_system_changed)
        self.refresh()

    @property
    def mode(self) -> ThemeMode:
        """The selected mode."""
        return self._mode

    @property
    def tokens(self) -> Tokens:
        """The colours in use."""
        return self._tokens

    @property
    def is_dark(self) -> bool:
        """Whether the effective theme is dark."""
        return self._tokens.dark

    def set_mode(self, mode: ThemeMode) -> None:
        """Selects a mode and applies it.

        Args:
            mode: The new mode.
        """
        mode = ThemeMode.parse(mode.value if isinstance(mode, ThemeMode) else mode)
        if mode == self._mode:
            return
        self._mode = mode
        self.refresh()

    def _on_system_changed(self, *_args: object) -> None:
        """Reacts to a desktop theme change while in system mode."""
        if self._applying or self._mode is not ThemeMode.SYSTEM:
            return
        self._system_palette = QPalette(self._app.palette())
        self.refresh()

    def _set_color_scheme(self) -> None:
        """Tells Qt which colour scheme native widgets should use."""
        hints = self._app.styleHints()
        if not hasattr(hints, "setColorScheme"):
            return
        scheme = {
            ThemeMode.SYSTEM: Qt.ColorScheme.Unknown,
            ThemeMode.LIGHT: Qt.ColorScheme.Light,
            ThemeMode.DARK: Qt.ColorScheme.Dark,
        }[self._mode]
        if hints.colorScheme() != scheme or scheme is Qt.ColorScheme.Unknown:
            hints.setColorScheme(scheme)

    def refresh(self) -> None:
        """Recomputes tokens, palette and stylesheet; emits ``changed`` if they differ."""
        self._applying = True
        try:
            self._set_color_scheme()
            if self._mode is ThemeMode.SYSTEM:
                # An empty palette hands control back to the platform theme.
                if self._app.palette().resolveMask() != 0:
                    self._app.setPalette(QPalette())
                tokens = system_tokens(self._system_palette)
            else:
                tokens = fixed_tokens(self._mode is ThemeMode.DARK)
                palette = palette_from_tokens(tokens)
                if self._app.palette() != palette:
                    self._app.setPalette(palette)
            sheet = build_stylesheet(tokens)
            if sheet == self._sheet:
                return
            self._tokens = tokens
            self._sheet = sheet
            self._app.setStyleSheet(sheet)
        finally:
            self._applying = False
        self.changed.emit()


_MANAGER: Optional[ThemeManager] = None


def get_theme() -> ThemeManager:
    """Returns the theme manager, creating it on first use.

    Returns:
        ThemeManager: The shared manager.

    Raises:
        RuntimeError: If no ``QApplication`` exists yet.
    """
    global _MANAGER  # pylint: disable=global-statement
    app = QGuiApplication.instance()
    if app is None:
        raise RuntimeError("create a QApplication before using the theme")
    if _MANAGER is None or _MANAGER.parent() is not app:
        _MANAGER = ThemeManager(app)  # type: ignore[arg-type]
    return _MANAGER
