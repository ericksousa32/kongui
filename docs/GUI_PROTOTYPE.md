# Visual prototype of the interface (PySide6 / Qt Widgets)

First version of KonGUI's graphical interface, created as a visual prototype.
**Update:** the interface is now wired to the services (`kongui/core/`) by default;
`--demo` mode keeps the prototype's original behavior, with fictitious data. The
wiring, the loading states and the limitations are in
[`GUI_SERVICES.md`](GUI_SERVICES.md). The original engine (`konsave/`) was not
changed, except for the cross-process lock listed in
[`KONSAVE_PATCHES.md`](KONSAVE_PATCHES.md).

Note on interface texts: the interface is available in English and Brazilian
Portuguese (see [section 8](#8-language-i18n)). Labels are quoted below as they
appear in the Portuguese interface, with an English gloss in parentheses where
needed.

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
| Sobre (About) | `about` | `Ctrl+5` | — | version, environment, links, prototype notice |

There is no `conf.yaml` editor (removed on 2026-10-19): as in Konsave, the user
edits `~/.config/konsave/conf.yaml` by hand ([`LIMITATIONS.md`](LIMITATIONS.md) §4).

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
| `i18n.py` | interface language: detection, `QTranslator` loading, live switching (`translations/*.ts` and `*.qm`) |
| `messages.py` | success and error texts (English source, translated through `i18n`) |
| `mock_data.py` | **all** the fictitious data (seven profiles, six events, list of sections) |
| `actions.py` | confirmation dialogs and calls to the controller; notice and activity for each result |
| `validation.py` | name rules (reuses `kongui.core.safety.validate_profile_name`) |
| `theme.py` | color tokens, Qt palette, style sheet and `ThemeManager` |
| `icons.py` | SVG icons drawn in code and colored by the theme |
| `formatting.py` | sizes, dates and relative dates in the language in use |
| `widgets/` | reusable pieces: `common` (button, label, badge, card, segmented control), `grid` (adaptive grid), `cards`, `shell` (side and top bars), `states` (empty state), `search`, `toast`, `dialogs`, `dropzone`, `rows`, `feedback` (busy bar, wait banner and error strip) |
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
| `tests.test_gui_overview` | overview: every feature once, chained the way a user would, through the real interface and dialogs down to the real services in a temporary `$HOME` (see [`TEST_OVERVIEW.md`](TEST_OVERVIEW.md)) |
| `tests.test_gui_startup` | opening, fixed structure, icons, preferences, `main` entry point, isolation from Konsave |
| `tests.test_gui_navigation` | side bar, top bar, shortcuts, theme switch |
| `tests.test_gui_widgets` | adaptive grid, notices, dialogs, drop area, theme, formatting |
| `tests.test_i18n` | language detection and saved choice, first run per locale, persistence after restart, live switching (page and typed data kept), later dialogs / notices / errors, fallback, plurals and formats, completeness and freshness of the `.ts` / `.qm` files, no Portuguese literals in the code |
| `tests.test_gui_interaction` | each page: search, sorting, apply, remove, export, import, settings |
| `tests.test_gui_operations` | the six operations, one by one, in the interface (in-memory backend): loading, success, error, confirmation |
| `tests.test_gui_real_backend` | the six operations on the real services, in a temporary `$HOME` |
| `tests.test_gui_transfer` | import and export in the interface (in-memory backend): form, conflicts, confirmations, errors |
| `tests.test_gui_transfer_roundtrip` | export and import on the real services, in two temporary homes; compatibility with the original `python -m konsave` |
| `tests.test_gui_backups` | safety copies in the interface: dialog, restore/delete with confirmation, locks, errors, messages and end to end with the real services |
| `tests.test_gui_dialogs` | the dialogs actually triggered (replace/unique name, typed word) and the helpers of `app.py` |
| `tests.test_gui_audit` | findings of the final audit: closing during an operation, archive warnings in the import form, export-folder check off the thread, Konsave version, export on a new account |
| `tests.test_version` | the version shown in the badge, the *About* row and the sidebar caption (short form, whole version, `dev` when unknown); see [`RELEASING.md`](RELEASING.md) |
| `tests.test_smoke` | `tools/smoke_test.py`, the check the release workflow runs on the built wheel: version, `konsave` command, translations, main window, normal exit; see [`RELEASING.md`](RELEASING.md) §5 |
| `tests.test_gui_support` | messages, executors, `FakeBackend`, `ProfileStore`, feedback widgets |
| `tests.test_gui_lock_wait` | waiting for and cancelling the cross-process lock in the interface (see [`CONCURRENCY.md`](CONCURRENCY.md)) |

Manual visual check: open the program, switch between the three themes, resize the
window down to the minimum and use **Configurações → Esvaziar perfis** (Settings →
Empty profiles) to see the empty states. For the existing-file notice, export the
profile "Minimalist" without checking "Substituir" (Replace).

## 6. What `--demo` mode simulates

* Applying, saving, duplicating, removing, exporting and importing only change
  lists and a virtual in-memory file system. Every notice says "Simulação: nada foi
  alterado no sistema." (Simulation: nothing was changed in the system).
* The rules are the real ones: conflict policy, invalid names and confirmations.
  Import never opens the file (only its name and, if it exists, its size).
* The file `~/Downloads/Minimalist.knsv` "already exists", to show the conflict.

## 7. Limitations and next steps

* Testing in a real Plasma 6 session is in progress: accent color, switching color
  scheme with the app open, fractional scaling and Wayland need manual
  verification.
* Accessibility: accessible names, keyboard focus and contrast were handled, but
  there was no test with a screen reader.
* Language limits are listed in [section 8](#8-language-i18n).
* The window depends on its own icon style; system theme icons
  (`QIcon.fromTheme`) are a future option.

## 8. Language (i18n)

**Source language.** Every text in the code is English. `kongui/gui/translations/`
holds `kongui_en.ts` / `kongui_pt_BR.ts` (Qt Linguist sources) and the compiled
`kongui_en.qm` / `kongui_pt_BR.qm` (committed, and packaged through `package_data`
in `setup.py`). English is also the fallback: a text with no translation, a missing
or unreadable `.qm`, or an unknown language code shows the English source and never
raises.

**Which language is used** (`i18n.py`):

* The `language` key of KonGUI's own settings (`kongui-gui.ini`, never Konsave's
  files). The empty value means "no preference"; valid values are `en` and `pt_BR`.
  Anything else is read as "no preference".
* With no preference, `QLocale.system().name()` decides: exactly `pt_BR` (with
  `.UTF-8` or `@modifier` stripped) gives Portuguese, any other locale, including
  `pt_PT` and `pt`, gives English. Detection is **never written** to the settings,
  so an explicit choice is the only thing that is stored and it is never overwritten.

**Switching.** `LanguageManager` (one per process, `i18n.manager()`) replaces the
`QTranslator`s (KonGUI's and Qt's own `qtbase_<lang>`), sets `QLocale` and sends
`QEvent.LanguageChange` to every top-level widget. Qt does not deliver the
application-wide event reliably, hence the explicit broadcast. Widgets refresh without being
recreated:

* `Label`, `Badge` and `Button` accept a text or a function returning the text; the
  function is evaluated again on each change.
* `i18n.bind(owner, apply)` runs `apply` on `LanguageChange` for anything else.
* `Page` has `TITLE` / `SUBTITLE` and a `retranslate()` hook; pages with built
  content (profile cards, counts, problem list, status line) rebuild it there. The
  current page, search text, sort order and form fields are kept.
* Dialogs are created per use, so they are always in the current language.

**Writing texts.** Use `self.tr("...")` (or `QCoreApplication.translate("Context",
"...")` where there is no `self`) with a *literal* context and text, because
`pyside6-lupdate` only reads literals. Messages are complete sentences with named
fields (`"Apply “{name}”?".format(name=name)`), never concatenated fragments. Plurals
use Qt's `%n` form (`self.tr("%n profile(s)", "", count)`). Texts defined at import
time use `QT_TRANSLATE_NOOP`. Not translated: proper names (KonGUI, Konsave, Plasma),
commands, paths, file extensions, section keys (`save`, `export`) and technical values.

**Updating the catalogs.** After adding or changing a text run `make translations`
(`pyside6-lupdate` then `pyside6-lrelease`), translate the new messages left
`unfinished` in `kongui_pt_BR.ts`, run it again and commit the `.ts` and `.qm`.
`tests.test_i18n` fails if a `.ts` file lacks a text of the code, if a `.qm` is not
what its `.ts` compiles to, if a message is unfinished or lost a `{field}` / `%n`, or
if a Portuguese literal appears in the code. To add a language, add it to
`i18n.SUPPORTED`, create the two files and extend `detect_language`.

**Konsave messages.** Text that comes from the bundled Konsave code (`kongui/core`,
`konsave/`) is not changed; `messages.py` maps its known English messages with
regular expressions to translatable sentences. An unknown message is shown as it
came, with a generic prefix.

**Limitations.**

* Notices already on screen and entries already in the activity list keep the language
  they were written in; the next ones use the new language.
* The fictitious `--demo` data (profile names, descriptions, areas and activity
  entries, `kongui/gui/mock_data.py`) is always in English, whatever the interface
  language: it is sample content, not interface text, and has no translation. The
  interface around it (buttons, notices, dialogs) is translated as usual.
* Brazilian Portuguese counts 0 as singular, as Qt / CLDR do ("0 perfil").
* A Konsave message that is reworded in a future release may show in English until
  its pattern in `messages.py` is adapted (see `KONSAVE_PATCHES.md`).
* Messages printed to the terminal by `kongui.gui.app.main` before the window exists
  (for example "Konsave not found") are English only.
