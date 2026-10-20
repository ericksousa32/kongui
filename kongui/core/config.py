"""Configuration service: the active ``conf.yaml``, the default one, and reading.

KonGUI does **not** edit, back up or validate ``conf.yaml`` files. As with
Konsave, the user edits ``~/.config/konsave/conf.yaml`` by hand. This service
only:

* says where the active file is and whether it exists;
* creates the default file the way Konsave does on its first run;
* reads a ``conf.yaml`` through the original ``read_konsave_config`` (which
  resolves the placeholders), so the operations that need to know where files
  go (the safety copies, the free-space estimates, the check that nothing is
  written outside the home) see exactly what Konsave will do.
"""

from __future__ import annotations

import os
import shutil
from importlib.resources import files
from pathlib import Path
from typing import Any, Dict, List, Optional

from kongui.core.engine import KonsaveEngine
from kongui.core.errors import ConfigError, ConfigMissingError, ValidationError
from kongui.core.lock import EXCLUSIVE

_DEFAULT_CONFIGS = {"kde": "conf_kde.yaml", "other": "conf_other.yaml"}

#: The two top-level keys Konsave reads; each holds groups of files.
GROUP_KINDS = ("save", "export")

#: ``{kind: {group: {"location": str, "entries": [str, ...]}}}``.
Groups = Dict[str, Dict[str, Dict[str, Any]]]


def _plain_groups(resolved: Any) -> Groups:
    """Keeps the ``save`` and ``export`` groups of a resolved configuration.

    This is not a validation: it only refuses the shapes the original code
    would crash on when it walks the groups (no ``location``, ``entries`` that
    is not a list), so the callers can rely on the structure. An empty
    ``entries:`` counts as an empty list.

    Args:
        resolved: Output of ``read_konsave_config``.

    Returns:
        Groups: The groups, with plain ``location`` and ``entries``.

    Raises:
        ConfigError: If the structure cannot be walked.
    """
    if not isinstance(resolved, dict):
        raise ConfigError("the configuration is not a mapping")
    groups: Groups = {}
    for kind in GROUP_KINDS:
        section = resolved.get(kind)
        if section is None:
            groups[kind] = {}
            continue
        if not isinstance(section, dict):
            raise ConfigError(
                "the configuration cannot be used",
                (f"'{kind}' must hold groups of files",),
            )
        kept: Dict[str, Dict[str, Any]] = {}
        for name, body in section.items():
            location = body.get("location") if isinstance(body, dict) else None
            entries = body.get("entries") if isinstance(body, dict) else None
            if not isinstance(location, str):
                raise ConfigError(
                    "the configuration cannot be used",
                    (f"{kind}.{name}: missing 'location'",),
                )
            if entries is None:
                entries = []
            if not isinstance(entries, list):
                raise ConfigError(
                    "the configuration cannot be used",
                    (f"{kind}.{name}: 'entries' must be a list",),
                )
            kept[str(name)] = {"location": location, "entries": list(entries)}
        groups[kind] = kept
    return groups


class ConfigService:
    """Finds, bootstraps and reads ``conf.yaml`` files (never writes them)."""

    #: Largest configuration file that is read (also the limit for the
    #: ``conf.yaml`` inside a ``.knsv``).
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
        source = self._template_path(kind, desktop)
        with self._engine.lock.hold(EXCLUSIVE, "ensure_default_config"):
            if not self.exists():  # another process may have created it meanwhile
                self._engine.ensure_runtime_dirs()
                shutil.copy(source, self.config_path)
        return self.config_path

    @staticmethod
    def _template_path(kind: Optional[str], desktop: Optional[str]) -> str:
        """Picks the packaged template the original bootstrap would copy."""
        if kind is None:
            if desktop is None:
                desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
            kind = "kde" if desktop == "KDE" else "other"
        if kind not in _DEFAULT_CONFIGS:
            raise ValidationError(f"unknown configuration template: {kind!r}")
        return str(files("konsave") / _DEFAULT_CONFIGS[kind])

    def resolve(self, path: Optional[Path] = None) -> Groups:
        """Reads a configuration the way Konsave does.

        The original ``read_konsave_config`` reads the file and resolves the
        placeholders (``$HOME``, ``$CONFIG_DIR``…); nothing else is checked.

        Args:
            path: File to read; defaults to the active configuration.

        Returns:
            Groups: The ``save`` and ``export`` groups, placeholders resolved.

        Raises:
            ConfigMissingError: If the file does not exist.
            ConfigError: If it is too large, unreadable, or Konsave cannot read
                it.
        """
        target = Path(path) if path is not None else self.config_path
        try:
            if not target.is_file():
                raise ConfigMissingError(f"configuration not found: {target}")
            size = target.stat().st_size
        except OSError as error:
            raise ConfigError("cannot read the configuration", (str(error),)) from error
        if size > self.MAX_CONFIG_BYTES:
            raise ConfigError(
                "the configuration file is too large",
                (f"{size} bytes (limit {self.MAX_CONFIG_BYTES})",),
            )
        call = self._engine.call("read_konsave_config", str(target))
        if call.failed:
            reasons: List[str] = list(call.error_messages) or ["unknown error"]
            raise ConfigError("Konsave could not read the configuration", reasons)
        return _plain_groups(call.returned)
