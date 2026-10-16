"""pt-BR texts for operation results and errors."""

from __future__ import annotations

from typing import Optional, Tuple

from kongui.core import (
    ConfigMissingError,
    ConfigValidationError,
    ConfirmationRequiredError,
    KonGuiError,
    OperationFailedError,
    OperationResult,
    ProfileExistsError,
    ProfileInvalidError,
    ProfileNotFoundError,
    RunningAsRootError,
    ValidationError,
)

#: Infinitive of each operation, for "Não foi possível <verb>".
VERBS = {
    "list": "listar os perfis",
    "save": "salvar o perfil",
    "overwrite": "sobrescrever o perfil",
    "apply": "aplicar o perfil",
    "remove": "remover o perfil",
    "wipe_all": "limpar os perfis",
    "duplicate": "duplicar o perfil",
    "import": "importar o perfil",
    "reset": "restaurar os dados",
}

#: Text of the success notification, ``{name}`` is the profile name.
SUCCESS = {
    "save": "Perfil “{name}” salvo",
    "overwrite": "Perfil “{name}” sobrescrito",
    "apply": "Perfil “{name}” aplicado",
    "remove": "Perfil “{name}” removido",
    "wipe_all": "Todos os perfis foram removidos",
    "duplicate": "Perfil “{name}” duplicado",
    "import": "Perfil “{name}” importado",
    "reset": "Perfis fictícios restaurados",
}

#: Extra advice appended to the success of some operations.
SUCCESS_HINT = {
    "apply": "Saia e entre na sessão para ver todas as mudanças.",
}


def success_title(operation: str, name: str) -> str:
    """Returns the success headline.

    Args:
        operation: Operation key.
        name: Profile name (may be empty).

    Returns:
        str: Text for a notification.
    """
    return SUCCESS.get(operation, "Operação concluída").format(name=name)


def _limit(lines, count: int = 4) -> Tuple[str, ...]:
    """Keeps the first lines and says how many were dropped."""
    lines = tuple(str(line) for line in lines if str(line).strip())
    if len(lines) <= count:
        return lines
    return lines[:count] + (f"… e mais {len(lines) - count}.",)


def failure_title(operation: str, name: str) -> str:
    """Returns the failure headline.

    Args:
        operation: Operation key.
        name: Profile name (may be empty).

    Returns:
        str: For example ``Não foi possível aplicar o perfil “Gaming”``.
    """
    verb = VERBS.get(operation, "concluir a operação")
    if name and operation not in ("wipe_all", "list", "reset"):
        return f"Não foi possível {verb} “{name}”"
    return f"Não foi possível {verb}"


def describe_result(result: OperationResult) -> Tuple[str, ...]:
    """Explains a failed :class:`OperationResult`.

    Args:
        result: A result with ``ok`` false.

    Returns:
        Tuple[str, ...]: Detail lines (engine errors, warnings, message).
    """
    lines = [result.message] if result.message else []
    lines += [line for line in result.errors if line not in lines]
    lines += [f"Aviso: {line}" for line in result.warnings]
    return _limit(lines)


def describe_error(  # pylint: disable=too-many-return-statements
    error: BaseException,
) -> Tuple[str, ...]:
    """Explains an exception raised by a service, in pt-BR.

    Args:
        error: The exception.

    Returns:
        Tuple[str, ...]: Detail lines. Unknown exceptions are reported with
        their type so that a bug is not hidden behind a generic text.
    """
    if isinstance(error, RunningAsRootError):
        return ("O KonGUI não deve ser executado como root. Abra-o com o seu usuário.",)
    if isinstance(error, ProfileExistsError):
        return (
            "Já existe um perfil com esse nome. Use “Sobrescrever” para substituí-lo.",
        )
    if isinstance(error, ProfileNotFoundError):
        return ("O perfil não existe mais. A lista foi atualizada.",)
    if isinstance(error, ProfileInvalidError):
        return ("O perfil está incompleto (sem conf.yaml) e não pode ser aplicado.",)
    if isinstance(error, ConfigMissingError):
        return ("Não há um conf.yaml ativo do Konsave.",)
    if isinstance(error, ConfirmationRequiredError):
        return ("A operação exige confirmação explícita e não foi confirmada.",)
    if isinstance(error, ConfigValidationError):
        report = error.report
        lines = [str(error)]
        if report is not None:
            lines += list(report.errors)
        return _limit(lines)
    if isinstance(error, OperationFailedError):
        return describe_result(error.result)
    if isinstance(error, ValidationError):
        return (f"Entrada inválida: {error}",)
    if isinstance(error, KonGuiError):
        return (str(error),)
    return (f"Erro inesperado ({type(error).__name__}): {error}",)


def outcome_hint(operation: str, ok: bool) -> Optional[str]:
    """Returns advice to show under a success notification.

    Args:
        operation: Operation key.
        ok: Whether the operation succeeded.

    Returns:
        Optional[str]: The hint, or ``None``.
    """
    return SUCCESS_HINT.get(operation) if ok else None
