"""The user install script, ``install.sh``, run for real in temporary homes.

Nothing is downloaded: "GitHub" is a folder served through ``file://`` URLs
(``KONGUI_DOWNLOAD_BASE``, ``KONGUI_API_URL``), and the wheels are small fakes
built here, with a ``kongui`` (and a ``konsave``) command that only prints its
version. PySide6 is not installed (``KONGUI_EXTRAS`` empty) and pip may not use
the network (``PIP_NO_INDEX``). Each real installation creates a virtual
environment with the system ``python3``, so the tests that need one are skipped
when it cannot.

The fake wheels carry two fake icons where the real package keeps them
(``kongui/gui/data/icons/hicolor``), except when a test needs a release without
icons, like ``0.1.0a1`` and ``0.1.0a2``.

The same script was also run against the real ``0.1.0a1`` release (with PySide6)
when it was written; see ``docs/RELEASING.md``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from tests.helpers import really_root

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "install.sh"
BASH = shutil.which("bash")


def _can_make_venvs() -> bool:
    python = shutil.which("python3")
    if not python:
        return False
    result = subprocess.run(
        [python, "-c", "import venv, ensurepip"], capture_output=True, check=False
    )
    return result.returncode == 0


CAN_INSTALL = bool(BASH) and sys.platform.startswith("linux") and _can_make_venvs()
ICONS = ("48x48/apps/kongui.png", "scalable/apps/kongui.svg")


def fake_icon(rel: str, version: str) -> str:
    """The content of a fake icon; it changes with the version."""
    return f"fake icon {rel} of {version}\n"


def fake_wheel(
    folder: Path, version: str, *, icons: bool = True, requires: str = ""
) -> Path:
    """Builds a tiny installable ``kongui`` wheel with two console scripts.

    ``requires`` adds a dependency; with ``PIP_NO_INDEX`` one that does not exist
    makes pip fail after the environment was created, as without network.
    """
    name = f"kongui-{version}-py3-none-any.whl"
    info = f"kongui-{version}.dist-info"
    files = {
        "kongui/__init__.py": "",
        "kongui/fake.py": (
            "import sys\n"
            "def main():\n"
            f"    print('fake kongui {version}', *sys.argv[1:])\n"
        ),
        f"{info}/METADATA": (
            f"Metadata-Version: 2.1\nName: kongui\nVersion: {version}\n"
            + (f"Requires-Dist: {requires}\n" if requires else "")
        ),
        f"{info}/WHEEL": (
            "Wheel-Version: 1.0\nGenerator: tests\nRoot-Is-Purelib: true\n"
            "Tag: py3-none-any\n"
        ),
        f"{info}/entry_points.txt": (
            "[console_scripts]\nkongui = kongui.fake:main\n"
            "konsave = kongui.fake:main\n"
        ),
    }
    if icons:
        for rel in ICONS:
            files[f"kongui/gui/data/icons/hicolor/{rel}"] = fake_icon(rel, version)
    record = []
    for path, text in files.items():
        data = text.encode()
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
        record.append(f"{path},sha256={digest.decode()},{len(data)}")
    record.append(f"{info}/RECORD,,")
    files[f"{info}/RECORD"] = "\n".join(record) + "\n"
    folder.mkdir(parents=True, exist_ok=True)
    wheel = folder / name
    with zipfile.ZipFile(wheel, "w") as handle:
        for path, text in files.items():
            handle.writestr(path, text)
    return wheel


def write_sums(folder: Path) -> None:
    """Writes a ``SHA256SUMS`` for the files of a folder, like the workflow."""
    lines = []
    for path in sorted(folder.iterdir()):
        if path.name != "SHA256SUMS":
            lines.append(
                f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}"
            )
    (folder / "SHA256SUMS").write_text("\n".join(lines) + "\n")


@unittest.skipUnless(BASH, "bash is not available")
class ScriptCase(unittest.TestCase):
    """A temporary home and a fake GitHub for each test."""

    def setUp(self):
        super().setUp()
        self.base = Path(tempfile.mkdtemp(prefix="kongui-install-test-"))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.home = self.base / "home"
        self.home.mkdir()
        self.github = self.base / "github"
        self.stubs = self.base / "stubs"
        self.stubs.mkdir()
        self.venv = self.home / ".venvs" / "kongui"
        self.link = self.home / ".local/bin/kongui"
        self.desktop = self.home / ".local/share/applications/kongui.desktop"
        self.icons = self.home / ".local/share/icons/hicolor"

    def run_script(self, *args, extra_env=None):
        env = {
            "HOME": str(self.home),
            "PATH": os.pathsep.join(
                [str(self.stubs), "/usr/local/bin", "/usr/bin", "/bin"]
            ),
            "TMPDIR": str(self.base),
            "LANG": "C.UTF-8",
            "KONGUI_EXTRAS": "",
            "PIP_NO_INDEX": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "KONGUI_DOWNLOAD_BASE": f"file://{self.github}",
            "KONGUI_API_URL": f"file://{self.github}/releases.json",
        }
        env.update(extra_env or {})
        return subprocess.run(
            [BASH, str(SCRIPT), *args],
            cwd=self.base,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )

    def publish(self, version, *, tamper=False, icons=True, requires=""):
        """Puts a release on the fake GitHub, as the workflow would."""
        folder = self.github / f"v{version}"
        fake_wheel(folder, version, icons=icons, requires=requires)
        write_sums(folder)
        if tamper:
            with zipfile.ZipFile(
                folder / f"kongui-{version}-py3-none-any.whl", "a"
            ) as z:
                z.writestr("kongui/extra.py", "# changed after the checksum")
        return folder

    def releases_json(self, *tags, draft=()):
        entries = [{"tag_name": tag, "draft": tag in draft} for tag in tags]
        self.github.mkdir(parents=True, exist_ok=True)
        (self.github / "releases.json").write_text(json.dumps(entries))

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def assert_fails(self, result, fragment):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(fragment, result.stdout + result.stderr)


class SafetyTests(ScriptCase):
    """What is refused before anything is installed."""

    def test_the_script_is_valid_and_passes_shellcheck(self):
        self.assertEqual(
            subprocess.run([BASH, "-n", str(SCRIPT)], check=False).returncode, 0
        )
        self.assertTrue(os.access(SCRIPT, os.X_OK), "install.sh must be executable")
        shellcheck = shutil.which("shellcheck")
        if shellcheck is None:
            self.skipTest("shellcheck is not installed")
        result = subprocess.run(
            [shellcheck, str(SCRIPT)], capture_output=True, text=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_help_and_unknown_options(self):
        result = self.run_script("--help")
        self.assert_ok(result)
        self.assertIn("--uninstall", result.stdout)
        self.assertEqual(self.run_script("--nope").returncode, 2)
        self.assert_fails(self.run_script("--release", "1", "--wheel", "x"), "not both")
        self.assert_fails(self.run_script("--uninstall", "--release", "1"), "no other")

    def test_refuses_to_run_as_root(self):
        stub = self.stubs / "id"
        stub.write_text("#!/bin/sh\necho 0\n")
        stub.chmod(0o755)
        self.assert_fails(self.run_script(), "do not run this as root")
        self.assertEqual(os.listdir(self.home), [])

    def test_a_wheel_that_does_not_match_its_checksum_is_refused(self):
        folder = self.publish("1.0.0", tamper=True)
        local = self.run_script(
            "--wheel", str(folder / "kongui-1.0.0-py3-none-any.whl")
        )
        self.assert_fails(local, "checksum mismatch")
        self.assert_fails(self.run_script("--release", "1.0.0"), "checksum mismatch")
        self.assertFalse((self.home / ".venvs").exists())

    def test_bad_names_and_missing_releases(self):
        other = self.base / "other.whl"
        other.write_text("x")
        self.assert_fails(self.run_script("--wheel", str(other)), "does not look like")
        self.assert_fails(self.run_script("--wheel", "/no/such.whl"), "no such file")
        self.assert_fails(self.run_script("--release", "1.0;rm"), "not a version")
        self.assert_fails(self.run_script("--release", "7.7.7"), "not found")
        self.releases_json()
        self.assert_fails(self.run_script(), "no KonGUI release found")
        self.assertFalse((self.home / ".venvs").exists())


@unittest.skipUnless(CAN_INSTALL, "cannot create virtual environments here")
@unittest.skipIf(really_root(), "the script refuses to run as root")
class InstallTests(ScriptCase):
    """Real installations (a virtual environment, pip, the link, the menu)."""

    def run_kongui(self, *args):
        return subprocess.run(
            [str(self.link), *args], capture_output=True, text=True, check=False
        )

    def test_install_open_update_repair_and_uninstall(self):
        first = self.publish("1.0.0")
        result = self.run_script(
            "--wheel", str(first / "kongui-1.0.0-py3-none-any.whl")
        )
        self.assert_ok(result)
        self.assertIn("checksum ok", result.stdout)
        self.assertIn("KonGUI 1.0.0 is installed", result.stdout)
        # the command works through the link, from anywhere
        self.assertTrue(self.link.is_symlink())
        self.assertEqual(os.readlink(self.link), str(self.venv / "bin/kongui"))
        self.assertEqual(
            self.run_kongui("--demo").stdout.strip(), "fake kongui 1.0.0 --demo"
        )
        self.assertFalse((self.home / ".local/bin/konsave").exists(), "never konsave")
        # the menu entry: absolute command, the icon, marked as ours
        entry = self.desktop.read_text()
        self.assertIn(f"Exec={self.venv}/bin/kongui\n", entry)
        self.assertIn("Name=KonGUI\n", entry)
        self.assertIn("Icon=kongui\n", entry)
        self.assertIn("StartupWMClass=kongui\n", entry)
        self.assertIn("X-KonGUI-Installed-By=install.sh", entry)
        # the icons, copied from the installed package into the hicolor theme
        for rel in ICONS:
            self.assertEqual((self.icons / rel).read_text(), fake_icon(rel, "1.0.0"))

        # running it again updates in place (here from the fake GitHub)
        self.publish("1.0.1")
        self.releases_json("v1.0.1", "v1.0.0")
        result = self.run_script()
        self.assert_ok(result)
        self.assertIn("newest release: 1.0.1", result.stdout)
        self.assertNotIn("creating the environment", result.stdout)
        self.assertEqual(self.run_kongui().stdout.strip(), "fake kongui 1.0.1")
        for rel in ICONS:
            self.assertEqual((self.icons / rel).read_text(), fake_icon(rel, "1.0.1"))

        # an environment that stopped working (Python upgraded) is made again
        python = self.venv / "bin/python"
        python.unlink()
        python.symlink_to(self.base / "gone/python3")
        result = self.run_script("--release", "1.0.1")
        self.assert_ok(result)
        self.assertIn("no longer works", result.stdout)
        self.assertEqual(self.run_kongui().stdout.strip(), "fake kongui 1.0.1")

        # uninstall removes what it made and keeps the user's data
        data = self.home / ".config/konsave/profiles/mine"
        data.mkdir(parents=True)
        result = self.run_script("--uninstall")
        self.assert_ok(result)
        self.assertFalse(self.link.exists() or self.link.is_symlink())
        self.assertFalse(self.desktop.exists())
        self.assertFalse((self.home / ".venvs").exists())
        self.assertEqual(list(self.icons.iterdir()), [], "icon folders left empty")
        self.assertTrue(data.is_dir())
        self.assertIn("nothing to do", self.run_script("--uninstall").stdout)

    def test_a_release_without_icons_and_icons_it_did_not_make(self):
        # 0.1.0a1 and 0.1.0a2 have no icons: they still install, without Icon=
        folder = self.publish("0.1.0a2", icons=False)
        result = self.run_script(
            "--wheel", str(folder / "kongui-0.1.0a2-py3-none-any.whl")
        )
        self.assert_ok(result)
        self.assertIn("has no icon", result.stdout)
        entry = self.desktop.read_text()
        self.assertNotIn("Icon=", entry)
        self.assertIn("StartupWMClass=kongui\n", entry)
        self.assertFalse(self.icons.exists())
        # an icon of the user's own (not the packaged bytes) is never deleted
        self.publish("1.0.0")
        result = self.run_script("--release", "1.0.0")
        self.assert_ok(result)
        self.assertIn("Icon=kongui\n", self.desktop.read_text())
        changed = self.icons / ICONS[0]
        changed.write_text("my own icon")
        result = self.run_script("--uninstall")
        self.assert_ok(result)
        self.assertIn("is not the icon this script installed", result.stderr)
        self.assertEqual(changed.read_text(), "my own icon")
        self.assertFalse((self.icons / ICONS[1]).exists())

    def test_newest_release_skips_drafts_and_odd_tags(self):
        self.publish("2.0.0")
        self.releases_json("v3.0.0", "nightly", "v2.0.0", draft=("v3.0.0",))
        result = self.run_script()
        self.assert_ok(result)
        self.assertIn("newest release: 2.0.0", result.stdout)
        self.assertEqual(self.run_kongui().stdout.strip(), "fake kongui 2.0.0")

    def test_an_installation_that_stopped_halfway_can_be_retried(self):
        marker = self.venv / ".kongui-install"
        # pip fails (a dependency it cannot get, as without network): the
        # environment is left without the kongui command, but marked as ours
        broken = self.publish("1.0.0", requires="kongui-test-missing-dependency")
        result = self.run_script(
            "--wheel", str(broken / "kongui-1.0.0-py3-none-any.whl")
        )
        self.assert_fails(result, "run this script again to retry")
        self.assertTrue(marker.is_file())
        self.assertFalse((self.venv / "bin/kongui").exists())
        # running it again reuses that environment and finishes
        self.publish("1.0.1")
        result = self.run_script("--release", "1.0.1")
        self.assert_ok(result)
        self.assertNotIn("creating the environment", result.stdout)
        self.assertEqual(self.run_kongui().stdout.strip(), "fake kongui 1.0.1")
        # an environment of an older install.sh (no marker) gets one
        marker.unlink()
        self.assert_ok(self.run_script("--release", "1.0.1"))
        self.assertTrue(marker.is_file())
        # the venv module stopped before making Python: the folder is made again
        shutil.rmtree(self.venv)
        self.venv.mkdir(parents=True)
        marker.write_text("x")
        result = self.run_script("--release", "1.0.1")
        self.assert_ok(result)
        self.assertIn("is incomplete", result.stdout)
        self.assertEqual(self.run_kongui().stdout.strip(), "fake kongui 1.0.1")
        # and a failed installation can also simply be removed
        shutil.rmtree(self.venv)
        self.assert_fails(
            self.run_script("--wheel", str(broken / "kongui-1.0.0-py3-none-any.whl")),
            "pip could not install",
        )
        self.assert_ok(self.run_script("--uninstall"))
        self.assertFalse((self.home / ".venvs").exists())

    def test_never_replaces_or_deletes_what_it_did_not_make(self):
        folder = self.publish("1.0.0")
        wheel = str(folder / "kongui-1.0.0-py3-none-any.whl")
        self.link.parent.mkdir(parents=True)
        self.link.write_text("#!/bin/sh\necho mine\n")
        self.desktop.parent.mkdir(parents=True)
        self.desktop.write_text("[Desktop Entry]\nName=Something else\n")
        result = self.run_script("--wheel", wheel)
        self.assert_ok(result)
        self.assertIn("is not a link", result.stderr)
        self.assertIn("is not KonGUI's menu entry", result.stderr)
        self.assertEqual(self.link.read_text(), "#!/bin/sh\necho mine\n")
        self.assertEqual(
            self.desktop.read_text(), "[Desktop Entry]\nName=Something else\n"
        )
        result = self.run_script("--uninstall")
        self.assert_ok(result)
        self.assertTrue(self.link.is_file() and self.desktop.is_file())
        # a folder that is not KonGUI's environment is neither used nor deleted
        foreign = self.base / "foreign"
        foreign.mkdir()
        (foreign / "important.txt").write_text("keep")
        env = {"KONGUI_VENV": str(foreign)}
        self.assert_fails(
            self.run_script("--wheel", wheel, extra_env=env), "is not KonGUI's"
        )
        self.assert_fails(
            self.run_script("--uninstall", extra_env=env), "refusing to delete"
        )
        self.assertEqual((foreign / "important.txt").read_text(), "keep")
        # nor is another virtual environment without KonGUI in it
        (foreign / "pyvenv.cfg").write_text("home = /usr/bin\n")
        result = self.run_script("--wheel", wheel, extra_env=env)
        self.assert_fails(result, f"rm -rf {foreign}")
        self.assert_fails(
            self.run_script("--uninstall", extra_env=env), "refusing to delete"
        )
        self.assertEqual((foreign / "important.txt").read_text(), "keep")
        self.assertFalse((foreign / ".kongui-install").exists())


if __name__ == "__main__":
    unittest.main()
