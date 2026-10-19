# Versions and releases

How the version of KonGUI is defined, where it is shown, and the steps for a
release. **No tag has been created yet**; this document describes the rule so the
first one follows it. What is still open before the first tag is in
[`LIMITATIONS.md`](LIMITATIONS.md) §5.

## 1. One source: the git tag

The version is not written in any source file. It comes from the **git tag**:

```
git tag v0.1.0a1  ──setuptools_scm──▶  package version 0.1.0a1  ──importlib.metadata──▶  kongui.__version__
```

* `setup.py` uses `use_scm_version=True` (build time): the wheel and the sdist get
  the version computed from the tag.
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
is merged into `master` (only when a version is complete).

1. Check that `master` is clean and passes the whole suite as a regular user
   (`python3 -m unittest discover -s tests -t .`), `black --check` and `pylint kongui`.
2. Put the changes of the release in `CHANGELOG.md` (move `[Unreleased]` under the new
   version) and update the status line in `README.md`.
3. Create an **annotated** tag on `master`: `git tag -a v0.1.0a1 -m "KonGUI 0.1.0a1"`.
4. Build from that tag, in a clean virtual environment with `setuptools` 75 or newer
   (`python -m build --wheel --sdist`). Both files must be named `kongui-0.1.0a1…`.
   The build needs the git history and the tag (`git fetch --tags`; in a CI checkout
   use `fetch-depth: 0`). An sdist carries its version and can be built without
   `.git`.
5. **Check that the tag and the version agree**: install the wheel in a clean
   environment and run
   `python -c "import kongui; print(kongui.__version__)"`; it must print the tag
   without the `v`. If it prints a `.dev` version, the tag is not on the built commit.
6. Push the tag (`git push origin v0.1.0a1`) and attach the files to a GitHub
   *pre-release* (alphas, betas and release candidates are always pre-releases).

> **Do not push a tag before the release workflow is dealt with:**
> `.github/workflows/deploy.yml` publishes to PyPI on any tag `v*`
> ([`LIMITATIONS.md`](LIMITATIONS.md) §5).

## 4. Tests

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

What the tests cannot do is build from a tag. That was checked by hand on a copy of
the repository (the real repository was not tagged): with the tag `v0.1.0a1` the
wheel was `kongui-0.1.0a1-py3-none-any.whl`, `kongui.__version__` was `0.1.0a1` and
`konsave -v` printed `Konsave: 2.2.0+kongui`; an sdist built from the tag, unpacked where there is no `.git`, built a wheel with the same version; after one more commit the wheel was
`kongui-0.1.0a2.dev1+g…` and the interface label `v0.1.0a2.dev1`. Step 5 above repeats
this for every real release.
