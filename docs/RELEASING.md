# Versions and releases

How the version of KonGUI is defined, where it is shown, and the steps for a
release. The first tag is **`v0.1.0a1`** (2026-10-22, [release page](https://github.com/ericksousa32/kongui/releases/tag/v0.1.0a1));
it followed the rules and the checklist below.

## 1. One source: the git tag

The version is not written in any source file. It comes from the **git tag**:

```
git tag v0.1.0a1  ──setuptools_scm──▶  package version 0.1.0a1  ──importlib.metadata──▶  kongui.__version__
```

* `setup.py` uses `use_scm_version=True` (build time): the wheel and the sdist get
  the version computed from the tag. `setuptools_scm` is a **build requirement**
  declared in `pyproject.toml` (`[build-system]`: `setuptools>=75`,
  `setuptools_scm>=8`), not in `setup_requires` (the old mechanism, deprecated).
  `pyproject.toml` declares nothing else; the package metadata stays in `setup.py`.
* `kongui/__init__.py` (run time) reads the version of the installed `kongui`
  distribution with `importlib.metadata.version("kongui")`. It has no copy of its
  own, so the command line, the *About* page and the sidebar can never disagree with
  the package.
* The Konsave engine has its own, separate version (`2.2.0+kongui`, the Konsave
  release the bundled code derives from; `KONSAVE_PATCHES.md` §3.5). The *About*
  page shows both.

## 2. What a version looks like

Versions follow PEP 440. The tag has a leading `v`; the version does not.

| Situation | Tag | `kongui.__version__` | Badge and sidebar |
|---|---|---|---|
| Alpha release | `v0.1.0a1` | `0.1.0a1` | `v0.1.0a1` |
| Beta, candidate, final | `v0.1.0b1`, `v0.1.0rc1`, `v0.1.0` | `0.1.0b1`, … | `v0.1.0b1`, … |
| Build made after the last tag, from a clean commit | `v0.1.0a1` is the last tag | `0.1.0a2.dev3+g1a2b3c4` (3 commits later) | `v0.1.0a2.dev3` |
| Build with uncommitted changes | — | `0.1.0a2.dev3+g1a2b3c4.d20261018` | `v0.1.0a2.dev3` |
| Checkout that was never installed (`python -m kongui.gui` from a clone) | — | `0+unknown` (`kongui.UNKNOWN_VERSION`) | `dev` |

* A build between two tags is always a **development** version (`.devN`), so it can
  not pass for a release.
* `kongui.short_version()` drops the part after `+` (the commit and the "modified"
  date) for narrow places (the badge and the sidebar caption, which has a fixed
  width). The full version is in *About → KonGUI version*. An unknown version is
  shown as `dev`, never as `0+unknown`.
* `pip install -e ".[gui]"` from a clone counts as installed: the version is the one
  computed from the git history at that moment.

## 3. Releasing (steps)

Preconditions: the PR that is going into the release is merged into `dev`, and `dev`
is merged into `master` (only when a version is complete). Before an *alpha*, also
go through the checklist in §6.

1. Check that `master` is clean and passes the whole suite as a regular user
   (`python3 -m unittest discover -s tests -t .`, with `pip install -e ".[gui,dev]"`),
   `black --check kongui tests tools konsave setup.py` and `pylint kongui`.
2. Put the changes of the release in `CHANGELOG.md` (move `[Unreleased]` under the new
   version) and update the status line in `README.md`.
3. Create an **annotated** tag on `master`: `git tag -a v0.1.0a1 -m "KonGUI 0.1.0a1"`.
4. Push the tag: `git push origin v0.1.0a1`. **This is what releases**: the workflow
   `.github/workflows/release.yml` (§5) builds, checks and publishes the GitHub
   pre-release by itself. Nothing else is uploaded by hand.
5. When the workflow ends, look at the release page (marked *Pre-release*, with the
   wheel, the sdist and `SHA256SUMS`) and do the post-release checks of §6.

To check the build **before** tagging, run it by hand from a clone (it only needs the
git history; with no tag the version is a `.dev` one, which is expected):

```
python -m build                                   # sdist and wheel in dist/
python -m venv /tmp/clean && /tmp/clean/bin/pip install dist/*.whl
/tmp/clean/bin/python tools/smoke_test.py --no-gui     # or without --no-gui if Qt is installed
```

If the tag was wrong, delete the release and the tag (`gh release delete`, `git push
--delete origin <tag>`, `git tag -d <tag>`) and tag again; a tag must never be moved
silently after people may have downloaded files.

## 4. Building from a source archive (no `.git`)

GitHub attaches "Source code (zip)" and "(tar.gz)" to every tag. They are made by
`git archive`, so they have no `.git` folder, and a build from one used to fail with
`setuptools_scm`'s "unable to detect version" (reproduced before the change). Two
small files fix it:

* `.git_archival.txt` holds `$Format:…$` placeholders (commit, date, `git describe`
  name, ref names);
* `.gitattributes` marks it `export-subst`, so `git archive` replaces the
  placeholders with the real values.

`setuptools_scm` reads the filled file where there is no repository. Results
(`pip wheel --no-deps .`, in a clean virtual environment):

| Source | Version of the wheel |
|---|---|
| a clone, at the tag `v0.1.0a1` | `0.1.0a1` |
| `git archive` of that tag, unpacked (no `.git`) | `0.1.0a1` |
| `git archive` of a commit after the tag | `0.1.0a2.dev1+g…` |
| an archive made *without* the attribute | the build fails (the control of the test) |

GitHub makes its "Source code" files with `git archive`. Checked with a real
download for `v0.1.0a1`: the zip has `.git_archival.txt` filled in (`describe-name:
v0.1.0a1`) and `pip wheel --no-deps .` builds `kongui-0.1.0a1`.

`git archive` only fills the file for the commit it is run on. A copy of the
working tree made by hand (not through `git archive`) still has the placeholders and
no `.git`: build it from a clone, or from an sdist.

Known warnings of the build (they do not fail it): setuptools says the licence
classifier is deprecated in favour of an SPDX expression, and that
`kongui.gui.translations` is "absent from `packages`" (it holds only the `.ts` and
`.qm` files, which are included through `package_data`; the wheel was checked to
contain the four files).

## 5. The release workflow

`.github/workflows/release.yml` (it replaced `deploy.yml`, which published to PyPI on
every `v*` tag; **KonGUI is not published to PyPI**). It runs when a tag `v[0-9]*` is
pushed, with read-only permissions except in the last job, and by hand
(*Actions → Release → Run workflow*) as a **dry run** of any branch: everything is
built and checked, nothing is published, and the files stay as the run's artifacts.

Job `build`:

1. on a tag: refuses anything that is not PEP 440 in the forms `v0.1.0a1`,
   `v0.1.0b1`, `v0.1.0rc1`, `v0.1.0` (`a`, `b` and `rc` mean *pre-release*), and a
   tag whose commit is not on `master`;
2. builds the sdist and the wheel (`python -m build`, with the whole history:
   `fetch-depth: 0`), reads the version from the wheel and, on a tag, checks that the
   file names carry the tag's version;
3. installs the wheel in a clean virtual environment and runs
   `tools/smoke_test.py --no-gui --expect-version <version>` from another folder:
   the package reports the version, the bundled `konsave` command starts and the
   application icon files were packaged;
4. installs the wheel with `install.sh --wheel` in a temporary home (without
   PySide6), checks the `kongui` link, the menu entry, its `Icon=kongui` line and the
   copied icons, and uninstalls it (the icons go too);
5. copies `install.sh` into `dist/` and uploads `dist/` as a workflow artifact.

Job `appimage`, once per architecture, each on its own kind of runner
(`ubuntu-24.04` for x86_64, `ubuntu-24.04-arm` for aarch64), from the wheel `build`
made (§7):

1. imports the signing key from the secrets (§7, *Signing key*). **On a tag without
   the key it fails**: nothing is published unsigned; a dry run without it builds
   unsigned AppImages and says so;
2. runs `packaging/appimage/build.sh` with the wheel, signing when the key is there
   and, on a tag, embedding the update information: channel `latest-all` for a
   pre-release (it follows any newer release), `latest` for a stable one;
3. runs the AppImage's `konsave -v`, and `tools/smoke_test.py --expect-version`
   with the AppImage's own Python and Qt (offscreen): window, pages, icon and both
   translations; on a tag it checks the embedded update information and the
   `.zsync` file;
4. checks the embedded signature with AppImageUpdate's `validate` tool (it must
   succeed with the key's fingerprint);
5. uploads the AppImage and its `.zsync`.

Job `release` (only on a tag; the only one with `contents: write`): gathers all the
files, writes `SHA256SUMS` of every one of them, signs it into `SHA256SUMS.asc`
(checked with `gpg --verify` right after), adds the public key as
`kongui-signing-key.asc`, and creates the GitHub release
(`gh release create --verify-tag`) with the text of `.github/release-notes.md` and
`--prerelease` when the tag is an `a`, `b` or `rc`.

What was tested (before the AppImage jobs): the steps of `build` were executed on a scratch repository (a branch
`master`, a local bare remote and the tag `v0.1.0a1`), reading them from the YAML file
with the version and the commit supplied through the same environment variables the
runner sets: the good tag built `kongui-0.1.0a1` (wheel and sdist), passed the
smoke test and produced the checksums; a tag that is not a version, and a tag whose
commit is not on `master`, were refused. The file also passes `actionlint`. Its first
real run on GitHub Actions, for the tag `v0.1.0a1` (2026-10-22), succeeded with no
change: both jobs passed and the pre-release was created with the three files. If a
later run fails, the tag can be deleted and pushed again (§3).

## 6. Pre-release checklist and post-release checks

Before tagging the first alpha:

* [x] The owner's report of the real Plasma session is recorded in
  [`PLASMA_TEST_PLAN.md`](PLASMA_TEST_PLAN.md) (*Results so far*),
  and has no blocker (2026-10-22, quick test).
* [x] `dev` is merged into `master`, and `master` passes the whole suite on the
  system Python and in a virtual environment (§3, step 1; PR #15, 805 tests OK on
  2026-10-22). The suite also ran on
  Python 3.9 to 3.14 ([`TEST_OVERVIEW.md`](TEST_OVERVIEW.md)).
* [x] `CHANGELOG.md` has the release under its own heading, with the date of the tag
  in place of `TBD` (2026-10-22), and the README status line
  is up to date.
* [x] **Repository settings** (they cannot be set from the code; confirmed by the owner
  on 2026-10-22): *Settings → Actions
  → General → Workflow permissions* must allow `GITHUB_TOKEN` to create releases
  (or at least not be blocked by an organisation policy). The workflow declares
  its own permissions.

After the workflow ends:

* [x] The release is marked *Pre-release* and lists the wheel, the sdist and
  `SHA256SUMS`.
* [x] Download the files, run `sha256sum -c SHA256SUMS`, install the wheel with
  `[gui]` in a new virtual environment and run
  `python tools/smoke_test.py --expect-version 0.1.0a1` (without `--no-gui`). Done
  for `0.1.0a1` on Linux with Qt offscreen, on Python 3.11, 3.13 and 3.14; repeated for `0.1.0a3` (2026-10-23,
  cloud container, Qt offscreen): checksums ok, the smoke test printed the 9 icon
  files, both translations, an 8-size window icon and the 5 pages.
* [ ] The same on a Fedora KDE desktop, with `kongui --demo` in a real window (left
  to the owner for `0.1.0a1`; the same is left open for `0.1.0a3`, to also confirm
  the icon in the window, the menu and the task manager on a real session).
* [x] From `0.1.0a2` on: the release also lists `install.sh`, `SHA256SUMS` covers it,
  and `bash install.sh --release <version>` installs that release on a desktop.
  `--release 0.1.0a3` was run for real against GitHub (2026-10-23, cloud container,
  unprivileged user): it downloaded, checked the checksum, installed `[gui]`,
  copied the icon, wrote `Icon=kongui` and `StartupWMClass=kongui`, `kongui --demo`
  started, and `--uninstall` removed everything (profiles kept). Not yet run on a
  real desktop.
* [x] From the first release after `0.1.0a2` on: after `install.sh`, the menu entry,
  the window and the task manager show the KonGUI icon. Confirmed for `0.1.0a3`
  (2026-10-23): the menu entry and the window icon (the task manager needs a real
  Plasma session, left to the owner with the item above).
* [x] Download GitHub's own *Source code (zip)*, unpack it where there is no `.git`,
  run `pip wheel --no-deps .` and check the version (`0.1.0a1`, §4); repeated for
  `0.1.0a3` (2026-10-23): the sdist built a wheel of the same version.

For the next release, copy this checklist and start again with every box empty.

## 7. AppImage

Every release from `0.1.0a4` on has an AppImage for x86_64 and one for aarch64,
built and checked by the release workflow (§5). The same recipe builds one from any
checkout:

```bash
make appimage          # or: packaging/appimage/build.sh [WHEEL]
```

The result is `dist/appimage/KonGUI-<version>-<arch>.AppImage` (about 50 MB) and
its `.sha256`. What `packaging/appimage/build.sh` does:

1. builds the wheel from a clean `git worktree` of `HEAD` (or takes the one given),
   so no `build/` or `*.egg-info` is left in the checkout;
2. extracts a relocatable CPython (3.12, manylinux_2_28) from
   [python-appimage](https://github.com/niess/python-appimage) and installs into it
   the wheel, PyYAML and **PySide6-Essentials** (the app only uses QtCore, QtGui,
   QtWidgets and QtSvg);
3. runs `packaging/appimage/trim.py`, which removes what KonGUI does not use (QML /
   Quick, Designer, SQL, the test library, developer tools, type stubs; about 145 MB
   unpacked) by explicit lists, then runs `ldd` on every remaining library and fails
   if one of them lost a dependency;
4. adds `AppRun` (`KonGUI.AppImage` starts the interface, `KonGUI.AppImage konsave …`
   the bundled command; the caller's `PYTHONPATH`, `PYTHONHOME` and user
   site-packages are ignored), the desktop entry, the AppStream metadata and the icon;
5. packages it with [appimagetool](https://github.com/AppImage/appimagetool), which
   embeds the static type-2 runtime.

Options of `build.sh` (environment): `UPDATE_INFORMATION` embeds where newer versions
are published (Gear Lever and AppImageUpdate read it) and writes a `.zsync` file next
to the AppImage (needs `zsyncmake`, package `zsync`); `SIGN=1` embeds a GPG signature
(`SIGN_KEY` picks the key, `APPIMAGETOOL_SIGN_PASSPHRASE` gives its passphrase). If
something asked for fails, the build fails and leaves no file behind: never an
unsigned AppImage when a signature was asked for.

On the user's machine it needs glibc 2.34 or newer on x86_64, 2.39 or newer on
aarch64 (PySide6 6.12 is only built for that there; any current Fedora) and, only for
X11 sessions, `libxcb-cursor` (Fedora: `xcb-util-cursor`, installed with
Plasma). It does **not** need `libfuse2`. The app id stays `kongui`, as in
`install.sh`, so the window, the menu entry and the icon match either way;
AppStream reports that id as not reverse-DNS, which is accepted.

Checked by hand (2026-11-06, x86_64): it starts with and without `--demo`, saves,
applies, exports and imports, and runs `konsave`, on Fedora KDE (Wayland); `make
appimage` output passes `tools/smoke_test.py` with its own Python and opens every
page and dialog. `tests.test_appimage` checks the recipe (see §8).

### Signing key

The release files are signed with a GPG key kept only in two repository secrets
(*Settings → Secrets and variables → Actions*): `KONGUI_SIGNING_KEY` (the armored
secret key) and `KONGUI_SIGNING_PASSPHRASE`. Its public part is attached to every
release as `kongui-signing-key.asc`.

* **Fingerprint:** `397A B1E6 6805 CDAB 9FB9 971E E4C5 D1C9 CF43 BE52`
  (ed25519, signing only, created 2026-11-07, valid for two years). Users compare
  it with the key attached to a release (README, *Checking the download*): `gpg
  --show-keys --fingerprint kongui-signing-key.asc` must print this line.

Creating it (once, on the owner's computer, not in the repository):

```bash
gpg --quick-gen-key "KonGUI release signing <EMAIL>" ed25519 sign 2y
gpg --list-secret-keys --keyid-format long          # the fingerprint
gpg --armor --export-secret-keys FINGERPRINT > kongui-signing-key.secret.asc
gh secret set KONGUI_SIGNING_KEY < kongui-signing-key.secret.asc
gh secret set KONGUI_SIGNING_PASSPHRASE              # asks for the passphrase
shred -u kongui-signing-key.secret.asc               # do not keep the export
gpg --output kongui-revoke.asc --gen-revoke FINGERPRINT   # keep it offline
```

Keep a backup of the key (and the revocation certificate) offline. When it expires,
extend it with `gpg --quick-set-expire FINGERPRINT 2y`, export it again and update
the secret; the fingerprint stays the same. Before the first signed tag, run the
workflow by hand on `dev` (dry run): with the secrets in place the AppImages come out
signed and validated.

Checked (2026-11-07, cloud container, with a throwaway key): `build.sh` with `SIGN=1`
and `UPDATE_INFORMATION` produced a signed AppImage that AppImageUpdate's `validate`
accepted with the key's fingerprint, and its `.zsync`; with no key it failed and left
no file; the `release` job's commands signed and verified `SHA256SUMS`, and a home with
only the exported public key verified it too; the `appimage` job's smoke-test step ran
as written. The workflow passes `actionlint` (with `shellcheck`). The aarch64 build
was not run here (no ARM machine): its first run is the workflow's.

First dry run on GitHub (`dev`, 2026-11-07, with the real key): the aarch64 AppImage
was built, passed its smoke test and its signature validated with the key above, but
the check step failed: `validate` writes its report to stderr and only stdout went
into `validate.log`. Fixed (`2>&1 | tee`); the step then passed as written, locally.

First tag (`v0.1.0a4`, 2026-11-07): the AppImages were built and smoke-tested, then
the step hung on reading the update information. `APPIMAGE_EXTRACT_AND_RUN=1` was
exported for the whole step, and with it the runtime ignores its own `--appimage-*`
options and starts KonGUI, which never ends offscreen (a dry run skips that tag-only
line). Nothing was published; the run was cancelled and the tag deleted. Now only the
calls that run the app use extract-and-run, every call has a time limit and the job
has `timeout-minutes: 30`. The fixed step passed as written in tag mode, locally.

## 8. Tests

`tests.test_appimage`: the desktop entry (same keys as `install.sh`'s, one main
category, `desktop-file-validate`), the AppStream metadata (points at the desktop
entry; `appstreamcli` finds nothing but the accepted id warning), `AppRun`'s
dispatching and its isolation from the caller's Python, `shellcheck` of the scripts,
and what `trim.py` keeps and removes, including that a lost library fails the build;
`ReleaseWorkflowTests`: both architectures on their own runners, the smoke test and
signature check of each AppImage, a tag without the key failing, the signed
`SHA256SUMS` of every file, the update channel per kind of release and the manual
run being a dry run.


`tests.test_version`:

* `short_version` / `version_label` for a release, a stable release, a build between
  tags, and an unknown version;
* the source holds no version of its own (no `__version__ = "<digits>"`, `setup.py`
  asks `setuptools_scm`);
* in a clean process with a fake installed distribution: a release, a build between
  tags, no distribution at all (`0+unknown`, `dev`), and the original Konsave
  installed (which must not be mistaken for KonGUI);
* the interface: the badge and the sidebar show the short form, only the *About* row
  shows the whole version, an unknown version shows `dev` and never `0+unknown`, and
  the sidebar in Portuguese.

`tests.test_packaging` also covers the build side: `pyproject.toml` declares the
build requirements, `setup_requires` is gone, and (when `git` and `setuptools_scm`
are installed; `requirements_dev.txt` has the latter) a repository made in a
temporary folder with the real `.git_archival.txt` and `.gitattributes` is archived
with `git archive` and its version is asked of `setuptools_scm`: the archive of a tag
gives the tag, the archive of a later commit a `.dev` version, and an archive without
the attribute gives none.

What the tests cannot do is build from a tag. That was checked by hand on a copy of
the repository (the real repository was not tagged): with the tag `v0.1.0a1` the
wheel was `kongui-0.1.0a1-py3-none-any.whl`, `kongui.__version__` was `0.1.0a1` and
`konsave -v` printed `Konsave: 2.2.0+kongui`; an sdist built from the tag, unpacked where there is no `.git`, built a wheel with the same version; after one more commit the wheel was
`kongui-0.1.0a2.dev1+g…` and the interface label `v0.1.0a2.dev1`. The release workflow (§5, step 4)
repeats the version check for every real release.

`tests.test_install_script` runs `install.sh` for real in temporary homes, offline:
fake wheels with a `kongui` command, a fake GitHub served through `file://` URLs
(`KONGUI_DOWNLOAD_BASE`, `KONGUI_API_URL`), no PySide6 (`KONGUI_EXTRAS=""`). It checks
the options, the refusal to run as root, checksum mismatches, the newest-release
lookup (drafts and odd tags skipped), install → open through the link → update →
repair of a broken environment → uninstall (data kept), an installation that
stopped halfway (pip failing after the environment was created, or the environment
left without Python) finished by running the script again or removed by
`--uninstall`, the icons (copied into the
hicolor theme, updated with the release, `Icon=kongui` in the menu entry, removed on
uninstall unless the user changed them; a release without icons installs without an
`Icon=` line), and that a file, a menu entry or a folder the script did not make is
never replaced or deleted. When the script was
written it was also run against the real `0.1.0a1` release, with PySide6.

`tests.test_smoke` runs `tools/smoke_test.py` (the script the workflow uses) in clean
processes: a healthy checkout passes and the process exits normally; `--no-gui`
skips Qt (the icon files are still checked); a checkout has the 9 icon files and
a window icon with 8 sizes; an uninstalled checkout fails the version check; a wrong expected version
fails; the right one passes. `tests.test_packaging` also checks that `setup.py`
packages every icon file and that the `gui` extra limits PySide6 on Python 3.9 ([`LIMITATIONS.md`](LIMITATIONS.md) §5).
