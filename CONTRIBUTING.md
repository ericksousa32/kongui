# Contributing to KonGUI

Thank you for helping. Bug reports, test reports and ideas are welcome as issues;
please discuss larger changes in an issue before starting.

## Reporting

- **Bugs:** use the *Bug report* issue template and include the version shown in
  *About*.
- **How it behaved on your Plasma session:** use the *Plasma test report* template.
  The checklist is in [`docs/PLASMA_TEST_PLAN.md`](docs/PLASMA_TEST_PLAN.md);
  "not tested" is a useful answer.
- **Ideas:** use the *Feature request* template.

## Setting up

```bash
git clone https://github.com/ericksousa32/kongui.git
cd kongui
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[gui,dev]"
```

Linux only, Python 3.9 or newer. Use a virtual environment: the package also
installs a Python package named `konsave`, which would replace an existing Konsave.

## Branches

- `master` only receives merges from `dev`; releases are tagged on `master`.
- Start every change on a new branch from `dev` (for example `fix/…`, `feat/…`,
  `chore/…`) and open the pull request against `dev`.

## Rules

1. **Never change the `.knsv` format** or the profile folder layout: KonGUI must
   stay compatible with Konsave.
2. **`konsave/` gets only minimal patches.** Every changed line carries a
   `KONGUI-PATCH(…)` marker and is listed in
   [`docs/KONSAVE_PATCHES.md`](docs/KONSAVE_PATCHES.md). Put new logic in
   `kongui/core/` instead.
3. **Tests only in temporary folders.** Tests must never read or write the real
   home folder or apply anything to the running session; use the helpers in
   `tests/helpers.py` and `tests/gui_helpers.py`.
4. **Update the documentation with the change:** the relevant file in `docs/` and a
   line under `[Unreleased]` in [`CHANGELOG.md`](CHANGELOG.md).
5. **Do not bump versions by hand.** The version comes from the git tag
   (`setuptools_scm`); see [`docs/RELEASING.md`](docs/RELEASING.md).

## Before opening a pull request

```bash
QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests -t .   # or: make tests
make smoke      # the app starts and opens a window (offscreen)
make fmt        # black, then pylint (aim for 10.00/10)
```

Run the tests as a **regular user**, not root: as root, the tests that write files
are skipped, so a green run proves much less. `tests/test_docs.py` also checks that
the public API and every test module are mentioned in `docs/`.

Code style: [PEP 8](https://peps.python.org/pep-0008/) formatted with
[black](https://github.com/psf/black), a [pylint](https://pylint.org/) score of
10.00/10, and a docstring on every function in the
[Google style](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings).

## Interface texts and translations

Interface texts are written in English and translated to Brazilian Portuguese with
Qt translations (`kongui/gui/translations/`). After adding or changing a text:

```bash
make translations
```

Then translate any message left `unfinished` in `kongui_pt_BR.ts` and run
`make translations` again to rebuild the `.qm` catalogs. The tests fail while a
message is untranslated. More in [`docs/GUI.md`](docs/GUI.md).

## Code of conduct

Be respectful and constructive. Harassment or personal attacks of any kind are not
accepted. Problems can be reported to the repository owner.
