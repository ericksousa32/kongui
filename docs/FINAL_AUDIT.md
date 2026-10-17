# KonGUI final audit

**Verdict: the project is NOT complete.** Mandatory requirements are still pending
(see §4: P-3). P-1 (RN-01, safety copy before apply/import) was implemented and
tested after the first report. Everything that was provably broken and within reach
was fixed; what depends on testing in a real Plasma session is marked as in
progress or blocked.

Note on interface texts: the interface is currently in Brazilian Portuguese. Labels
and messages are quoted in this document as they appear on screen, with an English
gloss in parentheses where needed.

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
  `tests.test_snapshot` and `tests.test_gui_backups`.

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
| Pruning of old backups | Pending (not mandatory) | backups grow without limit |

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
| RN-01: list/delete copies in the interface; buttons locked during an operation; nothing is deleted by itself | Tested | `tests.test_gui_backups` (DemoSafetyCopyTests) |
| Import → export preserves the profile (real Plasma 6 archive) | Tested | identical, except `conf.yaml` (A-4/§5) |
| `.knsv` exchanged with the original `konsave` in both directions | Tested | CliCompatibilityTests |
| Unused dependencies | Tested | A-10; `setuptools` still declared at runtime (see §5) |

### 3.4 Pending, in progress and blocked

| Id | Requirement | Status | Reason |
|---|---|---|---|
| P-2 | Cross-process lock (two KonGUI, or KonGUI + `konsave`) | Tested (mechanism, CLI, services and wait/cancel interface) | `fcntl.flock` on `~/.config/konsave/.kongui.lock`; `tests.test_locking`, `tests.test_gui_lock_wait`; see `CONCURRENCY.md` and `KONSAVE_PATCHES.md`. B-1 below no longer applies to the minimal changes authorized only for the lock |
| P-3 | Limits for zip bombs, total size and disk space on import/export | **Pending** | there is no size/space check |
| B-1 | Progress and cancellation of operations | Blocked | the engine cannot be interrupted, and `konsave/` is only changed for the lock; today there is only "busy" |
| B-2 | Profile description and sections | Blocked | Konsave does not store these data |
| B-3 | Validation in a real Plasma session (actually applying, Wayland/drag-and-drop, SELinux, Flatpak) | **In progress** | the project owner is testing in a real Plasma session; results are not recorded here yet |

## 4. Why it is not complete

P-3 (size, zip-bomb and disk-space limits) is a data-loss/availability risk that the
GUI does not mitigate and it remains pending; P-2 (cross-process lock, with wait and
cancel in the interface) was implemented and tested. While P-3 exists, the project
is not declared complete. B-1 and B-2 do not prevent use, but they limit what can
be claimed, and B-3 (real-session testing) is still in progress.

Limits of P-1, already documented: the copy of an `import` does not undo the
imported profile; restoring does not protect against programs that do not use the
lock (external tools, see `CONCURRENCY.md` §5); the copy has no size limit (P-3).

## 5. Decisions and open points for the project owner

1. **`conf.yaml` inside the `.knsv`**: Konsave writes the global `conf.yaml` but
   assembles `save/`/`export/` from the profile's. The GUI **warns** (A-4) but does
   not rewrite the archive's. Decide whether it should rewrite it.
2. **RN-01** (P-1): implemented with the scope "only the files the operation
   overwrites", in `~/.config/konsave/kongui-backups/`, without automatic retention
   (pruning would delete precisely the oldest copy, the one that holds the original
   state). Confirm whether this is what is wanted or whether there should be a
   limit on the number of copies.
3. `setuptools` is declared as a runtime dependency without proven need; left as
   is because it is outside the evidence of this audit.
4. The `kongui` command without PySide6 installed shows a raw `ImportError`.
5. `conf.yaml` backups are never pruned.
6. A *flow*-style `conf.yaml` falls back to a rewrite that loses comments (with
   explicit confirmation).

## 6. Test results

* 763 tests, all passing, run as an unprivileged user.
* Line and branch coverage of `kongui/`: 96% at the last measurement before the
  lock work (`snapshot.py`: 97%); it was not re-measured as a whole afterwards.
* `pylint kongui`: 10.00/10; `black --check`: clean.
