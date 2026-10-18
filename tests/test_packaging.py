"""Package metadata: name, dependencies and the version of the bundled engine."""

import ast
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = sorted(
    path for folder in ("kongui", "konsave") for path in (ROOT / folder).rglob("*.py")
)
BUILD_ONLY = {"setuptools", "pkg_resources", "distutils"}


def make_dist(folder: Path, name: str, version: str) -> None:
    """Creates fake installed-package metadata (a ``.dist-info`` folder)."""
    info = folder / f"{name}-{version}.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n", encoding="utf-8"
    )


class SetupMetadataTests(unittest.TestCase):
    """What ``setup.py`` and ``requirements.txt`` declare."""

    @classmethod
    def setUpClass(cls):
        cls.setup = (ROOT / "setup.py").read_text(encoding="utf-8")
        cls.requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

    def test_the_distribution_is_called_kongui(self):
        self.assertRegex(self.setup, r'name="kongui"')
        self.assertNotIn('name="Konsave"', self.setup)

    def test_metadata_points_to_this_repository_and_credits_konsave(self):
        self.assertIn("https://github.com/ericksousa32/kongui", self.setup)
        self.assertIn("https://github.com/Prayag2/konsave", self.setup)
        self.assertNotIn("prayagjain2@gmail.com", self.setup)

    def test_both_commands_are_installed(self):
        self.assertIn("konsave = konsave.__main__:main", self.setup)
        self.assertIn("kongui = kongui.gui.app:main", self.setup)

    def test_setuptools_is_not_a_runtime_requirement(self):
        names = {
            re.split(r"[<>=!~ ]", line.strip(), maxsplit=1)[0].lower()
            for line in self.requirements.splitlines()
            if line.strip() and not line.startswith("#")
        }
        self.assertEqual(names, {"pyyaml"})

    def test_no_runtime_code_imports_the_build_tools(self):
        self.assertTrue(SOURCES)
        for source in SOURCES:
            tree = ast.parse(source.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    modules = [node.module or ""]
                else:
                    continue
                for module in modules:
                    with self.subTest(source=source.name, module=module):
                        self.assertNotIn(module.split(".")[0], BUILD_ONLY)


class BundledEngineVersionTests(unittest.TestCase):
    """``konsave.__version__`` must exist whichever name the package is installed as."""

    def version_with(self, *dists):
        """Imports ``konsave`` in a clean process that "has installed" ``dists``."""
        with tempfile.TemporaryDirectory() as folder:
            site = Path(folder) / "site"
            site.mkdir()
            for name, version in dists:
                make_dist(site, name, version)
            env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT), str(site)]))
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import konsave; print(getattr(konsave, '__version__', None))",
                ],
                cwd=folder,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_installed_as_kongui_the_engine_gets_the_bundled_version(self):
        self.assertEqual(self.version_with(("kongui", "0.1.0")), "2.2.0+kongui")

    def test_an_installed_konsave_still_wins(self):
        self.assertEqual(
            self.version_with(("konsave", "9.9.9"), ("kongui", "0.1.0")), "9.9.9"
        )

    def test_an_uninstalled_checkout_is_left_as_before(self):
        self.assertEqual(self.version_with(), "None")


if __name__ == "__main__":
    unittest.main()
