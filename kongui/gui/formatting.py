"""Locale-aware text helpers: sizes, dates and relative times.

Every function follows the interface language in use (see
:mod:`kongui.gui.i18n`): decimal separators come from ``QLocale`` and the words
and patterns are translated.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import QCoreApplication, QLocale, QT_TRANSLATE_NOOP

from kongui.gui import i18n

#: Short month names, translated one by one.
_MONTHS = (
    QT_TRANSLATE_NOOP("formatting", "Jan"),
    QT_TRANSLATE_NOOP("formatting", "Feb"),
    QT_TRANSLATE_NOOP("formatting", "Mar"),
    QT_TRANSLATE_NOOP("formatting", "Apr"),
    QT_TRANSLATE_NOOP("formatting", "May"),
    QT_TRANSLATE_NOOP("formatting", "Jun"),
    QT_TRANSLATE_NOOP("formatting", "Jul"),
    QT_TRANSLATE_NOOP("formatting", "Aug"),
    QT_TRANSLATE_NOOP("formatting", "Sep"),
    QT_TRANSLATE_NOOP("formatting", "Oct"),
    QT_TRANSLATE_NOOP("formatting", "Nov"),
    QT_TRANSLATE_NOOP("formatting", "Dec"),
)


def _number(value: float) -> str:
    """Formats a number with one decimal in the language's style (no grouping)."""
    locale = QLocale(i18n.current())
    locale.setNumberOptions(QLocale.NumberOption.OmitGroupSeparator)
    return locale.toString(float(value), "f", 1)


def format_size(megabytes: float) -> str:
    """Formats a size given in MB.

    Args:
        megabytes: Size in megabytes.

    Returns:
        str: For example ``"48.2 MB"`` (English) or ``"48,2 MB"`` (Portuguese);
        ``GB`` from 1024 MB on.
    """
    if megabytes >= 1024:
        return f"{_number(megabytes / 1024)} GB"
    return f"{_number(megabytes)} MB"


def format_kib(size_bytes: int) -> str:
    """Formats a small size in bytes as KB with one decimal.

    Args:
        size_bytes: Size in bytes.

    Returns:
        str: For example ``"1.5 KB"`` or ``"1,5 KB"``.
    """
    return f"{_number(size_bytes / 1024)} KB"


def format_date(moment: datetime) -> str:
    """Formats a date such as ``"Oct 12, 2026"`` or ``"12 out 2026"``.

    Args:
        moment: The date.

    Returns:
        str: Short date.
    """
    month = QCoreApplication.translate("formatting", _MONTHS[moment.month - 1])
    return QCoreApplication.translate("formatting", "{month} {day}, {year}").format(
        month=month, day=moment.day, year=moment.year
    )


def format_datetime(moment: datetime) -> str:
    """Formats a date and time with seconds, in the language's usual order.

    Args:
        moment: The moment.

    Returns:
        str: For example ``"2026-10-12 14:30:05"`` or ``"12/10/2026 14:30:05"``.
    """
    pattern = QCoreApplication.translate(
        "formatting", "%Y-%m-%d %H:%M:%S", "strftime pattern for a date and time"
    )
    return moment.strftime(pattern)


def format_relative(moment: datetime, now: Optional[datetime] = None) -> str:
    """Describes how long ago something happened.

    Args:
        moment: The past moment.
        now: Reference time; defaults to the current time.

    Returns:
        str: Text such as ``"today"``, ``"yesterday"`` or ``"3 days ago"``
        (``"hoje"``, ``"ontem"``, ``"há 3 dias"`` in Portuguese).
    """
    reference = now or datetime.now()
    days = (reference.date() - moment.date()).days
    if days <= 0:
        return QCoreApplication.translate("formatting", "today")
    if days == 1:
        return QCoreApplication.translate("formatting", "yesterday")
    if days < 30:
        return QCoreApplication.translate("formatting", "%n day(s) ago", "", days)
    if days < 365:
        return QCoreApplication.translate(
            "formatting", "%n month(s) ago", "", days // 30
        )
    return format_date(moment)
