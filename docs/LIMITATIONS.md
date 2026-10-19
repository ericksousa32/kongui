# Limitations and decisions

One place for what KonGUI does **not** do, what was decided on purpose, and what is
still open. Details of each item are in the document linked next to it; the status
of every requirement is in [`FINAL_AUDIT.md`](FINAL_AUDIT.md).

Written on 2026-10-18, before the first tag or pre-release (how versions and releases work: [`RELEASING.md`](RELEASING.md)). Nothing here is a
promise of a future feature.

## 1. Required and still open

| Id | What is missing | Why | Where |
|---|---|---|---|
| B-3 | Validation in a real Fedora KDE / Plasma session: actually applying a profile, Wayland and drag-and-drop, SELinux, Flatpak, fractional scaling | being tested by the project owner; the result is not recorded yet. The automated tests never apply anything to a real session, and the screenshots only show that the interface renders | [`FINAL_AUDIT.md`](FINAL_AUDIT.md) §3.5 and §7 |
| B-1 | Progress and cancellation of an operation that has already started | the original engine cannot be interrupted and `konsave/` is only changed for the lock and the package rename; the interface only shows "busy" (waiting for the lock *can* be cancelled) | [`INTEGRATION.md`](INTEGRATION.md) §8 |

The other mandatory requirements are implemented and tested: safety copy before
`apply` and `import` (P-1 / RN-01), cross-process lock (P-2), import and export limits
(P-3).

## 2. Decisions of the project owner

| Decision | Consequence | Where |
|---|---|---|
| **What a profile includes is chosen by hand**, in *Edit .YAML*. The save dialog has no "what to include" check boxes in real mode | the `save` groups of the global `conf.yaml` decide what is saved; see §4 below for the steps | [`GUI_CONFIG.md`](GUI_CONFIG.md) §7 |
| **The `conf.yaml` inside a `.knsv` is not rewritten.** Konsave puts the *global* file there while it assembles `save/` and `export/` from the *profile's* file | if they differ the archive contradicts itself. KonGUI **warns** on export and when inspecting an archive (`+` only in the active one, `-` only in the profile, `~` changed) and does nothing else | [`FINAL_AUDIT.md`](FINAL_AUDIT.md) A-4 |
| **No limit on the number of safety copies** and **no automatic pruning** (also of the `conf.yaml` backups) | copies and backups grow until the user deletes them: safety copies in *Settings → Safety copies → Manage…*; the `conf.yaml` backups are the files `conf.yaml.bak-*` next to it in `~/.config/konsave/` and have no delete button (remove them by hand). Pruning would remove the oldest copy first, which is the one that holds the original state | [`INTEGRATION.md`](INTEGRATION.md) §9, [`GUI_CONFIG.md`](GUI_CONFIG.md) §6 |
| **The description does not travel in the `.knsv`** and **the `.knsv` format is unchanged** | an imported profile starts without a description | [`INTEGRATION.md`](INTEGRATION.md) §11 |
| **P-3 limits stay fixed constants** | see §3 | [`INTEGRATION.md`](INTEGRATION.md) §10 |
| **Without PySide6, `kongui` shows a raw `ImportError`** for now | the interface needs the `gui` extra: `pip install "kongui[gui]"` | [`README.md`](../README.md) |
| **A `conf.yaml` in YAML *flow* style stays as it is**: the editor falls back to regenerating the text, which **loses the comments**, and asks for explicit confirmation first | none beyond the confirmation | [`GUI_CONFIG.md`](GUI_CONFIG.md) §2 |
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

KonGUI does not ask this when saving. The rule is Konsave's own:

1. Open **Edit .YAML**. The `save:` groups are what a profile contains; the
   `export:` groups are only exported with it.
2. Add a group (a name, a `location` and the `entries` inside it) or edit one, or
   remove the ones you do not want, then save the file. The editor validates it first
   and keeps a backup of the previous version.
3. Save the profile (**Save profile**). The profile gets a copy of `save` as it was
   *at that moment*; profiles saved earlier keep what they had.
4. The cards show what each profile ended up holding (its sections).

Before **exporting** a profile, make sure the global file and the profile's agree
(see the A-4 warning above). Step-by-step detail and the reasons are in
[`GUI_CONFIG.md`](GUI_CONFIG.md) §7.

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
* `PySide6` is an extra (`pip install "kongui[gui]"`), not a plain requirement.
* The version comes from the git tag only: `setuptools_scm` computes the package
  version and `kongui.__version__` reads it from the installed package, so they can
  not disagree ([`RELEASING.md`](RELEASING.md)). A checkout that was never installed
  reports `0+unknown` and the interface shows `dev`; a build between two tags is a
  `.devN` version. `setuptools_scm` is declared as a build requirement in
  `pyproject.toml`. Building needs the git history and tags, an sdist, or an archive
  made by `git archive` (GitHub's "Source code" files carry the version through
  `.git_archival.txt`). A copy of the working tree made by hand, with no `.git`,
  can not be built: use a clone or an sdist.
* `.github/workflows/deploy.yml` still publishes to PyPI on any tag `v*`. It must be
  changed or disabled **before** the first tag.

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
