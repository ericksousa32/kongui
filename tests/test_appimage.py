"""The AppImage recipe (``packaging/appimage/``) is coherent and its scripts work.

Building the AppImage itself downloads a Python image and PySide6, so it is not
done here (``make appimage``; the release workflow builds and checks it). These
tests check the files that go into it: the desktop entry and the AppStream
metadata (validated with the freedesktop tools when they are installed), the
entry point's dispatching, and the choices of ``trim.py``.
"""

import contextlib
import importlib.util
import io
import os
import re
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECIPE = ROOT / "packaging" / "appimage"


def desktop_entry(path: Path) -> dict:
    """The ``[Desktop Entry]`` keys of a desktop file."""
    keys = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith(("#", "[")):
            key, value = line.split("=", 1)
            keys[key] = value
    return keys


def load_trim():
    """Imports ``packaging/appimage/trim.py`` (it is not a package)."""
    spec = importlib.util.spec_from_file_location("kongui_trim", RECIPE / "trim.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DesktopEntryTests(unittest.TestCase):
    """The menu entry ties the window to the app and matches install.sh."""

    def setUp(self):
        self.entry = desktop_entry(RECIPE / "kongui.desktop")

    def test_it_names_the_app_its_icon_and_its_window(self):
        self.assertEqual(self.entry["Name"], "KonGUI")
        self.assertEqual(self.entry["Exec"], "kongui")
        self.assertEqual(self.entry["Icon"], "kongui")
        # The window is matched to the entry through the desktop file name the
        # application sets (kongui/gui/app.py) and StartupWMClass.
        app = (ROOT / "kongui" / "gui" / "app.py").read_text(encoding="utf-8")
        self.assertIn('setDesktopFileName("kongui")', app)
        self.assertEqual(self.entry["StartupWMClass"], "kongui")

    def test_it_says_the_same_as_the_entry_install_sh_writes(self):
        script = (ROOT / "install.sh").read_text(encoding="utf-8")
        for key in ("Name", "GenericName", "Comment", "StartupWMClass", "Categories"):
            with self.subTest(key=key):
                self.assertIn(f"{key}={self.entry[key]}\n", script)

    def test_it_has_one_main_category(self):
        # Two main categories (Settings and Utility) list the app twice in some menus.
        main = {
            "AudioVideo",
            "Development",
            "Education",
            "Game",
            "Graphics",
            "Network",
            "Office",
            "Science",
            "Settings",
            "System",
            "Utility",
        }
        categories = set(filter(None, self.entry["Categories"].split(";")))
        self.assertEqual(categories & main, {"Settings"})

    def test_it_passes_desktop_file_validate(self):
        if shutil.which("desktop-file-validate") is None:
            self.skipTest("desktop-file-validate is not installed")
        result = subprocess.run(
            ["desktop-file-validate", str(RECIPE / "kongui.desktop")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "")


class AppStreamTests(unittest.TestCase):
    """The AppStream metadata describes the same app as the desktop entry."""

    def setUp(self):
        self.root = ET.parse(RECIPE / "kongui.appdata.xml").getroot()

    def test_it_points_at_the_desktop_entry(self):
        self.assertEqual(self.root.get("type"), "desktop-application")
        self.assertEqual(self.root.findtext("id"), "kongui")
        launchable = self.root.find("launchable")
        self.assertEqual(launchable.get("type"), "desktop-id")
        self.assertEqual(launchable.text, "kongui.desktop")
        self.assertEqual(self.root.findtext("provides/binary"), "kongui")
        self.assertEqual(self.root.findtext("project_license"), "GPL-3.0-or-later")

    def test_the_only_warning_is_the_accepted_id(self):
        # The id stays "kongui" (owner's decision), which AppStream flags as
        # not reverse-DNS. Anything else it reports is a real problem.
        if shutil.which("appstreamcli") is None:
            self.skipTest("appstreamcli is not installed")
        result = subprocess.run(
            [
                "appstreamcli",
                "validate",
                "--no-net",
                "--format=yaml",
                str(RECIPE / "kongui.appdata.xml"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        issues = re.findall(r"- tag: (\S+)\s+severity: (\S+)", result.stdout)
        self.assertTrue(issues, result.stdout)
        real = [
            (tag, severity)
            for tag, severity in issues
            if severity != "pedantic" and tag != "cid-desktopapp-is-not-rdns"
        ]
        self.assertEqual(real, [], result.stdout)


class AppRunTests(unittest.TestCase):
    """``AppRun`` starts the interface, or the bundled ``konsave`` command."""

    def run_apprun(self, *args, env=None):
        """Runs AppRun in a fake AppDir whose "python" records how it was called."""
        appdir = Path(tempfile.mkdtemp(prefix="kongui-apprun-"))
        self.addCleanup(shutil.rmtree, appdir, ignore_errors=True)
        text = (RECIPE / "AppRun").read_text(encoding="utf-8")
        (appdir / "AppRun").write_text(text.replace("@PYTHON_VERSION@", "3.12"))
        (appdir / "AppRun").chmod(0o755)
        python = appdir / "opt" / "python3.12" / "bin" / "python3.12"
        python.parent.mkdir(parents=True)
        python.write_text(
            "#!/bin/sh\n"
            'printf "%s\\n" "$@" > "$APPDIR/args"\n'
            'printf "%s|%s|%s\\n" "${PYTHONPATH-unset}" "${PYTHONHOME-unset}" '
            '"$PYTHONNOUSERSITE" > "$APPDIR/env"\n'
        )
        python.chmod(0o755)
        environment = dict(os.environ, PYTHONPATH="/elsewhere", PYTHONHOME="/nope")
        environment.pop("APPDIR", None)
        environment.update(env or {})
        subprocess.run([str(appdir / "AppRun"), *args], check=True, env=environment)
        called = (appdir / "args").read_text().split("\n")[:-1]
        return called, (appdir / "env").read_text().strip()

    def test_without_arguments_it_starts_the_interface(self):
        called, _ = self.run_apprun()
        self.assertEqual(called, ["-s", "-m", "kongui.gui"])

    def test_interface_arguments_are_passed_on(self):
        called, _ = self.run_apprun("--demo")
        self.assertEqual(called, ["-s", "-m", "kongui.gui", "--demo"])

    def test_konsave_as_first_argument_runs_the_bundled_command(self):
        called, _ = self.run_apprun("konsave", "-s", "my profile")
        self.assertEqual(called, ["-s", "-m", "konsave", "-s", "my profile"])

    def test_the_caller_s_python_settings_are_ignored(self):
        _, env = self.run_apprun()
        self.assertEqual(env, "unset|unset|1")

    def test_the_scripts_are_valid_shell(self):
        for script, shell in (("AppRun", "sh"), ("build.sh", "bash")):
            with self.subTest(script=script):
                subprocess.run([shell, "-n", str(RECIPE / script)], check=True)
        if shutil.which("shellcheck") is None:
            self.skipTest("shellcheck is not installed")
        result = subprocess.run(
            ["shellcheck", str(RECIPE / "AppRun"), str(RECIPE / "build.sh")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)


class TrimTests(unittest.TestCase):
    """``trim.py`` removes what KonGUI does not use, and keeps what it does."""

    KEPT = (
        "QtCore.abi3.so",
        "QtGui.abi3.so",
        "QtWidgets.abi3.so",
        "QtSvg.abi3.so",
        "libpyside6.abi3.so.6.12",
        "__init__.py",
        "Qt/lib/libQt6Core.so.6",
        "Qt/lib/libQt6Gui.so.6",
        "Qt/lib/libQt6Widgets.so.6",
        "Qt/lib/libQt6Svg.so.6",
        "Qt/lib/libQt6DBus.so.6",
        "Qt/lib/libQt6XcbQpa.so.6",
        "Qt/lib/libQt6WaylandClient.so.6",
        "Qt/lib/libicudata.so.73",
        "Qt/plugins/platforms/libqwayland.so",
        "Qt/plugins/platforms/libqxcb.so",
        "Qt/plugins/platforms/libqoffscreen.so",
        "Qt/plugins/iconengines/libqsvgicon.so",
        "Qt/plugins/imageformats/libqsvg.so",
        "Qt/plugins/platformthemes/libqgtk3.so",
        "Qt/translations/qtbase_pt_BR.qm",
    )
    REMOVED = (
        "QtQml.abi3.so",
        "QtTest.abi3.so",
        "QtCore.pyi",
        "libpyside6qml.abi3.so.6.12",
        "Qt/lib/libQt6Qml.so.6",
        "Qt/lib/libQt6QuickControls2.so.6",
        "Qt/lib/libQt6Designer.so.6",
        "Qt/lib/libQt6EglFsKmsSupport.so.6",
        "Qt/lib/libQt6Test.so.6",
        "Qt/plugins/platforms/libqvnc.so",
        "Qt/plugins/platforms/libqeglfs.so",
        "Qt/plugins/sqldrivers/libqsqlite.so",
        "Qt/plugins/qmltooling/libqmldbg_tcp.so",
        "Qt/plugins/imageformats/libqpdf.so",
        "Qt/qml/QtQuick/qmldir",
        "Qt/translations/qtdeclarative_pt_BR.qm",
        "Qt/translations/designer_pt_BR.qm",
        "designer",
        "include/pyside6.h",
    )

    def test_it_keeps_the_desktop_essentials_and_removes_the_rest(self):
        trim = load_trim()
        site = Path(tempfile.mkdtemp(prefix="kongui-trim-"))
        self.addCleanup(shutil.rmtree, site, ignore_errors=True)
        for relative in self.KEPT + self.REMOVED:
            path = site / "PySide6" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")
        self.assertGreater(trim.trim(site), 0)
        for relative in self.KEPT:
            with self.subTest(kept=relative):
                self.assertTrue((site / "PySide6" / relative).exists())
        for relative in self.REMOVED:
            with self.subTest(removed=relative):
                self.assertFalse((site / "PySide6" / relative).exists())

    def test_a_library_lost_by_trimming_fails_the_check(self):
        trim = load_trim()
        site = Path(tempfile.mkdtemp(prefix="kongui-trim-"))
        self.addCleanup(shutil.rmtree, site, ignore_errors=True)
        (site / "PySide6" / "Qt" / "lib").mkdir(parents=True)
        reports = iter(
            (
                {"PySide6/Qt/plugins/x.so": {"libxcb-cursor.so.0"}},
                {"PySide6/Qt/plugins/x.so": {"libxcb-cursor.so.0", "libQt6Qml.so.6"}},
            )
        )
        original = trim.missing_libraries
        trim.missing_libraries = lambda root, qt_lib: next(reports)
        trim.trim = lambda site_packages: 0
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ) as errors:
                self.assertEqual(trim.main(["trim.py", str(site)]), 1)
            self.assertIn("needs removed libQt6Qml.so.6", errors.getvalue())
        finally:
            trim.missing_libraries = original


class ReleaseWorkflowTests(unittest.TestCase):
    """The release workflow builds, checks, signs and publishes the AppImages."""

    def setUp(self):
        import yaml

        path = ROOT / ".github" / "workflows" / "release.yml"
        self.text = path.read_text(encoding="utf-8")
        self.jobs = yaml.safe_load(self.text)["jobs"]

    def steps(self, job):
        return "\n".join(step.get("run", "") for step in self.jobs[job]["steps"])

    def test_both_architectures_are_built_natively(self):
        matrix = self.jobs["appimage"]["strategy"]["matrix"]["include"]
        self.assertEqual(
            {(entry["arch"], entry["runner"]) for entry in matrix},
            {("x86_64", "ubuntu-24.04"), ("aarch64", "ubuntu-24.04-arm")},
        )
        self.assertIn(
            'packaging/appimage/build.sh "dist/kongui-', self.steps("appimage")
        )

    def test_the_appimage_is_smoke_tested_and_its_signature_validated(self):
        run = self.steps("appimage")
        self.assertIn('"$appimage" konsave -v', run)
        self.assertIn("tools/smoke_test.py", run)
        self.assertIn("validation successful", run)

    def test_a_tag_without_the_key_fails_instead_of_publishing_unsigned(self):
        run = self.steps("appimage")
        self.assertRegex(
            run,
            r'if \[ "\$IS_TAG" = "true" \]; then\s+echo "::error::KONGUI_SIGNING_KEY',
        )
        self.assertIn(
            'test -n "$KEY" || { echo "::error::KONGUI_SIGNING_KEY',
            self.steps("release"),
        )

    def test_the_release_signs_the_checksums_of_every_file(self):
        release = self.jobs["release"]
        self.assertEqual(release["needs"], ["build", "appimage"])
        self.assertIn("refs/tags/", release["if"])
        run = self.steps("release")
        self.assertIn("sha256sum -- * > SHA256SUMS", run)
        self.assertIn("--detach-sign --output SHA256SUMS.asc SHA256SUMS", run)
        self.assertIn("gpg --verify SHA256SUMS.asc SHA256SUMS", run)
        self.assertIn("kongui-signing-key.asc", run)

    def test_the_update_channel_follows_the_kind_of_release(self):
        run = self.steps("appimage")
        self.assertIn("channel=latest-all; else channel=latest;", run)
        self.assertIn("gh-releases-zsync|", run)

    def test_a_manual_run_is_a_dry_run(self):
        on = yaml_on(self.text)
        self.assertIn("workflow_dispatch", on)
        self.assertNotIn("workflow_dispatch", self.jobs["release"]["if"])


def yaml_on(text: str) -> dict:
    """The workflow's triggers (PyYAML reads the key ``on`` as ``True``)."""
    import yaml

    data = yaml.safe_load(text)
    return data.get("on", data.get(True))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
