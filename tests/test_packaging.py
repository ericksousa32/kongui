"""Package metadata: name, dependencies and the version of the bundled engine."""

import ast
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tarfile
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

    def test_the_build_requirements_are_declared_in_pyproject(self):
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("[build-system]", text)
        self.assertRegex(text, r'"setuptools>=\d+"')
        self.assertRegex(text, r'"setuptools_scm>=\d+"')
        self.assertIn('build-backend = "setuptools.build_meta"', text)

    def test_the_old_setup_requires_is_gone(self):
        self.assertNotIn("setup_requires", self.setup)

    def test_git_archive_carries_the_version(self):
        archival = (ROOT / ".git_archival.txt").read_text(encoding="utf-8")
        for key in ("node:", "node-date:", "describe-name:", "ref-names:"):
            self.assertIn(key, archival)
        attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertRegex(attributes, r"(?m)^\.git_archival\.txt\s+export-subst$")

    def test_pyside6_is_limited_where_it_crashes(self):
        """PySide6 6.10+ crashes Python older than 3.12 (see ``docs/LIMITATIONS.md``)."""
        self.assertIn("\"PySide6>=6.8,<6.10; python_version < '3.12'\"", self.setup)
        self.assertIn("\"PySide6>=6.8; python_version >= '3.12'\"", self.setup)
        self.assertNotIn('"gui": ["PySide6>=6.8"]', self.setup)

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


def git(folder, *args):
    """Runs git in ``folder`` with no user configuration; returns its output."""
    env = dict(
        os.environ,
        HOME=str(folder),
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_SYSTEM=os.devnull,
        GIT_AUTHOR_NAME="t",
        GIT_AUTHOR_EMAIL="t@example.invalid",
        GIT_COMMITTER_NAME="t",
        GIT_COMMITTER_EMAIL="t@example.invalid",
    )
    return subprocess.run(
        ["git", *args],
        cwd=folder,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    ).stdout


@unittest.skipUnless(shutil.which("git"), "git is not installed")
@unittest.skipUnless(
    importlib.util.find_spec("setuptools_scm"), "setuptools_scm is not installed"
)
class SourceArchiveTests(unittest.TestCase):
    """A "Source code" archive (no ``.git``) must still know its version.

    GitHub makes one for every tag. The test makes a repository holding the real
    ``.git_archival.txt`` and ``.gitattributes``, archives it with ``git archive``
    (what GitHub does) and asks ``setuptools_scm`` for the version of the result.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        for name in (".git_archival.txt", "pyproject.toml"):
            shutil.copy(ROOT / name, self.repo / name)
        shutil.copy(ROOT / ".gitattributes", self.repo / ".gitattributes")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "first")
        git(self.repo, "tag", "-a", "v1.2.3", "-m", "release")

    def version_of_archive(self, name):
        """Archives ``HEAD``, unpacks it elsewhere and returns its version."""
        archive = self.base / f"{name}.tar"
        git(self.repo, "archive", "--format=tar", "-o", str(archive), "HEAD")
        target = self.base / name
        target.mkdir()
        with tarfile.open(archive) as handle:
            if hasattr(tarfile, "data_filter"):
                handle.extractall(target, filter="data")
            else:  # Python before the safe extraction filters
                handle.extractall(target)
        self.assertFalse((target / ".git").exists())
        return subprocess.run(
            [sys.executable, "-m", "setuptools_scm"],
            cwd=target,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def test_the_archive_of_a_tag_has_the_version_of_the_tag(self):
        result = self.version_of_archive("tagged")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "1.2.3")

    def test_the_archive_of_a_later_commit_is_a_development_version(self):
        (self.repo / "later.txt").write_text("x", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "later")
        result = self.version_of_archive("later")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout.strip(), r"^1\.2\.4\.dev1\+g[0-9a-f]+$")

    def test_without_the_attribute_the_archive_has_no_version(self):
        """The control: the file alone is not enough, ``export-subst`` fills it."""
        (self.repo / ".gitattributes").unlink()
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "no attribute")
        git(self.repo, "tag", "-a", "v1.2.4", "-m", "again")
        result = self.version_of_archive("plain")
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
