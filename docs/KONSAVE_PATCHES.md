# Changes to the Konsave code (`konsave/`)

This is the **only** document that lists what KonGUI changed inside the `konsave/`
package of the original project. It exists so that a new Konsave release can be
incorporated without guesswork: redo the changes below, run the verification list
(§5) and you are done.

**Baseline of the changes:** Konsave with `konsave/__main__.py` as in commit
`5179e0f` of this repository (before any lock change).
Every changed line in an original file carries the marker `KONGUI-PATCH(lock)`; to
find them all: `grep -rn "KONGUI-PATCH" konsave/` (the one-line change in
`setup.py` carries no marker; see §1).

## 1. Summary

| File | Type | Size | Reason |
|---|---|---|---|
| `konsave/lock.py` | **new** (standard library only) | ~420 lines | mechanism of the cross-process lock (`fcntl.flock`) |
| `konsave/__main__.py` | changed | +56 / −8 lines | the CLI now runs every command under the lock |
| `setup.py` | changed | 1 line | `python_requires` from `>=3.6` to `>=3.9` |

No other file in `konsave/` was touched (`funcs.py`, `consts.py`, `parse.py`,
`conf_*.yaml` and `__init__.py` are identical to the original). The behavior of the
commands does not change when nobody else is using Konsave; the only visible
differences are in §4.

## 2. `konsave/lock.py` (new file)

A standalone file: it imports nothing from Konsave or KonGUI. With a new Konsave
release you only need to **copy it again**. Interface used by the rest:

* `OperationLock(path).hold(mode, operation=, timeout=, cancel=, on_wait=)`
  (context manager; `mode` is `SHARED` or `EXCLUSIVE`);
* `command_lock(konsave_dir, mode, operation)` (command-line version: waits with a
  message and ends with an exit status);
* `default_lock_path`, `timeout_from_environment`, `describe_holder`;
* exceptions `LockError` ← `LockBusyError` ← `LockTimeoutError`,
  `LockCancelledError`, `LockUnavailableError`, `LockUsageError`.

Full behavior: [`CONCURRENCY.md`](CONCURRENCY.md).

## 3. `konsave/__main__.py`

Four changes, all marked. The dispatch body (`if args.list: … elif …`) was **not
rewritten**: it was only moved to `_run`, with no change beyond reading the profile
list.

### 3.1 Imports

```diff
 from konsave.consts import (
     CONFIG_FILE,
+    KONSAVE_DIR,
+    PROFILES_DIR,
     VERSION,
-    length_of_lop,
-    list_of_profiles,
 )
 ...
+from konsave.lock import EXCLUSIVE, SHARED, command_lock  # KONGUI-PATCH(lock)
```

`list_of_profiles` and `length_of_lop` are no longer imported because
`konsave.consts` computes them **when the module is imported**, before any wait for
the lock (they would be stale). See 3.4.

### 3.2 New function `_lock_request(args)`

Returns the command's `(mode, operation)`. It mirrors the **same order** as the
`if/elif` chain in `_run` (the first match runs):

| Command | Lock | Why |
|---|---|---|
| `--list` | shared | only reads |
| `--save`, `--remove`, `--apply`, `--import-profile`, `--wipe` | exclusive | change profiles or user files |
| `--export-profile` | shared | reads the profile; writes outside Konsave's data |
| `--version`, `--help`, no arguments | none | do not touch shared data |

> **When adapting:** if a new Konsave release adds a command, include it in
> `_lock_request` at the equivalent position in `_run`'s chain and decide whether it
> reads (shared) or changes (exclusive). A command left without a lock works, but is
> no longer protected.

### 3.3 `main()`

* The creation of the default `conf.yaml` now happens under the exclusive lock, with
  a second `os.path.exists` check inside it (two processes on first run do not copy
  the file at the same time). The body of the copied `if/else` is the original.
* After `parse_args()`, the command runs in
  `with command_lock(KONSAVE_DIR, mode, operation): _run(parser, args)`.

### 3.4 Function `_run(parser, args)`

Contains what used to come after `args = parser.parse_args()` in `main()`,
**unchanged**, except for the first two lines:

```python
list_of_profiles = os.listdir(PROFILES_DIR)
length_of_lop = len(list_of_profiles)
```

Without this, a `--save name` that waited for the lock would decide "exists / does
not exist" with the list read before the wait. Covered by
`tests.test_locking.CliTests.test_a_waiting_save_does_not_overwrite_what_the_first_one_created`.

> **When adapting:** if the original starts computing the list some other way, keep
> the rule: **read it after obtaining the lock**.

## 4. Visible behavior differences in the CLI

| Situation | Original | With the patch |
|---|---|---|
| No other operation in progress | — | identical |
| Another operation in progress | both run at the same time | waits up to 30 s with the message `Konsave: another Konsave operation is running…; waiting up to 30 s (Ctrl+C to give up)...` (stderr) |
| Waited and did not get it | — | `Konsave: … Nothing was changed.`, **exit status 75** (the original always exits with 0, even on error) |
| Unusable lock file (folder without permission, etc.) | — | `Konsave: cannot open the lock file …`, status 1 |
| Ctrl+C while waiting | — | status 130, nothing changed |
| `KONSAVE_LOCK_TIMEOUT` variable | — | seconds to wait (`0` = do not wait; negative or `inf` = no limit; default 30) |
| Konsave folder | — | now contains `.kongui.lock` (empty/small file, never deleted) |

## 5. How to adapt to a new Konsave release

1. Bring the new `konsave/` into the repository (replacing the current one).
2. Copy `konsave/lock.py` back (it does not exist in the original).
3. Reapply the changes of §3 to `konsave/__main__.py` (`grep` for the marker shows
   where they were). If `__main__.py` changed a lot, do it by concept: *one command
   = one lock; the profile list is read after the lock*.
4. In `setup.py`, keep `python_requires=">=3.9"` (or whatever the new Konsave
   requires).
5. Check that `konsave/funcs.py`/`consts.py` still have the same functions that
   `kongui/core/engine.py` uses (`docs/INTEGRATION.md` §2). KonGUI's lock does
   **not** depend on `__main__`: it wraps the calls in `kongui/core/` (see
   [`CONCURRENCY.md`](CONCURRENCY.md) §3).
6. Run the verification:
   * `python -m unittest tests.test_locking tests.test_cli_runner tests.test_profile_service_integration`
     (real processes; fails if the CLI or the service stop using the lock);
   * `python -m unittest discover -s tests -t .` (whole suite, **as a regular user**);
   * `git diff <old-version> -- konsave/` must show only what is in this document.

## 6. History

| KonGUI version | Change |
|---|---|
| this stage | cross-process lock (`lock.py`, `__main__.py`, `setup.py`) |
