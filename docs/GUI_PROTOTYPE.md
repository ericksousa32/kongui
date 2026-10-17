# Visual prototype of the interface (PySide6 / Qt Widgets)

First version of KonGUI's graphical interface, created as a visual prototype.
**Update:** the interface is now wired to the services (`kongui/core/`) by default;
`--demo` mode keeps the prototype's original behavior, with fictitious data. The
wiring, the loading states and the limitations are in
[`GUI_SERVICES.md`](GUI_SERVICES.md). The original engine (`konsave/`) was not
changed, except for the cross-process lock listed in
[`KONSAVE_PATCHES.md`](KONSAVE_PATCHES.md).

Note on interface texts: the interface is currently in Brazilian Portuguese (fixed
in the code; internationalization is a future step). Labels are quoted below as
they appear on screen, with an English gloss in parentheses where needed.

## 1. How to run

```bash
pip install "PySide6>=6.8"      # or: pip install -e ".[gui]"
python3 -m kongui.gui           # real profiles (KonGUI services over Konsave)
python3 -m kongui.gui --demo    # fictitious data, nothing is written or applied
```

The program refuses to run as root (it uses `kongui.core.safety.ensure_not_root`).
Preferences live in `<user config folder>/kongui/kongui-gui.ini` (through
`QStandardPaths`); nothing else is written to disk.

## 2. Pages

| Page (UI label) | Key | Shortcut | Top-bar actions | Content |
|---|---|---|---|---|
| Dashboard | `dashboard` | `Ctrl+1` | Import, Save current profile (`Ctrl+S`) | 4 summary cards, active profile, recent activity |
| Perfis (Profiles) | `profiles` | `Ctrl+2` | Clear all, New profile (`Ctrl+N`) | search (`Ctrl+F`), sorting, grid/list, profile cards |
| Importar / Exportar (Import / Export) | `transfer` | `Ctrl+3` | — | export form (profile, folder, name; if the file already exists, it always asks), `.knsv` drop area with verification, recent transfers (see [`GUI_SERVICES.md`](GUI_SERVICES.md) §4) |
| Configurações (Settings) | `settings` | `Ctrl+4` | — | theme, display, notice duration, safety copies, demo data (only in `--demo` mode) |
| Editar .YAML (Edit .YAML) | `config` | `Ctrl+5` | Validate, Backups…, Discard, Save | `conf.yaml` editor: separate `save` and `export` sections, YAML text, problems panel with line/column, backups and restore (see [`GUI_CONFIG.md`](GUI_CONFIG.md)) |
| Sobre (About) | `about` | `Ctrl+6` | — | version, environment, links, prototype notice |

The side navigation is fixed (232 px) with icon and label. The window has a minimum
size of 900 × 600.

## 3. Code structure (`kongui/gui/`)

| Module | Responsibility |
|---|---|
| `app.py`, `__main__.py` | creation of the `QApplication`, root refusal, backend choice (`--demo`), preferences path |
| `main_window.py` | `MainWindow`: side bar, top bar, progress bar, page stack, shortcuts |
| `context.py` | `AppContext`: what each page receives (model, backend, controller, theme, notices, navigation) |
| `state.py` | `Profile`, `ProfileStore`, `ActivityLog`, `AppSettings` (in-memory models, with signals) |
| `backend.py` | `ProfileBackend`, `ServiceBackend` (real services) and `FakeBackend` (memory); the only GUI module that imports the engine and the services |
| `controller.py` | `ProfileController`: runs one operation at a time, loading state, updates the `ProfileStore` |
| `tasks.py` | executors: `ThreadExecutor` (worker thread), `InlineExecutor` (tests) |
| `messages.py` | pt-BR success and error texts |
| `mock_data.py` | **all** the fictitious data (seven profiles, six events, list of sections) |
| `actions.py` | confirmation dialogs and calls to the controller; notice and activity for each result |
| `validation.py` | name rules (reuses `kongui.core.safety.validate_profile_name`) |
| `theme.py` | color tokens, Qt palette, style sheet and `ThemeManager` |
| `icons.py` | SVG icons drawn in code and colored by the theme |
| `formatting.py` | sizes, relative dates and plurals in pt-BR |
| `widgets/` | reusable pieces: `common` (button, label, badge, card, segmented control), `grid` (adaptive grid), `cards`, `shell` (side and top bars), `states` (empty state), `search`, `toast`, `dialogs`, `dropzone`, `rows`, `feedback` (busy bar, wait banner and error strip), `confedit` (section editor and problems list for `conf.yaml`) |
| `pages/` | one class per page, on top of `pages/base.py` |

Rules followed: colors only come from `Tokens`; icons are rebuilt when
`ThemeManager.changed` fires; only `backend.py` imports `kongui.core.engine`,
`profiles` and `config`; nobody imports `konsave` or `subprocess`. The tests check
these rules.

## 4. Theme

Three modes, chosen in Settings (or with the sun/moon button of the side bar):

* **Sistema** (System): uses the platform palette. On KDE, that means the Plasma
  color scheme and the accent color chosen by the user. If the contrast of the text
  over the accent is below 4.5:1, the text is switched to black or white.
* **Claro** (Light) and **Escuro** (Dark): fixed palettes (minimum contrast of
  4.5:1 checked in a test). A `QPalette` is also applied, so the native controls
  follow along.

Combos, check boxes and `QSpinBox` deliberately keep the native look of the system
style, to match KDE.

## 5. How to validate

```bash
QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests -t . -v
```

The interface tests do not need a screen (`offscreen`) and use a temporary `$HOME`.
If PySide6 is not installed, they are skipped.

| Test module | Covers |
|---|---|
| `tests.test_gui_startup` | opening, fixed structure, icons, preferences, `main` entry point, isolation from Konsave |
| `tests.test_gui_navigation` | side bar, top bar, shortcuts, theme switch |
| `tests.test_gui_widgets` | adaptive grid, notices, dialogs, drop area, theme, formatting |
| `tests.test_gui_interaction` | each page: search, sorting, apply, remove, export, import, settings |
| `tests.test_gui_operations` | the six operations, one by one, in the interface (in-memory backend): loading, success, error, confirmation |
| `tests.test_gui_real_backend` | the six operations on the real services, in a temporary `$HOME` |
| `tests.test_gui_transfer` | import and export in the interface (in-memory backend): form, conflicts, confirmations, errors |
| `tests.test_gui_transfer_roundtrip` | export and import on the real services, in two temporary homes; compatibility with the original `python -m konsave` |
| `tests.test_gui_config` | `conf.yaml` editor in the interface (memory and real services): validate, save, cancel, backups, conflict, special characters |
| `tests.test_gui_backups` | safety copies in the interface: dialog, restore/delete with confirmation, locks, errors, messages and end to end with the real services |
| `tests.test_gui_dialogs` | the dialogs actually triggered (replace/unique name, reload/write, typed word, group name, backup preview and restore) and the helpers of `app.py` |
| `tests.test_gui_audit` | findings of the final audit: closing during an operation, differing `conf.yaml` warning, export-folder check off the thread, Konsave version, export on a new account |
| `tests.test_gui_support` | messages, executors, `FakeBackend`, `ProfileStore`, feedback widgets |
| `tests.test_gui_lock_wait` | waiting for and cancelling the cross-process lock in the interface (see [`CONCURRENCY.md`](CONCURRENCY.md)) |

Manual visual check: open the program, switch between the three themes, resize the
window down to the minimum and use **Configurações → Esvaziar perfis** (Settings →
Empty profiles) to see the empty states. For the existing-file notice, export the
profile "Minimalista" without checking "Substituir" (Replace).

## 6. What `--demo` mode simulates

* Applying, saving, duplicating, removing, exporting and importing only change
  lists and a virtual in-memory file system. Every notice says "Simulação: nada foi
  alterado no sistema." (Simulation: nothing was changed in the system).
* The rules are the real ones: conflict policy, invalid names and confirmations.
  Import never opens the file (only its name and, if it exists, its size).
* The file `~/Downloads/Minimalista.knsv` "already exists", to show the conflict.

## 7. Limitations and next steps

* Testing in a real Plasma 6 session is in progress: accent color, switching color
  scheme with the app open, fractional scaling and Wayland need manual
  verification.
* Accessibility: accessible names, keyboard focus and contrast were handled, but
  there was no test with a screen reader.
* pt-BR texts are fixed in the code; internationalization (`tr`) is missing.
* The window depends on its own icon style; system theme icons
  (`QIcon.fromTheme`) are a future option.
