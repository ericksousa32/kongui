"""Configuration service: the active ``conf.yaml`` and its validation."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from dataclasses import replace
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from kongui.core.engine import KonsaveEngine
from kongui.core.errors import (
    BackupNotFoundError,
    ConfigConflictError,
    ConfigMissingError,
    ConfigValidationError,
    ValidationError,
)
from kongui.core.results import (
    BackupInfo,
    OperationResult,
    PathStep,
    Problem,
    ValidationReport,
)
from kongui.core.yamlmap import compose, locate, mapping_pairs

_TOP_LEVEL_KEYS = ("save", "export")
_SECTION_KEYS = {"location", "entries"}
_BARE_PLACEHOLDER = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")
_FUNCTION_PLACEHOLDER = re.compile(r"\$\{(\w+)=")
_UNRESOLVED = re.compile(r"\$\{|\$[A-Z][A-Z_]+")
_ANY: Any = object()
BACKUP_MARK = ".bak-"
BACKUP_STAMP = "%Y%m%d-%H%M%S-%f"
_DEFAULT_CONFIGS = {"kde": "conf_kde.yaml", "other": "conf_other.yaml"}


def _is_safe_component(value: object) -> bool:
    """Tells whether a value is a single, relative path component.

    Args:
        value: Candidate entry or section name.

    Returns:
        bool: ``True`` if safe to join to a folder.
    """
    return (
        isinstance(value, str)
        and bool(value)
        and value not in {".", ".."}
        and "/" not in value
        and "\0" not in value
    )


def _backup_time(stamp: str, path: Path) -> datetime:
    """Reads the date of a backup from its name (else from the file)."""
    try:
        return datetime.strptime(stamp[: len("20000101-000000-000000")], BACKUP_STAMP)
    except ValueError:
        return datetime.fromtimestamp(path.stat().st_mtime)


def _problem(  # pylint: disable=too-many-arguments
    severity: str,
    code: str,
    path: Tuple[PathStep, ...],
    message: str,
    label: str = "",
    **args: Any,
) -> Problem:
    """Builds a :class:`Problem` (position is filled in later)."""
    return Problem(severity, code, tuple(path), message, label, args=args)


def _error(
    code: str, path: Tuple[PathStep, ...], message: str, label: str = "", **args: Any
) -> Problem:
    """Builds a blocking :class:`Problem`."""
    return _problem("error", code, path, message, label, **args)


def _warning(
    code: str, path: Tuple[PathStep, ...], message: str, label: str = "", **args: Any
) -> Problem:
    """Builds a non-blocking :class:`Problem`."""
    return _problem("warning", code, path, message, label, **args)


def group_not_mapping(kind: str, name: object) -> Problem:
    """Problem for a group whose body is not a mapping."""
    return _error(
        "group-not-mapping",
        (kind, str(name)),
        "must be a mapping with 'location' and 'entries'",
        f"{kind}.{name}",
    )


def entries_not_list(kind: str, name: object) -> Problem:
    """Problem for a group whose ``entries`` is not a list."""
    return _error(
        "entries-not-list",
        (kind, str(name), "entries"),
        "'entries' must be a list",
        f"{kind}.{name}",
    )


def _yaml_problem(error: yaml.YAMLError) -> Problem:
    """Turns a PyYAML error into a located problem."""
    first_line = str(error).strip().splitlines()[0]
    problem = _error(
        "yaml-syntax",
        (),
        f"invalid YAML: {first_line}",
        problem=getattr(error, "problem", None) or first_line,
        context=getattr(error, "context", None) or "",
    )
    mark = getattr(error, "problem_mark", None)
    if mark is not None:
        problem = replace(problem, line=mark.line + 1, column=mark.column + 1)
    else:
        problem = replace(problem, line=1, column=1)
    return problem


def _check_duplicates(root: Optional[yaml.Node]) -> List[Problem]:
    """Finds repeated keys, which ``yaml.safe_load`` silently collapses.

    Only the levels Konsave reads are inspected: the root, the ``save``/
    ``export`` mappings and the groups.
    """
    found: List[Problem] = []

    def walk(node: yaml.Node, path: Tuple[str, ...], depth: int) -> None:
        seen = set()
        for key_node, value_node in mapping_pairs(node):
            if not isinstance(key_node, yaml.ScalarNode):
                continue
            key = key_node.value
            if key in seen:
                label = ".".join(path) if path else ""
                found.append(
                    replace(
                        _error(
                            "duplicate-key",
                            path + (key,),
                            f"duplicate key {key!r}; Konsave would keep only the "
                            "last one",
                            label,
                            key=key,
                        ),
                        line=key_node.start_mark.line + 1,
                        column=key_node.start_mark.column + 1,
                    )
                )
            seen.add(key)
            if depth < 2:
                walk(value_node, path + (key,), depth + 1)

    if root is not None:
        walk(root, (), 0)
    return found


def _report(
    problems: List[Problem],
    root: Optional[yaml.Node] = None,
    resolved: Optional[Dict[str, Any]] = None,
) -> ValidationReport:
    """Builds the report, locating every problem that has no position yet."""
    located = []
    for problem in problems:
        if problem.line is None:
            line, column = locate(root, problem.path)
            problem = replace(problem, line=line, column=column)
        located.append(problem)
    return ValidationReport(
        tuple(p.text for p in located if p.is_error),
        tuple(p.text for p in located if not p.is_error),
        resolved,
        tuple(located),
    )


class ConfigService:
    """Reads, validates, bootstraps and writes the active ``conf.yaml``.

    Reuses the original ``read_konsave_config`` (and through it ``parse``) to
    resolve placeholders, so validation reflects what Konsave would really do.
    """

    #: Maximum accepted size of a configuration file.
    MAX_CONFIG_BYTES = 1024 * 1024

    def __init__(self, engine: KonsaveEngine) -> None:
        """Creates the service.

        Args:
            engine: The engine that owns the home directory in use.
        """
        self._engine = engine

    @property
    def config_path(self) -> Path:
        """Path of the active ``conf.yaml``."""
        return self._engine.config_file

    def exists(self) -> bool:
        """Tells whether the active configuration file exists.

        Returns:
            bool: ``True`` if ``conf.yaml`` is a regular file.
        """
        return self.config_path.is_file()

    def ensure_default_config(
        self, kind: Optional[str] = None, *, desktop: Optional[str] = None
    ) -> Path:
        """Creates the default ``conf.yaml`` if there is none.

        Replicates the bootstrap of ``konsave.__main__.main`` (which cannot be
        called without parsing ``sys.argv``): ``conf_kde.yaml`` when
        ``XDG_CURRENT_DESKTOP`` equals ``KDE``, ``conf_other.yaml`` otherwise.
        An existing file is never touched.

        Args:
            kind: ``"kde"`` or ``"other"`` to force a template.
            desktop: Value to use instead of ``$XDG_CURRENT_DESKTOP``.

        Returns:
            Path: Path of the configuration file.

        Raises:
            ValidationError: If ``kind`` is unknown.
        """
        if self.exists():
            return self.config_path
        if kind is None:
            if desktop is None:
                desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
            kind = "kde" if desktop == "KDE" else "other"
        if kind not in _DEFAULT_CONFIGS:
            raise ValidationError(f"unknown configuration template: {kind!r}")
        source = str(files("konsave") / _DEFAULT_CONFIGS[kind])
        self._engine.ensure_runtime_dirs()
        shutil.copy(source, self.config_path)
        return self.config_path

    def read_text(self, path: Optional[Path] = None) -> str:
        """Reads a configuration file as text.

        Args:
            path: File to read; defaults to the active configuration.

        Returns:
            str: File contents.

        Raises:
            ConfigMissingError: If the file does not exist.
        """
        target = Path(path) if path is not None else self.config_path
        try:
            return target.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise ConfigMissingError(f"configuration not found: {target}") from error

    def placeholders(self) -> Dict[str, Tuple[str, ...]]:
        """Lists the placeholders the original ``parse`` module supports.

        Returns:
            Dict[str, Tuple[str, ...]]: ``keywords`` (``$NAME``) and
            ``functions`` (``${NAME='text'}``).
        """
        tokens = self._engine.parse.tokens
        symbol = self._engine.parse.TOKEN_SYMBOL
        return {
            "keywords": tuple(symbol + key for key in tokens["keywords"]["dict"]),
            "functions": tuple(tokens["functions"]["dict"]),
        }

    def read_resolved(self, path: Optional[Path] = None) -> Dict[str, Any]:
        """Returns the configuration with placeholders resolved.

        Args:
            path: File to read; defaults to the active configuration.

        Returns:
            Dict[str, Any]: Output of the original ``read_konsave_config``.

        Raises:
            ConfigValidationError: If the file is invalid.
        """
        report = self.validate(path)
        if not report.ok or report.resolved is None:
            raise ConfigValidationError("invalid configuration", report)
        return report.resolved

    def validate_text(self, text: str) -> ValidationReport:
        """Validates configuration text without touching the active file.

        Args:
            text: Candidate ``conf.yaml`` contents.

        Returns:
            ValidationReport: Errors, warnings and resolved configuration.
        """
        with tempfile.TemporaryDirectory(prefix="kongui-conf-") as folder:
            candidate = Path(folder) / "conf.yaml"
            candidate.write_text(text, encoding="utf-8")
            return self.validate(candidate)

    def validate(  # pylint: disable=too-many-return-statements
        self, path: Optional[Path] = None
    ) -> ValidationReport:
        """Validates a configuration file.

        Static checks come first (YAML, structure, entries, placeholders), then
        the original ``read_konsave_config`` resolves the placeholders and the
        result is checked again. Every finding is also returned as a
        :class:`~kongui.core.results.Problem` located in the text.

        Args:
            path: File to validate; defaults to the active configuration.

        Returns:
            ValidationReport: Errors, warnings and resolved configuration.
        """
        target = Path(path) if path is not None else self.config_path
        try:
            if not target.is_file():
                return _report(
                    [_error("file-missing", (), f"configuration not found: {target}")]
                )
            if target.stat().st_size > self.MAX_CONFIG_BYTES:
                return _report(
                    [_error("file-too-large", (), "configuration file is too large")]
                )
            text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            return _report(
                [
                    _error(
                        "file-unreadable",
                        (),
                        f"cannot read configuration: {error}",
                        detail=str(error),
                    )
                ]
            )
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as error:
            return _report([_yaml_problem(error)])
        root = compose(text)
        problems: List[Problem] = []
        problems += _check_duplicates(root)
        problems += self._check_structure(data)
        if not any(p.is_error for p in problems):
            call = self._engine.call("read_konsave_config", str(target))
            resolved = call.returned
            if call.failed or not isinstance(resolved, dict):
                detail = "; ".join(call.error_messages) or "unknown error"
                problems.append(
                    _error(
                        "konsave-failed",
                        (),
                        f"Konsave could not resolve the configuration: {detail}",
                        detail=detail,
                    )
                )
                return _report(problems, root)
            problems += self._check_resolved(resolved)
            return _report(problems, root, resolved)
        return _report(problems, root)

    def digest(self) -> Optional[str]:
        """Fingerprint of the active file, to detect outside changes.

        Returns:
            Optional[str]: SHA-256 of the contents, or ``None`` if missing.
        """
        try:
            return hashlib.sha256(self.config_path.read_bytes()).hexdigest()
        except OSError:
            return None

    def write_text(
        self, text: str, *, expected_digest: Optional[str] = _ANY
    ) -> OperationResult:
        """Validates and atomically replaces the active ``conf.yaml``.

        The previous file, if any, is kept next to it as
        ``conf.yaml.bak-<timestamp>``. A symbolic link is followed (the file it
        points to is replaced, the link stays) and the permissions of the old
        file are kept. Nothing is written if validation fails.

        Args:
            text: New ``conf.yaml`` contents.
            expected_digest: Result of :meth:`digest` when the text was loaded
                for editing; ``None`` means "the file did not exist". If given
                and the file changed since, nothing is written.

        Returns:
            OperationResult: Result with the written path.

        Raises:
            ConfigValidationError: If the text is not a valid configuration.
            ConfigConflictError: If the file changed after it was loaded.
        """
        report = self.validate_text(text)
        if not report.ok:
            raise ConfigValidationError(
                "refusing to write an invalid configuration", report
            )
        if expected_digest is not _ANY and self.digest() != expected_digest:
            raise ConfigConflictError("conf.yaml changed on disk after it was loaded")
        self._engine.ensure_runtime_dirs()
        target = self.config_path
        real = Path(os.path.realpath(target))
        backup: Optional[Path] = None
        if real.exists():
            backup = self._new_backup_path()
            shutil.copy2(real, backup)
        handle, temp_name = tempfile.mkstemp(
            dir=real.parent, prefix=".conf.", suffix=".tmp"
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="") as temp_file:
                temp_file.write(text)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            if real.exists():
                shutil.copymode(real, temp_name)
            else:
                os.chmod(temp_name, 0o644)
            os.replace(temp_name, real)
        except BaseException:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise
        message = "configuration saved"
        if backup is not None:
            message += f" (previous version kept as {backup.name})"
        return OperationResult(
            operation="write_config",
            ok=True,
            message=message,
            warnings=report.warnings,
            path=target,
        )

    def _new_backup_path(self) -> Path:
        """Picks an unused backup name next to the active file."""
        target = self.config_path
        stamp = datetime.now().strftime(BACKUP_STAMP)
        path = target.with_name(f"{target.name}{BACKUP_MARK}{stamp}")
        counter = 1
        while path.exists():
            path = target.with_name(f"{target.name}{BACKUP_MARK}{stamp}-{counter}")
            counter += 1
        return path

    def list_backups(self) -> Tuple[BackupInfo, ...]:
        """Lists the saved previous versions, newest first.

        Returns:
            Tuple[BackupInfo, ...]: One entry per ``conf.yaml.bak-*`` file.
        """
        target = self.config_path
        found = []
        try:
            names = os.listdir(target.parent)
        except OSError:
            return ()
        prefix = f"{target.name}{BACKUP_MARK}"
        for name in names:
            path = target.parent / name
            if not name.startswith(prefix) or not path.is_file():
                continue
            try:
                size = path.stat().st_size
                created = _backup_time(name[len(prefix) :], path)
            except OSError:
                continue
            found.append(BackupInfo(name, path, created, size))
        found.sort(key=lambda info: (info.created, info.name), reverse=True)
        return tuple(found)

    def backup_path(self, name: str) -> Path:
        """Resolves a backup name to its file.

        Args:
            name: File name from :meth:`list_backups`.

        Returns:
            Path: The backup file.

        Raises:
            BackupNotFoundError: If there is no such backup (names with
                folders in them are never accepted).
        """
        for info in self.list_backups():
            if info.name == name:
                return info.path
        raise BackupNotFoundError(f"backup not found: {name}")

    def read_backup(self, name: str) -> str:
        """Reads a backup as text.

        Args:
            name: File name from :meth:`list_backups`.

        Returns:
            str: Its contents.

        Raises:
            BackupNotFoundError: If there is no such backup.
            ValidationError: If it is not readable text.
        """
        path = self.backup_path(name)
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise ValidationError(f"cannot read backup {name}: {error}") from error

    def restore_backup(
        self, name: str, *, expected_digest: Optional[str] = _ANY
    ) -> OperationResult:
        """Puts a backup back as the active ``conf.yaml``.

        The backup is validated like any other text, and the file it replaces
        is itself backed up first, so a restore can be undone.

        Args:
            name: File name from :meth:`list_backups`.
            expected_digest: See :meth:`write_text`.

        Returns:
            OperationResult: Result of the write.

        Raises:
            BackupNotFoundError: If there is no such backup.
            ConfigValidationError: If the backup is not a valid configuration.
            ConfigConflictError: If the active file changed since it was loaded.
        """
        result = self.write_text(
            self.read_backup(name), expected_digest=expected_digest
        )
        return replace(result, operation="restore_config", message=f"restored {name}")

    def _check_structure(self, data: Any) -> List[Problem]:
        """Checks the raw YAML structure.

        Args:
            data: Output of ``yaml.safe_load``.

        Returns:
            List[Problem]: Findings, blocking or not.
        """
        if not isinstance(data, dict):
            return [
                _error(
                    "root-not-mapping",
                    (),
                    "the root must be a mapping with 'save' and 'export'",
                )
            ]
        found: List[Problem] = []
        for key in _TOP_LEVEL_KEYS:
            if key not in data:
                found.append(
                    _error(
                        "missing-top-key",
                        (),
                        f"missing required top-level key '{key}'",
                        key=key,
                    )
                )
                continue
            sections = data[key]
            if not isinstance(sections, dict):
                found.append(
                    _error(
                        "section-not-mapping",
                        (key,),
                        f"'{key}' must be a mapping of sections (an empty '{key}:' "
                        f"makes Konsave crash; write '{key}: {{}}' instead)",
                        key=key,
                    )
                )
                continue
            for name, section in sections.items():
                found.extend(self._check_section(key, name, section))
        for key, value in data.items():
            if key in _TOP_LEVEL_KEYS:
                continue
            # parse_keywords/parse_functions iterate over *every* top-level key
            # as if it were a group of sections.
            if isinstance(value, dict):
                found.append(
                    _warning(
                        "unknown-top-mapping",
                        (str(key),),
                        f"unknown top-level key '{key}' is ignored by save/export",
                        key=str(key),
                    )
                )
            else:
                found.append(
                    _error(
                        "unknown-top-scalar",
                        (str(key),),
                        f"unknown top-level key '{key}' must be a mapping of "
                        "sections (Konsave iterates over it and would crash)",
                        key=str(key),
                    )
                )
        return found

    def _check_section(  # pylint: disable=too-many-return-statements
        self, kind: str, name: object, section: object
    ) -> List[Problem]:
        """Checks one ``save``/``export`` section.

        Args:
            kind: ``"save"`` or ``"export"``.
            name: Section name (a key of the YAML mapping).
            section: Section contents.

        Returns:
            List[Problem]: Findings, blocking or not.
        """
        label = f"{kind}.{name}"
        where = (kind, str(name))
        if not _is_safe_component(name):
            return [
                _error(
                    "group-name-invalid",
                    where,
                    "section names must be plain folder names",
                    label,
                    name=str(name),
                )
            ]
        if not isinstance(section, dict):
            return [group_not_mapping(kind, name)]
        found: List[Problem] = []
        unknown = [str(key) for key in section if key not in _SECTION_KEYS]
        if unknown:
            found.append(
                _warning(
                    "group-unknown-keys",
                    where,
                    f"unknown keys are ignored: {', '.join(unknown)}",
                    label,
                    keys=unknown,
                )
            )
        location = section.get("location")
        if not isinstance(location, str) or not location.strip():
            found.append(
                _error(
                    "location-invalid",
                    where + ("location",),
                    "'location' must be a non-empty string",
                    label,
                    missing="location" not in section,
                )
            )
        else:
            found.extend(self._check_placeholders(label, where, location))
        if "entries" not in section:
            found.append(
                _error(
                    "entries-missing",
                    where,
                    "missing 'entries' (use an empty list if none)",
                    label,
                )
            )
            return found
        entries = section["entries"]
        if entries is None:
            return found
        if not isinstance(entries, list):
            found.append(entries_not_list(kind, name))
            return found
        seen = set()
        for index, entry in enumerate(entries):
            at = where + ("entries", index)
            if not _is_safe_component(entry):
                found.append(
                    _error(
                        "entry-invalid",
                        at,
                        f"entry {entry!r} must be a single file or folder name "
                        "(nested paths abort the whole save in Konsave)",
                        label,
                        value=entry,
                    )
                )
            elif entry in seen:
                found.append(
                    _warning(
                        "entry-duplicate",
                        at,
                        f"duplicated entry {entry!r}",
                        label,
                        value=entry,
                    )
                )
            seen.add(entry)
        return found

    def _check_placeholders(
        self, label: str, where: Tuple[str, ...], location: str
    ) -> List[Problem]:
        """Rejects placeholders the original ``parse`` does not implement.

        Args:
            label: Section label for messages.
            where: Path of the section.
            location: Raw ``location`` text.

        Returns:
            List[Problem]: Findings, blocking or not.
        """
        tokens = self._engine.parse.tokens
        keywords = set(tokens["keywords"]["dict"])
        functions = set(tokens["functions"]["dict"])
        at = where + ("location",)
        found: List[Problem] = []
        for name in _BARE_PLACEHOLDER.findall(location):
            if name not in keywords:
                supported = ", ".join("$" + key for key in sorted(keywords))
                found.append(
                    _error(
                        "placeholder-unsupported",
                        at,
                        f"unsupported placeholder ${name} (supported: {supported})",
                        label,
                        name=name,
                        supported=supported,
                    )
                )
        calls = _FUNCTION_PLACEHOLDER.findall(location)
        for name in calls:
            if name not in functions:
                found.append(
                    _error(
                        "function-unsupported",
                        at,
                        f"unsupported function ${{{name}=...}}",
                        label,
                        name=name,
                        supported=", ".join(sorted(functions)),
                    )
                )
        if len(calls) > 1:
            found.append(
                _warning(
                    "function-multiple",
                    at,
                    "only the last function placeholder takes effect in the "
                    "original parser",
                    label,
                )
            )
        return found

    def _check_resolved(self, resolved: Dict[str, Any]) -> List[Problem]:
        """Checks locations after the original code resolved the placeholders.

        Args:
            resolved: Output of the original ``read_konsave_config``.

        Returns:
            List[Problem]: Findings, blocking or not.
        """
        found: List[Problem] = []
        for kind in _TOP_LEVEL_KEYS:
            for name, section in resolved.get(kind, {}).items():
                label = f"{kind}.{name}"
                at = (kind, str(name), "location")
                location = section["location"]
                if _UNRESOLVED.search(location):
                    found.append(
                        _error(
                            "location-unresolved",
                            at,
                            f"placeholder was not resolved ({location}); with no "
                            "matching folder Konsave would use this text as a "
                            "relative path",
                            label,
                            resolved=location,
                        )
                    )
                elif not os.path.isabs(location):
                    found.append(
                        _error(
                            "location-relative",
                            at,
                            f"location is not absolute: {location}",
                            label,
                            resolved=location,
                        )
                    )
                elif not os.path.isdir(location):
                    found.append(
                        _warning(
                            "location-missing-dir",
                            at,
                            f"'{location}' does not exist; its entries are "
                            "skipped silently",
                            label,
                            resolved=location,
                        )
                    )
        return found
