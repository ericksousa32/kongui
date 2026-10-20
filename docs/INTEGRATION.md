# KonGUI ↔ Konsave integration layer

This document describes the layer the graphical interface (PySide6) uses to talk
to the original Konsave engine. The code lives in `kongui/core/`; the tests live
in `tests/`.

Convention: **[CONFIRMED]** = read in the Konsave source and proven by a test or by
a run in a temporary directory.

## 1. Principles

1. **Reuse the original engine.** Operations call the functions of
   `konsave/funcs.py` inside the same process. No service uses a subprocess.
2. **Subprocess only where it is the goal.** `CliRunner` runs the real CLI
   (`python -m konsave`) for diagnostics and compatibility checks. It is
   **read-only by default** (see §6).
3. **Cross-process lock.** Every operation that uses Konsave data goes through
   `fcntl.flock` on `~/.config/konsave/.kongui.lock` ([`CONCURRENCY.md`](CONCURRENCY.md)).
   It is the only change to the `konsave/` package (listed in
   [`KONSAVE_PATCHES.md`](KONSAVE_PATCHES.md)).
4. **No root.** Every entry point (`KonsaveEngine`, `CliRunner`) refuses
   `euid == 0` with `RunningAsRootError`, before touching the disk. Nothing in the
   layer uses `sudo`, `pkexec` or switches user.
5. **No shell.** Commands are lists (`shell=False`); arguments are validated; the
   subprocess environment is rebuilt from a list of allowed variables.
6. **Tests never touch the real `HOME`.** Each test uses a temporary directory and
   replaces `$HOME`; the last test compares the real `~/.config/konsave` and log
   before and after the suite.

## 2. Confirmed Konsave APIs in use

Only these exist; the layer calls nothing else.

| File | Name | Use in the layer |
|---|---|---|
| `konsave/consts.py` | `HOME`, `KONSAVE_DIR`, `PROFILES_DIR`, `CONFIG_FILE`, `EXPORT_EXTENSION`, `VERSION` | Paths and version (read from a copy of the module bound to the chosen `HOME`) |
| `konsave/parse.py` | `tokens`, `TOKEN_SYMBOL` | List of supported placeholders |
| `konsave/funcs.py` | `save_profile`, `apply_profile`, `remove_profile`, `export`, `import_profile`, `wipe`, `read_konsave_config` | Operations, and reading/resolving `conf.yaml` |
| `konsave/conf_kde.yaml`, `conf_other.yaml` | data files | Default configuration templates (through `importlib.resources`) |
| `konsave/__main__.py` | `main()` (L127–133) | **Not called.** The creation of `conf.yaml` is replicated in `ConfigService.ensure_default_config` |

Functions of the original that are **not** used: `list_profiles` (only prints),
`copy` and `mkdir` (internal), `log`, `exception_handler`, `main` (reads `sys.argv`).

## 3. Architecture

```
kongui/core/
├── engine.py    KonsaveEngine   loads the engine for a HOME, captures stdout/stderr and the log
├── config.py    ConfigService   conf.yaml: create the default, read it through Konsave (never writes it)
├── profiles.py  ProfileService  profiles: save, apply, remove, export, import, wipe all
├── cli.py       CliRunner       real CLI (diagnostics, read-only by default)
├── safety.py    name validation and root guard
├── results.py   OperationResult, ArchiveInspection, CliResult, ProfileInfo
└── errors.py    exception hierarchy
```

### Why `KonsaveEngine` loads a private copy of the engine

[CONFIRMED] `konsave.consts` reads `$HOME` at import time, creates the profiles
folder and keeps a profile list that is never refreshed. So that tests and
different instances do not share state, the engine imports a private copy of
`consts`, `parse` and `funcs` bound to the chosen `HOME` and then restores
`sys.modules`, the attributes of the `konsave` package, `konsave.__version__` and
`os.environ["HOME"]`. The profile lists passed to the original functions are always
recomputed from disk (`KonsaveEngine.profile_names`).

## 4. Errors, exit codes, stdout and stderr

The original engine **always returns `None`**, swallows every exception, prints the
error to stdout and writes the traceback to `~/.cache/konsave_log.txt` [CONFIRMED].
Therefore:

* `KonsaveEngine.call` runs the function, captures **stdout** and **stderr**
  separately and reads only the part of the log written during the call. Each
  recorded error becomes a `Type: message` summary. An exception that escapes the
  handler is also captured. Calls are serialized by a lock.
* `OperationResult.ok` is true only if **no error was recorded** *and* the
  post-conditions hold (the profile and `conf.yaml` exist, the `.knsv` exists and
  contains `conf.yaml`, the folder is gone after `remove`, and so on). So an
  `apply` that prints "applied successfully" after a section failed [CONFIRMED] is
  reported as a failure.
* `CliResult.ok` requires exit code 0 **and** the absence of the original's error
  marker in the output. [CONFIRMED] The original CLI exits with **0 even when it
  fails** (the marker is `Please check the log at`). If `~/.cache` does not exist,
  the error handler itself breaks and the CLI exits with **1**, empty stdout and a
  traceback on stderr. In both cases `ok` is false. A `timeout` returns
  `returncode=None` and `timed_out=True`, with the partial output. A non-zero code
  is a result, not an exception.

General rule: **invalid preconditions raise an exception before touching the disk**
(`ValidationError`, `ProfileNotFoundError`, `ConfirmationRequiredError`, ...);
**engine results come back in `OperationResult`** (`ok`, `message`, `stdout`,
`stderr`, `errors`, `warnings`, `path`). `OperationResult.raise_for_status()`
turns a failure into `OperationFailedError`.

## 5. Safety rules applied

| Risk (audit) | Protection |
|---|---|
| A profile named `../x` or `.` escapes/pollutes the profiles folder | `validate_profile_name` refuses separators, `.`/`..`, control characters, leading/trailing spaces, a leading `-`, `.knsv` and the reserved prefix `.kongui-` (listing hides that prefix: the profile would be invisible). The limit is 200 UTF-8 **bytes** (Linux limits bytes, not characters) |
| `apply`, `import`, `remove`, `wipe` are destructive | They require `confirmed=True` (exactly `True`; `1` or `"yes"` do not count) |
| `export` with `force` deletes the `<destination>/<name>` folder | `force` is never used for folders; `on_conflict` = `error` (default), `unique` or `overwrite` (only replaces a regular `.knsv`) |
| `save` with a nested entry (`a/b`) aborts halfway | `conf.yaml` is not validated (2026-10-19): Konsave aborts and its reason is reported; the folder the failed call created is removed, so no partial profile is left |
| An unmatched `ENDS_WITH` stays literal text (a relative path) | `save` copies nothing for that group (as Konsave); `apply` refuses because the location is not inside the home, so nothing is written |
| `apply` with a missing destination reports success | Destination pre-check; post-check through the log |
| A `.knsv` (or a profile) writes wherever its `conf.yaml` says | Destinations outside `HOME` (including through a symbolic link), and entries that are not a single name (`../x`, `a/b`), are refused on `import` and `apply` (`allow_outside_home=True` allows other locations, never such entries); members with `..` or an absolute path are refused |
| `import` of `x.knsv.knsv` merges into an existing profile | Names containing `.knsv` are refused |
| Partial profile after a failure | Leftovers the call itself created are removed (only if they did not exist before) |
| `wipe` uses `input()` | The engine supplies the `WIPE` answer only during the call, and only with `confirmed=True` |
| The original handler fails without `~/.cache` | The engine creates `~/.cache` and the profiles folder before every call |
| Subprocess | Argument list, `shell=False`, minimal environment, closed `stdin`, timeout, read-only flags |

## 6. Services

### `KonsaveEngine(home=None, *, euid_provider=...)`

| Member | Description |
|---|---|
| `home`, `konsave_dir`, `profiles_dir`, `config_file`, `temp_dir`, `log_file`, `export_extension`, `version` | Paths and version of the loaded engine |
| `funcs`, `parse` | Private copies of the original modules |
| `profile_names()` | Names of the entries in the profiles folder, read from disk |
| `ensure_runtime_dirs()` | Creates the profiles folder and `~/.cache` |
| `lock` | `EngineLock` of the Konsave folder: `lock.path`, `lock.policy` (`LockPolicy`: `timeout`, `cancel`, `on_wait`), `lock.hold(mode, operation)`; see [`CONCURRENCY.md`](CONCURRENCY.md) |
| `call(name, *args, overrides=None, **kwargs)` | Calls a function from the allowed list and returns `EngineCall` (`returned`, `stdout`, `stderr`, `errors`, `raised`, `failed`) |

Without the package installed, `version` is `0+unknown`.

### `ConfigService(engine)`

KonGUI does not edit, back up or validate `conf.yaml` files (removed on
2026-10-19, see [`LIMITATIONS.md`](LIMITATIONS.md) §2): the user edits them by hand,
as with Konsave. The service only finds, bootstraps and reads them.

| Method | Description |
|---|---|
| `config_path`, `exists()` | Location and existence of the active `conf.yaml` |
| `MAX_CONFIG_BYTES` | Largest file read (1 MiB); also the limit for the `conf.yaml` inside a `.knsv` |
| `ensure_default_config(kind=None, *, desktop=None)` | Creates the default if it does not exist: `conf_kde.yaml` when `XDG_CURRENT_DESKTOP == "KDE"`, otherwise `conf_other.yaml`. Never changes an existing file |
| `resolve(path=None)` | Reads a file through the original `read_konsave_config` (placeholders resolved) and returns its `save` and `export` groups as `{kind: {group: {"location", "entries"}}}`. `ConfigMissingError` if the file does not exist; `ConfigError` (with `details`) if it is too large or Konsave cannot read it, or if a group has no `location` or `entries` that is not a list (shapes the operations could not walk). Nothing else is checked, and nothing is written |

### `ProfileService(engine, config=None)`

| Method | Delegates to | Notes |
|---|---|---|
| `list_profiles()`, `get_profile(name)` | disk read | Fresh list; ignores stray files; `has_config` marks a complete profile |
| `save(name, *, overwrite=False, description=None)` | `save_profile` | `overwrite` **merges** into the existing profile (see §8). To really replace, use `replace`. `description` is kept in a small file next to the profile (§11); if only that write fails the result is still `ok` and carries a warning starting with `DESCRIPTION_NOT_SAVED` |
| `profile_details(names)` | (disk read) | Description and sections of some profiles (§11), read separately from `list_profiles` so the operations do not parse every `conf.yaml`; never raises for one bad profile |
| `set_description(name, description)` | (small file) | Sets, changes or clears the description (§11); writes nothing else |
| `replace(name, *, confirmed)` | `save_profile` (temporary name) | Real replacement: saves the current configuration to `.kongui-new-…`, swaps with `rename` and deletes the old one; if anything fails, the old profile stays (or returns) in place. Does not change Konsave's code. The temporaries never appear in `list_profiles` |
| `apply(name, *, confirmed, allow_outside_home=False)` | `apply_profile` | Reads the profile's `conf.yaml` through Konsave; refuses (`ConfigError`, reasons in `details`) a group whose destination is outside the home, an entry that is not a single name, a group whose folder is missing from the profile, or a destination whose parent does not exist either. Before writing, copies the files it will overwrite (safety copy, §9); if the copy fails, **nothing is applied** (`SnapshotError`). Folders are merged |
| `remove(name, *, confirmed)` | `remove_profile` | Irreversible |
| `export(name, *, directory, archive_name=None, on_conflict="error")` | `export` | The output folder must exist; the temporary assembly folder is created in it. Requires the active `conf.yaml` (`ConfigMissingError` if missing: the original copies it into the archive). The active `conf.yaml`, which goes into the `.knsv`, may have other groups than the profile's; as in Konsave, nothing is said about it (§8) |
| `import_profile(archive_path, *, confirmed, allow_outside_home=False)` | `import_profile` | Writes the archive's `export` section into the system immediately, after making a safety copy of the files it will overwrite (§9) |
| `inspect_archive(archive_path, *, allow_outside_home=False)` | (read-only) | Applies the same checks as `import_profile` and returns `ArchiveInspection` (name, size, `save`/`export` sections, warnings, `name_taken`) without extracting anything. Warnings include groups without a folder in `save/` (the imported profile could not be applied) and folders the archive's `conf.yaml` does not list (ignored when applying) |
| `wipe_all(*, confirmed)` | `wipe` | Deletes every profile; keeps `conf.yaml` |
| `list_backups()` | (read) | Safety copies from `apply`/`import`/restore, newest to oldest (`SnapshotInfo`) |
| `restore_backup(backup_id, *, confirmed, allow_outside_home=False)` | (safety copy) | Puts the files back to the stored state; first stores the current state as a new copy (so it can be undone) |
| `delete_backup(backup_id, *, confirmed)` | (safety copy) | Deletes one copy. No copy is deleted automatically |

### `CliRunner(home, *, python=None, timeout=60, extra_pythonpath=(), allow_mutating=False, ...)`

`run(args)` executes `python -m konsave <args>` and returns `CliResult`; `version()`
returns the CLI version. It requires the `konsave` package to be installed (or the
folder with its metadata to be in `extra_pythonpath`).

* **Read-only by default:** it only accepts the exact tokens of `READ_ONLY_FLAGS`
  (`-h`, `--help`, `-v`, `--version`, `-l`, `--list`), one per element.
  Abbreviations such as `--sav`, combined flags such as `-lv` and any value are
  refused.
* `allow_mutating=True` allows any argument (each is still a single list element,
  never interpreted by a shell). The services never use this mode; whoever uses it
  takes responsibility.
* Limits: `DEFAULT_TIMEOUT` (60 s), `MAX_ARGS` (64 arguments) and `MAX_ARG_LENGTH`
  (4096 characters per argument; no NUL bytes).
* Even the read-only flags have an inherited side effect: the original `main`
  creates `~/.config/konsave/conf.yaml` and the profiles folder on first run.

## 7. How to validate each service

All commands run from the repository root, **as a regular user** (the suite
refuses real file operations as root), and **do not touch `~/.config/konsave`**.
Only the standard library and PyYAML are needed.

```bash
# Everything (plus the final test that compares the real HOME before and after)
python3 -m unittest discover -s tests -t . -v

# Per service
python3 -m unittest tests.test_safety -v                        # guards and names
python3 -m unittest tests.test_engine -v                        # KonsaveEngine
python3 -m unittest tests.test_config_service -v                # ConfigService (default file, reading)
python3 -m unittest tests.test_profile_service_mocked -v        # ProfileService, simulated engine
python3 -m unittest tests.test_profile_service_integration -v   # ProfileService, real original engine
python3 -m unittest tests.test_cli_runner -v                    # CliRunner (simulated and real subprocess)
python3 -m unittest tests.test_core_audit -v                   # findings of the final audit (core)
python3 -m unittest tests.test_docs -v                          # this documentation vs. the code
```

Manual check, in a disposable `HOME`:

```bash
python3 - <<'EOF'
import tempfile
from pathlib import Path
from kongui.core import ConfigService, KonsaveEngine, ProfileService

home = Path(tempfile.mkdtemp(prefix="kongui-manual-"))
(home / ".config").mkdir()
(home / ".config" / "kdeglobals").write_text("demo")

engine = KonsaveEngine(home)                      # refuses root
config = ConfigService(engine)
config.ensure_default_config(kind="kde")          # creates the default conf.yaml
groups = config.resolve()                         # read through Konsave
print(sorted(groups["save"]))

profiles = ProfileService(engine, config)
result = profiles.save("demo")
print(result.ok, result.message, result.path)
print([p.name for p in profiles.list_profiles()])
out = Path(tempfile.mkdtemp(prefix="kongui-out-"))
print(profiles.export("demo", directory=out).path)
print(profiles.remove("demo", confirmed=True).ok)
EOF
```

What to look for in each service:

* **KonsaveEngine**: `engine.profiles_dir` is inside the given `HOME`; after the
  engine is created, `os.environ["HOME"]` and `sys.modules` are unchanged.
* **ConfigService**: `resolve()` returns the groups with `$HOME` and the other
  placeholders replaced, and never writes; a broken file raises `ConfigError` with
  Konsave's own reason in `details`.
* **ProfileService**: `apply`/`remove`/`import_profile`/`wipe_all` without
  `confirmed=True` raise `ConfirmationRequiredError`; `export` with
  `on_conflict="overwrite"` over a folder with the same name raises
  `ArchiveExistsError` and does not delete the folder.
* **CliRunner**: `CliRunner(home, extra_pythonpath=[...]).run(["--list"])` in a
  `HOME` with `~/.cache` and no profiles returns `returncode == 0` but
  `ok == False`; `run(["--save", "x"])` raises `ValidationError`.

## 8. Unimplemented operations and inherited limitations

### Not implemented

`NOT_IMPLEMENTED_OPERATIONS` (`kongui/core/profiles.py`) is **empty**: the backup
before `apply`/`import` (requirement RN-01) has existed since §9.

### Out of scope

* Progress and cancellation of operations already running: the engine has no
  progress callbacks and cannot be interrupted; calls are serialized and blocking.
* Configurable limits: the limits of §10 are constants in `kongui/core/safety.py`,
  not a policy system.
* Nothing regarding the lock: it and the waiting interface are described in
  [`CONCURRENCY.md`](CONCURRENCY.md).
* `XDG_CONFIG_HOME` support (the original hardcodes `~/.config`).
* Validation on a real Fedora KDE (Plasma 6) session, **in progress**: value of
  `XDG_CURRENT_DESKTOP` in the session, Plasma 6 file paths, overwriting by a
  running Plasma, SELinux and Flatpak ("to investigate" items of the audit).
* Editing, backing up or validating `conf.yaml` (removed on 2026-10-19), pruning of
  safety copies or a limit on their number, and rewriting the `conf.yaml` stored in a
  `.knsv`: decided **not** to do (see [`LIMITATIONS.md`](LIMITATIONS.md) §2).

### Limitations of the original engine that the layer does **not** fix

* The executable bit and metadata do not survive the export → import cycle;
  symbolic links become files [CONFIRMED, covered by a test].
* `apply` merges folders: files that are not in the profile stay.
* `export` reads the `export` section from the live system at export time and
  writes the current **global** `conf.yaml` into the `.knsv`, which may differ from
  the profile's `conf.yaml` [CONFIRMED]; KonGUI no longer warns about it.
* `import` needs the destination folder of each `export` section to exist already
  (for example `~/.local/share`); otherwise the copy fails, the original still
  prints success, and the layer reports a failure and removes the profile it
  created [CONFIRMED, covered by a test].
* `ConfigService.ensure_default_config` keeps the original rule
  `XDG_CURRENT_DESKTOP == "KDE"`: composite values such as `KDE:GNOME` pick the
  generic template.
* The engine iterates over **all** top-level keys of `conf.yaml` as if they were
  section groups and fails if any is not a mapping [CONFIRMED]; the layer reports
  Konsave's error (`ConfigError` when reading, a failed result when saving).
* Without `~/.cache`, the original CLI breaks when trying to record an error (exit
  1 and a traceback). In-process calls do not suffer from this because the engine
  creates the folder.

## 9. Safety copies before apply and import (RN-01)

`kongui/core/snapshot.py` (`SnapshotService`, used by `ProfileService`).

* **What is copied:** only the files the operation will overwrite, computed before
  it runs. For `apply`: each file in the folder of each group of the profile, at
  the `location/…` destination. For `import`: each `export/<group>/…` file of the
  `.knsv` whose first level is in `entries`. Files that **do not exist yet** are
  noted (the restore removes them, and removes the folders the operation created if
  they end up empty). Symbolic links are recreated as links (and, if `import`
  writes through the link, the target's content is also stored). File mode is
  preserved.
* **Where:** `~/.config/konsave/kongui-backups/<date>-<time>-<µs>-<operation>/`
  (`apply`, `import` or `restore`), with `manifest.json` and `files/`. Folders use
  mode 0700.
* **Fail closed:** if the copy cannot be made (no space, no permission, folder in
  the way), `SnapshotError` is raised and the operation **does not start**; the
  partial folder is deleted.
* **Result:** `OperationResult.backup` points to the folder and `warnings` carries
  `KEPT_PREFIX + id`. The manifest records whether the operation finished well
  (`SnapshotInfo.succeeded`); an operation that failed halfway still has its copy.
* **Restoring** requires `confirmed=True`, validates the whole manifest before
  touching any file (id only in the expected format, absolute paths inside the
  home, names stored only as `files/NNNN`), writes file by file through a
  temporary file + `os.replace`, continues with the rest if one fails (`ok=False`
  and `errors`) and first stores the current state (a `restore` copy, note
  `UNDO_PREFIX`). If that copy fails, nothing is restored.
* **Does not:** undo the profile created by an `import` (it stays in the list);
  protect against changes made by another program during the operation; limit the
  total size (see §8). Nothing is deleted by itself: use `delete_backup`. There is
  **no limit on the number of copies and no automatic pruning** (project decision):
  pruning would delete first the oldest copy, which holds the original state.

## 10. Limits and free space on import and export (P-3)

Basic protections implemented in `ProfileService`, **before** the original engine
writes anything. The `.knsv` format and the engine are unchanged.

| Constant (`kongui/core/safety.py`) | Value | Effect |
|---|---|---|
| `MAX_ARCHIVE_BYTES` | 512 MiB | a compressed file above it is refused (`ArchiveLimitError`, kind `size`) |
| `MAX_EXTRACTED_BYTES` | 2 GiB | limit for the bytes **actually decompressed** (kind `extracted`) |
| `MAX_ARCHIVE_ENTRIES` | 10,000 | maximum number of entries (kind `entries`) |
| `DISK_MARGIN_BYTES` | 64 MiB | safety margin added to every free-space estimate |

* **Import**: `_check_archive` refuses the file by size; `_read_archive_config`
  refuses it by entry count; absolute paths, `..`, backslashes and NUL in member names were already
  refused (`unsafe path`). `_measure_extracted` then decompresses every member in
  1 MiB pieces to nowhere, counts the bytes really produced (the sizes declared in
  the headers are not trusted) and **stops at the first piece that passes the
  limit**. The same pass reads every member to the end, so a damaged archive
  (`BadZipFile`, bad CRC, truncated data) is found here and reported as
  `corrupted archive`, before the safety copy and before the engine is called.
  Extraction itself still happens only in the engine's staging folder
  (`~/.config/konsave/temp/<name>`), which is removed on failure.
* **Free space**: `require_free_space` uses `shutil.disk_usage`. Import needs
  `2 × extracted bytes + margin` in the Konsave folder (staging plus the profile);
  export needs `2 × (profile + export section read from the live system) + margin`
  in the destination folder (the folder tree plus the zip). Failure raises
  `InsufficientSpaceError` and **nothing is changed**. If the disk cannot be queried
  the check is skipped.
* **A real "no space left" error** during the engine call (`ENOSPC`) is swallowed by
  the original exception handler and only appears as log text; the layer already
  detected the failure through its post-conditions, and the message layer
  recognises the text and explains it in plain words. Leftovers are removed as before.
* **Export** keeps the original flow (option A of the audit): the engine assembles
  the files in a staging folder next to the destination, makes the zip and moves it
  over the final name only at the end. If it fails, the previous valid export stays
  and no temporary folder or `.zip` remains (`tests.test_transfer_limits`). The
  overwrite confirmation (`on_conflict`) is unchanged.

Tests: `tests.test_transfer_limits` lowers the constants with `mock.patch` and
simulates a full disk by replacing `shutil.disk_usage` or making a write raise
`ENOSPC`; the real disk is never filled.

**What these limits are not.** They stop a damaged or hostile archive and an obviously
full disk; they are not a policy and not a guarantee (project decision: they stay
fixed constants, not settings):

* the free-space check is an estimate and is **not atomic** with the operation:
  another program can fill the disk between the check and the copy (a real `ENOSPC`
  is then reported and cleaned up);
* the decompression pass reads the archive once more before importing, which costs
  time on large archives;
* the `export` section is read from the live system, so its size can change between
  the estimate and the copy;
* the safety copy of §9 has no size limit (these limits apply to the archive);
* the `.knsv` is neither signed nor encrypted and its `conf.yaml` decides where files
  go (KonGUI only accepts destinations inside the home): import only archives you
  trust;
* the original engine is not interrupted or made atomic: an import that fails
  halfway is undone by this layer, not by the engine.

The same list, with the other decisions, is in [`LIMITATIONS.md`](LIMITATIONS.md) §3;
see also `GUI_SERVICES.md` §6.

## 11. Profile description and sections (B-2)

Konsave stores neither; KonGUI adds them **without changing the engine or the `.knsv` format**.

* **Description**: `<profile>/.kongui-profile.json`, JSON `{"version": 1, "description": "…"}`, at most 500 characters (`MAX_DESCRIPTION_CHARS`) and 16 KiB. Living inside the profile folder it is deleted with the profile, survives `apply`, `save(overwrite=True)` and a folder renamed outside the program, and cannot be attached to another profile by name. Konsave does not export it, so **it does not travel in the `.knsv`**.
  * Writing is atomic (temporary file, then rename; nothing is left behind on failure) and keeps the folder's modification time, so editing a text does not make the profile look "updated".
  * Reading never raises: a missing, oversized, non-regular (link), malformed, non-object or other-version file simply means "no description"; an over-long stored text is cut. Text is cleaned (control characters and text-direction overrides removed) and the interface shows it as plain text, never as markup.
  * `replace` swaps the whole folder, so it carries the description over *before* the swap; if that fails nothing changes and the previous profile stays.
  * `import_profile` removes any such file that came inside the archive: Konsave copies everything under `save/` into the profile, so an archive could plant one. An imported profile always starts without a description (if the removal fails, a warning says so).
* **Sections**: not stored. They are the `save` groups of the profile's own `conf.yaml` that hold at least one file (a group with no files, such as `autostart` in the default configuration, is left out; a group name that could point outside the profile, or a linked folder, is ignored). The `export` groups are not sections of a profile: they are read from the live system at export time and never stored in it. The interface shows friendly, translated names only for the groups of the default configuration (`configs`, `app_layouts`, `autostart`); any other group keeps its own name.
* **What to include**: choosing what a profile contains is **not** offered. It stays manual: the user edits `~/.config/konsave/conf.yaml` by hand, as with Konsave; the steps are in [`LIMITATIONS.md`](LIMITATIONS.md) §4.

Tests: `tests.test_profile_details` (service: persistence, isolation, renaming, import, removal, failures, compatibility with the exported archive) and `tests.test_gui_details` (dialog, card, warnings, plain text, friendly names), always in temporary homes.
