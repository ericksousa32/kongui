"""pt-BR texts for operation results and errors."""

from __future__ import annotations

from typing import Optional, Tuple

from kongui.core import (
    ArchiveExistsError,
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
    "export": "exportar o perfil",
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
    "export": "Perfil “{name}” exportado",
    "reset": "Perfis fictícios restaurados",
}

#: Extra advice appended to the success of some operations.
SUCCESS_HINT = {
    "apply": "Saia e entre na sessão para ver todas as mudanças.",
    "import": (
        "Os arquivos do perfil foram gravados no sistema. "
        "Saia e entre na sessão para ver tudo."
    ),
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


#: Fragments of ``ValidationError`` messages (English, from the services) and
#: their pt-BR text. The first match wins; unknown messages are shown as they are.
_VALIDATION_TEXTS = (
    ("archive not found", "O arquivo não foi encontrado."),
    ("must be a '*", "Escolha um arquivo com a extensão .knsv."),
    (
        "not a readable archive",
        "O arquivo não é um .knsv válido (não é um zip legível).",
    ),
    (
        "archive has no conf.yaml",
        "O arquivo não contém o conf.yaml e não é um perfil do Konsave.",
    ),
    (
        "no 'save/' folder",
        "O arquivo não contém a pasta save/ e não é um perfil do Konsave.",
    ),
    (
        "unsafe path inside archive",
        "O arquivo contém caminhos inseguros e foi recusado.",
    ),
    ("conf.yaml is too large", "O conf.yaml do arquivo é grande demais."),
    ("output folder does not exist", "A pasta de destino não existe."),
    ("output folder is not writable", "Sem permissão de escrita na pasta de destino."),
    (
        "stale import folder",
        "Há uma pasta de importação antiga e abandonada; remova-a antes.",
    ),
)


def _translate_validation(text: str) -> str:
    """Returns the pt-BR text for a validation message."""
    for fragment, translation in _VALIDATION_TEXTS:
        if fragment in text:
            return translation
    return f"Entrada inválida: {text}"


def _describe_os_error(error: OSError) -> Tuple[str, ...]:
    """Explains a file-system error (permissions, missing file…)."""
    where = f" ({error.filename})" if error.filename else ""
    if isinstance(error, PermissionError):
        return (f"Sem permissão para acessar o arquivo ou a pasta{where}.",)
    if isinstance(error, FileNotFoundError):
        return (f"Arquivo ou pasta não encontrado{where}.",)
    if isinstance(error, IsADirectoryError):
        return (f"Era esperado um arquivo, mas é uma pasta{where}.",)
    if isinstance(error, NotADirectoryError):
        return (f"Era esperada uma pasta, mas é um arquivo{where}.",)
    return (f"Erro de arquivo{where}: {error.strerror or error}",)


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
    if isinstance(error, ArchiveExistsError):
        return (
            "Já existe um arquivo, pasta ou .zip com esse nome no destino. "
            "Escolha outro nome ou outra política de conflito.",
        )
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
        return (_translate_validation(str(error)),)
    if isinstance(error, KonGuiError):
        return (str(error),)
    if isinstance(error, OSError):
        return _describe_os_error(error)
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
