<h1 align="center">KonGUI</h1>

<p align="center">
A graphical interface for managing KDE Plasma configuration profiles, built as an independent fork of <a href="https://github.com/Prayag2/konsave">Konsave</a>.
</p>

> **Status: early development (`0.1.0.dev0`).** KonGUI is not packaged or released yet, and testing on a live Plasma session is in progress. It is an independent fork and is **not** affiliated with, endorsed by, or maintained by the Konsave authors.

## Overview

Konsave saves your desktop customizations (themes, icons, panels, shortcuts and other dotfiles) as named profiles that you can apply later or share as `.knsv` archives. It is a command-line tool.

KonGUI keeps Konsave's engine and data format and adds a desktop application on top of it, so the same operations can be done without memorizing flags. The project focuses on Linux and the KDE Plasma desktop, with Fedora KDE as the main target.

What it aims to solve:

- Make saving, applying, importing and exporting profiles approachable from a GUI.
- Make risky steps explicit: destructive actions ask for confirmation, and files are copied to a safety copy before a profile is applied or imported.
- Make the shared `conf.yaml` (what Konsave saves and exports) editable and validated.
- Prevent two Konsave operations (two KonGUI windows, or KonGUI and the `konsave` command) from running over each other.

## Screenshots

![Dashboard](./screenshots/Captura_de_tela_20261018_124635.png)

The screenshots were taken in demo mode, so every profile shown is fictitious. View more in [screenshots](./screenshots/).

You can preview the interface without touching any real data using the demo mode described in [Running](#running).

## Features

### Working today

Everything below is covered by the automated test suite (run in temporary home directories with Qt in offscreen mode). Testing on a real Plasma session is in progress.

- **Profiles:** list, save, overwrite, apply, remove, and remove all. Destructive actions require confirmation.
- **Import / export:** `.knsv` archives. When the destination file already exists, the interface asks what to do instead of overwriting silently.
- **Import / export protections:** a `.knsv` above 512 MiB, with more than 10,000 entries or that really expands to more than 2 GiB is refused before anything is written; corrupted or unsafe archives get a clear message; free disk space is checked before import and export; a failed export keeps the previous one and leaves no temporary files. The limits are fixed constants (see [`docs/INTEGRATION.md`](docs/INTEGRATION.md) §10).
- **Profile description and sections:** an optional description per profile (saved with it or edited later from the card menu), and the sections of each profile read from its own `conf.yaml`. The description is kept next to the profile, not inside the `.knsv`, so it does not travel when exporting. What a profile contains is still decided in the `conf.yaml` editor.
- **Safety copies:** the files that would be replaced are copied before a profile is applied or imported. Copies can be listed, restored and deleted from *Settings*; nothing is deleted automatically.
- **`conf.yaml` editor:** edit the `save` and `export` sections or the YAML text, with validation (problems reported with line and column), automatic backups of the previous file, and restore.
- **Cross-process lock:** operations use a `flock` lock on `~/.config/konsave/.kongui.lock`. If another Konsave operation is running, KonGUI shows that it is waiting, stays responsive, and lets you cancel the wait. The bundled `konsave` command waits too (see [Command line](#command-line-bundled-konsave)). Programs that do not use the lock, such as Plasma itself or a text editor, are not covered.
- **Interface:** dashboard, profiles, import/export, settings, YAML editor and about pages; light, dark and system themes; keyboard shortcuts (`Ctrl+1` to `Ctrl+6` switch pages).
- **Language:** English and Brazilian Portuguese. The first time it runs, KonGUI follows the system language (`pt_BR` gives Portuguese; any other locale, including `pt_PT`, gives English). Change it any time in *Settings → Language*; the choice is saved, applies immediately without restarting, and is never overwritten by the system language afterwards. See [Language](#language).
- **Demo mode:** `--demo` runs the interface on fictitious in-memory data.
- **Safety:** KonGUI refuses to run as root, and profile or archive names are validated before anything reaches the original code.

### In progress

- Testing on a real Fedora KDE / Plasma session (applying profiles, Wayland, SELinux, Flatpak). Results will be recorded in [`docs/FINAL_AUDIT.md`](docs/FINAL_AUDIT.md).

### Planned

- Progress reporting and cancelling of long operations that have already started. The original engine cannot be interrupted today.
- Packaging and distribution. No installable package or AppImage exists yet.

The detailed status of each requirement is in [`docs/FINAL_AUDIT.md`](docs/FINAL_AUDIT.md).

## Technologies

- Python 3.9 or newer (`python_requires` in `setup.py`)
- [PySide6](https://doc.qt.io/qtforpython-6/) (Qt for Python) 6.8 or newer, for the interface (optional `gui` extra)
- [PyYAML](https://pyyaml.org/), as in Konsave, and `setuptools` (both listed in `requirements.txt`)
- Standard library only for the locking mechanism (`fcntl.flock`)
- Development: `unittest`, [black](https://github.com/psf/black), [pylint](https://pylint.org/)

## Installation (development)

There is no released package yet. To try KonGUI from a clone of this repository:

```bash
git clone https://github.com/ericksousa32/kongui.git
cd kongui
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[gui]"
```

Use a virtual environment: the package is still called `Konsave` in `setup.py` and installs the `konsave` and `kongui` commands, so it would replace an existing Konsave installation. The version is taken from the git history (`setuptools_scm`), so install from a clone, not from a source archive without `.git`.

Linux only. The install and launch commands above were checked with Python 3.13 in a fresh virtual environment (Qt offscreen), installing from a local clone of this repository.

## Running

```bash
kongui --demo            # fictitious data; nothing is read from or written to your profiles
kongui                   # real profiles in ~/.config/konsave
python3 -m kongui.gui    # same as `kongui`; --demo also works
```

Run it as a regular user: KonGUI exits with an error if started as root. Preferences are stored in the user's Qt application config folder (`kongui/kongui-gui.ini`).

Applying a profile rewrites your real configuration files and may require logging out and back in to take full effect. Try `--demo` first, and note that the safety copies mentioned above are made before each apply.

## Command line (bundled Konsave)

The repository includes the Konsave source (`konsave/`), and the `konsave` command works as before. KonGUI changes it only to take the cross-process lock; every change is listed in [`docs/KONSAVE_PATCHES.md`](docs/KONSAVE_PATCHES.md), written to make updating to a newer Konsave release easier.

<details>
<summary>Command reference</summary>

| Command | Description |
|---|---|
| `konsave -h` / `--help` | Show help |
| `konsave -s <name>` / `--save` | Save the current configuration as a profile (add `-f` to overwrite) |
| `konsave -l` / `--list` | List profiles |
| `konsave -a <name>` / `--apply` | Apply a profile (you may need to log out and in) |
| `konsave -r <name>` / `--remove` | Remove a profile |
| `konsave -w` / `--wipe` | Remove all profiles |
| `konsave -e <name>` / `--export-profile` | Export a profile as a `.knsv` file; add `-d <directory>` / `--export-directory` and `-n <name>` / `--export-name`, and `-f` to overwrite (without it, the name gets a date and time) |
| `konsave -i <file>` / `--import-profile` | Import a `.knsv` file |
| `konsave -v` / `--version` | Show the version |

**Lock behavior** (differs from upstream): if another Konsave operation is running, the command waits up to 30 seconds and prints a message. Set `KONSAVE_LOCK_TIMEOUT` (seconds; `0` = do not wait; negative or `inf` = wait without limit) to change that. If the wait times out the command exits with status `75` and changes nothing; if the lock file cannot be used it exits with `1`; Ctrl+C while waiting exits with `130`. Details in [`docs/CONCURRENCY.md`](docs/CONCURRENCY.md).

</details>

<details>
<summary>The configuration file (<code>~/.config/konsave/conf.yaml</code>)</summary>

The file defines what is saved and what is only exported with a profile. On first use Konsave creates it from a KDE default when `XDG_CURRENT_DESKTOP` is `KDE`, and from a generic one otherwise. KonGUI has an editor for it (*Edit .YAML*); you can also edit it by hand.

```yaml
---
save:
    name:
        location: "path/to/parent/directory"
        entries:
        # Files to be backed up. They must exist in the given location.
            - file1
            - folder1
export:
    # Files that are not saved, only exported and imported with the profile
    # (for example complete icon packs and themes).
    anotherName:
        location: "another/path/to/parent/directory"
        entries:
            - file1
...
```

Placeholders usable in `location`:

- `$HOME`: the home directory
- `$CONFIG_DIR`: `$HOME/.config`
- `$SHARE_DIR`: `$HOME/.local/share`
- `$BIN_DIR`: `$HOME/.local/bin`
- `${ENDS_WITH="text"}` / `${BEGINS_WITH="text"}`: folders whose names differ between computers but end or begin with the same text

```yaml
save:
    firefox:
        location: "$HOME/.mozilla/firefox/${ENDS_WITH='.default-release'}"
        entries:
            - chrome
```

</details>

## Language

The interface is written in English and translated to Brazilian Portuguese with Qt translations (`kongui/gui/translations/*.ts`, compiled to `*.qm`). Which language is used:

1. The language chosen in *Settings → Language*, if you chose one (stored in KonGUI's own settings file, never in Konsave's).
2. Otherwise the system locale: exactly `pt_BR` selects Portuguese, anything else selects English. This detection is never saved, so a later change of the system language is followed until you choose a language yourself.
3. A text with no translation is shown in English.

Known limits: the fictitious data of `--demo` (profile names, descriptions and activity) is always in English, while the interface around it is translated; notices already on screen and entries already in the activity list keep the language they were written in; and messages that come from the bundled Konsave code are translated by matching their English text, so a message that Konsave later rewords may appear in English. Details are in [`docs/GUI_PROTOTYPE.md`](docs/GUI_PROTOTYPE.md#8-language-i18n).

## Roadmap

No dates are promised. In rough order of priority:

1. Finish the real Fedora KDE (Plasma) session testing that is in progress, and fix what it reveals.
2. Import and export limits (size, "zip bomb", free disk space).
3. A first tagged release with a defined package name and distribution channel.
4. AppImage packaging, only after a working, tested build exists.
5. Progress and cancellation for operations already running, if the engine allows it.

## Compatibility

KonGUI uses the same profile folder and `.knsv` format as the Konsave code bundled in this repository, and the tests check that archives are exchanged correctly with the bundled `konsave` command in both directions. Compatibility with other Konsave releases has **not** been verified.

## Documentation

Technical documentation is in [`docs/`](docs/):
[integration layer](docs/INTEGRATION.md), [services used by the interface](docs/GUI_SERVICES.md), [`conf.yaml` editor](docs/GUI_CONFIG.md), [interface prototype](docs/GUI_PROTOTYPE.md), [concurrency](docs/CONCURRENCY.md), [changes to Konsave](docs/KONSAVE_PATCHES.md) and the [final audit](docs/FINAL_AUDIT.md).

## Original project and credits

KonGUI is a fork of [Konsave](https://github.com/Prayag2/konsave), created by Prayag Jain and released under the GPL v3. The profile engine, the `.knsv` format and the configuration file design come from that project; thank you to its author and contributors. Konsave's history is kept in [`CHANGELOG.md`](CHANGELOG.md). Please report problems specific to KonGUI in this repository, not to the Konsave maintainers.

## Contributing

Bug reports and ideas are welcome: please open an issue in this repository, and discuss larger changes before starting. Read [`CONTRIBUTION.md`](CONTRIBUTION.md) first (inherited from Konsave; some of its details may not apply to this fork yet).

To work on the code:

```bash
pip install -r requirements_dev.txt
python3 -m unittest discover -s tests -t .    # or: make tests
black kongui tests
pylint kongui
make translations                              # after changing interface texts (see docs/GUI_PROTOTYPE.md)
```

Run the tests as a regular user: they create temporary home directories and refuse to touch real files, and the file-writing ones are skipped when run as root. The tests never apply profiles to your real session.

## License

KonGUI is distributed under the **GNU General Public License v3.0**, the same license as Konsave. The full text is in [`LICENSE`](LICENSE). The original Konsave code remains the work of its authors and is included under the same license; keep this notice and the original credits when redistributing.
