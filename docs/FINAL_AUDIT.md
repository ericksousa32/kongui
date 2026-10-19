# KonGUI final audit

**Verdict: the project is NOT complete, but it is ready for an alpha pre-release as
soon as the owner records the real Plasma session report (B-3).** Everything that can
be prepared from here is: package, version from the tag, release workflow, smoke test,
installation instructions and the test script for the session
([`PLASMA_TEST_PLAN.md`](PLASMA_TEST_PLAN.md)). No tag or release exists. The mandatory requirements P-1 (RN-01, safety copy before
apply/import), P-2 (lock) and P-3 (basic limits and free-space checks on
import/export) are implemented and tested, and so are the profile descriptions and
sections (B-2). What remains open is B-3 (validation in a real Plasma session, in
progress) and B-1 (progress and cancellation, blocked by the engine) (§3.5, §4).
Everything that was provably broken and within reach was fixed. The owner's
decisions on the open points of the earlier audit are in §5, and all the limits,
decisions and open items are collected in [`LIMITATIONS.md`](LIMITATIONS.md).

Note on interface texts: the interface is available in English and Brazilian
Portuguese. Labels and messages are quoted in this document as they appear in the
Portuguese interface, with an English gloss in parentheses where needed.

## 1. Scope and method

* Baseline: the original CLI (`konsave/__main__.py`) and the requirements of each
  earlier stage (integration, prototype, wiring to the services, import/export,
  `conf.yaml` editor).
* **Limitation of this audit:** the "requirements matrix" of the first audit is not
  in the repository, in the project documents or in the history this session has
  access to (only the "RN-01" reference remains in `docs/INTEGRATION.md`). The list
  in §3 was **reconstructed** from the CLI and from the requests of each stage. If
  the original matrix has items that are not here, the project owner needs to
  check them.
* For each finding: a reproducible probe, a minimal fix, and a test that fails
  without the fix. Only **proven** problems were fixed; nothing was rewritten.
* Tests run as an unprivileged user, with a temporary `$HOME`. None applies a
  profile to the real session (`tests.test_zz_real_home_guard` checks this).
* Tests of this audit: `tests.test_gui_audit`, `tests.test_core_audit` (plus
  `tests.test_safety` and `tests.test_gui_dialogs`, extended). P-1 has its own:
  `tests.test_snapshot` and `tests.test_gui_backups`. The interface language has
  `tests.test_i18n`. The package name, its dependencies and the version of the bundled
  engine have `tests.test_packaging`; the version shown by the interface, and how it
  follows the package, have `tests.test_version`.

## 2. Fixed findings

| # | Proven problem | Fix | Commit |
|---|---|---|---|
| A-1 | A `.kongui-*` name was accepted on save but never listed (an "invisible" profile, impossible to remove) | reserved prefix refused by the core and by the GUI | b05e3db |
| A-2 | Name limit counted in characters: names with accents/emoji passed and the file system refused them (255 bytes) | limit of 200 **bytes** (core + message in the GUI) | b05e3db |
| A-3 | Closing the window during an operation froze it, left an orphan process and printed a traceback | window refuses to close while busy; the worker ignores `RuntimeError` after teardown | 8730a08 |
| A-4 | Exporting with a global `conf.yaml` different from the profile's produced a contradictory `.knsv` without a warning | warning on export and on inspect (`+` only in the active one, `-` only in the profile, `~` changed); message in pt-BR | c6c9a6d |
| A-5 | `probe_export` (disk access) ran on the interface thread | runs in the background; button locked while checking | 969d8d5 |
| A-6 | The Konsave version (`-v`) did not appear in the interface | "Versão do Konsave" (Konsave version) in the About page | 969d8d5 |
| A-7 | The import message with a leftover folder did not say which folder | path included | 969d8d5 |
| A-8 | Exporting on an account without `conf.yaml` failed with a raw `FileNotFoundError` | creates the default first (as the original does on startup); the core requires an active config | 4d2730f |
| A-9 | The `conf.yaml` editor could mix `\n` and `\r\n` | the original's line breaks are preserved | 0f268a0 |
| A-10 | `requirements_dev.txt` listed unused dependencies | only `black` and `pylint` | 0f268a0 |
| A-12 | **P-1 / RN-01:** apply and import overwrote files with no way back (the confirmation texts said "no backup") | `kongui/core/snapshot.py`: copy of the files that would be overwritten before running (fail closed), restore/list/delete, dialog in Settings → Safety copies ("Configurações → Cópias de segurança"; `docs/INTEGRATION.md` §9, `docs/GUI_SERVICES.md` §7) | commit of that stage |
| A-11 | Real dialogs (confirm, choose, type `APAGAR`) without a test | `tests.test_gui_dialogs`; failure paths of the editor in `tests.test_gui_audit` | 0f268a0 + this one |

## 3. Final requirements matrix

Legend: **Tested** = implemented and covered by an automated test;
**Implemented** = exists, without sufficient automated testing; **Pending** = does
not exist and is a requirement; **Blocked** = depends on something out of reach;
**In progress** = being carried out.

### 3.1 Options of the original CLI

| Requirement | Graphical equivalent | Status | Evidence / note |
|---|---|---|---|
| `-l/--list` | Profile list (page and panel) | Tested | `tests.test_gui_real_backend` (RealListTests), `tests.test_profile_service_integration` |
| `-s/--save` | "Salvar perfil" (Save profile) dialog | Tested | SaveIntegrationTests, RealSaveTests; names: `tests.test_safety` |
| `-s -f` (overwrite) | "Sobrescrever" (Overwrite) (`ProfileService.replace`, **replace** semantics, not merge) | Tested | ReplaceIntegrationTests, RealOverwriteTests; destructive confirmation |
| `-a/--apply` | "Aplicar" (Apply) | Tested | ApplyIntegrationTests, RealApplyTests; destructive confirmation; safety copy first (RN-01). Still not atomic (the warning shows Konsave's errors; the copy allows going back) |
| `-r/--remove` | "Remover" (Remove) | Tested | RemoveAndWipeIntegrationTests, RealRemoveTests; confirmation |
| `-w/--wipe` | "Limpar todos" (Clear all) | Tested | confirmation **and** typing `APAGAR` (`tests.test_gui_dialogs`) |
| `-e/--export-profile` | Export page | Tested | `tests.test_gui_transfer_roundtrip` (ExportTests, CliCompatibilityTests) |
| `-d/--export-directory` | "Pasta de destino" (Destination folder) + "Escolher…" (Choose…) | Tested | default `~/Downloads` (the original uses the current folder); folder checked first (`tests.test_gui_audit`) |
| `-n/--export-name` | "Nome do arquivo" (File name) | Tested | core name rules |
| `-f` on export | "O arquivo já existe" (The file already exists) dialog (replace / unique name / cancel), always shown | Tested | never passes `force` to folders; unique name `name-2` instead of `name_fDate` (known difference) |
| `-i/--import-profile` | Import page (drop/choose) | Tested | HostileArchiveIntegrationTests, InspectArchiveIntegrationTests, ImportTests |
| `-v/--version` | About → "Versão do Konsave" | Tested | `tests.test_gui_audit` (EngineVersionTests) |
| `-h/--help` | — | N/A | makes no sense in a GUI |
| Default `conf.yaml` created on startup | `ensure_default_config` before save/export | Tested | `conf_kde.yaml` vs. `conf_other.yaml` according to the desktop; FreshAccountExportTests |

### 3.2 The `conf.yaml` editor

| Requirement | Status | Evidence |
|---|---|---|
| Validate before writing; do not write on failure | Tested | `tests.test_config_editor`, `tests.test_gui_config` |
| Errors with line/column and path; go to the spot | Tested | same |
| Backup before each write; restore a backup | Tested | same; conflict can be forced (`tests.test_gui_audit`) |
| Preserve comments, unknown keys, placeholders, BOM, anchors | Tested | real Plasma 6 archive (`tests/profile_test.knsv`) |
| *Flow* style ⇒ rewrite without comments, only with explicit "yes" | Tested | `tests.test_gui_audit` (ConfigPageFailurePathTests) |
| Writing while busy / without validating writes nothing | Tested | same |
| Placeholders (`$HOME`, `$XDG_*`…) interpreted like the original | Tested | `tests.test_config_service` (PlaceholderValidationTests) |
| Pruning of old backups | Decided: not done | project decision (2026-10-18): `conf.yaml.bak-*` files are never removed automatically and have no count limit; see `LIMITATIONS.md` §2 |

### 3.3 Safety, concurrency and files

| Requirement | Status | Evidence / note |
|---|---|---|
| Every destructive operation confirmed (apply, remove, wipe, import, replace file) and refused without a real `confirmed=True` | Tested | `tests.test_gui_dialogs`, `tests.test_profile_service_mocked` |
| Interface does not freeze; one operation at a time; "wait" state | Tested | `tests.test_gui_operations`, `tests.test_gui_audit` |
| Closing the window with an operation running | Tested | CloseWhileBusyTests |
| Profile/file names (`/`, `..`, leading `-`, reserved, bytes) | Tested | `tests.test_safety` |
| Hostile archives (`..`, absolute, links, destination outside home) | Tested | HostileArchiveIntegrationTests |
| Permissions and missing folders become a clear message | Tested | `tests.test_gui_transfer`, `tests.test_gui_audit` |
| Refusal to run as root | Tested | `tests.test_engine`, `tests.test_cli_runner` |
| **RN-01 / P-1:** copy of the files `apply`/`import` overwrite, before writing; a failed copy prevents the operation | Tested | `tests.test_snapshot` (ApplySnapshotTests, ImportSnapshotTests), `tests.test_gui_backups` (RealSafetyCopyTests) |
| RN-01: restore (files, mode, links, created files), with confirmation, manifest validation, paths only inside the home, undo of the restore | Tested | RestoreRulesTests, EdgeCaseTests |
| Profile description (small file inside the profile folder) and read-only sections: persistence, isolation between profiles, renamed folder, removal, import without metadata (a description planted in an archive is dropped), failed writes, `replace` carry-over, no change to the exported archive; dialog, card, warnings, plain-text display, friendly group names | Tested | `tests.test_profile_details`, `tests.test_gui_details` |
| RN-01: list/delete copies in the interface; buttons locked during an operation; nothing is deleted by itself | Tested | `tests.test_gui_backups` (DemoSafetyCopyTests) |
| Import → export preserves the profile (real Plasma 6 archive) | Tested | identical, except `conf.yaml` (A-4/§5) |
| `.knsv` exchanged with the original `konsave` in both directions | Tested | CliCompatibilityTests |
| Unused dependencies | Tested | A-10; `setuptools` is no longer declared at runtime: nothing imports it and the whole suite passes with it made unimportable (§5, `tests.test_packaging`) |
| Distribution called `kongui`, with the author, URL and links of this repository; both commands installed; the `konsave` command still starts | Tested | `tests.test_packaging`; a wheel built in a clean virtual environment and installed there printed `Konsave: 2.2.0+kongui` for `konsave -v` (patch `KONGUI-PATCH(rename)`, `KONSAVE_PATCHES.md` §3.5) |
| Build from a clone, from an sdist and from a `git archive` / GitHub "Source code" file gives the version of the tag (`.git_archival.txt`, `pyproject.toml`) | Tested | `tests.test_packaging` (SourceArchiveTests, needs `git` and `setuptools_scm`; skipped otherwise); `pip wheel --no-deps .` and `python -m build` of the real files in a clean virtual environment (2026-10-18) |
| The version in the interface is the version of the package, which comes from the git tag; unknown shows `dev` | Tested | `tests.test_version`; a wheel built from a local tag `v0.1.0a1` in a copy of the repository reported `0.1.0a1`, and one commit later `0.1.0a2.dev1+g…` (`RELEASING.md` §4) |
| Choosing what a profile includes | Decided: manual | done in *Edit .YAML*, steps in `GUI_CONFIG.md` §7 and the README; not offered when saving |

### 3.4 Interface language

| Requirement | Status | Evidence / note |
|---|---|---|
| English and Brazilian Portuguese, English as source and fallback | Tested | `tests.test_i18n` (FallbackTests, TranslationFilesTests) |
| First run follows the system locale: exactly `pt_BR` gives Portuguese, any other locale (including `pt_PT` and `pt`) gives English | Tested | DetectionTests, FirstRunTests |
| An explicit choice is saved in KonGUI's own settings, survives a restart and is never overwritten by detection; "no preference" is different from a choice | Tested | PreferenceTests, RestartTests |
| Switching at runtime without a restart, keeping the page and typed data | Tested | LiveSwitchTests |
| Dialogs, notices, errors and cards created after a switch use the new language | Tested | LaterComponentsTests |
| Missing translation, missing or unreadable catalog, unknown language: English, no failure | Tested | FallbackTests |
| Plurals, sizes and dates in the language in use | Tested | FormatTests |
| Nothing left in the other language on any page; catalogs complete, finished, with the same fields as the source, up to date with the code and compiled | Tested | WholeInterfaceTests, TranslationFilesTests; no Portuguese literal in the code (NoHardcodedPortugueseTests) |
| Translation files are packaged | Tested | `package_data` in `setup.py`, checked by `tests.test_i18n`; a wheel built with `python -m build --wheel` in a clean virtual environment (2026-10-17) contains the four files in `kongui/gui/translations/`, no `tests/`, and still contains `mock_data.py` (demo mode) |

Limits (see `GUI_PROTOTYPE.md`, section 8): notices and activity entries already
shown keep the language they were written in; the fictitious demo data is always
English (not translated); messages from the bundled Konsave are
translated by matching their English text; terminal messages printed before the
window exists are English only.

### 3.5 Pending, in progress and blocked

| Id | Requirement | Status | Reason |
|---|---|---|---|
| P-2 | Cross-process lock (two KonGUI, or KonGUI + `konsave`) | Tested (mechanism, CLI, services and wait/cancel interface) | `fcntl.flock` on `~/.config/konsave/.kongui.lock`; `tests.test_locking`, `tests.test_gui_lock_wait`; see `CONCURRENCY.md` and `KONSAVE_PATCHES.md`. B-1 below no longer applies to the minimal changes authorized only for the lock |
| P-3 | Limits for zip bombs, total size and disk space on import/export | Tested (basic protection) | 512 MiB file, 2 GiB really decompressed (stops at the limit), 10,000 entries, free-space check before import and export, friendly messages, failed export keeps the previous one; `tests.test_transfer_limits`; see `INTEGRATION.md` §10. Limits are fixed constants and estimates, not guarantees (see §4) |
| B-1 | Progress and cancellation of operations | Blocked | the engine cannot be interrupted, and `konsave/` is only changed for the lock; today there is only "busy" |
| B-2 | Profile description and sections | Tested (description and read-only sections) | the description is a small file inside the profile folder and the sections come from the profile's `conf.yaml` (`INTEGRATION.md` §11; `tests.test_profile_details`, `tests.test_gui_details`). The description does not travel in the `.knsv`; choosing what to include when saving is not offered (manual, through *Edit .YAML*) |
| R-1 | First tag / pre-release | **Prepared, not created** | `.github/workflows/release.yml` replaced `deploy.yml` (no PyPI): tag check, build, clean-environment smoke test, checksums, GitHub pre-release; its steps were run on a scratch repository, never on real GitHub Actions (`RELEASING.md` §5). Before the first tag: record the B-3 report and follow the checklist in `RELEASING.md` §6 |
| B-3 | Validation in a real Plasma session (actually applying, Wayland/drag-and-drop, SELinux, Flatpak) | **In progress** | the project owner is testing in a real Plasma session; results are not recorded here yet. The screenshots in `screenshots/` (Fedora 44, Qt 6.12, demo mode) show that the interface renders there, but they do not validate applying profiles, Wayland, SELinux or Flatpak |

## 4. Why it is not complete

P-2 (cross-process lock, with wait and cancel in the interface) and P-3 (basic
limits and free-space checks, `INTEGRATION.md` §10) were implemented and tested. The
project is still not declared complete: B-1 does not prevent use, but it limits
what can be claimed, and B-3 (real-session testing) is still in progress. B-2 was
resolved in part (description and read-only sections, `INTEGRATION.md` §11); what
remains of it is by design: the description does not travel in the `.knsv`, and
choosing what a profile contains stays manual in the `conf.yaml` editor (steps in
`GUI_CONFIG.md` §7).

Limits of P-3: the limits are constants, not a policy; the free-space check is an
estimate and is not atomic with the operation (another program can fill the disk
in between; a real `ENOSPC` is then reported and cleaned up); the decompression
pass reads the archive once more before importing; the export section is read from
the live system, so its size can change between the estimate and the copy; the
original engine is not interrupted or made atomic, so an import that fails halfway
is still undone by the layer, not by the engine.

Limits of P-1, already documented: the copy of an `import` does not undo the
imported profile; restoring does not protect against programs that do not use the
lock (external tools, see `CONCURRENCY.md` §5); the copy has no size limit (the P-3 limits apply to the archive, not to the safety copy).

## 5. Decisions of the project owner and open points

Decisions given on 2026-10-18 for the points left open by the earlier audit (each
one is written down in [`LIMITATIONS.md`](LIMITATIONS.md)):

1. **`conf.yaml` inside the `.knsv`**: Konsave writes the global `conf.yaml` but
   assembles `save/`/`export/` from the profile's. Decision: **it is not rewritten**.
   The GUI keeps warning (A-4).
2. **RN-01 safety copies**: scope "only the files the operation overwrites", in
   `~/.config/konsave/kongui-backups/`. Decision: **no limit on the number of copies
   and no automatic pruning** (pruning would delete precisely the oldest copy, which
   holds the original state).
3. **`setuptools` as a runtime dependency**: **it was not real, and the declaration was
   removed** from `requirements.txt`. Evidence: no module of `kongui/` or `konsave/`
   imports `setuptools`, `pkg_resources` or `distutils` (`tests.test_packaging` reads
   the syntax tree of every file); the whole suite (912 tests at that point) passed
   with those three names made unimportable by a `sitecustomize` import hook; the
   only use is `setup.py`, which is build time (the release workflow installs it).
4. **Missing PySide6**: the `kongui` command still shows a raw `ImportError`. Left as
   it is for now.
5. **`conf.yaml` backups** are never pruned. Decision: no pruning.
6. **A *flow*-style `conf.yaml`** falls back to a rewrite that loses comments (with
   explicit confirmation). Left as it is.
7. **P-3 limits**: left as fixed constants; their limits are now spelled out in
   [`LIMITATIONS.md`](LIMITATIONS.md) §3 and `INTEGRATION.md` §10.
8. **Package name and metadata**: the distribution is now `kongui`, with the author,
   URL and project links of this repository (and credit to Konsave). This broke the
   bundled `konsave` command (its version lookup is by distribution name), which was
   reproduced with a wheel and fixed with the patch `KONGUI-PATCH(rename)`
   (`KONSAVE_PATCHES.md` §3.5). The owner approved this exception to the rule of
   changing `konsave/` only for the lock.
9. **Version of the package and of the interface (decided, option A):**
   `kongui.__version__` is no longer a constant; it reads the version of the
   installed package, which `setuptools_scm` takes from the git tag, so the two can
   not disagree. Unknown (uninstalled checkout) is shown as `dev`; the badge and the
   sidebar show the short form. See [`RELEASING.md`](RELEASING.md) and
   `tests.test_version`.
10. **`setuptools_scm` (decided):** it is now a declared build requirement
    (`pyproject.toml`, `[build-system]`) and `setup_requires` was removed. Building
    from GitHub's "Source code" archive of a tag failed ("unable to detect version")
    and now works through `.git_archival.txt` + `.gitattributes`; see
    [`RELEASING.md`](RELEASING.md) §4 and `tests.test_packaging`.
11. **Release workflow (decided by the owner: "up to you"):** `deploy.yml` was
    replaced by `release.yml`. It no longer publishes to PyPI; it builds with `python
    -m build` from a checkout with the whole history, refuses tags that are not PEP 440
    versions or not on `master`, tests the wheel in a clean environment
    (`tools/smoke_test.py`), writes `SHA256SUMS` and creates a GitHub pre-release for
    `a`, `b` and `rc` tags. `pip install kongui` still does not install PySide6 (extra
    `gui`), as decided.
12. **PySide6 on older Pythons (found while preparing the release):** PySide6 6.10 and
    newer crash on Python older than 3.12, so the `gui` extra limits it to 6.8–6.9
    there ([`LIMITATIONS.md`](LIMITATIONS.md) §5, evidence in §6 below).

## 6. Test results

Measured on 2026-10-18 and 2026-10-19 on branch `chore/prerelease-readiness` (uncommitted work on top of `dev`, which already contains everything merged up to PR #9), as an unprivileged user with a temporary `$HOME`, Qt offscreen, each run **in the foreground**:

* **949 tests, all passing** (`python3 -m unittest discover -s tests -t .`, about 3 minutes). With `setuptools_scm` installed all 949 run; without it the 3 tests of `SourceArchiveTests` are skipped (946 run). Run it **in the foreground**: started as a background job, the shell makes the child processes ignore Ctrl+C and `tests.test_locking.CliTests.test_a_waiting_command_can_be_interrupted` fails with `-9` instead of `130`; the same test passes alone and in the foreground. Earlier in this work one coverage run reported a single failure whose name was not captured and that was not reproduced; if a test fails once, rerun it alone and in the foreground before treating it as a regression. One more one-off: a run on Python 3.10 that crossed midnight failed `tests.test_i18n...test_switching_back_and_forth_leaves_no_mixed_text` ("3 days ago" against "2 days ago": the demo dates are relative to now); it is time-dependent, not a regression, and that combination passed in the next run.
* **Python and PySide6 matrix** (full suite each, all 949 tests OK and the process exiting with status 0):

  | Python | PySide6 | Result |
  |---|---|---|
  | 3.9.25 | 6.9.3 (6.8.3 also) | OK |
  | 3.10.22 | 6.9.3 | OK |
  | 3.11.17 | 6.9.3 | OK |
  | 3.12.15 | 6.12.0 | OK |
  | 3.13 (system and venv) | 6.12.0 | OK |
  | 3.14.8 | 6.12.0 | OK |

  Where it did **not** work (hence the limit in the `gui` extra, `LIMITATIONS.md` §5):
  3.9 with PySide6 6.10.3 segfaulted opening *Settings → Safety copies → Manage…*
  (gdb: `PySide::qobjectConnectCallback`, inside PySide6); 3.11 with 6.10.3 segfaulted
  in the GUI tests; 3.10 and 3.11 with 6.12.0 passed every test and then **aborted
  while the interpreter shut down** (`free(): invalid size`, `bool_dealloc:
  deallocating True or False`), reproducibly with the whole GUI test set (no single
  module or pair of modules triggers it). It is not found in KonGUI's code; it
  follows the PySide6 version and the Python version (3.12 and newer are not affected).
* The installed application was also checked on 3.11 (PySide6 6.9.3, resolved by pip from the extra) and 3.13 (6.12.0): a wheel built from a tagged scratch copy, installed with `[gui]` in a clean environment, `tools/smoke_test.py --expect-version 0.1.0a1` run from another folder: version `0.1.0a1`, `konsave -v` prints `Konsave: 2.2.0+kongui`, both catalogs load, the window opens with its six pages, exit status 0.
* **Release workflow:** the steps of its `build` job were run on a scratch repository (branch `master`, local bare remote, tag `v0.1.0a1`): version read, ancestor-of-`master` check, build, file names, clean-environment smoke test and `SHA256SUMS` all passed; a tag that is not a version, a tag whose commit is not on `master` and a tag that disagrees with the build were each refused. `actionlint` passes. **Not tested on real GitHub Actions** (`RELEASING.md` §5).
* The same suite also passed (912 tests, before `tests.test_packaging` existed) with `setuptools`, `pkg_resources` and `distutils` made unimportable (§5, item 3).
* Coverage of `kongui/` with `coverage run --branch --source=kongui`: **96%**
  (6943 statements, 224 not run; 1666 branches, 127 partly covered; measured earlier in this work, before the packaging, version and smoke-test tests, which only touch packaging files and scripts). `konsave/` was
  not measured. The lowest modules: `gui/__main__.py` 0% (three lines, only the
  `python -m kongui.gui` entry), `core/yamlmap.py` 87%, `gui/messages.py` 88%,
  `gui/widgets/dropzone.py` 88%, `gui/widgets/confedit.py` 90%, `gui/backend.py` 90%.
* `pylint kongui`: 10.00/10; `black --check kongui tests konsave setup.py`: clean.
* Packaging: `python -m build --wheel --no-isolation`, in a virtual environment with `setuptools` 75 or newer, built `kongui-0.1.dev43+g…-py3-none-any.whl` (2026-10-18): metadata `Name: kongui`, the new author, URLs and classifiers, `Requires-Dist: PyYaml>=5.4.1` only (PySide6 in the `gui` extra), both console scripts, no `tests/`. Installed there, `konsave -v` prints `Konsave: 2.2.0+kongui` and `ServiceBackend.engine_version`, which the *About* page shows, returns `2.2.0+kongui`. The version of the wheel comes from git (no tag exists yet).
* `pyproject.toml` makes pip build in an isolated environment with `setuptools>=75`
  and `setuptools_scm>=8`. `pip wheel --no-deps .` and `python -m build` (sdist and
  wheel) were run on a copy of the repository tagged `v0.1.0a1` (and on a `git
  archive` of it) in clean virtual environments: all gave `0.1.0a1`. The earlier
  failure with the distribution's own `setuptools` (Debian 68.1.2, `pip wheel .`,
  `AttributeError: install_layout`) came from using that old `setuptools` in the legacy
  `setup.py` path; with `pyproject.toml` it is not used, but this was **not** re-tested
  on Debian.
* All tests use temporary home directories, and most GUI tests use the in-memory
  backend. None of this replaces testing in a real Plasma session (B-3).

## 7. Real Plasma session report

**Pending.** The project owner is testing in a real Fedora KDE / Plasma session
(applying profiles, Wayland and drag-and-drop, SELinux, Flatpak, fractional scaling,
switching color scheme with the app open). The report will be added here, and B-3
changes status only then.
