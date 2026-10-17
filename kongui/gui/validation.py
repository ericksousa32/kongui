"""Input checks for names typed in the interface, with pt-BR messages."""

from __future__ import annotations

from typing import Collection, Optional

from kongui.core.errors import ValidationError
from kongui.core.safety import (
    is_plain_name,
    validate_archive_name,
    validate_profile_name,
)


def profile_name_problem(name: str, existing: Collection[str] = ()) -> Optional[str]:
    """Explains why a profile name cannot be used.

    The rules come from the integration layer
    (:func:`kongui.core.safety.validate_profile_name`), so the interface
    refuses exactly what the services would refuse.

    Args:
        name: Name typed by the user.
        existing: Names already in use.

    Returns:
        Optional[str]: A pt-BR message, or ``None`` if the name is fine.
    """
    if not name.strip():
        return "Informe um nome para o perfil."
    try:
        validate_profile_name(name)
    except ValidationError:
        return (
            "Nome inválido. Não use barras, “.” ou “..”, hífen no início, "
            "espaços nas pontas, caracteres de controle, a extensão .knsv ou "
            "o prefixo reservado “.kongui-”. Máximo de 200 bytes (letras "
            "acentuadas e emojis ocupam mais de um)."
        )
    if name in existing:
        return "Já existe um perfil com esse nome."
    return None


def archive_name_problem(name: str) -> Optional[str]:
    """Explains why an exported file name (without extension) cannot be used.

    Uses :func:`kongui.core.safety.validate_archive_name`, so the interface
    refuses exactly what the export service would refuse.

    Args:
        name: Name typed by the user.

    Returns:
        Optional[str]: A pt-BR message, or ``None`` if the name is fine.
    """
    if not name.strip():
        return "Informe um nome para o arquivo."
    try:
        validate_archive_name(name)
    except ValidationError:
        return (
            "Nome inválido. Não use barras, “.” ou “..”, hífen no início, espaços "
            "nas pontas, caracteres de controle, nem as extensões .knsv ou .zip. "
            "Máximo de 200 bytes (letras acentuadas e emojis ocupam mais de um)."
        )
    return None


def group_name_problem(name: str, existing: Collection[str] = ()) -> Optional[str]:
    """Explains why a ``save``/``export`` group name cannot be used.

    Args:
        name: Name typed by the user.
        existing: Other group names of the same section.

    Returns:
        Optional[str]: A pt-BR message, or ``None`` if the name is fine.
    """
    if not name.strip():
        return "Informe um nome para o grupo."
    if not is_plain_name(name):
        return "Nome inválido. Use um nome simples de pasta: sem “/”, “.” ou “..”."
    if name in existing:
        return "Já existe um grupo com esse nome nesta seção."
    return None
