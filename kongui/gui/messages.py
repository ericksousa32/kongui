"""pt-BR texts for operation results and errors."""

from __future__ import annotations

import re
from typing import Optional, Tuple

from kongui.core import (
    CONF_DIFFERS_PREFIX,
    ArchiveExistsError,
    BackupNotFoundError,
    ConfigConflictError,
    ConfigMissingError,
    ConfigValidationError,
    ConfirmationRequiredError,
    KonGuiError,
    OperationFailedError,
    OperationResult,
    Problem,
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
    "save_config": "salvar o conf.yaml",
    "restore_config": "restaurar o backup do conf.yaml",
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
    "save_config": "conf.yaml salvo",
    "restore_config": "Backup do conf.yaml restaurado",
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
    if name and operation not in (
        "wipe_all",
        "list",
        "reset",
        "save_config",
        "restore_config",
    ):
        return f"Não foi possível {verb} “{name}”"
    return f"Não foi possível {verb}"


_NO_DATA_FOLDER = re.compile(r"^the archive has no data folder in save/ for: (.+?) \(")
_UNLISTED_FOLDER = re.compile(
    r"^save/ has folders that its conf.yaml does not list: (.+?) \("
)


def describe_warning(line: str) -> str:
    """Translates a non-blocking warning of the services.

    Args:
        line: English warning text.

    Returns:
        str: pt-BR text; warnings it does not know are returned unchanged.
    """
    if line.startswith(CONF_DIFFERS_PREFIX):
        found = line.rsplit("): ", 1)[-1]
        return (
            "O .knsv leva o conf.yaml atual do Konsave, que é diferente do conf.yaml "
            f"guardado neste perfil. Grupos: {found} (+ só no atual, − só no perfil, "
            "~ alterado). Em outro computador, um grupo novo impede aplicar o perfil "
            "e um grupo que sumiu é ignorado sem aviso."
        )
    match = _NO_DATA_FOLDER.match(line)
    if match:
        return (
            f"O arquivo não traz dados para os grupos: {match.group(1)}. O perfil "
            "importado não poderá ser aplicado."
        )
    match = _UNLISTED_FOLDER.match(line)
    if match:
        return (
            f"O arquivo tem pastas que o conf.yaml dele não lista: {match.group(1)}. "
            "Elas serão ignoradas ao aplicar o perfil."
        )
    return line


def describe_result(result: OperationResult) -> Tuple[str, ...]:
    """Explains a failed :class:`OperationResult`.

    Args:
        result: A result with ``ok`` false.

    Returns:
        Tuple[str, ...]: Detail lines (engine errors, warnings, message).
    """
    lines = [result.message] if result.message else []
    lines += [line for line in result.errors if line not in lines]
    lines += [f"Aviso: {describe_warning(line)}" for line in result.warnings]
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


#: pt-BR explanation of each kind of ``conf.yaml`` finding (``Problem.code``).
#: ``{…}`` fields are taken from ``Problem.args``.
PROBLEM_TEXTS = {
    "file-missing": "O arquivo conf.yaml não existe.",
    "file-too-large": "O arquivo é grande demais para ser uma configuração do Konsave.",
    "file-unreadable": "Não foi possível ler o arquivo: {detail}",
    "yaml-syntax": (
        "O YAML está malformado: {problem}. Corrija a sintaxe (indentação, "
        "aspas, dois-pontos ou colchetes) neste ponto."
    ),
    "root-not-mapping": (
        "O arquivo precisa ser um mapa com as seções “save” e “export” na raiz."
    ),
    "missing-top-key": (
        "Falta a seção “{key}”. O Konsave exige as duas seções, “save” e “export”; "
        "use “{key}: {{}}” se ela deve ficar vazia."
    ),
    "section-not-mapping": (
        "“{key}” precisa ser um mapa de grupos. Deixá-la vazia (“{key}:”) faz o "
        "Konsave falhar; escreva “{key}: {{}}”."
    ),
    "unknown-top-mapping": (
        "A chave “{key}” é desconhecida e é ignorada ao salvar e exportar. Ela foi "
        "mantida no arquivo."
    ),
    "unknown-top-scalar": (
        "A chave desconhecida “{key}” precisa ser um mapa de grupos; o Konsave "
        "percorre todas as chaves da raiz e falharia aqui."
    ),
    "duplicate-key": (
        "A chave “{key}” aparece mais de uma vez. O YAML guarda só a última e a "
        "outra seria perdida em silêncio."
    ),
    "group-name-invalid": (
        "O nome do grupo “{name}” precisa ser um nome simples de pasta: sem “/”, "
        "sem ser vazio, “.” ou “..”."
    ),
    "group-not-mapping": "O grupo precisa ter “location” e “entries”.",
    "group-unknown-keys": (
        "Chaves desconhecidas neste grupo são ignoradas pelo Konsave: "
        "{keys_text}. Elas foram mantidas no arquivo."
    ),
    "location-invalid": "“location” precisa ser um texto não vazio (a pasta de origem).",
    "placeholder-unsupported": (
        "O placeholder ${name} não existe no Konsave. Os reconhecidos são: "
        "{supported}."
    ),
    "function-unsupported": (
        "A função ${{{name}=...}} não existe no Konsave. Reconhecidas: {supported}."
    ),
    "function-multiple": (
        "Só a última função de placeholder tem efeito no Konsave original."
    ),
    "entries-missing": (
        "Falta “entries”. Use uma lista vazia (“entries: []”) se o grupo não tem "
        "itens."
    ),
    "entries-not-list": "“entries” precisa ser uma lista de nomes.",
    "entry-invalid": (
        "O item {value_text} precisa ser um único nome de arquivo ou pasta, sem "
        "“/”. Caminhos aninhados fazem o Konsave abortar todo o salvamento."
    ),
    "entry-duplicate": "O item {value_text} está repetido.",
    "location-unresolved": (
        "O placeholder não foi resolvido ({resolved}). Sem uma pasta correspondente, "
        "o Konsave usaria esse texto como caminho relativo."
    ),
    "location-relative": "A pasta resolvida não é um caminho absoluto: {resolved}.",
    "location-missing-dir": (
        "A pasta {resolved} não existe neste computador; os itens deste grupo "
        "serão ignorados em silêncio."
    ),
    "comments-lost": (
        "Os comentários do arquivo não puderam ser mantidos nesta edição; ao "
        "salvar, eles serão perdidos (o arquivo anterior fica como backup)."
    ),
    "konsave-failed": "O Konsave não conseguiu interpretar o arquivo: {detail}",
}


def describe_problem(problem: Problem) -> str:
    """Explains one ``conf.yaml`` finding in pt-BR, with its position.

    Args:
        problem: A finding from the validation report.

    Returns:
        str: For example
        ``linha 12, coluna 9 · save.configs.entries[3]: O item … precisa …``.
    """
    return f"{problem_place(problem)}: {problem_text(problem)}"


def problem_text(problem: Problem) -> str:
    """Explains one ``conf.yaml`` finding in pt-BR, without its position."""
    args = dict(problem.args)
    args["keys_text"] = ", ".join(str(key) for key in args.get("keys", ()))
    args["value_text"] = repr(args.get("value", ""))
    template = PROBLEM_TEXTS.get(problem.code)
    try:
        return template.format(**args) if template else problem.message
    except (KeyError, IndexError):
        return problem.message


def problem_place(problem: Problem) -> str:
    """Writes where a finding is, as ``linha 3, coluna 5 · save.a.location``."""
    parts = []
    if problem.line is not None:
        place = f"linha {problem.line}"
        if problem.column is not None:
            place += f", coluna {problem.column}"
        parts.append(place)
    if problem.dotted_path:
        parts.append(problem.dotted_path)
    return " · ".join(parts) or "arquivo"


def _translate_validation(text: str) -> str:
    """Returns the pt-BR text for a validation message."""
    for fragment, translation in _VALIDATION_TEXTS:
        if fragment in text:
            if fragment == "stale import folder":
                # The user has to delete it by hand, so say where it is.
                return f"{translation} Pasta: {text.rsplit(': ', 1)[-1]}"
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
        if report is not None and report.problems:
            return _limit(
                describe_problem(problem)
                for problem in report.problems
                if problem.is_error
            )
        lines = [str(error)]
        if report is not None:
            lines += list(report.errors)
        return _limit(lines)
    if isinstance(error, ConfigConflictError):
        return (
            "O conf.yaml foi alterado por outro programa depois de aberto aqui. "
            "Nada foi gravado.",
        )
    if isinstance(error, BackupNotFoundError):
        return ("Esse backup não existe mais. A lista foi atualizada.",)
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
