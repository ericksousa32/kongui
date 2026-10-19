"""Smoke test of an installed KonGUI: does the package start and exit cleanly?

Run it with the Python of the environment where KonGUI is installed (a wheel in a
clean virtual environment, for a release)::

    python tools/smoke_test.py --expect-version 0.1.0a1

It uses a temporary home folder and the demo data, so it never reads or writes the
real profiles, and it needs no display (Qt's ``offscreen`` platform). The checks:

1. the version of the package (and, with ``--expect-version``, that it is the one
   expected, which is how a release proves that the tag and the build agree);
2. the bundled ``konsave`` command starts and prints its version;
3. the translation catalogs were packaged and Qt can load them;
4. the main window opens in demo mode, shows its six pages and closes;
5. the process then **exits normally** (the caller checks the exit status, so a
   crash while the interpreter shuts down fails the run).

With ``--no-gui`` the translation and window checks are skipped (a machine without
PySide6 or without the system libraries Qt needs, such as a CI runner).

With ``--from-checkout`` the checks that only make sense for an installed package
(the version and the ``konsave`` command) are skipped, so the script can also be run
from a clone (the root of the clone is then put on ``sys.path``); the test suite
does that.

Exit status: 0 if everything passed, 1 if a check failed (each failure is printed).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Sequence


def check_version(expected: Optional[str], problems: List[str]) -> None:
    """Checks the version of the package."""
    import kongui

    print(f"kongui {kongui.__version__} ({kongui.version_label()})")
    if kongui.__version__ == kongui.UNKNOWN_VERSION:
        problems.append(
            "kongui is not installed as a package: its version is unknown "
            f"({kongui.UNKNOWN_VERSION})"
        )
    if expected is not None and kongui.__version__ != expected:
        problems.append(
            f"version {kongui.__version__!r} is not the expected {expected!r}"
        )


def check_konsave(home: str, problems: List[str]) -> None:
    """Checks that the bundled ``konsave`` command starts."""
    env = dict(os.environ, HOME=home)
    result = subprocess.run(
        [sys.executable, "-m", "konsave", "-v"],
        env=env,
        cwd=home,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    line = result.stdout.strip()
    print(f"konsave -v: {line or result.stderr.strip()[-200:]}")
    if result.returncode != 0 or not line.startswith("Konsave:"):
        problems.append(f"`konsave -v` failed (status {result.returncode})")


def check_translations(problems: List[str]) -> None:
    """Checks that the packaged catalogs exist and load."""
    from PySide6.QtCore import QTranslator

    import kongui.gui

    folder = Path(kongui.gui.__file__).parent / "translations"
    for language in ("en", "pt_BR"):
        path = folder / f"kongui_{language}.qm"
        translator = QTranslator()
        if not path.is_file() or not translator.load(str(path)):
            problems.append(f"translation catalog missing or unreadable: {path.name}")
        else:
            print(f"translations: {path.name} loaded")


def check_window(problems: List[str]) -> None:
    """Opens the main window in demo mode and closes it."""
    from PySide6.QtTest import QTest

    from kongui.gui.app import create_app
    from kongui.gui.backend import FakeBackend
    from kongui.gui.main_window import MainWindow
    from kongui.gui.state import AppSettings

    app = create_app(["kongui-smoke-test"])
    window = MainWindow(AppSettings(None), FakeBackend(latency=0))
    window.show()
    QTest.qWait(300)
    pages = list(window.pages)
    print(f"window: {len(pages)} pages ({', '.join(pages)})")
    if len(pages) != 6 or not window.isVisible():
        problems.append("the main window did not open with its six pages")
    window.close()
    window.deleteLater()
    QTest.qWait(50)
    app.processEvents()


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Runs the checks.

    Args:
        argv: Arguments (default ``sys.argv``).

    Returns:
        int: ``0`` if all checks passed, ``1`` otherwise.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--expect-version",
        help="the version the package must report (a release tag"
        " without its leading v)",
    )
    parser.add_argument(
        "--from-checkout",
        action="store_true",
        help="skip the checks that need an installed package (version, konsave)",
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="skip the translation and window checks (no PySide6 / Qt libraries)",
    )
    args = parser.parse_args(argv)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if args.from_checkout:
        # Python puts this script's folder (tools/) on the path, not the clone's
        # root; an installed package must NOT get this help, or the check is moot.
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    problems: List[str] = []
    with tempfile.TemporaryDirectory() as home:
        os.environ["HOME"] = home
        os.environ.pop("XDG_CONFIG_HOME", None)
        os.environ["XDG_CONFIG_HOME"] = str(Path(home) / ".config")
        if args.from_checkout:
            print("from a checkout: version and konsave checks skipped")
        else:
            check_version(args.expect_version, problems)
            check_konsave(home, problems)
        if args.no_gui:
            print("--no-gui: translation and window checks skipped")
        else:
            check_translations(problems)
            check_window(problems)
    for problem in problems:
        print(f"FAILED: {problem}", file=sys.stderr)
    print("smoke test: " + ("FAILED" if problems else "ok"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
