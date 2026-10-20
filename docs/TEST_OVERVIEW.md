# Test overview

One map of what the tests cover, feature by feature, and the result of the general
review of the test suite made on 2026-10-19, updated the same day after the
`conf.yaml` management was removed (§5). It builds on the feature list in the
[README](../README.md), the pages in [`GUI_PROTOTYPE.md`](GUI_PROTOTYPE.md) §2 and the
requirements matrix in [`FINAL_AUDIT.md`](FINAL_AUDIT.md) §3, and does not repeat
them.

## 1. Two kinds of interface tests

* **Detailed tests** (most of `tests/`): one feature at a time, with every edge case.
  The interface tests mostly use the in-memory backend (`FakeBackend`) or call the
  controller directly; the services are tested on their own, in temporary homes.
* **Overview tests** (`tests.test_gui_overview`, 4 tests): each one chains several
  features the way a user would, **through the real interface** (buttons, card
  menus, dialogs, the drop area) **down to the real services** and the bundled
  Konsave code, in a temporary `$HOME`. They answer "does the application work as
  a whole?", not "is every case handled?". They were written for this review,
  because no test went from a click to the files on disk for the profile
  operations, the transfers and the safety copies.

How the overview tests answer dialogs: `ScriptedUser` replaces `QDialog.exec` for
the test. Each expected dialog is answered through its own widgets (typing in its
fields, clicking its buttons), so the real dialog logic runs; for example, the
*Clear all* button stays disabled until the word is typed. A dialog that was not
expected, one of the wrong kind, or one that never opened fails the test.

```bash
python3 -m unittest tests.test_gui_overview -v    # about 3 seconds
```

## 2. Feature map

"Overview" names the test of `tests.test_gui_overview` that goes through the feature;
"In depth" names the modules that test it in detail.

| Feature | Overview | In depth |
|---|---|---|
| Window, the five pages, navigation | every test (dashboard, profiles, transfer, settings) | `tests.test_gui_startup`, `tests.test_gui_navigation` |
| Dashboard figures, empty state, activity feed | `ProfileJourneyTests` (0 → 1 profile, active profile, activity entries) | `tests.test_gui_interaction` |
| Save a profile with a description (dashboard button, *New profile*) | `ProfileJourneyTests`, `HandEditedConfigJourneyTests` | `tests.test_gui_operations`, `tests.test_gui_real_backend`, `tests.test_gui_details` |
| Profile card: sections and description | `ProfileJourneyTests`, `HandEditedConfigJourneyTests` | `tests.test_gui_details`, `tests.test_profile_details` |
| Apply, with the safety copy made first | `ProfileJourneyTests`, `HandEditedConfigJourneyTests`, `RealApplicationTests` | `tests.test_gui_operations`, `tests.test_gui_real_backend`, `tests.test_snapshot` |
| Restore a safety copy (*Settings → Safety copies*) | `ProfileJourneyTests` | `tests.test_gui_backups`, `tests.test_snapshot` |
| Edit details (card menu) | `ProfileJourneyTests` | `tests.test_gui_details` |
| Overwrite (card menu) | `ProfileJourneyTests` | `tests.test_gui_operations`, `tests.test_gui_real_backend` |
| A declined confirmation changes nothing | `ProfileJourneyTests` (remove declined) | `tests.test_gui_operations`, `tests.test_gui_dialogs` |
| Export from the card, file conflict (unique name) | `TransferJourneyTests` | `tests.test_gui_transfer`, `tests.test_gui_transfer_roundtrip` |
| Remove (card menu) | `TransferJourneyTests` | `tests.test_gui_operations`, `tests.test_gui_real_backend` |
| Import by dropping a `.knsv`: check, export section written, copy first, description not carried | `TransferJourneyTests` | `tests.test_gui_transfer`, `tests.test_gui_transfer_roundtrip`, `tests.test_profile_details` |
| Recent transfers | `TransferJourneyTests` | none: before this review no test looked at this list |
| Clear all (the word must be typed) | `TransferJourneyTests` | `tests.test_gui_dialogs`, `tests.test_gui_real_backend` |
| No `conf.yaml` editor: a group added **by hand** goes into the next profile only, and is applied (`LIMITATIONS.md` §4) | `HandEditedConfigJourneyTests` | `tests.test_gui_details`, `tests.test_config_service` |
| A broken `conf.yaml` (not checked beforehand): saving fails with Konsave's reason and leaves nothing | `HandEditedConfigJourneyTests` | `tests.test_profile_service_integration` |
| The real assembly of the `kongui` command (`build_backend`, worker thread) | `RealApplicationTests` | `tests.test_gui_startup` (with the backend mocked), `tests.test_gui_lock_wait` |
| Preferences saved and restored (theme, language) | `RealApplicationTests` (restart with the same settings file) | `tests.test_i18n`, `tests.test_gui_startup`, `tests.test_gui_interaction` |

Left out of the overview on purpose, because a detailed test already covers it
end to end and repeating it would add time, not information:

| Feature | Covered by |
|---|---|
| Demo mode writes nothing to the home | `tests.test_gui_interaction` (`NoSideEffectsTests`: a walk through every page) |
| Waiting for, and cancelling, another program's lock | `tests.test_gui_lock_wait`, `tests.test_locking` |
| Search, sorting, grid/list view, notice duration, *About* | `tests.test_gui_interaction`, `tests.test_version`, `tests.test_gui_audit` |
| Import and export limits, hostile or damaged archives | `tests.test_transfer_limits`, `tests.test_gui_transfer_roundtrip` |
| `.knsv` exchanged with the bundled `konsave` command | `tests.test_gui_transfer_roundtrip` (`CliCompatibilityTests`) |
| Every text translated, catalogs up to date, live language switch on every page | `tests.test_i18n` |
| Theme contrast, icons, adaptive grid | `tests.test_gui_widgets`, `tests.test_gui_startup` |
| Refusal to run as root, name rules | `tests.test_safety`, `tests.test_engine`, `tests.test_gui_startup` |
| Packaging, version, smoke test | `tests.test_packaging`, `tests.test_version`, `tests.test_smoke` |

## 3. What the overview found

**A refused operation could be reported with no reason** (fixed). When the service
refused to apply a profile, or to import an archive, for a reason it adds after
validating the `conf.yaml` (a destination folder whose parent does not exist, or a
destination outside the home), and the file only had warnings otherwise, the notice
said "Não foi possível aplicar o perfil" ("Could not apply the profile") with
**no explanation**: `messages.describe_error` only listed the located errors of the
report and dropped those added later. It showed up in `RealApplicationTests`, whose
first version used a home without `~/.local/share`. Now the added errors are listed
too (in English, as the service writes them, like other engine messages). Regression
tests: `tests.test_gui_support` (now `test_a_refusal_says_what_was_refused_and_why`,
rewritten when the validation report was removed: a refusal is a `ConfigError` whose
`details` are always shown) and `tests.test_gui_real_backend`
(`test_a_refused_apply_says_why`).

The refusal itself was correct: KonGUI does not apply a group whose folder and parent
folder are both missing. A real desktop home always has `~/.local/share` and
`~/.config`, so the test now creates them.

Nothing else failed: every feature in §2 worked through the interface on the real
services. One gap of the detailed tests was found: no test looked at the *Recent
transfers* list of the Import / Export page; the overview now checks that it lists
the two exports and the import.

## 4. Review of the existing tests

Measured on 2026-10-19, after the removal of §5, as an unprivileged user, in the
foreground (method in [`FINAL_AUDIT.md`](FINAL_AUDIT.md) §6).

* **805 tests in 32 modules, all passing** (802 run and 3 skipped where
  `setuptools_scm` is missing), on Python 3.13 (system and virtual environment,
  PySide6 6.12.0), 3.9 and 3.11 (PySide6 6.9.3) and 3.14 (PySide6 6.12.0). About
  2.5 minutes. (Before the removal: 955 tests in 34 modules.)
* **Coverage** of `kongui/` (`coverage run --branch`): **96 %** for the whole suite
  (5,174 statements, 137 not run). The four overview tests alone reach **77 %**
  (79 % of `kongui/gui`). The least covered modules: `gui/__main__.py` (three lines,
  the `python -m` entry), `core/config.py` 88 % (unreadable-file paths),
  `gui/widgets/dropzone.py` 88 %, `gui/backend.py` 90 %.
* **Every test checks something.** A static pass over the syntax tree found three
  tests with no assertion call; all three check that a call does *not* raise
  (`ensure_not_root` for an ordinary user and on a platform without `geteuid`;
  `require_free_space` when the disk cannot be read), which is a valid test.
* **Same names, different layers.** 12 test names appear in more than one class.
  Most are the same rule checked for each operation (for example "declining changes
  nothing" for apply, overwrite, remove and clear all). A few check the same
  behaviour at different layers: the service (`tests.test_profile_service_integration`),
  the interface's backend (`tests.test_gui_real_backend`,
  `tests.test_gui_transfer_roundtrip`) and the interface itself (the overview).
  That overlap is intentional (a failure then points at the layer that broke) and
  costs little time, so no test was removed for it.
* **Skips** are deliberate: tests that would write files are skipped when the
  process is really root, the GUI tests when PySide6 is missing, and the source
  archive tests when `git` or `setuptools_scm` is missing.
* **Documentation**: every test module is named in `docs/` (`tests.test_docs`
  enforces it), and the table in [`GUI_PROTOTYPE.md`](GUI_PROTOTYPE.md) §5 lists the
  interface modules.
* **Known sensitivities** (from [`FINAL_AUDIT.md`](FINAL_AUDIT.md) §6): run the suite
  in the foreground (a background job makes one lock test fail with `-9`); one
  language test compares relative dates and can fail once when a run crosses
  midnight.

## 5. After removing the `conf.yaml` management (2026-10-19)

The owner decided to stay within Konsave's scope: no editor, no backups of
`conf.yaml`, no validation of it by KonGUI, no A-4 warning
([`LIMITATIONS.md`](LIMITATIONS.md) §2). Nothing else was to be removed. What was
checked:

* **Removed with it:** `tests.test_config_editor` and `tests.test_gui_config`
  (59 + 37 tests, only the editor), the editor's dialogs in `tests.test_gui_dialogs`,
  its failure paths and the A-4 tests in `tests.test_gui_audit` and
  `tests.test_core_audit`, and the validation tests of `tests.test_config_service`
  (rewritten for what is left: the default file and reading through Konsave).
* **Behaviour that changed, and is now tested as it is:** a broken or unusual
  `conf.yaml` is no longer refused beforehand. Saving with it fails with Konsave's
  own reason and leaves no partial profile (nested entry, broken YAML,
  `tests.test_profile_service_integration`); an unmatched `${ENDS_WITH=…}` is saved
  as an empty group, as Konsave does, and applying it is refused because that
  location is not inside the home. `HandEditedConfigJourneyTests` replaces the
  editor journey: a broken file, then a group added by hand, saved and applied
  through the interface.
* **Kept, and still tested:** the safety copies, the free-space checks, the
  sections on the cards, the refusal of archives or profiles that would write
  outside the home (now also any entry that is not a single name, which the
  removed validation used to catch), and the refusal to apply to a destination
  whose parent does not exist.
* **Every other feature:** the three other overview journeys (profiles and safety
  copies; export, import and clear all; the `kongui` command's assembly with its
  worker thread and preferences) pass unchanged, and so do the detailed modules.
* **Installed package:** a wheel built from a tagged copy contains none of the
  removed modules; installed with `[gui]` on Python 3.11 and 3.13 it passes
  `tools/smoke_test.py` (five pages), and in a temporary home it saved, applied,
  restored the safety copy, exported, removed and imported a profile, refused to
  save with a broken `conf.yaml` (Konsave's reason, nothing left), saved after a
  group was added by hand, and wrote no file next to `conf.yaml`.

## 6. Limits

* Nothing here replaces a real Plasma session ([`PLASMA_TEST_PLAN.md`](PLASMA_TEST_PLAN.md)):
  the "session" is a temporary folder, Qt runs offscreen and no window manager is
  involved.
* The dialogs are answered by replacing `exec`: their widgets and logic run, but not
  the window manager's modality, focus or keyboard handling.
* The file pickers (`QFileDialog`) are not opened: the overview types the folder and
  drops the file instead, as the detailed tests do.
* Only `RealApplicationTests` runs the work on the worker thread; the other overview
  tests run it inline, so each step finishes before the next assertion.
