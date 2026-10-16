"""Input checks for names typed in the interface, with pt-BR messages."""

from __future__ import annotations

from typing import Collection, Optional

from kongui.core.errors import ValidationError
from kongui.core.safety import validate_profile_name


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
            "espaços nas pontas, caracteres de controle ou a extensão .knsv "
            "(máximo de 200 caracteres)."
        )
    if name in existing:
        return "Já existe um perfil com esse nome."
    return None
