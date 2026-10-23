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
every `v*` tag; **KonGUI is not published to PyPI**). It runs only when a tag
`v[0-9]*` is pushed, with read-only permissions except in the last job.

Job `build`:

1. reads the version from the tag and refuses anything that is not PEP 440 in the
   forms `v0.1.0a1`, `v0.1.0b1`, `v0.1.0rc1`, `v0.1.0` (`a`, `b` and `rc` mean
   *pre-release*);
2. refuses a tag whose commit is not on `master`;
3. builds the sdist and the wheel (`python -m build`, with the whole history:
   `fetch-depth: 0`) and checks that their file names carry the version of the tag;
4. installs the wheel in a clean virtual environment and runs
   `tools/smoke_test.py --no-gui --expect-version <version>` from another folder:
   the package reports the tag's version, the bundled `konsave` command starts and
   the application icon files were packaged (the window and translation checks are left out because a CI runner has no Qt
   system libraries);
5. installs the wheel with `install.sh --wheel` in a temporary home (without
   PySide6), checks the `kongui` link, the menu entry, its `Icon=kongui` line and the
   copied icons, and uninstalls it (the icons go too);
6. copies `install.sh` into `dist/`, writes `SHA256SUMS` (which lists it too) and
   uploads `dist/` as a workflow artifact.

Job `release` (the only one with `contents: write`): creates the GitHub release
(`gh release create --verify-tag`) with the files of `dist/`, the text of
`.github/release-notes.md` (the alpha warning) and `--prerelease` when the tag is an
`a`, `b` or `rc`.

What was tested: the steps of `build` were executed on a scratch repository (a branch
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
  [`FINAL_AUDIT.md`](FINAL_AUDIT.md) §7 (script: [`PLASMA_TEST_PLAN.md`](PLASMA_TEST_PLAN.md)),
  and has no blocker (2026-10-22, quick test).
* [x] `dev` is merged into `master`, and `master` passes the whole suite on the
  system Python and in a virtual environment (§3, step 1; PR #15, 805 tests OK on
  2026-10-22). The suite also ran on
  Python 3.9 to 3.14 ([`FINAL_AUDIT.md`](FINAL_AUDIT.md) §6).
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
  for `0.1.0a1` on Linux with Qt offscreen, on Python 3.11, 3.13 and 3.14
  ([`FINAL_AUDIT.md`](FINAL_AUDIT.md) §6).
* [ ] The same on a Fedora KDE desktop, with `kongui --demo` in a real window (left
  to the owner for `0.1.0a1`).
* [ ] From `0.1.0a2` on: the release also lists `install.sh`, `SHA256SUMS` covers it,
  and `bash install.sh --release <version>` installs that release on a desktop.
* [ ] From the first release after `0.1.0a2` on: after `install.sh`, the menu entry,
  the window and the task manager show the KonGUI icon.
* [x] Download GitHub's own *Source code (zip)*, unpack it where there is no `.git`,
  run `pip wheel --no-deps .` and check the version (`0.1.0a1`, §4).

For the next release, copy this checklist and start again with every box empty.

## 7. Tests

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
