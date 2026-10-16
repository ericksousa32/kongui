"""Configuration service: the active ``conf.yaml`` and its validation."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from kongui.core.engine import KonsaveEngine
from kongui.core.errors import (
    ConfigMissingError,
    ConfigValidationError,
    ValidationError,
)
from kongui.core.results import OperationResult, ValidationReport

_TOP_LEVEL_KEYS = ("save", "export")
_SECTION_KEYS = {"location", "entries"}
_BARE_PLACEHOLDER = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")
_FUNCTION_PLACEHOLDER = re.compile(r"\$\{(\w+)=")
_UNRESOLVED = re.compile(r"\$\{|\$[A-Z][A-Z_]+")
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
        result is checked again.

        Args:
            path: File to validate; defaults to the active configuration.

        Returns:
            ValidationReport: Errors, warnings and resolved configuration.
        """
        target = Path(path) if path is not None else self.config_path
        try:
            if not target.is_file():
                return ValidationReport(errors=(f"configuration not found: {target}",))
            if target.stat().st_size > self.MAX_CONFIG_BYTES:
                return ValidationReport(errors=("configuration file is too large",))
            text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            return ValidationReport(errors=(f"cannot read configuration: {error}",))
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as error:
            first_line = str(error).strip().splitlines()[0]
            return ValidationReport(errors=(f"invalid YAML: {first_line}",))
        warnings: List[str] = []
        errors = self._check_structure(data, warnings)
        if errors:
            return ValidationReport(tuple(errors), tuple(warnings))
        call = self._engine.call("read_konsave_config", str(target))
        resolved = call.returned
        if call.failed or not isinstance(resolved, dict):
            detail = "; ".join(call.error_messages) or "unknown error"
            return ValidationReport(
                (f"Konsave could not resolve the configuration: {detail}",),
                tuple(warnings),
            )
        errors = self._check_resolved(resolved, warnings)
        return ValidationReport(tuple(errors), tuple(warnings), resolved)

    def write_text(self, text: str) -> OperationResult:
        """Validates and atomically replaces the active ``conf.yaml``.

        The previous file, if any, is kept next to it as
        ``conf.yaml.bak-<timestamp>``.

        Args:
            text: New ``conf.yaml`` contents.

        Returns:
            OperationResult: Result with the written path.

        Raises:
            ConfigValidationError: If the text is not a valid configuration.
        """
        report = self.validate_text(text)
        if not report.ok:
            raise ConfigValidationError(
                "refusing to write an invalid configuration", report
            )
        self._engine.ensure_runtime_dirs()
        target = self.config_path
        backup: Optional[Path] = None
        if target.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            backup = target.with_name(f"{target.name}.bak-{stamp}")
            shutil.copy2(target, backup)
        handle, temp_name = tempfile.mkstemp(
            dir=target.parent, prefix=".conf.", suffix=".tmp"
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as temp_file:
                temp_file.write(text)
            os.replace(temp_name, target)
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

    def _check_structure(self, data: Any, warnings: List[str]) -> List[str]:
        """Checks the raw YAML structure.

        Args:
            data: Output of ``yaml.safe_load``.
            warnings: List that receives non-blocking observations.

        Returns:
            List[str]: Blocking errors.
        """
        if not isinstance(data, dict):
            return ["the root must be a mapping with 'save' and 'export'"]
        errors: List[str] = []
        for key in _TOP_LEVEL_KEYS:
            if key not in data:
                errors.append(f"missing required top-level key '{key}'")
                continue
            sections = data[key]
            if not isinstance(sections, dict):
                errors.append(
                    f"'{key}' must be a mapping of sections (an empty '{key}:' "
                    f"makes Konsave crash; write '{key}: {{}}' instead)"
                )
                continue
            for name, section in sections.items():
                errors.extend(self._check_section(key, name, section, warnings))
        for key, value in data.items():
            if key in _TOP_LEVEL_KEYS:
                continue
            # parse_keywords/parse_functions iterate over *every* top-level key
            # as if it were a group of sections.
            if isinstance(value, dict):
                warnings.append(
                    f"unknown top-level key '{key}' is ignored by save/export"
                )
            else:
                errors.append(
                    f"unknown top-level key '{key}' must be a mapping of sections "
                    "(Konsave iterates over it and would crash)"
                )
        return errors

    def _check_section(
        self, kind: str, name: object, section: object, warnings: List[str]
    ) -> List[str]:
        """Checks one ``save``/``export`` section.

        Args:
            kind: ``"save"`` or ``"export"``.
            name: Section name (a key of the YAML mapping).
            section: Section contents.
            warnings: List that receives non-blocking observations.

        Returns:
            List[str]: Blocking errors.
        """
        label = f"{kind}.{name}"
        if not _is_safe_component(name):
            return [f"{label}: section names must be plain folder names"]
        if not isinstance(section, dict):
            return [f"{label}: must be a mapping with 'location' and 'entries'"]
        errors: List[str] = []
        unknown = [str(key) for key in section if key not in _SECTION_KEYS]
        if unknown:
            warnings.append(f"{label}: unknown keys are ignored: {', '.join(unknown)}")
        location = section.get("location")
        if not isinstance(location, str) or not location.strip():
            errors.append(f"{label}: 'location' must be a non-empty string")
        else:
            errors.extend(self._check_placeholders(label, location, warnings))
        if "entries" not in section:
            errors.append(f"{label}: missing 'entries' (use an empty list if none)")
            return errors
        entries = section["entries"]
        if entries is None:
            return errors
        if not isinstance(entries, list):
            errors.append(f"{label}: 'entries' must be a list")
            return errors
        seen = set()
        for entry in entries:
            if not _is_safe_component(entry):
                errors.append(
                    f"{label}: entry {entry!r} must be a single file or folder name "
                    "(nested paths abort the whole save in Konsave)"
                )
            elif entry in seen:
                warnings.append(f"{label}: duplicated entry {entry!r}")
            seen.add(entry)
        return errors

    def _check_placeholders(
        self, label: str, location: str, warnings: List[str]
    ) -> List[str]:
        """Rejects placeholders the original ``parse`` does not implement.

        Args:
            label: Section label for messages.
            location: Raw ``location`` text.
            warnings: List that receives non-blocking observations.

        Returns:
            List[str]: Blocking errors.
        """
        tokens = self._engine.parse.tokens
        keywords = set(tokens["keywords"]["dict"])
        functions = set(tokens["functions"]["dict"])
        errors = []
        for found in _BARE_PLACEHOLDER.findall(location):
            if found not in keywords:
                errors.append(
                    f"{label}: unsupported placeholder ${found} "
                    f"(supported: {', '.join('$' + key for key in sorted(keywords))})"
                )
        calls = _FUNCTION_PLACEHOLDER.findall(location)
        for found in calls:
            if found not in functions:
                errors.append(f"{label}: unsupported function ${{{found}=...}}")
        if len(calls) > 1:
            warnings.append(
                f"{label}: only the last function placeholder takes effect in "
                "the original parser"
            )
        return errors

    def _check_resolved(
        self, resolved: Dict[str, Any], warnings: List[str]
    ) -> List[str]:
        """Checks locations after the original code resolved the placeholders.

        Args:
            resolved: Output of the original ``read_konsave_config``.
            warnings: List that receives non-blocking observations.

        Returns:
            List[str]: Blocking errors.
        """
        errors = []
        for kind in _TOP_LEVEL_KEYS:
            for name, section in resolved.get(kind, {}).items():
                label = f"{kind}.{name}"
                location = section["location"]
                if _UNRESOLVED.search(location):
                    errors.append(
                        f"{label}: placeholder was not resolved ({location}); with "
                        "no matching folder Konsave would use this text as a "
                        "relative path"
                    )
                elif not os.path.isabs(location):
                    errors.append(f"{label}: location is not absolute: {location}")
                elif not os.path.isdir(location):
                    warnings.append(
                        f"{label}: '{location}' does not exist; its entries "
                        "are skipped silently"
                    )
        return errors
