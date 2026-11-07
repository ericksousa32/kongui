"""Removes the parts of PySide6 that KonGUI does not use, then checks the rest.

    python3 trim.py SITE_PACKAGES

KonGUI only imports QtCore, QtGui, QtWidgets and QtSvg. PySide6-Essentials also
ships QML / Quick, Designer, SQL, the test library, developer tools, type stubs
and headers: about two thirds of its size. This removes them by explicit lists
(nothing is guessed), keeping the platform plugins a desktop needs (Wayland,
X11) plus ``offscreen`` and ``minimal`` for headless checks.

The check: every remaining shared object is run through ``ldd`` (with Qt's own
``lib`` folder on the search path) before and after. A library that only goes
missing *after* trimming means something still needed was removed, and the
script fails. Libraries missing before as well are expected from the host
(for example ``libxcb-cursor.so.0`` for X11) and are only listed.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, Set

#: Qt libraries (``Qt/lib/libQt6<name>.so*``) that are removed, by name prefix.
REMOVED_LIBRARIES = (
    "Concurrent",
    "Designer",
    "EglFS",
    "EglFs",
    "Help",
    "Labs",
    "Lottie",
    "OpenGLWidgets",
    "PrintSupport",
    "Qml",
    "Quick",
    "Sql",
    "SvgWidgets",
    "Test",
    "UiTools",
    "WaylandCompositor",
    "WaylandEglCompositor",
    "Xml",
)

#: Python modules of PySide6 that are kept (``<name>.abi3.so``); the rest go.
KEPT_MODULES = ("QtCore", "QtGui", "QtWidgets", "QtSvg")

#: Plugin folders removed whole.
REMOVED_PLUGIN_FOLDERS = (
    "designer",
    "egldeviceintegrations",
    "networkinformation",
    "printsupport",
    "qmltooling",
    "sqldrivers",
    "tls",
    "vectorimageformats",
    "wayland-graphics-integration-server",
)

#: Platform plugins kept (``plugins/platforms/libq<name>.so``).
KEPT_PLATFORMS = ("wayland", "xcb", "offscreen", "minimal")

#: Single plugins removed.
REMOVED_PLUGINS = (
    "platforminputcontexts/libqtvirtualkeyboardplugin.so",
    "imageformats/libqpdf.so",
)

#: Folders and files (glob patterns) of the PySide6 package that are only for
#: developers, or only for the removed modules.
REMOVED_PATHS = (
    "libpyside6qml.abi3.so*",
    "Qt/qml",
    "Qt/libexec",
    "Qt/metatypes",
    "include",
    "doc",
    "glue",
    "typesystems",
    "scripts",
    "assistant",
    "designer",
    "linguist",
    "lrelease",
    "lupdate",
    "qmlformat",
    "qmllint",
    "qmlls",
    "qmltyperegistrar",
    "rcc",
    "uic",
)

#: Translation families kept (``Qt/translations/<family>_<lang>.qm``).
KEPT_TRANSLATIONS = ("qtbase",)


def shared_objects(root: Path) -> Iterable[Path]:
    """Every ELF shared object under ``root`` (no symbolic links)."""
    for path in sorted(root.rglob("*.so*")):
        if path.is_file() and not path.is_symlink():
            with open(path, "rb") as handle:
                if handle.read(4) == b"\x7fELF":
                    yield path


def missing_libraries(root: Path, qt_lib: Path) -> Dict[str, Set[str]]:
    """``{shared object: {library not found}}`` for everything under ``root``."""
    env = dict(os.environ, LD_LIBRARY_PATH=str(qt_lib))
    found: Dict[str, Set[str]] = {}
    for path in shared_objects(root):
        result = subprocess.run(
            ["ldd", str(path)], capture_output=True, text=True, env=env, check=False
        )
        gone = set(re.findall(r"^\s*(\S+) => not found", result.stdout, re.M))
        if gone:
            found[str(path.relative_to(root))] = gone
    return found


def remove(path: Path) -> int:
    """Deletes a file or folder; returns the bytes freed."""
    if path.is_symlink() or path.is_file():
        size = path.lstat().st_size
        path.unlink()
        return size
    if path.is_dir():
        size = sum(p.lstat().st_size for p in path.rglob("*"))
        shutil.rmtree(path)
        return size
    return 0


def trim(site_packages: Path) -> int:
    """Trims PySide6 in place; returns the bytes freed."""
    pyside = site_packages / "PySide6"
    qt = pyside / "Qt"
    freed = 0
    for entry in sorted((qt / "lib").iterdir()):
        name = entry.name
        if name.startswith("libQt6") and name[6:].startswith(REMOVED_LIBRARIES):
            freed += remove(entry)
    for entry in sorted(pyside.glob("*.abi3.so")):
        if entry.name.split(".", 1)[0] not in KEPT_MODULES:
            freed += remove(entry)
    for entry in sorted(pyside.rglob("*.pyi")):
        freed += remove(entry)
    for folder in REMOVED_PLUGIN_FOLDERS:
        freed += remove(qt / "plugins" / folder)
    for entry in sorted((qt / "plugins" / "platforms").glob("libq*.so")):
        if entry.stem[4:] not in KEPT_PLATFORMS:
            freed += remove(entry)
    for plugin in REMOVED_PLUGINS:
        freed += remove(qt / "plugins" / plugin)
    for pattern in REMOVED_PATHS:
        for match in sorted(pyside.glob(pattern)):
            freed += remove(match)
    for entry in sorted((qt / "translations").glob("*.qm")):
        if entry.name.split("_", 1)[0] not in KEPT_TRANSLATIONS:
            freed += remove(entry)
    return freed


def main(argv) -> int:
    """Trims, checks and reports."""
    site_packages = Path(argv[1]).resolve()
    qt_lib = site_packages / "PySide6" / "Qt" / "lib"
    before = missing_libraries(site_packages, qt_lib)
    host = set().union(*before.values()) if before else set()
    freed = trim(site_packages)
    after = missing_libraries(site_packages, qt_lib)
    broken = {path: sorted(gone - host) for path, gone in after.items() if gone - host}
    print(f"trim: freed {freed / 1048576:.0f} MiB")
    still = set().union(*after.values()) & host if after else set()
    if still:
        print("trim: expected from the host: " + ", ".join(sorted(still)))
    if broken:
        for path, gone in sorted(broken.items()):
            print(
                f"trim: ERROR {path} needs removed {', '.join(gone)}", file=sys.stderr
            )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv))
