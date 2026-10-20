# Limitations and decisions

One place for what KonGUI does **not** do, what was decided on purpose, and what is
still open. Details of each item are in the document linked next to it; the status
of every requirement is in [`FINAL_AUDIT.md`](FINAL_AUDIT.md).

Written on 2026-10-18, before the first tag or pre-release (how versions and releases work: [`RELEASING.md`](RELEASING.md)). Nothing here is a
promise of a future feature. The release is **ready to be tagged** except for B-3 below.

## 1. Required and still open

| Id | What is missing | Why | Where |
|---|---|---|---|
| B-3 | Validation in a real Fedora KDE / Plasma session: actually applying a profile, Wayland and drag-and-drop, SELinux, Flatpak, fractional scaling | being tested by the project owner; the result is not recorded yet. The automated tests never apply anything to a real session, and the screenshots only show that the interface renders. The script and the report template are in [`PLASMA_TEST_PLAN.md`](PLASMA_TEST_PLAN.md) | [`FINAL_AUDIT.md`](FINAL_AUDIT.md) §3.5 and §7 |
| B-1 | Progress and cancellation of an operation that has already started | the original engine cannot be interrupted and `konsave/` is only changed for the lock and the package rename; the interface only shows "busy" (waiting for the lock *can* be cancelled) | [`INTEGRATION.md`](INTEGRATION.md) §8 |

The other mandatory requirements are implemented and tested: safety copy before
`apply` and `import` (P-1 / RN-01), cross-process lock (P-2), import and export limits
(P-3).

## 2. Decisions of the project owner

| Decision | Consequence | Where |
|---|---|---|
| **No `conf.yaml` management (2026-10-19).** The editor, its backups (`conf.yaml.bak-*`), KonGUI's own validation of the file (errors with line and column, duplicate keys, placeholder checks) and the warning about a `.knsv` whose `conf.yaml` differs from the profile's (A-4) were removed, to stay within Konsave's scope | the user edits `~/.config/konsave/conf.yaml` by hand, as with Konsave (§4). KonGUI still *reads* the file through Konsave's own parser, because the safety copies, the free-space estimates, the sections on the cards and the refusals below need to know where files go | this file, §4 |
| **What a profile includes is chosen by hand**, in `~/.config/konsave/conf.yaml`. The save dialog has no "what to include" check boxes in real mode | the `save` groups of the global `conf.yaml` decide what is saved | §4 |
| **The `conf.yaml` inside a `.knsv` is not rewritten, and there is no warning about it.** Konsave puts the *global* file there while it assembles `save/` and `export/` from the *profile's* file | if they differ the archive contradicts itself: a group added since makes the profile impossible to apply on the other computer (KonGUI refuses and says which group), a group removed since is ignored. Inspecting an archive before importing still lists groups without data | [`FINAL_AUDIT.md`](FINAL_AUDIT.md) A-4 |
| **Safety refusals are kept.** Applying a profile, or importing a `.knsv`, whose `conf.yaml` would write outside the home folder (a `location` outside it, or an entry such as `../x`) is refused, and so is applying a group whose folder and parent folder are both missing | the notice lists the reasons. These are not validation of the user's file: they protect the session from a hostile archive or a profile that would leave the home | [`INTEGRATION.md`](INTEGRATION.md) §10 |
| **No limit on the number of safety copies** and **no automatic pruning** | copies grow until the user deletes them in *Settings → Safety copies → Manage…*. Pruning would remove the oldest copy first, which is the one that holds the original state | [`INTEGRATION.md`](INTEGRATION.md) §9 |
| **The description does not travel in the `.knsv`** and **the `.knsv` format is unchanged** | an imported profile starts without a description | [`INTEGRATION.md`](INTEGRATION.md) §11 |
| **P-3 limits stay fixed constants** | see §3 | [`INTEGRATION.md`](INTEGRATION.md) §10 |
| **Without PySide6, `kongui` shows a raw `ImportError`** for now | the interface needs the `gui` extra: `pip install "kongui[gui]"` | [`README.md`](../README.md) |
| **The package is called `kongui`** (not `Konsave`); author, URL and links in `setup.py` are this repository's | the bundled `konsave` command is still installed; see §5 | [`KONSAVE_PATCHES.md`](KONSAVE_PATCHES.md) §3.5 |
| **`setuptools` is not a runtime dependency** and was removed from `requirements.txt` | it is only needed to *build* the package. Proof: nothing in `kongui/` or `konsave/` imports it, and the whole test suite passes with `setuptools`, `pkg_resources` and `distutils` made unimportable (`tests.test_packaging` checks the imports and the requirements) | [`FINAL_AUDIT.md`](FINAL_AUDIT.md) §5 |

## 3. Import and export limits (P-3)

They protect against a damaged or hostile `.knsv` and against a full disk. They are
**basic protections, not a guarantee**, and are not configurable:

* constants in `kongui/core/safety.py`: file up to **512 MiB**, **2 GiB** really
  decompressed (counted while reading, so a forged header does not help), up to
  **10,000** entries;
* the free-space check is an **estimate** and is **not atomic** with the operation:
  another program can fill the disk in between (a real "no space left" is then
  reported and cleaned up);
* the decompression pass reads the archive once more before importing, which costs
  time for large archives;
* the `export` section is read from the live system, so its size can change between
  the estimate and the copy;
* the safety copy of §2 has no size limit: the limits above apply to the archive,
  not to it;
* the `.knsv` is neither signed nor encrypted, and its `conf.yaml` decides where the
  files go (KonGUI only accepts destinations inside the home): import only archives
  from people you trust;
* the original engine is not interrupted or made atomic, so an import that fails
  halfway is undone by the KonGUI layer, not by the engine.

## 4. How to choose what a profile includes

KonGUI does not ask this when saving and has no screen for it. The rule is
Konsave's own, and so is the tool: a text editor.

1. Open `~/.config/konsave/conf.yaml` in a text editor (Konsave creates it the first
   time; KonGUI creates the same default file before the first save). The `save:`
   groups are what a profile contains; the `export:` groups are only exported with
   it. The default KDE file already lists the usual Plasma settings, the layouts of
   the main KDE apps, and the themes, icons and fonts to export; its `autostart`
   group is empty.
2. Add a group (a name, a `location` and the `entries` inside it), edit one, or remove
   the ones you do not want. **Keep a copy of the file first**: KonGUI does not check
   it or keep backups of it.
3. Save the profile (**Save profile**). The profile gets a copy of `save` as it was
   *at that moment*; profiles saved earlier keep what they had. If the file has a
   mistake, the save fails and the notice shows Konsave's own reason (for example a
   YAML error, or an entry with a `/` in it); nothing is left behind.
4. The cards show what each profile ended up holding (its sections).

Before **exporting** a profile, make sure the global file and the profile's agree
(see A-4 in §2): KonGUI no longer warns about it.

## 5. Package and installation

* The distribution is `kongui` and installs two commands: `kongui` and the bundled
  `konsave`. Both ship a Python package called `konsave`, so **installing KonGUI in
  the same environment as the original Konsave replaces it**; use a virtual
  environment.
* The `konsave` package normally reads its version from the installed distribution
  called `konsave`. With the rename that lookup finds nothing, so a one-line patch
  makes it report `2.2.0+kongui` (the Konsave release this copy derives from)
  when `kongui` is installed. Without it the `konsave` command would fail to start.
  See [`KONSAVE_PATCHES.md`](KONSAVE_PATCHES.md) §3.5.
* `PySide6` is an extra (`pip install "kongui[gui]"`), not a plain requirement. **On
  Python older than 3.12 (3.9, 3.10, 3.11) the extra limits it to 6.8 and 6.9**
  (`PySide6>=6.8,<6.10`). Evidence: on 3.9 with PySide6 6.10.3 the interpreter crashed
  with a segmentation fault when opening *Settings → Safety copies → Manage…* (gdb: in
  PySide6's own signal connection code, `PySide::qobjectConnectCallback`); on 3.11 with
  6.10.3 the GUI tests segfaulted too, and with 6.12.0 every test passed but the test
  process aborted while shutting down (`bool_dealloc: deallocating True or False`,
  `free(): invalid size`; 3.10 the same); with 6.9.3 the whole suite passes and exits
  normally on 3.9, 3.10 and 3.11 (6.8.3 on 3.9). These are bugs of the PySide6
  releases, not found in KonGUI's code; Python 3.12 or newer (where `True`/`False`
  are immortal objects) takes the newest PySide6 (6.12 was tested on 3.12, 3.13, 3.14).
  `tests.test_packaging` checks that the limit is declared. If you install PySide6
  by hand (not through the extra) on Python older than 3.12, use 6.9 or older.
* Python versions: the suite was run on 3.9, 3.10, 3.11, 3.12, 3.13 and 3.14
  ([`FINAL_AUDIT.md`](FINAL_AUDIT.md) §6).
* The version comes from the git tag only: `setuptools_scm` computes the package
  version and `kongui.__version__` reads it from the installed package, so they can
  not disagree ([`RELEASING.md`](RELEASING.md)). A checkout that was never installed
  reports `0+unknown` and the interface shows `dev`; a build between two tags is a
  `.devN` version. `setuptools_scm` is declared as a build requirement in
  `pyproject.toml`. Building needs the git history and tags, an sdist, or an archive
  made by `git archive` (GitHub's "Source code" files carry the version through
  `.git_archival.txt`). A copy of the working tree made by hand, with no `.git`,
  can not be built: use a clone or an sdist.
* **KonGUI is not published to PyPI.** The old `.github/workflows/deploy.yml` (any
  `v*` tag → PyPI) was replaced by `.github/workflows/release.yml`, which builds the
  wheel and the sdist, tests the wheel in a clean environment and creates a GitHub
  *pre-release* with the files and `SHA256SUMS`. It was tested step by step on a
  scratch repository but **never on real GitHub Actions**; see
  [`RELEASING.md`](RELEASING.md) §5.
* The build prints two warnings that do not fail it: the licence classifier is
  deprecated in favour of an SPDX expression, and `kongui.gui.translations` is "absent
  from `packages`" (it holds only the `.ts` and `.qm` files, which are included
  through `package_data`; the wheel was checked to contain them).
* There is no AppImage, no RPM and no Flatpak; the pre-release is a wheel and an sdist.

## 6. Inherited from Konsave (not fixed here)

* `apply` merges folders: files that are not in the profile stay; it is **not atomic**
  (the safety copy is what allows going back).
* The executable bit and file metadata do not survive the export → import cycle;
  symbolic links become files.
* `import` needs the destination folder of every `export` group to exist already.
* Konsave records no "active" profile: the one shown as active is only the last one
  applied from this interface.
* The engine reads `~/.config` directly (`XDG_CONFIG_HOME` is not supported).
* The default `conf.yaml` is picked with `XDG_CURRENT_DESKTOP == "KDE"`; a composite
  value such as `KDE:GNOME` picks the generic one.

## 7. Interface

* Notices and activity entries already on screen keep the language they were written
  in when you switch language; messages that come from the bundled Konsave are
  translated by matching their English text.
* Programs that do not use the lock (Plasma itself, a text editor) are not covered by
  the cross-process lock.
* Demo mode (`--demo`) shows things real mode does not (for example the "what to
  include" check boxes in the save dialog); its data is fictitious and English.
* A mistake in `conf.yaml` is only found when an operation reads it (saving reports
  Konsave's reason). A placeholder that matches no folder (`${ENDS_WITH="…"}`) is
  read as Konsave reads it, as literal relative text: the group is saved empty, and
  applying the profile is refused (that location is not inside the home), so nothing
  is written.
