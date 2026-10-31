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

This lands the whole selective-save feature end to end: the 12-category catalog
and filtering, the Konsave patch, the service layer, the real backend, and the
save dialog. What is still not offered is picking individual files within a
category (see `docs/LIMITATIONS.md` §4).

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

## [2.2.0] - 2023-01-31
### Added
- You can now set the output directory and archive name when exporting a profile ([#72](https://github.com/Prayag2/konsave/pull/72))
- Profiles will now be listed in alphabetical order (#67)

### Fixed
- Fixed typo in README (#48)

### Changed
- Improved README (#75)
- Made it clear that a profile needs to be saved before exporting in the help text.
- Logs will now be saved to `$HOME/.cache/konsave_log.txt`


## [2.1.2] - 2022-04-20
### Fixed
- Empty entries in the config files will now be parsed as empty strings to prevent an exception. See [#50](https://github.com/Prayag2/konsave/pull/50)
- A small typo was fixed. See [#51](https://github.com/Prayag2/konsave/pull/51)
- Fixed incorrect PyYaml version in `requirements.txt`. See [#56](https://github.com/Prayag2/konsave/pull/56)

### Added
- Kate's (KDE's code editor) config files were added in the default KDE config file. See [#58](https://github.com/Prayag2/konsave/pull/58)

## [2.1.1] - 2021-10-24
### Removed
- Removed the prompt that asked you which desktop environment you use when you ran Konsave for the first time. See [#45](https://github.com/Prayag2/konsave/issues/45).
- Removed unused import of the `log` function in `__main__.py`.

### Changed
- Konsave will now automatically detect if you're using KDE plasma or not.
- Fixed some Pylint errors.

## [2.1.0] - 2021-09-07
### Added
- The following placeholders for `config.yaml` were added:
    1. `$SHARE_DIR`: It points to `$HOME/.local/share`
    2. `$BIN_DIR`: It points to `$HOME/.local/bin`

### Changed
- Now, there's no need to check for the ID of a profile if you already know its name. You can remove, apply and export a profile using its name. For example `konsave --export myprofile`. See [#38](https://github.com/Prayag2/konsave/issues/38)
- Replaced the words "variables and functions" with "placeholders".
- Updated readme.

### Removed
- You'll no longer be able to use IDs to remove, apply and export profiles. You have to use the name of the profile to do so.
- The following placeholders were removed:
    - `$KONSAVE_DIR`
    - `$CONFIG_DIR`

## [2.0.2] - 2021-04-13
### Fixed
- Fixed a bug with export. Previously, exporting a profile would export the current profile but now it will export the specified profile.
- Fixed a typo in the readme

## Added
- Added a line in the readme

## [2.0.1] - 2021-04-11
### Removed
- KDE Plasma won't be restarted after applying a new configuration now. You'll have to restart it yourself. This was done because using Konsave on other DEs would give an error.

## [2.0.0] - 2021-04-11
### Added
- Possibility to define multiple backup targets via the configuration file.
- Errors will be saved to `konsave_log.txt` in the home directory.
- Ability to use a few variables and functions in the configuration file.
- Ability to use Konsave on all desktop environments.

### Changed
- Improved export and import feature. You'll be able change which files to export and import from the configuration file.
- Changed yaml loader from `yaml.FullLoader` to `yaml.SafeLoader`
- The version will now be dynamically printed.

### Break
- The old configuration files and profiles won't work with this version of Konsave.

## [1.1.9] - 2021-03-18
### Fixes
- Fixes [#26](https://github.com/Prayag2/konsave/issues/26)
- Prints help when entering "konsave" without any arguments

## [1.1.8] - 2021-03-18
### Changes
- Add missing new lines at end of `.pylintrc` and `CONTRIBUTION.md`.
- Gitignore:
    - Common VS Code and JetBrains IDE user-specific stuff.
    - All `__pycache__` dirs (`**/__pycache__`).
- Delete and untrack all `*.pyc` files.
- Reformat and improve some docstrings.
- Remove some excessive comments, e.g. `## IMPORTS ##` or `# WIPE`. The import section is clear and visible enough to not need such additional comment. Same with functions - docstrings do that job well.
- Refactor and simplify CLI argument parsing.
- Adapt `setup.py` to use pip requirement text files.
    - Create extra `dev` and corresponding `requirements_dev.txt` requirement text file. Can be installed via `pip install -e .[dev]` or from PyPI via `pip install konsave[dev]`.
- Remove "Dependencies" section from `README.md` - dependencies get installed automatically anyway.

## [1.1.7] - 2021-03-13
### Fixes
- Fixed [#28](https://github.com/Prayag2/konsave/issues/28)

## Changes
- The program will now quit on any error


## [1.1.6] - 2021-03-11
### Changes
- Changed code style to [PEP8](https://www.python.org/dev/peps/pep-0008/)
- Changed docstring style to [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)
- Updated README

### Additions
- Added a CONTRIBUTIONS.md

### Fixes
- Fixed a possible bug. Refer to [#26](https://github.com/Prayag2/konsave/issues/26).

## [1.1.5] - 2021-03-08
### Changes
- Changed `print_msg` to `log`.
- Changed `check_error` function to a decorator (Thanks to (this article)[https://medium.com/swlh/handling-exceptions-in-python-a-cleaner-way-using-decorators-fae22aa0abec]) for easier maintenance.
- Improved logging

## [1.1.4] - 2021-03-07
### Changes
- Created a function called `copy` to replace `shutil.copytree`. This would add support for python versions <= 3.7. 
- Changed version in `vars.py` from 1.1.3 to 1.1.4

### Fixes
- Previously, running `konsave --export <id>` would cause it to export the CURRENT icon and cursor theme. Now, it will export the icon and cursor theme of the profile being exported.
- Some fixes in `copy()`

## [1.1.3] - 2021-03-06
### Changes
- Fixed something

## [1.1.2] - 2021-03-06
### Changes
- Fixed something

## [1.1.1] - 2021-03-06
### Changes
- Fixed a bug

## [1.1.0] - 2021-03-06
### Changes
- You can now wipe all your profiles at once using konsave -w or konsave --wipe

## [1.0.7] - 2021-03-06
### Changes
- bug fixes

## [1.0.6] - 2021-03-06
### Changes made by @majabojarska
- Add GitHub Actions workflow "Release". Runs on tag push, named v* (e.g. v1.0.5). This workflow creates a GitHub release and publishes the package to PyPI repository.
- Change setup.py manual versioning to SCM versioning - the tag's version determines the package's version. This means that tag v1.0.5 results in package version 1.0.5 on PyPI. This also means that the package version won't be maintained via source code, but via Git tags.


## [1.0.5] - 2021-03-06
### Changes
- Fixed a small mistake with the versioning

## [1.0.4] - 2021-03-05
### Changes
- You can now use the --force or -f option to overwrite existing profiles!
- A separate config file has been introduced for easier maintenance

## [1.0.3] - 2021-03-05
### Changes
- Deployed it to PyPI!

## [1.0.2] - 2021-02-28
### Changes
- Fixed a small bug

## [1.0.1] - 2021-02-28
### Changes
- Bug fixes
- Better import and export
    + It will now export and import the installed themes, icons, cursors and plasmoids so there will be no need to install the themes manually on other machines.

## [1.0.0] - 2021-02-27
### Changes
- You can now export and import your favourite profiles as ".knsv" files and share them with your friends!
- You can also import ".knsv" files as profiles!


[2.2.0]: https://github.com/Prayag2/konsave/compare/v2.1.2...v2.2.0
[2.1.2]: https://github.com/Prayag2/konsave/compare/v2.1.1...v2.1.2
[2.1.1]: https://github.com/Prayag2/konsave/compare/v2.1.0...v2.1.1
[2.1.0]: https://github.com/Prayag2/konsave/compare/v2.0.2...v2.1.0
[2.0.2]: https://github.com/Prayag2/konsave/compare/v2.0.1...v2.0.2
[2.0.1]: https://github.com/Prayag2/konsave/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/Prayag2/konsave/compare/v1.1.9...v2.0.0
[1.1.9]: https://github.com/Prayag2/konsave/compare/v1.1.8...v1.1.9
[1.1.8]: https://github.com/Prayag2/konsave/compare/v1.1.7...v1.1.8
[1.1.7]: https://github.com/Prayag2/konsave/compare/v1.1.6...v1.1.7
[1.1.6]: https://github.com/Prayag2/konsave/compare/v1.1.5...v1.1.6
[1.1.5]: https://github.com/Prayag2/konsave/compare/v1.1.4...v1.1.5
[1.1.4]: https://github.com/Prayag2/konsave/compare/v1.1.3...v1.1.4
[1.1.3]: https://github.com/Prayag2/konsave/compare/v1.1.2...v1.1.3
[1.1.2]: https://github.com/Prayag2/konsave/compare/v1.1.1...v1.1.2
[1.1.1]: https://github.com/Prayag2/konsave/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/Prayag2/konsave/compare/v1.0.7...v1.1.0
[1.0.7]: https://github.com/Prayag2/konsave/compare/v1.0.6...v1.0.7
[1.0.6]: https://github.com/Prayag2/konsave/compare/v1.0.5...v1.0.6
[1.0.5]: https://github.com/Prayag2/konsave/compare/v1.0.4...v1.0.5
[1.0.4]: https://github.com/Prayag2/konsave/compare/v1.0.3...v1.0.4
[1.0.3]: https://github.com/Prayag2/konsave/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/Prayag2/konsave/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/Prayag2/konsave/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/Prayag2/konsave/compare/6b4a0c0bbf8c29684cc2a334065314bc8e4ea529...v1.0.0
[Unreleased]: https://github.com/ericksousa32/kongui/compare/v0.1.0a2...HEAD
[0.1.0a2]: https://github.com/ericksousa32/kongui/releases/tag/v0.1.0a2
[0.1.0a1]: https://github.com/ericksousa32/kongui/releases/tag/v0.1.0a1
