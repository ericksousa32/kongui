"""The smoke test script used to check an installed build (``tools/smoke_test.py``)."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.gui_helpers import HAVE_QT
from tests.test_packaging import make_dist

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "smoke_test.py"


def run_script(*args, dists=()):
    """Runs the script in a clean process with a temporary home.

    Args:
        *args: Command-line arguments.
        dists: ``(name, version)`` pairs of fake installed distributions.

    Returns:
        subprocess.CompletedProcess: The result.
    """
    with tempfile.TemporaryDirectory() as folder:
        site = Path(folder) / "site"
        site.mkdir()
        for name, version in dists:
            make_dist(site, name, version)
        env = dict(
            os.environ,
            HOME=folder,
            PYTHONPATH=os.pathsep.join([str(ROOT), str(site)]),
            QT_QPA_PLATFORM="offscreen",
        )
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=folder,
            env=env,
            capture_output=True,
            text=True,
            timeout=240,
            check=False,
        )


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class SmokeScriptTests(unittest.TestCase):
    """The checks pass on a healthy checkout and fail when they should."""

    def test_a_checkout_passes_and_the_process_exits_normally(self):
        result = run_script("--from-checkout")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("5 pages", result.stdout)
        self.assertIn("kongui_pt_BR.qm loaded", result.stdout)
        self.assertIn("icon: 9 files packaged", result.stdout)
        self.assertIn("icon: window icon set (8 sizes)", result.stdout)
        self.assertIn("smoke test: ok", result.stdout)

    def test_no_gui_skips_qt_and_still_checks_the_rest(self):
        result = run_script("--no-gui", dists=(("kongui", "0.1.0a1"),))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("translation and window checks skipped", result.stdout)
        self.assertNotIn("pages", result.stdout)
        self.assertIn("icon: 9 files packaged", result.stdout)
        self.assertIn("konsave -v: Konsave: 2.2.0+kongui", result.stdout)

    def test_an_uninstalled_checkout_fails_the_version_check(self):
        result = run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn("not installed as a package", result.stderr)

    def test_the_expected_version_must_match(self):
        dists = (("kongui", "0.1.0a1"),)
        wrong = run_script("--expect-version", "9.9.9", "--from-checkout", dists=dists)
        # --from-checkout skips the version check, so only the two options together
        # are a no-op; without it the mismatch is reported.
        self.assertEqual(wrong.returncode, 0, wrong.stderr)
        result = run_script("--expect-version", "9.9.9", dists=dists)
        self.assertEqual(result.returncode, 1)
        self.assertIn("is not the expected '9.9.9'", result.stderr)

    def test_a_matching_version_passes_that_check(self):
        result = run_script(
            "--expect-version", "0.1.0a1", dists=(("kongui", "0.1.0a1"),)
        )
        self.assertNotIn("is not the expected", result.stderr)
        self.assertIn("kongui 0.1.0a1 (v0.1.0a1)", result.stdout)


if __name__ == "__main__":
    unittest.main()
