**Early test build. Read this before installing.**

KonGUI is a graphical interface for [Konsave](https://github.com/Prayag2/konsave) (KDE Plasma profiles). This release is meant for people who want to try it and report problems. It was only tested quickly on a real Plasma session (Fedora 44, Plasma 6.7.5, Wayland: every feature tried worked); X11, SELinux and Flatpak were not tested yet. Reports are welcome: open an issue with the *Plasma test report* template.

- Applying a profile rewrites real configuration files. KonGUI copies the files it will overwrite first (*Settings → Safety copies*), but make your own backup of `~/.config` before trying it, and try `kongui --demo` first.
- **Install it with the script** (no root; everything stays in your home folder):

  ```bash
  curl -fsSLO https://raw.githubusercontent.com/ericksousa32/kongui/master/install.sh
  bash install.sh
  ```

  It downloads the newest release, checks it against `SHA256SUMS`, installs it with PySide6 in its own virtual environment (`~/.venvs/kongui`, because KonGUI ships its own `konsave` package), and adds the `kongui` command and a menu entry. After that, open KonGUI from the application menu or with `kongui` in any terminal; run the script again to update, or `bash install.sh --uninstall` to remove it. Details, options and the manual way: [Installing the pre-release](https://github.com/ericksousa32/kongui#installing-the-pre-release) in the README.

Files: the wheel (`.whl`), the source distribution (`.tar.gz`), `SHA256SUMS` and, from `0.1.0a2` on, `install.sh` (also listed in `SHA256SUMS`).

Changes in this release: see [CHANGELOG.md](https://github.com/ericksousa32/kongui/blob/master/CHANGELOG.md). Known limitations and decisions: [docs/LIMITATIONS.md](https://github.com/ericksousa32/kongui/blob/master/docs/LIMITATIONS.md). Installing and testing: [docs/PLASMA_TEST_PLAN.md](https://github.com/ericksousa32/kongui/blob/master/docs/PLASMA_TEST_PLAN.md). Report problems at https://github.com/ericksousa32/kongui/issues.
