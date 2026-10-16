"""Small text helpers for Portuguese (pt-BR) labels."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

_MONTHS = (
    "jan",
    "fev",
    "mar",
    "abr",
    "mai",
    "jun",
    "jul",
    "ago",
    "set",
    "out",
    "nov",
    "dez",
)


def format_size(megabytes: float) -> str:
    """Formats a size given in MB.

    Args:
        megabytes: Size in megabytes.

    Returns:
        str: For example ``"48,2 MB"`` or ``"1,3 GB"``.
    """
    if megabytes >= 1024:
        return f"{megabytes / 1024:.1f} GB".replace(".", ",")
    return f"{megabytes:.1f} MB".replace(".", ",")


def format_date(moment: datetime) -> str:
    """Formats a date as ``"12 out 2026"``.

    Args:
        moment: The date.

    Returns:
        str: Short date.
    """
    return f"{moment.day} {_MONTHS[moment.month - 1]} {moment.year}"


def format_relative(moment: datetime, now: Optional[datetime] = None) -> str:
    """Describes how long ago something happened.

    Args:
        moment: The past moment.
        now: Reference time; defaults to the current time.

    Returns:
        str: Text such as ``"hoje"``, ``"ontem"`` or ``"há 3 dias"``.
    """
    reference = now or datetime.now()
    days = (reference.date() - moment.date()).days
    if days <= 0:
        return "hoje"
    if days == 1:
        return "ontem"
    if days < 30:
        return f"há {days} dias"
    if days < 365:
        months = days // 30
        return "há 1 mês" if months == 1 else f"há {months} meses"
    return format_date(moment)


def plural(count: int, singular: str, many: str) -> str:
    """Chooses the singular or plural form for a count.

    Args:
        count: The number of items.
        singular: Text for exactly one item.
        many: Text for any other count.

    Returns:
        str: ``"1 perfil"`` or ``"3 perfis"`` style text.
    """
    return f"{count} {singular if count == 1 else many}"
