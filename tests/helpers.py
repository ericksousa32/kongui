"""Shared fixtures for the KonGUI tests."""

import contextlib
import logging
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import Callable, Mapping, Optional, Tuple
from unittest import mock

from kongui.core import ConfigService, KonsaveEngine, ProfileService
from kongui.core.engine import EngineCall


@contextlib.contextmanager
def no_logs(case: unittest.TestCase, level: str = "ERROR"):
    """Fails the test if anything is logged at ``level`` or above.

    ``unittest.TestCase.assertNoLogs`` only exists from Python 3.10 and the project
    supports 3.9.

    Args:
        case: The running test.
        level: Lowest level that counts.
    """
    records = []

    class Collector(logging.Handler):
        """Keeps every record it receives."""

        def emit(self, record):
            records.append(record)

    collector = Collector(level=logging.getLevelName(level))
    root = logging.getLogger()
    previous = root.level
    root.addHandler(collector)
    root.setLevel(min(previous or logging.WARNING, collector.level))
    try:
        yield
    finally:
        root.removeHandler(collector)
        root.setLevel(previous)
    case.assertEqual(
        [record.getMessage() for record in records], [], "unexpected log records"
    )


BASE_CONF = """---
save:
    configs:
        location: "$HOME/.config"
        entries:
            - kdeglobals
            - gtk-3.0
export:
    share_folder:
        location: "$HOME/.local/share"
        entries:
            - icons
...
"""


def install_conf(config, text: str) -> Path:
    """Writes the active ``conf.yaml`` the way a user would: by hand.

    KonGUI no longer writes ``conf.yaml`` files, so the tests put the text in
    place themselves.

    Args:
        config: The ``ConfigService`` whose active file is written.
        text: YAML text.

    Returns:
        Path: The file written.
    """
    # A real home already has ~/.cache and the profiles folder (every engine
    # call creates them if missing), as the removed ConfigService.write_text did.
    config._engine.ensure_runtime_dirs()  # pylint: disable=protected-access
    path = config.config_path
    path.write_text(text, encoding="utf-8")
    return path


def small_conf(location: str = "$HOME/.config", entries=("kdeglobals",)) -> str:
    """Builds a minimal configuration with one ``save`` section.

    Args:
        location: ``location`` of the section.
        entries: Entries of the section.

    Returns:
        str: YAML text.
    """
    items = "".join(f"            - {entry}\n" for entry in entries)
    return (
        "save:\n    configs:\n"
        f'        location: "{location}"\n'
        f"        entries:\n{items}"
        "export: {}\n"
    )


def non_root() -> int:
    """Euid provider that pretends to be an ordinary user.

    Returns:
        int: A non-zero user id.
    """
    return 1000


def as_root() -> int:
    """Euid provider that pretends to be root.

    Returns:
        int: Zero.
    """
    return 0


def really_root() -> bool:
    """Tells whether the test process itself runs as root.

    Returns:
        bool: ``True`` if the real effective user id is 0.
    """
    return hasattr(os, "geteuid") and os.geteuid() == 0


def write(path: Path, text: str = "x", mode: Optional[int] = None) -> Path:
    """Writes a text file, creating parent folders.

    Args:
        path: File to write.
        text: Contents.
        mode: Permission bits to set afterwards, if any.

    Returns:
        Path: The same path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mode is not None:
        path.chmod(mode)
    return path


def make_knsv(path: Path, members: Mapping[str, str]) -> Path:
    """Builds a ``.knsv`` (a ZIP) from a mapping of member name to text.

    Args:
        path: Archive to create.
        members: Member names and their text contents.

    Returns:
        Path: The same path.
    """
    with zipfile.ZipFile(path, "w") as handle:
        for name, text in members.items():
            handle.writestr(name, text)
    return path


def make_dist_info(folder: Path, version: str = "9.9.9") -> Path:
    """Creates fake package metadata so an uninstalled checkout has a version.

    Args:
        folder: Folder that will be added to ``PYTHONPATH``.
        version: Version to advertise.

    Returns:
        Path: ``folder``.
    """
    info = folder / f"konsave-{version}.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: Konsave\nVersion: {version}\n",
        encoding="utf-8",
    )
    return folder


def fake_call(
    name: str = "x",
    *,
    errors=(),
    stdout: str = "",
    stderr: str = "",
    returned=None,
    raised=None,
) -> EngineCall:
    """Builds an :class:`EngineCall` as the engine would return it.

    Args:
        name: Function name.
        errors: Logged error summaries.
        stdout: Captured stdout.
        stderr: Captured stderr.
        returned: Return value.
        raised: Escaped exception.

    Returns:
        EngineCall: The simulated observation.
    """
    return EngineCall(name, returned, stdout, stderr, tuple(errors), raised)


def patch_engine_call(
    engine: KonsaveEngine, fakes: Mapping[str, Callable[..., EngineCall]]
) -> mock.MagicMock:
    """Replaces ``engine.call`` for some functions, keeping the real one for the rest.

    ``read_konsave_config`` still goes to the original code unless listed, so
    configuration validation keeps working while ``save_profile`` and friends
    are simulated.

    Args:
        engine: Engine to patch (for the duration of the test).
        fakes: Function name to replacement. Each replacement receives the same
            arguments as :meth:`KonsaveEngine.call`.

    Returns:
        mock.MagicMock: The mock; ``call_args_list`` records every call.
    """
    real_call = engine.call

    def dispatch(name, *args, **kwargs):
        if name in fakes:
            return fakes[name](*args, **kwargs)
        return real_call(name, *args, **kwargs)

    patcher = mock.patch.object(engine, "call", side_effect=dispatch)
    patched = patcher.start()
    return patched


class IsolatedHomeTestCase(unittest.TestCase):
    """Base class: a private home, a private working folder, a fake ``$HOME``.

    The tests perform real file operations, so they refuse to run when the
    process is really root (the layer itself refuses root as well).

    Attributes:
        base: Temporary folder that holds everything the test creates.
        home: Home directory used by the engine under test.
        work: Current working directory and default output folder.
    """

    def setUp(self) -> None:
        """Creates the folders and isolates the process environment."""
        super().setUp()
        if really_root():
            self.skipTest("refusing to run file operations as root")
        folder = tempfile.mkdtemp(prefix="kongui-test-")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        self.base = Path(os.path.realpath(folder))
        self.home = self.base / "home"
        self.work = self.base / "work"
        self.home.mkdir()
        self.work.mkdir()
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("XDG_CURRENT_DESKTOP", None)
        previous = os.getcwd()
        os.chdir(self.work)
        self.addCleanup(os.chdir, previous)
        self.addCleanup(mock.patch.stopall)

    def new_engine(self, home: Optional[Path] = None) -> KonsaveEngine:
        """Creates an engine for ``home`` (default: the test home).

        Args:
            home: Home directory; created if missing.

        Returns:
            KonsaveEngine: The engine, pretending to run as a normal user.
        """
        target = Path(home) if home is not None else self.home
        target.mkdir(parents=True, exist_ok=True)
        return KonsaveEngine(target, euid_provider=non_root)

    def new_services(
        self, home: Optional[Path] = None, conf: Optional[str] = BASE_CONF
    ) -> Tuple[KonsaveEngine, ConfigService, ProfileService]:
        """Creates engine and services, optionally with an active ``conf.yaml``.

        Args:
            home: Home directory; defaults to the test home.
            conf: Text of the active configuration, or ``None`` for none.

        Returns:
            Tuple[KonsaveEngine, ConfigService, ProfileService]: The objects.
        """
        engine = self.new_engine(home)
        config = ConfigService(engine)
        if conf is not None:
            install_conf(config, conf)
        return engine, config, ProfileService(engine, config)

    def populate_live(self, home: Optional[Path] = None) -> Path:
        """Creates the live files that ``BASE_CONF`` saves and exports.

        Args:
            home: Home directory; defaults to the test home.

        Returns:
            Path: The home directory used.
        """
        target = Path(home) if home is not None else self.home
        write(target / ".config" / "kdeglobals", "kdeglobals-A")
        write(target / ".config" / "gtk-3.0" / "settings.ini", "[Settings]")
        write(target / ".local" / "share" / "icons" / "theme.txt", "theme-A")
        return target
