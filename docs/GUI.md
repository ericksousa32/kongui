# The interface (PySide6 / Qt Widgets)

How KonGUI's window is organized, how it talks to the profile services, and what
it does and does not do. The services themselves (`kongui/core/`) are described in
[`INTEGRATION.md`](INTEGRATION.md); the few changes made inside the original engine
(`konsave/`) are listed in [`KONSAVE_PATCHES.md`](KONSAVE_PATCHES.md).

The interface is available in English and Brazilian Portuguese (§9). Labels are
quoted below as they appear in English.

## 1. How to run

```bash
pip install -e ".[gui]"         # or: pip install "PySide6>=6.8"
python3 -m kongui.gui           # real profiles of the current user
python3 -m kongui.gui --demo    # fictitious data; nothing is written or applied
```

The program refuses to run as root (`kongui.core.safety.ensure_not_root`) and exits
with a message if Konsave cannot be loaded. Its preferences live in
`<user config folder>/kongui/kongui-gui.ini` (through `QStandardPaths`).

## 2. Pages

| Page | Key | Shortcut | Top-bar actions | Content |
|---|---|---|---|---|
| Dashboard | `dashboard` | `Ctrl+1` | Import, Save current profile (`Ctrl+S`) | 4 summary cards, active profile (up to 3 section badges, then "+N"), recent activity |
| Profiles | `profiles` | `Ctrl+2` | Clear all, New profile (`Ctrl+N`) | search (`Ctrl+F`), sorting, grid / list, profile cards |
| Import / Export | `transfer` | `Ctrl+3` | — | export form, `.knsv` drop area with verification, recent transfers (§5) |
| Settings | `settings` | `Ctrl+4` | — | language, theme, default view, profiles folder, safety copies, notice duration, demo data (only in `--demo` mode) |
| About | `about` | `Ctrl+5` | — | version, environment, links, status notice |

There is no `conf.yaml` editor: as in Konsave, the user edits
`~/.config/konsave/conf.yaml` by hand ([`LIMITATIONS.md`](LIMITATIONS.md) §4).

The side bar is fixed (232 px) with icon and label. The window's minimum size is
900 × 600; the pages scroll, and the section badges of a profile show at most three
labels followed by a "+N" badge that is always visible (its tooltip lists every
section).

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
| `messages.py` | success and error texts, section labels (English source, translated through `i18n`) |
| `mock_data.py` | **all** the fictitious data of `--demo` (seven profiles, six events, list of sections) |
| `actions.py` | confirmation dialogs and calls to the controller; notice and activity for each result |
| `validation.py` | name rules (reuses `kongui.core.safety.validate_profile_name`) |
| `theme.py` | color tokens, Qt palette, style sheet and `ThemeManager` |
| `icons.py` | SVG icons drawn in code and colored by the theme; `app_icon()`, the application icon read from `data/icons/hicolor` |
| `formatting.py` | sizes, dates and relative dates in the language in use |
| `data/icons/hicolor/` | the application icon (`kongui.png` in 8 sizes, 16–512 px, and `scalable/apps/kongui.svg`), packaged with the wheel; `install.sh` copies it into the user's icon theme for the menu entry |
| `widgets/` | reusable pieces: `common` (button, label, badge, badge row, card, segmented control, `AppLogo`), `grid` (adaptive grid), `cards`, `shell` (side and top bars), `states` (empty state), `search`, `toast`, `dialogs`, `dropzone`, `rows`, `feedback` (busy bar, wait banner and error strip) |
| `pages/` | one class per page, on top of `pages/base.py` |

Rules followed (and checked by the tests): colors only come from the theme tokens;
icons are rebuilt when `ThemeManager.changed` fires; only `backend.py` imports
`kongui.core.engine`, `profiles` and `config`; nobody imports `konsave` or
`subprocess`.

## 4. How the window reaches the services

```
Page ──► ProfileActions (dialogs) ──► ProfileController ──► Executor (thread)
  ▲                                          │                     │
  └────────── ProfileStore ◄─────────────────┘            ProfileBackend
                                                  ServiceBackend │ FakeBackend
```

* `ProfileBackend` (`backend.py`) is what the interface needs. `ServiceBackend`
  calls `ProfileService` (and, through it, Konsave); `FakeBackend` keeps profiles in
  memory (`--demo` and tests). The methods block and never touch Qt objects.
* `ProfileController` (`controller.py`) runs **one operation at a time**; requests
  made during an operation are refused with a "please wait" notice. After each
  operation, even a failed one, the list is read again and published to the
  `ProfileStore`, and an `Outcome` is emitted.
* `ThreadExecutor` (`tasks.py`) runs the work in a thread and hands the result back
  through a signal, so the interface does not freeze. **Nothing that touches the
  disk runs on the interface thread**: reads (safety copies, `.knsv` inspection, the
  export-folder check `probe_export`) go through `controller.background`.
* The window **does not close** while an operation runs: Konsave cannot be
  interrupted, and closing would leave the work orphaned.
* `OutcomeNotifier` (`actions.py`) shows the notice (errors stay until closed) and
  records the activity. `messages.py` turns results and exceptions into sentences in
  the language in use; unknown exceptions show their type, so a bug is not hidden.

### The operations

| Operation | Service | While it runs | Confirmation |
|---|---|---|---|
| List | `list_profiles` | "Loading…" on the page and panel; thin bar under the top bar | — |
| Save | `ConfigService.ensure_default_config` + `save` | buttons locked, busy bar | — (name validated first) |
| Overwrite | `ProfileService.replace` | card shows "Overwriting…" | destructive dialog |
| Apply | `apply` | card shows "Applying…" | destructive dialog |
| Remove | `remove` | card shows "Removing…" | destructive dialog |
| Clear all | `wipe_all` | buttons locked | destructive dialog **and** typing a confirmation word |
| Export | `ProfileService.export` | busy bar, button locked | only to replace a file (§5) |
| Import | `ProfileService.import_profile` | background check, then busy bar | always |

Each error appears as a persistent notice with its cause; a failure to list shows a
strip with "Try again". The lower layers also require `confirmed=True` ("truthy"
values such as `1` are refused).

**Why `replace` exists.** `konsave save -f` *merges* the old profile instead of
replacing it: files that no longer exist stay in it. For a real overwrite,
`ProfileService.replace` saves under a temporary name (`.kongui-…`), checks the
result and swaps with `rename`, rolling back if anything fails. Entries with that
prefix are never listed.

**Choosing what a profile includes.** The save dialog offers the 12 export
categories as check boxes (`kongui.core.CATEGORIES`), with *Select all* / *Clear
all*, a warning for a missing dependency and a running summary; only the list of
check boxes scrolls, so nothing overlaps on a short screen. The chosen keys reach
`ProfileService.save(..., categories=...)` ([`INTEGRATION.md`](INTEGRATION.md) §12).
The badges of a card are the categories re-derived from the profile's own
`conf.yaml` (§11 there).

**Profile details.** The save dialog also asks for an optional description (500
characters at most). *Edit details…* in the card menu changes it later; cancelling
changes nothing and an empty text clears it. A profile saved without its description
gives a **warning**, not a success; a failed edit is an error and keeps the old text.

## 5. Import and export

Format: Konsave's **original** `.knsv` (a zip with `conf.yaml`, `save/` and
`export/`). KonGUI creates no new format; the tests exchange files with the original
`python -m konsave` in both directions.

| Original CLI | In the interface | Behavior |
|---|---|---|
| `-e PROFILE` | "Profile" list | the profile must exist and have a valid `conf.yaml` |
| `-d FOLDER` | "Destination folder" + **Choose…** | default `~/Downloads`; the folder must exist and accept writing (checked first) |
| `-n NAME` | "File name (without extension)" | starts equal to the profile; same name rules as profiles |
| `-f` | "The file already exists" dialog | see below |
| `-i FILE` | drop area / **Choose file** | `.knsv` only; checked (read-only) as soon as it is chosen |
| (none) | "Imported profile name" | the original uses the file name; see *Rename* |
| (none) | "Apply the profile after importing" | a separate second step: if it fails, the profile stays imported and a warning explains |

**Conflict on export.** Without `-f` the original appends date and time to the
name; with `-f` it replaces, and its `force` also deletes a *folder* with that name.
KonGUI **always asks** when the destination exists: for a `.knsv`, **Replace**,
**Use unique name** (`name-2.knsv`, …) or Cancel; for a folder, `.zip` or link, only
**Use unique name** or Cancel. When nothing exists the export runs with the `error`
policy, so a file created meanwhile is never overwritten.

**Import.**

* Always confirms, listing the sections that will be written: the archive's `export`
  section goes straight into the system (for example `~/.local/share/icons`). The
  files it would overwrite are copied first (§6).
* Never replaces a profile: an existing name is refused, as in the original.
* `ProfileService.inspect_archive` (read-only) runs the same checks as the import —
  readable zip, safe member names, `conf.yaml` and `save/` present, a configuration
  Konsave can read, destinations inside the home — and shows name, size and sections
  before anything is written. Destinations outside the home are refused.
* **Rename:** to import under another name, the same file is copied to a private
  temporary folder under the new name and imported from there; the copy is always
  deleted and the original file is not touched.

**Limits and free space.** An import refuses a file above 512 MiB, more than 10,000
entries or more than 2 GiB really decompressed; import and export check free space
(with a 64 MiB margin) and stop with nothing changed; a failed export never replaces
the previous file. Constants and details: [`INTEGRATION.md`](INTEGRATION.md) §10.
Permission and file errors become messages in the language in use, and the form
stays filled in.

## 6. Safety copies

Before **applying** or **importing**, the service copies the files that would be
overwritten ([`INTEGRATION.md`](INTEGRATION.md) §9). In the interface:

* the apply / import notices name the copy that was kept;
* **Settings → Safety copies → Manage…** lists them (date, operation, profile, files
  replaced / created, size, newest first), read in the background;
* **Restore** asks for confirmation, keeps the current state as a new copy and puts
  the files back; **Delete** asks for confirmation; both stay locked while another
  operation runs;
* if the copy cannot be made, the error appears and **nothing is applied or
  imported**;
* no copy is deleted automatically, and the copy of an import does not undo the
  imported profile;
* in `--demo` mode the copies are fictitious.

## 7. Theme

Three modes, chosen in Settings (or with the sun / moon button of the side bar):

* **System** uses the platform palette: on KDE, the Plasma color scheme and accent
  color. If the text over the accent has a contrast below 4.5:1, it is switched to
  black or white.
* **Light** and **Dark** are fixed palettes (minimum contrast of 4.5:1, checked in a
  test). A `QPalette` is applied too, so native controls follow.

Combos, check boxes and `QSpinBox` keep the native look of the system style, to
match KDE.

## 8. `--demo` mode

* Applying, saving, duplicating, removing, exporting and importing only change
  in-memory lists and a virtual file system; every notice says it was a simulation.
* The rules are the real ones: conflicts, invalid names and confirmations. Import
  never opens the file (only its name and, if it exists, its size).
* `~/Downloads/Minimalist.knsv` "already exists", to show the export conflict.
* *Settings → Demo data* empties or restores the fictitious profiles, to see the
  empty states.

## 9. Language (i18n)

**Source language.** Every text in the code is English. `kongui/gui/translations/`
holds `kongui_en.ts` / `kongui_pt_BR.ts` (Qt Linguist sources) and the compiled
`kongui_en.qm` / `kongui_pt_BR.qm` (committed and packaged). English is also the
fallback: a missing translation, a missing or unreadable `.qm` or an unknown
language code shows the English source and never raises.

**Which language is used** (`i18n.py`):

* The `language` key of KonGUI's own settings (`kongui-gui.ini`, never Konsave's
  files): `en` or `pt_BR`; empty (or anything else) means "no preference".
* With no preference, `QLocale.system().name()` decides: exactly `pt_BR` (with
  `.UTF-8` or `@modifier` stripped) gives Portuguese; any other locale, including
  `pt_PT` and `pt`, gives English. Detection is **never written** to the settings,
  so only an explicit choice is stored.

**Switching.** `LanguageManager` (`i18n.manager()`) replaces the `QTranslator`s
(KonGUI's and Qt's own `qtbase_<lang>`), sets `QLocale` and sends
`QEvent.LanguageChange` to every top-level widget. Widgets refresh without being
recreated: `Label`, `Badge` and `Button` accept a text or a function returning it;
`i18n.bind(owner, apply)` covers anything else; `Page` has `TITLE` / `SUBTITLE` and a
`retranslate()` hook that rebuilds built content while keeping the current page,
search text, sort order and form fields. Dialogs are created per use.

**Writing texts.** Use `self.tr("...")` (or `QCoreApplication.translate("Context",
"...")`) with a *literal* context and text, because `pyside6-lupdate` only reads
literals. Messages are complete sentences with named fields
(`"Apply “{name}”?".format(name=name)`), never concatenated fragments. Plurals use
Qt's `%n` form (`self.tr("%n profile(s)", "", count)`); texts defined at import time
use `QT_TRANSLATE_NOOP`. Proper names (KonGUI, Konsave, Plasma), commands, paths,
extensions and section keys are not translated.

**Updating the catalogs.** After adding or changing a text, run
`make translations` (`pyside6-lupdate`, then `pyside6-lrelease`), translate the new
`unfinished` messages in `kongui_pt_BR.ts`, run it again and commit the `.ts` and
`.qm` files. `tests.test_i18n` fails if a `.ts` lacks a text of the code, a `.qm` is
not what its `.ts` compiles to, a message is unfinished or lost a `{field}` / `%n`,
or a Portuguese literal appears in the code. To add a language, add it to
`i18n.SUPPORTED`, create the two files and extend `detect_language`.

**Konsave messages.** Text from the bundled Konsave code is not changed;
`messages.py` maps its known English messages, with regular expressions, to
translatable sentences. An unknown message is shown as it came, with a generic
prefix.

**Language limits.**

* Notices already on screen and activity entries already written keep their
  language; the next ones use the new one.
* The fictitious `--demo` data (profile names, descriptions, sections and activity,
  `kongui/gui/mock_data.py`) is always English: it is sample content, not interface
  text. The interface around it is translated.
* Brazilian Portuguese counts 0 as singular, as Qt / CLDR do ("0 perfil").
* A Konsave message reworded in a future release may show in English until its
  pattern in `messages.py` is adapted.
* Messages printed to the terminal before the window exists (for example "Konsave
  not found") are English only.

## 10. Tests

```bash
QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests -t . -v
```

The interface tests need no screen (`offscreen`) and use a temporary `$HOME`; tests
that write files refuse to run as root, and no test applies a profile to the real
session. Without PySide6 the interface tests are skipped. The feature-by-feature map
is in [`TEST_OVERVIEW.md`](TEST_OVERVIEW.md).

| Test module | Covers |
|---|---|
| `tests.test_gui_overview` | every feature once, chained the way a user would, through the real interface and dialogs down to the real services |
| `tests.test_gui_startup` | opening, fixed structure, icons, preferences, `main` entry point, isolation from Konsave, this document |
| `tests.test_gui_navigation` | side bar, top bar, shortcuts, theme switch |
| `tests.test_gui_widgets` | adaptive grid, badge row, notices, dialogs (including layout at minimum size), drop area, theme, formatting |
| `tests.test_i18n` | language detection and saved choice, live switching, plurals and formats, completeness and freshness of the `.ts` / `.qm` files, no Portuguese literals in the code |
| `tests.test_gui_interaction` | each page: search, sorting, apply, remove, export, import, settings, dashboard |
| `tests.test_gui_operations` | the operations one by one in the interface (in-memory backend): loading, success, error, confirmation |
| `tests.test_gui_real_backend` | the operations on the real services, in a temporary `$HOME` |
| `tests.test_gui_transfer` | import and export in the interface (in-memory backend): form, conflicts, confirmations, errors |
| `tests.test_gui_transfer_roundtrip` | export in one home and import in another with the real Konsave, compared byte by byte, and with the original CLI |
| `tests.test_gui_backups` | safety copies in the interface: dialog, restore / delete with confirmation, locks, errors, end to end |
| `tests.test_snapshot` | safety copies in the core, with the real Konsave in a temporary `$HOME` |
| `tests.test_gui_dialogs` | the dialogs actually triggered (replace / unique name, typed word) and the helpers of `app.py` |
| `tests.test_gui_audit` | closing during an operation, archive warnings in the import form, export-folder check off the thread, Konsave version, export on a new account |
| `tests.test_version` | the version shown in the badge, the *About* row and the side-bar caption; see [`RELEASING.md`](RELEASING.md) |
| `tests.test_smoke` | `tools/smoke_test.py`, the check the release workflow runs on the built wheel; see [`RELEASING.md`](RELEASING.md) §5 |
| `tests.test_gui_support` | messages, executors, `FakeBackend`, `ProfileStore`, feedback widgets |
| `tests.test_gui_lock_wait` | waiting for and cancelling the cross-process lock (see [`CONCURRENCY.md`](CONCURRENCY.md)) |

Manual visual check: open the program, switch between the three themes and both
languages, resize the window down to its minimum, and in `--demo` use *Settings →
Demo data → Empty profiles* to see the empty states. For the existing-file dialog,
export the profile "Minimalist" to `~/Downloads`.

## 11. Known limitations

* Apply is not atomic: if it fails halfway, part of the files has already been
  swapped (the notice shows Konsave's errors); restore the safety copy (§6).
* Import writes the archive's `export` section **before** anything else; if Konsave
  fails afterwards the profile is undone, but those files only come back from the
  safety copy.
* "Active" is only the last profile applied from this interface; Konsave does not
  record it.
* The description lives in a small file inside the profile folder
  ([`INTEGRATION.md`](INTEGRATION.md) §11): it does not travel in the `.knsv`.
* Single files within a category cannot be picked in the interface: edit
  `~/.config/konsave/conf.yaml` by hand ([`LIMITATIONS.md`](LIMITATIONS.md) §4).
* No cancellation or partial progress, only "busy"; a large export or import blocks
  other operations.
* Safety copies are never deleted automatically and their number is not limited.
* The size limits and free-space estimates are constants and approximations; the
  check and the operation are not atomic.
* The `.knsv` is neither signed nor encrypted and its `conf.yaml` decides where files
  go: only destinations inside the home are accepted, but import only archives from
  trusted sources.
* Export copies the **global** `conf.yaml` into the `.knsv` while assembling `save/`
  and `export/` from the **profile's** one (a Konsave limitation); KonGUI neither
  warns nor rewrites it.
* The executable bit and file metadata do not survive export → import (a Konsave
  limitation).
* `replace` uses `rename` (same file system) and only leaves a `.kongui-*` leftover
  if the process dies halfway.
* Two KonGUI instances, or KonGUI and `konsave`, are serialized by the cross-process
  lock; the interface shows the wait and lets you cancel it
  ([`CONCURRENCY.md`](CONCURRENCY.md) §4).
* The engine redirects `stdout` globally during each call.
* Accessibility: accessible names, keyboard focus and contrast were handled, but not
  tested with a screen reader. System theme icons (`QIcon.fromTheme`) are not used.
* Real Plasma sessions: what has and has not been tested (X11, SELinux, Flatpak) is
  in [`PLASMA_TEST_PLAN.md`](PLASMA_TEST_PLAN.md).

The complete list of limitations and the decisions behind them is in
[`LIMITATIONS.md`](LIMITATIONS.md).
