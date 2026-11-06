# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- (KonGUI) `kongui/core/categories.py`: a catalog of 12 export categories (system, panels, themes, icons, wallpaper, fonts, apps, window management, GTK, shortcuts, autostart, other) that classify Konsave's `save`/`export` entries one by one, finer-grained than Konsave's own groups; `validate_categories`, `categorize`, `build_catalog` and `filter_groups` work on the already-resolved configuration (`ConfigService.resolve()`). A small dependency table (`CATEGORY_DEPENDENCIES`) records which category needs another to make sense (icons/wallpaper/fonts/themes all need system). See `docs/INTEGRATION.md` §12. Tests: `tests.test_categories`
- (KonGUI) `ProfileService.save()` accepts `categories` and `excluded_entries`: when given, the profile is saved from a temporary, filtered copy of the active configuration instead of the active one, so it only contains the chosen categories (and any individually excluded entries within a kept category); the active `~/.config/konsave/conf.yaml` is only ever read, never written. `categories=None` (the default) is unchanged behavior. Because Konsave's `export()` reads a profile's `export` groups from the profile's own stored `conf.yaml`, a selectively-saved profile also exports only what was selected, with no change to `export()` itself. Tests: `tests.test_profile_service_mocked.SaveTests`, `tests.test_profile_service_integration.SaveIntegrationTests` (end to end against the real Konsave code, including a selective save that is exported and re-imported)
- (KonGUI patch) `konsave/funcs.py`: `save_profile` takes an optional `config_path`, the configuration file to read and copy as the profile's `conf.yaml` instead of the active `CONFIG_FILE`; without it, behavior is unchanged. See `docs/KONSAVE_PATCHES.md` §3.6
- (KonGUI) `ServiceBackend.save()` no longer discards its `sections` argument: it is now passed through to `ProfileService.save()` as `categories`, so the real backend saves a filtered profile when given category keys. `Capabilities.sections` is now `True` for `ServiceBackend`. Tests: `tests.test_gui_real_backend.RealSaveTests`
- (KonGUI) **Save profile** now lets you choose what goes into a profile: `ProfileDialog` offers the 12 export categories as checkboxes (translated labels, via a new `kongui.gui.messages.SECTION_LABELS` extension), with **Select all** / **Clear all** buttons, a non-blocking warning when a checked category needs another that is not checked (e.g. Icons and Cursors needs System Settings), and a running summary of what will be included. The chosen categories reach `ProfileService.save()` through `ServiceBackend.save()` above; saving without touching any checkbox still saves everything, as before. Demo mode's save dialog and "import preview" now use the same 12 categories instead of seven fictitious area names (`kongui/gui/mock_data.py`'s `sections()` is unchanged and still backs only the seven ready-made demo profiles shown on first launch). See `docs/INTEGRATION.md` §11 and §12. Tests: `tests.test_gui_widgets.DialogTests`, `tests.test_i18n`
- (KonGUI) `kongui.core.profilemeta.profile_categories()`: re-derives a profile's export categories entry by entry from its own saved `conf.yaml` (`save` entries that are actually present in the profile, plus every `export` entry it lists, since Konsave only ever copies `export` files in at export time) — read-only, nothing is written or changed in the profile or in `conf.yaml`. `ProfileDetails` gets a new `categories` field carrying this. **Fixes the profile cards always showing a single generic "Desktop settings" badge** regardless of which categories were chosen at save time: `ServiceBackend.list_profiles()` now prefers `categories` for a profile's badges (falling back to the coarse Konsave `save` group names, `sections`, only when nothing is recognized at all), so a profile saved with System and GTK checked shows exactly those two badges instead of the one group name ("configs") they both happened to live inside — and this applies to every profile, not only a selectively-saved one. One behavior change: a custom, hand-added group with entries the catalog does not recognize now shows as "Other settings" rather than under its own group name. See `docs/INTEGRATION.md` §11. Tests: `tests.test_profile_details.CategoriesTests`, `tests.test_gui_details.SectionChipsTests`

This lands the whole selective-save feature end to end: the 12-category catalog
and filtering, the Konsave patch, the service layer, the real backend, the save
dialog, and accurate per-category badges on every profile card. What is still
not offered is picking individual files within a category (see
`docs/LIMITATIONS.md` §4).

### Fixed
- (KonGUI) `kongui/gui/widgets/common.py`: `Badge` (the profile card chips) could show raw, un-ellipsized, truncated text — missing characters from *both* ends, e.g. "Panels and desktop layout" rendered as "s and desktop l" — during interactive window resizing. The elision was only recomputed on `resizeEvent`, which caches the shown text for the width known at that moment; a live, continuous drag can deliver a paint for a width the last `resizeEvent` hasn't caught up to yet, so the stale, wrongly-sized string got centered and clipped by the real (narrower) paint rect instead of being elided for it. `Badge` now also re-checks and, if needed, recomputes the elision in a `paintEvent` override, immediately before painting, so what is drawn always matches the widget's true current width — closing the race regardless of how many resizes land between two paints. Tests: `tests.test_gui_widgets.CommonWidgetTests.test_badge_elides_long_text_when_too_narrow`, `tests.test_gui_widgets.CommonWidgetTests.test_badge_reelides_at_paint_time_if_the_cached_width_is_stale`
- (KonGUI) Profile card chips also all shrank together once they stopped fitting as a group, so a card could show three half-elided badges side by side even when the first one or two would have fit at their full width with room to spare — and, because the old `QHBoxLayout` row was never actually given the card's full width, no badge showed its full text even with the window maximized. New `kongui/gui/widgets/common.py::BadgeRow` lays badges out by priority instead: each one gets its full width as long as there's room left, only the first one that doesn't fully fit is elided (to whatever space remains), and any badge after that is hidden rather than squeezed to an unreadable sliver — this also fixed an off-by-one in `Badge.sizeHint`/`minimumSizeHint` where `QFontMetrics.elidedText` could still elide a string given exactly its own measured width. `kongui/gui/widgets/cards.py::ProfileCard` uses `BadgeRow` for its chips row, and the overflow "+N" badge's tooltip now lists every section the profile covers (not just the hidden ones), so hovering it tells the whole story regardless of which other badges got elided. Tests: `tests.test_gui_widgets.CommonWidgetTests` (`BadgeRow` layout cases), `tests.test_gui_details.SectionChipsTests.test_more_than_max_chips_gets_an_overflow_badge_listing_every_section`
- (KonGUI) Section badges, now the same everywhere (profile cards, the Dashboard's **Active profile** card, and the **Import** preview): `BadgeRow` (`kongui/gui/widgets/common.py`) now takes the labels and shows at most 3 of them at full width, followed by a "+N" badge counting every section left out. The Dashboard card used to show one badge per section, so with many sections they all collapsed into a row of bare "…"; it now uses the same row. The "+N" badge could also disappear when the window was resized; its room is now reserved first, so it is always visible and never cut off, and a badge that does not fit is counted in "+N" instead of being shown elided (only the first badge is ever elided, when not even it fits next to "+N"). Hovering "+N" lists every section. New `kongui.gui.messages.section_short_label` gives the badge text (the section name without the explanation in parentheses).
- (KonGUI) **Save current profile** / **New profile** dialog: on a short screen or with a long "Will include" summary, "What to include" was drawn over the description box and the summary over the **Cancel** / **Save** buttons. Only the list of section checkboxes now scrolls (a `QScrollArea`); the heading, **Select all** / **Clear all**, the summary and the buttons stay fixed, and `BaseDialog.fit_wrapped_labels()` reserves each wrapped text's real height at the current width, so no dialog can be squeezed shorter than its text. Checked by an overlap scan of every page (Dashboard, Profiles in grid and list, Import / Export, Settings, About) and dialog (confirmation, conflict, details, safety copies) at their minimum sizes; no other overlap was found.
- (KonGUI) Segmented controls (Settings: language, theme, default view; Profiles: grid / list): the selected option is drawn in semibold, but Qt sized every option for regular text, so the selected label was clipped at both ends (most visible on "English" with wide fonts such as Noto Sans). `Button` now reserves the semibold width for `segment` buttons in `sizeHint` (and so in the minimum size), in both states, so selecting an option no longer makes the control jump either.

### Changed
- (KonGUI) Repository and documentation cleanup. The README was rewritten to be shorter and current (it still said choosing what goes into a profile was not offered). `CONTRIBUTION.md`, still upstream Konsave's text (it pointed to a `konsave/vars.py` that no longer exists), became a KonGUI `CONTRIBUTING.md`. `docs/GUI_PROTOTYPE.md` and `docs/GUI_SERVICES.md` were merged into `docs/GUI.md`. `docs/TEST_OVERVIEW.md` now explains how to run the suite (as a regular user) and holds the Python/PySide6 matrix. `docs/PLASMA_TEST_PLAN.md` now holds the real-session results. The screenshots moved to `docs/screenshots/`. This changelog now keeps only KonGUI's releases and links to Konsave's own history.

### Removed
- (KonGUI) `docs/FINAL_AUDIT.md`, an out-of-date status snapshot that cited four removed modules; its still-useful parts moved to `docs/LIMITATIONS.md`, `docs/TEST_OVERVIEW.md` and `docs/PLASMA_TEST_PLAN.md`. Also removed: `docs/reports/` (its only report is summarized in `docs/PLASMA_TEST_PLAN.md`), `.vscode/settings.json` (editor settings with keys VS Code no longer reads), and a `package_data` entry in `setup.py` for a `config` package that does not exist (the wheel's contents are unchanged).

## [0.1.0a3] - 2026-10-23
Third alpha (GitHub pre-release). Adds the application icon.

### Added
- (KonGUI) Application icon: `kongui/gui/data/icons/hicolor` (`kongui.png` in 8 sizes, 16–512 px, and `kongui.svg`), packaged with the wheel. It is the window icon, the mark at the top of the side bar and the logo of the About page (`icons.app_icon()`, drawn by `widgets.common.AppLogo` at the screen's pixel ratio). See `docs/GUI_PROTOTYPE.md` §3

### Changed
- (KonGUI) `install.sh` copies the icon into `~/.local/share/icons/hicolor` and the menu entry gets `Icon=kongui` and `StartupWMClass=kongui`; `--uninstall` removes the icon files that are still the installed ones. Releases without an icon (0.1.0a1, 0.1.0a2) still install, with a generic icon
- (KonGUI) The smoke test checks the icon files (also with `--no-gui`) and the window icon; the release workflow checks the icon installed by `install.sh`

### Fixed
- (KonGUI) `install.sh`: an installation that stopped halfway (pip without network, for example) left `~/.venvs/kongui` without the `kongui` command, and the script then refused that folder as "not KonGUI's environment" until it was deleted by hand. The script now leaves a `.kongui-install` marker in the folder before creating the environment, so running it again finishes the installation (or `--uninstall` removes it); environments of the older script get the marker on the next run. A folder without the marker or the `kongui` command is still never touched; the message now says how to delete it if it is a failed installation

## [0.1.0a2] - 2026-10-23
Second alpha (GitHub pre-release). **The program is the same as in 0.1.0a1**: this
release adds `install.sh` to the release files (listed in `SHA256SUMS`) and brings the
updated documentation into the source distribution.

### Added
- (KonGUI) `install.sh`: installs KonGUI for the current user (no root): downloads the newest release, or `--release VERSION`, or takes `--wheel FILE`; checks it against `SHA256SUMS`; installs it with PySide6 in `~/.venvs/kongui`; links the `kongui` command into `~/.local/bin` (never `konsave`) and adds a menu entry (no icon yet). Running it again updates (and remakes a broken environment); `--uninstall` removes it and keeps `~/.config/konsave`. It never replaces a file, menu entry or folder it did not make. The release workflow tests it and attaches it to each release (in `SHA256SUMS`). Tests: `tests/test_install_script.py`

### Changed
- (KonGUI) README, *Installing the pre-release*: rewritten as install once / open every time / update / uninstall. The install block now also links the `kongui` command into `~/.local/bin` and adds a Plasma menu entry, so the app opens later without activating the virtual environment (before, it only opened in the terminal where it was installed). The release notes point to it
- (KonGUI) Documentation records the publication of `0.1.0a1` and its post-release checks (`docs/FINAL_AUDIT.md` §6, `docs/RELEASING.md` §6)

## [0.1.0a1] - 2026-10-22
First KonGUI release (alpha, GitHub pre-release). Versions below 0.1.0a1 are those of
the original Konsave.

### Added
- (KonGUI) Interface language: English and Brazilian Portuguese with Qt translations, first-run detection from the system locale, a *Settings → Language* selector and live switching. See `docs/GUI_PROTOTYPE.md`
- (KonGUI patch) Cross-process lock, `konsave/lock.py` + `konsave/__main__.py`: commands wait for other Konsave operations (`KONSAVE_LOCK_TIMEOUT`, exit code 75 on timeout). See `docs/KONSAVE_PATCHES.md`
- (KonGUI) Protections for `.knsv` import and export: size (512 MiB), real decompressed size (2 GiB), entry count (10,000), free-space check before import and export, clear messages for corrupted archives and full disks. The format and the engine are unchanged. See `docs/INTEGRATION.md` §10
- (KonGUI) Profile description (a small file inside the profile folder, not part of the `.knsv`) and sections read from each profile's `conf.yaml`, with friendly names for the default groups and an *Edit details…* action. See `docs/INTEGRATION.md` §11
- (KonGUI) Interface screenshots (demo mode, Fedora 44) in `screenshots/`, shown in the README
- (KonGUI) `docs/LIMITATIONS.md`: one document with the open requirements, the decisions of the project owner and the known limits (including those of the import and export protections); README section on choosing what a profile includes (manual: `conf.yaml` edited by hand)
- (KonGUI) `tests/test_packaging.py`: package name and metadata, no `setuptools` at runtime, version of the bundled engine
- (KonGUI) `docs/RELEASING.md` and `tests/test_version.py`: how the version is defined (git tag), what it looks like between tags, and the release steps

- (KonGUI) Release workflow `.github/workflows/release.yml` (replaces `deploy.yml`, which published to PyPI): on a tag `v*` it checks that the tag is a PEP 440 version on `master`, builds the sdist and wheel, installs the wheel in a clean environment, runs `tools/smoke_test.py`, writes `SHA256SUMS` and creates a GitHub *pre-release* (for `a`, `b`, `rc`). `.github/release-notes.md` is the alpha warning. Not yet run on real GitHub Actions. See `docs/RELEASING.md` §5
- (KonGUI) `tools/smoke_test.py` and `tests/test_smoke.py`: version, bundled `konsave` command, translation catalogs and main window of an installed build, and a normal exit of the process
- (KonGUI) `docs/PLASMA_TEST_PLAN.md`: script and report template for the real Plasma session (B-3); README section *Installing the pre-release*; pre-release checklist in `docs/RELEASING.md` §6
- (KonGUI) Issue templates for this repository (KonGUI version, Python and PySide6, Plasma, Wayland or X11, demo or real, safety copy), replacing the ones inherited from Konsave

- (KonGUI) `tests/test_gui_overview.py`: four tests that chain every feature through the real interface and dialogs down to the real services in a temporary home (save, apply, safety copy restore, details, overwrite, export with conflict, remove, import by drag and drop, clear all, a `conf.yaml` edited by hand, the `kongui` command's assembly with its worker thread, preferences after a restart); `docs/TEST_OVERVIEW.md` maps each feature to its tests and records the review of the suite

- (KonGUI) First report of a real Plasma session (Fedora 44, Plasma 6.7.5, Wayland, 2026-10-22): no blocker; X11, SELinux and Flatpak not tested yet. `docs/reports/2026-10-22-plasma-session.md`, summarized in `docs/FINAL_AUDIT.md` §7. New *Plasma test report* issue template so users can send theirs (`docs/PLASMA_TEST_PLAN.md`)

### Changed
- (KonGUI) The `gui` extra limits PySide6 to 6.8–6.9 on Python older than 3.12 (PySide6 6.10 and newer segfault or abort there); Python 3.12 or newer takes the newest PySide6. See `docs/LIMITATIONS.md` §5
- (KonGUI) `Makefile`: `black` and `pylint` now cover `kongui`, `tests` and `tools` (they covered only `konsave`); new `smoke` and `dist` targets
- (KonGUI) The test suite no longer needs Python 3.10's `assertNoLogs`, and the Qt windows are released before the interpreter shuts down
- (KonGUI) `kongui.__version__` is no longer a constant (`0.1.0.dev0`): it is the version of the installed package, taken from the git tag by `setuptools_scm`. A checkout that was never installed reports `0+unknown`, shown as `dev`. The badge in *About* and the sidebar caption show the short form (no commit part); *About → KonGUI version* shows the whole version. The sidebar caption texts changed (`{version} · real profiles`, `{version} · fictitious data`)
- (KonGUI) `setuptools_scm` is declared as a build requirement in a new `pyproject.toml` (`[build-system]`) instead of `setup_requires`; `.git_archival.txt` and `.gitattributes` let a `git archive` (GitHub's "Source code" files of a tag) be built without `.git` and still get the version of the tag. `requirements_dev.txt` lists `setuptools_scm`. See `docs/RELEASING.md` §4
- (KonGUI) The distribution is now called `kongui` (it was `Konsave`); author, URL and project links in `setup.py` point to this repository and credit Konsave. The `konsave` and `kongui` commands are both still installed
- (KonGUI patch) `konsave/__init__.py`: when the package is installed as `kongui`, `konsave.__version__` is `2.2.0+kongui` instead of missing (without it the `konsave` command failed to start). See `docs/KONSAVE_PATCHES.md` §3.5
- (KonGUI) `setuptools` removed from `requirements.txt`: nothing imports it at runtime (checked by `tests.test_packaging` and by running the suite with it made unimportable); it stays a build tool
- (KonGUI) The fictitious data of `--demo` mode (profile names, descriptions, areas, activity) is now always English and no longer part of the translation catalogs; the interface stays translated
- (KonGUI) The interface texts are now written in English in the code and translated to Portuguese through `kongui/gui/translations`; `Makefile` has a `translations` target
- (KonGUI patch) `python_requires` is now `>=3.9`
- Reorganized CLI arguments into logical groups (Profile Management, Import & Export, Options, Miscellaneous) for better readability
- Improved all help messages with clearer and more descriptive text

### Removed
- (KonGUI) Everything that managed `conf.yaml`, to stay within Konsave's scope: the *Edit .YAML* page (so the pages are now five and `Ctrl+5` opens *About*), the comment-preserving editor (`kongui/core/confedit.py`, `kongui/core/yamlmap.py`), the `conf.yaml.bak-*` backups and their restore, KonGUI's own validation of the file (errors with line and column, duplicate keys, placeholder checks) and the warning about a `.knsv` whose `conf.yaml` differs from the profile's. `ConfigService` keeps only `ensure_default_config` and `resolve` (reading through Konsave); `ConfigValidationError` became `ConfigError` (with `details`). The user edits `~/.config/konsave/conf.yaml` by hand, as with Konsave; a mistake is reported when saving, with Konsave's reason. The safety copies, the free-space checks, the sections and the refusal of archives or profiles that would write outside the home are unchanged. See `docs/LIMITATIONS.md` §2 and §4

### Fixed
- (KonGUI) A refused apply or import could be reported with no reason: errors the service adds after validating the `conf.yaml` (a destination whose parent folder does not exist, a destination outside the home) were dropped from the notice when the file only had warnings. They are now listed. See `docs/TEST_OVERVIEW.md` §3

## Konsave 2.2.0 and earlier
KonGUI starts from Konsave 2.2.0 (2023-01-31). The history of Konsave itself is in the
[original project's changelog](https://github.com/Prayag2/konsave/blob/master/CHANGELOG.md).
